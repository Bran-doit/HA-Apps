"""Home Assistant event bridge to the source-neutral media and player layer."""
import json
import os
import time
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import appdaemon.plugins.hass.hassapi as hass
from .hmk_adapter import KodiClient, KodiSource
from .hmk_models import MediaError
from .hmk_kodi import KodiMediaSource, KodiMediaPlayer, KodiArtwork
from .hmk_media import MediaSearch, PlayerManager
from .hmk_voice import VoiceController
from .hmk_startup import KodiStartup

class HAMediensteuerungKodi(hass.Hass):
    def initialize(self):
        self.base = Path(self.args.get("data_dir", "/config/ha_mediensteuerung_kodi"))
        self.base.mkdir(parents=True, exist_ok=True)
        config_path = Path(self.args.get("player_config", str(self.base / "player.json")))
        with config_path.open(encoding="utf-8") as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise ValueError("Bitte die Player-Konfigurationsdatei prüfen.")
        for key in ("id", "name", "connection_file"):
            if not isinstance(config.get(key), str) or not config[key].strip():
                raise ValueError("player."+key+" muss angegeben sein.")
        aliases = config.get("room_aliases")
        if not isinstance(aliases, list) or not aliases or any(not isinstance(v,str) or not v.strip() for v in aliases):
            raise ValueError("player.room_aliases muss eine Liste von Raum-/Gerätenamen sein.")
        self.player_name = config["name"].strip()
        self.connection_file = Path(config["connection_file"])
        if not self.connection_file.is_absolute():
            self.connection_file = self.base / self.connection_file
        with self.connection_file.open(encoding="utf-8") as handle:
            self.client = KodiClient(json.load(handle))
        self.startup_config = config.get("startup", {})
        self.probe_client = KodiClient(json.loads(self.connection_file.read_text(encoding="utf-8")))
        self.probe_client.timeout = 1
        self.startup = KodiStartup(self.probe_ready, self.launch_kodi, timeout=self.startup_config.get("timeout_seconds",20), foreground=self.kodi_foreground)
        source = KodiMediaSource(self.client)
        player = KodiMediaPlayer(self.client)
        self.media = MediaSearch({source.source_id: source}, source.source_id)
        self.players = PlayerManager({config["id"].strip(): player}, config["id"].strip())
        self.artwork = KodiArtwork(self.client)
        self.voice = VoiceController(self.media, self.players, room_aliases=aliases, player_name=self.player_name)
        self.listen_event(self.command, "ha_mediensteuerung_kodi")
        self.run_in(self.initial_probe, 2)
        self.log("HA-Mediensteuerung auf Kodi: bereit; Player-Konfiguration geladen; Kodi-Start bei Bedarf aktiv.")

    def initial_probe(self, kwargs):
        self.execute({"action": "diagnostic", "query": "Matrix", "passive": True})

    def probe_ready(self):
        try:
            return self.probe_client.rpc("JSONRPC.Ping") == "pong"
        except MediaError:
            return False

    def kodi_foreground(self):
        if not self.startup_config.get("bring_to_front",True):
            return True
        return self.get_state(self.startup_config.get("remote_entity"),attribute="current_activity")==self.startup_config.get("activity")

    def launch_kodi(self):
        remote = self.startup_config.get("remote_entity")
        activity = self.startup_config.get("activity")
        if not self.startup_config.get("sony") and (not isinstance(remote,str) or not remote.startswith("remote.") or not activity):
            raise MediaError("Kodi-Start ist nicht korrekt konfiguriert.")
        native_file=self.startup_config.get("sony_connection_file")
        if native_file or self.startup_config.get("sony"):
            tv=self.startup_config.get("sony") or json.loads(Path(native_file).read_text(encoding="utf-8"))
            origin=("https" if tv.get("use_ssl") else "http")+"://"+tv["host"]
            def sony(endpoint,method,params):
                request=urllib.request.Request(origin+"/sony/"+endpoint,data=json.dumps({"method":method,"params":params,"id":1,"version":"1.0"}).encode(),headers={"X-Auth-PSK":tv["pin"],"Content-Type":"application/json"})
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request,timeout=5) as response:result=json.load(response)
                if "error" in result:
                    raise MediaError("Der Sony-Fernseher hat den Kodi-Start abgewiesen.")
            self.log("Kodi-Start über bestätigte Sony-App-URI angefordert")
            sony("system","setPowerStatus",[{"status":True}])
            sony("appControl","setActiveApp",[{"uri":self.startup_config["launch_uri"]}])
            return
        def service(domain, name, payload):
            request=urllib.request.Request("http://supervisor/core/api/services/"+domain+"/"+name,
                data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+os.environ["SUPERVISOR_TOKEN"],"Content-Type":"application/json"})
            with urllib.request.urlopen(request,timeout=6) as response:
                response.read()
        self.log("Kodi-Start angefordert: {}".format(activity))
        launch_entity=self.startup_config.get("launch_entity")
        if self.get_state(remote,attribute="current_activity")=="com.google.android.apps.tv.dreamx":
            service("remote","send_command",{"entity_id":remote,"command":"HOME"})
        if launch_entity:
            service("media_player","turn_on",{"entity_id":launch_entity})
            service("media_player","select_source",{"entity_id":launch_entity,"source":self.startup_config.get("launch_source","Kodi")})
        else:
            service("remote","turn_on",{"entity_id":remote,"activity":activity})

    def prepare_kodi(self, data):
        action=data.get("action","diagnostic")
        if data.get("passive") or action=="now_playing":
            return {"status":"passive"}
        if action=="voice":
            text=data.get("text","")
            if not isinstance(text,str) or not re.search(r"\b(?:filme?|staffel|folge|kinderfilme?|familienfilme?)\b",text,re.I):
                return {"status":"not_routed"}
        elif action not in ("diagnostic","search","resolve","movie","series","seasons","episodes","play","proof"):
            return {"status":"not_routed"}
        if data.get("expires_at") and time.time()>=float(data["expires_at"]):
            raise MediaError("Der Auftrag ist abgelaufen. Bitte wiederhole ihn.")
        if not self.startup_config.get("enabled",False):
            return {"status":"disabled"}
        remote=self.startup_config.get("remote_entity")
        foreground=self.get_state(remote,attribute="current_activity")
        bring_forward=self.startup_config.get("bring_to_front",True) and foreground!=self.startup_config.get("activity")
        self.ui["startup_status"]="Kodi-Verfügbarkeit wird geprüft …"
        self.publish()
        result=self.startup.ensure(force_launch=bring_forward or data.get("force_launch") is True)
        self.ui["startup_status"]="Kodi ist bereit"
        self.log("Kodi-Vorbereitung: {} ({} ms)".format(result["status"],result["ms"]))
        return result

    def command(self, event_name, data, kwargs):
        self.execute(data)

    def diagnostic(self, query):
        # Transport diagnostics deliberately remain adapter-specific.
        library = KodiSource(self.client)
        ping = self.client.rpc("JSONRPC.Ping")
        version = self.client.rpc("JSONRPC.Version")
        movies = library.listing("movie", limit=5)
        series = library.listing("series", limit=5)
        result = {"ping": ping, "version": version, "movies": movies, "series": series,
                  "search": self.media.search_media(query).to_dict(),
                  "now_playing": [p.to_dict() for p in self.players.get_now_playing()],
                  "sources": list(self.media.sources), "players": list(self.players.players)}
        if series["items"]:
            sid = series["items"][0]["library_id"]
            result.update(sample_series_id=sid, seasons=[s.to_dict() for s in self.media.get_seasons(sid)], episodes=self.media.get_episodes(sid).to_dict())
        return result

    def output_search_results(self,rows):
        from .hmk_tv_results import show_items
        try:return show_items(self.client,rows)
        except Exception:return {'shown':False,'reason':'display_unavailable'}

    def execute(self, data):
        started = time.monotonic()
        self.client.timings = []
        action = data.get("action", "diagnostic")
        report = {"timestamp": datetime.now(timezone.utc).isoformat(), "action": action}
        source_id, player_id = data.get("source"), data.get("player")
        try:
            report["startup"] = self.prepare_kodi(data)
            if action == "diagnostic":
                result = self.diagnostic(data.get("query", "Matrix"))
            elif action == "voice":
                result = self.voice.handle(data)
                if data.get('show_on_kodi') and not data.get('dry_run') and result.get('status') in ('choose','ready') and 'tv_results' not in result and 'Test ohne Wiedergabe' not in result.get('speech',''):
                    result['tv_results']=self.output_search_results(result.get('choices') or ([result['selected']] if result.get('selected') else []))
                    if result['tv_results'].get('shown'):
                        result['speech']=str(result['tv_results'].get('count',len(result.get('choices',[]))))+' Treffer. Die Suchergebnisse sind in Kodi geöffnet.'
                    else:result['speech']+=' Die Treffer stehen im Dashboard; diese Liste konnte nicht in Kodi geöffnet werden.'

                if result.get("handled") and result.get("status") == "error":
                    report["error"] = result["speech"]
            elif action == "search":
                result = self.media.search_media(data.get("query", ""), data.get("media_type", "movie"), source_id, data.get("limit", 100)).to_dict()
                if data.get('show_on_kodi'):
                    result['tv_results']=self.output_search_results(result['items'])

            elif action == "movie":
                result = self.media.get_movie(data.get("media_id"), source_id).to_dict()
            elif action == "series":
                result = self.media.get_series(data.get("media_id"), source_id).to_dict()
            elif action == "seasons":
                result = {"items": [s.to_dict() for s in self.media.get_seasons(data.get("series_id"), source_id)]}
            elif action == "episodes":
                result = self.media.get_episodes(data.get("series_id"), data.get("season"), source_id).to_dict()
            elif action == "resolve":
                result = self.media.resolve_media(data.get("query", ""), data.get("media_type", "movie"), data.get("year"), source_id).to_dict()
            elif action == "now_playing":
                result = [p.to_dict() for p in self.players.get_now_playing(player_id)]
            elif action in ("proof", "play"):
                if action == "proof":
                    media = self.media.resolve_media(data.get("query", "Matrix"), "movie", data.get("year"), source_id)
                else:
                    kind = data.get("media_type", "movie")
                    if kind not in ("movie", "episode"):
                        raise MediaError("Abspielen unterstuetzt movie oder episode")
                    media = self.media.get_movie(data.get("media_id"), source_id) if kind == "movie" else self.media.get_episode(data.get("media_id"), source_id)
                result = self.players.play(media, player_id, data.get("replace_current", False))
                if not result["verified"]:
                    report["error"] = (result.get("error_code", "PLAYBACK_COMMAND_FAILED")+": Wiedergabebefehl gesendet, aber fortschreitende Wiedergabe nicht bestaetigt")
            else:
                raise MediaError("Unbekannte Aktion")
            report.update(result=result, ok="error" not in report)
        except Exception as exc:
            if hasattr(self,"ui"):
                self.ui["startup_status"]="Auftrag fehlgeschlagen"
            report.update(ok=False, error=str(exc) if isinstance(exc, MediaError) else "Interner Fehler: " + type(exc).__name__)
        report.update(elapsed_ms=round((time.monotonic()-started)*1000, 1), rpc_timings=list(self.client.timings))
        temporary = self.base / "last_report.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.base / "last_report.json")
        if action == "proof":
            (self.base / "proof_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        history_path=self.base/"command_history.json"
        try:
            history=json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
        except (ValueError,OSError):
            history=[]
        summary={k:report.get(k) for k in ("timestamp","action","ok","elapsed_ms","error","startup")}
        summary["request_id"]=str(data.get("request_id",""))[:100]
        summary["text"]=str(data.get("text",data.get("query","")))[:300]
        summary["status"]=report.get("result",{}).get("status") if isinstance(report.get("result"),dict) else None
        history_path.write_text(json.dumps(([summary]+history)[:100],ensure_ascii=False,indent=2),encoding="utf-8")
        self.set_state("sensor.ha_mediensteuerung_kodi", state="bereit" if report["ok"] else "fehler", attributes={"friendly_name": "HA-Mediensteuerung auf Kodi", "target": self.players.default_player, "source": self.media.default_source, "last_action": action, "last_ok": report["ok"], "elapsed_ms": report["elapsed_ms"], "error": report.get("error", ""), "updated_at": report["timestamp"]})
        self.log("Medienauftrag {}: ok={}, {} ms{}".format(action, report["ok"], report["elapsed_ms"], " - " + report["error"] if "error" in report else ""))
        self.fire_event("ha_mediensteuerung_kodi_result", action=action, ok=report["ok"], elapsed_ms=report["elapsed_ms"])
        if action == "voice":
            reply = report.get("result", {"handled": True, "status": "error", "speech": report.get("error", "Unbekannter Fehler")})
            self.fire_event("ha_mediensteuerung_kodi_voice_result", request_id=data.get("request_id", ""), payload=json.dumps(reply, ensure_ascii=False))
        return report
