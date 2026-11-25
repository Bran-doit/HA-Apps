"""Dashboard bridge; HA events and state updates, no unauthenticated command API."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from .hmk_app import HAMediensteuerungKodi
from .hmk_adapter import KodiClient
from .hmk_kodi import KodiMediaPlayer
from .hmk_models import MediaError


class HAMedienDashboard(HAMediensteuerungKodi):
    def initialize(self):
        self.ui = {"items": [], "total": 0, "view": "search", "heading": "Noch keine Suche", "history": [], "busy": False, "error": "", "request_id": "", "target_name": "", "connected": False}
        self.posters = Path("/homeassistant/www/ha-medien-kodi/posters")
        self.posters.mkdir(parents=True, exist_ok=True)
        super().initialize()
        self.ui["target_name"] = self.player_name
        with self.connection_file.open(encoding="utf-8") as handle:
            self.monitor = KodiClient(json.load(handle))
        self.monitor.timeout = 2
        self.run_every(self.poll, "now+5", 30)
        self.publish()

    def terminate(self):
        self.ui.update(busy=False,connected=False,checked_at="",error="Mediensteuerung wird neu geladen; noch nicht bereit.")
        self.publish()

    def publish(self):
        self.set_state("sensor.ha_mediensteuerung_kodi_dashboard", state="beschaeftigt" if self.ui["busy"] else "fehler" if self.ui["error"] else "bereit", attributes={"friendly_name": "HA-Mediensteuerung auf Kodi Dashboard", **self.ui, **{key:"true" if self.ui.get(key,default) else "false" for key,default in (("show_on_kodi",True),("replace_current",True),("kodi_output_available",False))}})

    def poll(self, kwargs):
        try:
            self.monitor.rpc("JSONRPC.Ping")
            playing = KodiMediaPlayer(self.monitor).get_now_playing()
            self.ui.update(connected=True, connection_error="", now_playing=[p.to_dict() for p in playing])
        except Exception:
            self.ui.update(connected=False, connection_error="Kodi antwortet nicht. Ist Kodi auf dem Fernseher gestartet?", now_playing=[])
        self.ui["checked_at"] = datetime.now(timezone.utc).isoformat()
        self.publish()

    def poster(self, row):
        thumb = row.get("thumbnail", "")
        if not thumb:
            return ""
        key = hashlib.sha256(thumb.encode()).hexdigest() + ".jpg"
        destination = self.posters / key
        if destination.exists():
            return "/local/ha-medien-kodi/posters/" + key
        try:
            content = self.artwork.fetch(thumb)
            if not content:
                return ""
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(content)
            temporary.replace(destination)
            return "/local/ha-medien-kodi/posters/" + key
        except Exception:
            return ""

    def display_items(self, rows):
        with ThreadPoolExecutor(max_workers=6) as executor:
            posters = list(executor.map(self.poster, rows))
        return [{**{k: row.get(k) for k in ("kind", "library_id", "title", "year", "season", "episode")}, "poster": poster} for row, poster in zip(rows, posters)]

    def execute(self, data):
        action = data.get("action", "diagnostic")
        self.ui.update(busy=True, error="", startup_status="", request_id=str(data.get("request_id", ""))[:100], action=action)
        self.publish()
        started = time.monotonic()
        try:
            if action == "search":
                query = data.get("query", "")
                kind = data.get("media_type", "movie")
                report = super().execute({**data, "limit": 24})
                if not report["ok"]:
                    raise MediaError(report["error"])
                result = report["result"]
                self.ui.update(items=self.display_items(result["items"]), total=result["total"], view="search", heading='Treffer fuer "' + query + '"', query=query, media_type=kind)
            else:
                report = super().execute(data)
                if report["ok"] and action == "seasons":
                    rows = report["result"].get("items", [])
                    self.ui.update(items=[{"kind": "season", "library_id": data["series_id"], "season": r["number"], "title": "Staffel " + str(r["number"]), "episode_count": r["episode_count"]} for r in rows], total=len(rows), view="seasons", heading=str(data.get("title", "Staffeln")), series_id=data["series_id"])
                elif report["ok"] and action == "episodes":
                    result = report["result"]
                    rows = result["items"]
                    self.ui.update(items=self.display_items(rows), total=result["total"], view="episodes", heading=str(data.get("title", "Episoden")))
                elif report["ok"] and action == "diagnostic":
                    self.ui.update(movie_count=report["result"]["movies"]["total"], series_count=report["result"]["series"]["total"])
            if action == "voice":
                voice = report.get("result", {})
                self.ui.update(last_voice_text=str(data.get('text','')),last_voice_interpretation=voice.get('interpretation') or 'Nicht vollständig erkannt',last_voice_response=voice.get('speech') or report.get('error',''),last_voice_at=datetime.now(timezone.utc).isoformat(),last_voice_target=self.player_name,last_voice_backend=getattr(self,'backend','kodi'))

                self.ui["voice_speech"] = voice.get("speech", report.get("error", ""))
                if voice.get("handled"):
                    rows = voice.get("choices") or ([voice["selected"]] if voice.get("selected") else [])
                    items = self.display_items(rows)
                    if voice.get("choices"):
                        items = [{**item, "title": str(i+1)+". "+item["title"]} for i,item in enumerate(items)]
                    self.ui.update(items=items, total=voice.get("total",len(rows)), view="voice", heading="Treffer aus der Sprachsuche", voice_text=str(data.get("text", "")))
            if action in ('search','voice'):
                tv=report.get('result',{}).get('tv_results',{})
                self.ui['output_status']='Trefferliste in Kodi geöffnet; zusätzlich im Dashboard verfügbar.' if tv.get('shown') else 'Suchergebnisse im Dashboard.'
            self.ui["error"] = report.get("error", "")
            self.ui["last_ok"] = report["ok"]
            self.ui["elapsed_ms"] = report["elapsed_ms"]
        except Exception as exc:
            self.ui.update(error=str(exc) if isinstance(exc, MediaError) else "Dashboard-Auftrag fehlgeschlagen: " + type(exc).__name__, last_ok=False, elapsed_ms=round((time.monotonic()-started)*1000, 1))
        if self.ui["error"] and action in ("search", "seasons", "episodes"):
            self.ui.update(items=[], total=0)
        self.ui["history"] = ([{"at": datetime.now(timezone.utc).isoformat(), "action": action, "ok": self.ui["last_ok"], "ms": self.ui["elapsed_ms"], "error": self.ui["error"]}] + self.ui["history"])[:10]
        self.ui["busy"] = False
        self.ui["completed_request_id"] = self.ui["request_id"]
        self.poll({})
