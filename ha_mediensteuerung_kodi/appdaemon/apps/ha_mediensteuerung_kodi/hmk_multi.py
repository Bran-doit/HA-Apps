"""Multiple isolated Kodi runtimes backed by the private HA configuration store."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .hmk_dashboard import HAMedienDashboard
from .hmk_adapter import KodiClient
from .hmk_kodi import KodiMediaSource, KodiMediaPlayer, KodiArtwork
from .hmk_media import MediaSearch, PlayerManager
from .hmk_voice import VoiceController, normalize_selection
from .hmk_startup import KodiStartup
from .hmk_models import MediaError
from .hmk_emby import EmbyClient, EmbyMediaSource, EmbyArtwork
from .hmk_identity import EmbyKodiResolver
from .hmk_tv_results import show_results
from .hmk_target_names import target_name
from .hmk_voice_origin import player_for_origin


class HAMedienMultiDashboard(HAMedienDashboard):
    fields = ("player_name", "client", "probe_client", "startup_config", "startup", "media", "players", "artwork", "voice", "monitor")

    def initialize(self):
        self.base = Path(self.args.get("data_dir", "/config/ha_mediensteuerung_kodi"))
        self.base.mkdir(parents=True, exist_ok=True)
        self.config_path = Path("/homeassistant/ha_medien_kodi_private/players.json")
        self.ui = {"items":[], "total":0, "view":"search", "heading":"Noch keine Suche", "history":[], "busy":False, "error":"", "request_id":"", "target_name":"", "connected":False}
        self.posters = Path("/homeassistant/www/ha-medien-kodi/posters")
        self.posters.mkdir(parents=True, exist_ok=True)
        self.registry = {}
        self.revision = -1
        self.active_id = ""
        self.reload_players()
        self.listen_event(self.command, "ha_mediensteuerung_kodi")
        self.listen_event(self.configuration_changed, "ha_medien_kodi_config_changed")
        self.run_every(self.poll, "now+5", 30)
        self.publish()
        self.log("Kodi: Mehrgeräte-Konfiguration geladen (Revision {}).".format(self.revision))

    def reload_players(self):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if config["revision"] == self.revision:
            return
        registry = {}
        central = EmbyMediaSource(EmbyClient(config["emby"])) if config.get("emby",{}).get("enabled") else None
        for p in config["players"]:
            if not p["enabled"]:
                continue
            client = KodiClient(p["connection"])
            probe = KodiClient(p["connection"])
            probe.timeout = 1
            monitor = KodiClient(p["connection"])
            monitor.timeout = 2
            source = KodiMediaSource(client)
            library = central or source
            media = MediaSearch({library.source_id:library}, library.source_id)
            players = PlayerManager({p["id"]:KodiMediaPlayer(client)}, p["id"])
            if central:
                players.before_play = lambda: super(HAMedienMultiDashboard,self).prepare_kodi({"action":"play"})
            if central:
                players.register_resolver(central.source_id,p["id"],EmbyKodiResolver(central,source))
            registry[p["id"]] = {"config":p, "player_name":target_name(p), "client":client, "probe_client":probe,
                "startup_config":p["startup"], "media":media, "players":players, "artwork":EmbyArtwork(central.client) if central else KodiArtwork(client),
                "voice":VoiceController(media, players, room_aliases=p["room_aliases"], player_name=target_name(p)),
                "monitor":monitor, "startup":KodiStartup(self.probe_ready, self.launch_kodi,
                    timeout=p["startup"].get("timeout_seconds",20), foreground=self.kodi_foreground)}
        for runtime in registry.values():
            runtime["voice"].show_results = lambda q,rows,client=runtime["client"]: show_results(client,q,rows)
        self.registry = registry
        self.config_players = config["players"]
        self.default_id = config.get("default_player", "")
        self.revision = config["revision"]
        self.active_id = ""
        self.ui.update(items=[], total=0, heading="Noch keine Suche", view="search", voice_text="", voice_speech="", now_playing=[], error="")
        if self.default_id:
            self.activate(self.default_id)
        else:
            self.ui.update(target_name="Kein Kodi aktiviert", connected=False, connection_error="Bitte im Tab Konfiguration ein Gerät aktivieren.", player_id="", source_id="", config_revision=self.revision)

    def activate(self, player_id):
        runtime = self.registry.get(player_id)
        if runtime is None:
            raise MediaError("Dieser Kodi ist deaktiviert oder nicht mehr eingerichtet.")
        for field in self.fields:
            setattr(self, field, runtime[field])
        if self.active_id != player_id:
            self.ui.update(items=[], total=0, heading="Noch keine Suche", voice_text="", voice_speech="", now_playing=[])
        self.active_id = player_id
        self.ui.update(target_name=self.player_name, player_id=player_id, source_id=self.media.default_source, config_revision=self.revision)

    def configuration_changed(self, event_name, data, kwargs):
        self.reload_players()
        self.poll({})

    def poll(self, kwargs):
        try:
            self.reload_players()
        except Exception:
            self.ui.update(connected=False, error="Die Gerätekonfiguration konnte nicht geladen werden.")
            self.publish()
            return
        if not self.registry:
            self.ui["checked_at"] = datetime.now(timezone.utc).isoformat()
            self.publish()
            return
        super().poll(kwargs)

    def execute(self, data):
        try:
            self.reload_players()
            action = data.get("action", "diagnostic")
            # The LMS boundary applies even when every Kodi has been disabled.
            if action == "voice" and not re.search(r"\b(?:filme?|staffel|folge|kinderfilme?|familienfilme?)\b",str(data.get("text", "")),re.I):
                self.fire_event("ha_mediensteuerung_kodi_voice_result", request_id=data.get("request_id", ""), payload=json.dumps({"handled":False,"status":"unhandled","speech":""}))
                return
            player_id = data.get("player") or self.default_id
            if action == "voice" and not data.get("player"):
                text = normalize_selection(str(data.get("text", ""))).casefold()
                matches = [p["id"] for p in self.config_players if any(re.search(r"\s+(?:im|auf dem|auf)\s+"+re.escape(alias)+r"[.!?]*$",text) for alias in p["room_aliases"])]
                if len(matches)>1:
                    raise MediaError("Bitte nur einen Raum oder Kodi nennen.")
                if matches:
                    player_id = matches[0]
                elif re.search(r"\bnummer\s+|\bfilm\s+(?:von|aus dem jahr)\s+\d{4}",text):
                    pending = [pid for pid,r in self.registry.items() if str(data.get("session", ""))[:200] in r["voice"].pending]
                    if len(pending)>1:
                        raise MediaError("Es gibt eine Auswahl auf mehreren Geräten. Bitte den vollständigen Befehl mit Raum wiederholen.")
                    if pending:
                        player_id = pending[0]
                    else:
                        player_id = player_for_origin(data,self.config_players) or player_id
                else:
                    player_id = player_for_origin(data,self.config_players) or player_id
            if not player_id:
                raise MediaError("Kein Kodi ist aktiviert. Bitte die Konfiguration öffnen.")
            self.activate(player_id)
            if data.get("source") and data["source"] != self.media.default_source:
                raise MediaError("Diese Treffer stammen von einer anderen Kodi-Verbindung. Bitte erneut suchen.")
            if data.get("config_revision") is not None and data["config_revision"] != self.revision:
                raise MediaError("Die Konfiguration wurde geändert. Bitte erneut suchen.")
            return super().execute({**data, "player":player_id})
        except MediaError as exc:
            message = str(exc)
            self.ui.update(error=message, busy=False, last_ok=False, completed_request_id=data.get("request_id", ""))
            self.publish()
            if data.get("action") == "voice":
                self.fire_event("ha_mediensteuerung_kodi_voice_result", request_id=data.get("request_id", ""), payload=json.dumps({"handled":True,"status":"error","speech":message},ensure_ascii=False))

    def prepare_kodi(self, data):
        # Central searches do not wake the television. Resolve/start remains target-specific.
        if self.media.default_source.startswith("emby:") and data.get("action") in ("search","movie","series","seasons","episodes","resolve"):
            return {"status":"central_search"}
        if self.media.default_source.startswith("emby:") and data.get("action") in ("voice","play","proof"):
            return {"status":"deferred_until_play"}
        return super().prepare_kodi(data)

    def display_items(self, rows):
        return [{**r, "player":self.active_id, "source":self.media.default_source, "config_revision":self.revision} for r in super().display_items(rows)]
