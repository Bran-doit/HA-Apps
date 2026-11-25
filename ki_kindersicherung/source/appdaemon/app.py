"""KI-gestützte Kindersicherung für Home Assistant und AppDaemon."""

from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import appdaemon.plugins.hass.hassapi as hass
import requests
import yaml
from aiohttp import web


class KiKindersicherung(hass.Hass):
    """Steuert harte und aufgabenbasierte Mediensperren."""

    NS = "ki_kindersicherung"
    MODE_OFF = "aus"
    MODE_LOCKED = "kindersicherung"
    MODE_CONDITIONAL = "bedingt"
    MODE_SINGLE_QUESTION = "einzelaufgabe"
    MODE_FREE_QUESTION = "freie_aufgabe"
    DUMMY_PLAYER = "media_player.ki_kinderschutz_dummy"
    TV_TASK_URL = "__APPDAEMON_URL__/app/ki_kindersicherung_aufgabe"
    TV_QUIZ_URL = "__APPDAEMON_URL__/app/ki_kindersicherung_quiz"
    DEBUG_DISPLAY_URL = "__APPDAEMON_URL__/app/ki_kindersicherung_debug"
    SPEECH_PAUSE_SELECT = "select.wohnen_nabu_sprechpausen_erkennung"
    TTS_VOICE_CATALOG = {
        "tts.openai_tts": [
            (voice.lower(), voice) for voice in (
                "Marin", "Cedar", "Alloy", "Ash", "Ballad", "Coral", "Echo",
                "Fable", "Nova", "Onyx", "Sage", "Shimmer", "Verse",
            )
        ],
        "tts.google_ai_tts": [
            (voice.split(" ", 1)[0].lower(), voice) for voice in (
                "Zephyr (Hell)", "Puck (Lebhaft)", "Charon (Informativ)",
                "Kore (Bestimmt)", "Fenrir (Begeistert)", "Leda (Jugendlich)",
                "Orus (Bestimmt)", "Aoede (Unbeschwert)", "Callirrhoe (Gelassen)",
                "Autonoe (Hell)", "Enceladus (Hauchig)", "Iapetus (Klar)",
                "Umbriel (Gelassen)", "Algieba (Sanft)", "Despina (Sanft)",
                "Erinome (Klar)", "Algenib (Rau)", "Rasalgethi (Informativ)",
                "Laomedeia (Lebhaft)", "Achernar (Weich)", "Alnilam (Bestimmt)",
                "Schedar (Ausgeglichen)", "Gacrux (Reif)", "Pulcherrima (Direkt)",
                "Achird (Freundlich)", "Zubenelgenubi (Locker)",
                "Vindemiatrix (Sanft)", "Sadachbia (Lebendig)",
                "Sadaltager (Sachkundig)", "Sulafat (Warm)",
            )
        ],
    }

    def initialize(self) -> None:
        self._handles: List[Any] = []
        self._media_handles: List[Any] = []
        self._voice_handles: List[Any] = []
        self._event_handles: List[Any] = []
        self._release_timer = None
        self._answer_timer = None
        self._activation_timer = None
        self._question = ""
        self._question_id = 0
        self._question_topic = ""
        self._question_subtopic = ""
        self._question_audience = "kind"
        self._tv_speech_text = ""
        self._tv_speech_id = 0
        self._tv_audio_url = ""
        self._tv_audio_id = 0
        self._tv_hide_timer = None
        self._quiz_running = False
        self._quiz_player_index = 0
        self._quiz_round = 0
        self._quiz_question = ""
        self._quiz_solution = ""
        self._quiz_choices: List[str] = []
        self._quiz_topic = ""
        self._quiz_feedback = ""
        self._quiz_scores: Dict[str, int] = {}
        self._quiz_winner = ""
        self._quiz_finale_message = ""
        self._quiz_question_history: List[str] = []
        self._quiz_question_id = 0
        self._quiz_attempts = 0
        self._quiz_voice_player = ""
        self._quiz_advance_timer = None
        self._solution = ""
        self._attempts = 0
        self._releases = 0
        self._mode = self.MODE_OFF
        self._mode_before_free = self.MODE_OFF
        self._session_voice_player = ""
        self._last_assist_satellite = ""
        self._last_assist_seen: Optional[datetime] = None
        self._free_topic = ""
        self._free_subtopic = ""
        self._time_limit_text = "Keine"
        self._locked_until: Optional[datetime] = None
        self._media_before_lock: Dict[str, Dict[str, Any]] = {}
        self._restoring_media = False
        self._history: List[str] = []
        self._conversation_history: List[Dict[str, str]] = []
        config_path = Path(self.args.get("config_file", "/config/ki_kindersicherung/config.yaml"))
        self._conversation_file = config_path.with_name("conversation_history.json")
        self._load_conversation_history()

        self._load_config()
        self._ensure_dummy_player()
        self._register_admin_web()
        self._publish_initial_state()
        self._register_listeners()
        self.run_in(self._configure_speech_pause, 5)
        self._log_event("App gestartet")

    def terminate(self) -> None:
        for handle in self._handles:
            try:
                self.cancel_listen_state(handle)
            except Exception:
                pass
        for handle in self._event_handles:
            try:
                self.cancel_listen_event(handle)
            except Exception:
                pass
        for handle in self._media_handles:
            try:
                self.cancel_listen_state(handle)
            except Exception:
                pass
        for handle in self._voice_handles:
            try:
                self.cancel_listen_state(handle)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Konfiguration und Home-Assistant-Anbindung
    # ------------------------------------------------------------------
    @staticmethod
    def _topics_with_defaults(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        default_subtopics = [
            [
                {"name": "Einmaleins", "enabled": True, "prompt": "Stelle genau eine Aufgabe aus dem kleinen Einmaleins von 1 bis 10."},
                {"name": "Addition", "enabled": True, "prompt": "Stelle eine Additionsaufgabe mit zwei Zahlen und einem Ergebnis bis 100. Variiere Aufgaben mit und ohne Zehnerübergang."},
                {"name": "Subtraktion", "enabled": True, "prompt": "Stelle eine Subtraktionsaufgabe im Zahlenraum bis 100 mit einem nicht negativen Ergebnis. Variiere Aufgaben mit und ohne Zehnerübergang."},
            ],
            [
                {"name": "Wortschatz", "enabled": True, "prompt": "Stelle eine eindeutig bewertbare Aufgabe zu Wortbedeutungen, Gegenteilen oder verwandten Wörtern."},
                {"name": "Rechtschreibung", "enabled": True, "prompt": "Stelle eine mündlich eindeutig beantwortbare Aufgabe zur deutschen Rechtschreibung."},
                {"name": "Grammatik und Satzbau", "enabled": True, "prompt": "Stelle eine Aufgabe zu Wortarten, Satzgliedern oder einem einfachen korrekten Satzbau."},
            ],
            [
                {"name": "Natur und Umwelt", "enabled": True, "prompt": "Stelle eine altersgerechte Wissensfrage zu Tieren, Pflanzen, Wetter oder Umwelt."},
                {"name": "Mensch und Alltag", "enabled": True, "prompt": "Stelle eine altersgerechte Verständnisfrage zum Körper, zur Gesundheit oder zum Alltag."},
                {"name": "Technik und Zusammenleben", "enabled": True, "prompt": "Stelle eine altersgerechte Frage zu einfacher Technik, Verkehr, Berufen oder gesellschaftlichem Zusammenleben."},
            ],
            [
                {"name": "Sprachrätsel", "enabled": True, "prompt": "Stelle ein kurzes Sprach- oder Worträtsel mit einer nachvollziehbaren Lösung."},
                {"name": "Logisches Denken", "enabled": True, "prompt": "Stelle eine kurze Denk- oder Kombinationsaufgabe mit einer eindeutig prüfbaren Lösung."},
                {"name": "Erzählen und Kombinieren", "enabled": True, "prompt": "Stelle eine kleine kreative Aufgabe und nenne in der Musterlösung klare Kriterien, anhand derer die Antwort fair bewertet werden kann."},
            ],
        ]
        result = []
        for index, topic in enumerate(topics or []):
            normalized = dict(topic)
            normalized.setdefault("subtopics_enabled", True)
            subtopics = normalized.get("subtopics")
            if not isinstance(subtopics, list) or not subtopics:
                defaults = default_subtopics[index] if index < len(default_subtopics) else []
                normalized["subtopics"] = [dict(item) for item in defaults]
            result.append(normalized)
        return result

    @staticmethod
    def _adult_topics_with_defaults(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        defaults = [
            {
                "name": "Geografie",
                "enabled": True,
                "weight": 17,
                "difficulty": "gemischt",
                "subtopics": "Länder und Hauptstädte, Landschaften, Europa, Weltgeografie",
                "prompt": "Stelle eine eindeutig beantwortbare Wissensfrage aus der Geografie.",
            },
            {
                "name": "Geschichte",
                "enabled": True,
                "weight": 17,
                "difficulty": "gemischt",
                "subtopics": "Antike, Mittelalter, Neuzeit, Zeitgeschichte",
                "prompt": "Stelle eine eindeutig beantwortbare Frage zu historischen Ereignissen, Personen oder Epochen.",
            },
            {
                "name": "Wissenschaft und Technik",
                "enabled": True,
                "weight": 17,
                "difficulty": "gemischt",
                "subtopics": "Naturwissenschaften, Medizin, Erfindungen, moderne Technik",
                "prompt": "Stelle eine eindeutig beantwortbare Frage aus Wissenschaft oder Technik.",
            },
            {
                "name": "Kunst und Literatur",
                "enabled": True,
                "weight": 17,
                "difficulty": "gemischt",
                "subtopics": "Malerei, Musik, Architektur, Bücher und Autoren",
                "prompt": "Stelle eine eindeutig beantwortbare Frage zu Kunst, Musik oder Literatur.",
            },
            {
                "name": "Unterhaltung",
                "enabled": True,
                "weight": 16,
                "difficulty": "gemischt",
                "subtopics": "Film, Fernsehen, Popkultur, bekannte Persönlichkeiten",
                "prompt": "Stelle eine eindeutig beantwortbare Frage aus Film, Fernsehen oder Unterhaltung.",
            },
            {
                "name": "Sport und Freizeit",
                "enabled": True,
                "weight": 16,
                "difficulty": "gemischt",
                "subtopics": "Sportarten, Wettbewerbe, Rekorde, Spiele und Freizeit",
                "prompt": "Stelle eine eindeutig beantwortbare Frage zu Sport, Spielen oder Freizeit.",
            },
        ]
        source = topics if isinstance(topics, list) and topics else defaults
        result = []
        for index, default in enumerate(defaults):
            topic = source[index] if index < len(source) and isinstance(source[index], dict) else {}
            normalized = dict(default)
            normalized.update(topic)
            normalized["enabled"] = bool(normalized.get("enabled", True))
            try:
                normalized["weight"] = min(100, max(0, int(normalized.get("weight", default["weight"]))))
            except (TypeError, ValueError):
                normalized["weight"] = default["weight"]
            if normalized.get("difficulty") not in ("leicht", "mittel", "schwer", "gemischt"):
                normalized["difficulty"] = "gemischt"
            result.append(normalized)
        return result

    def _load_config(self) -> None:
        config_file = Path(self.args.get("config_file", "/config/apps/ki_kindersicherung/config.yaml"))
        with config_file.open("r", encoding="utf-8") as stream:
            config = yaml.safe_load(stream) or {}

        self.config = config
        self.enabled = bool(config.get("enabled", True))
        self.tv_display_supported = bool(self.args.get("tv_display_supported", True))
        self.tv_display_enabled = self.tv_display_supported and bool(config.get("tv_display_enabled", True))
        self.quiz_tv_display_enabled = self.tv_display_supported and bool(config.get("quiz_tv_display_enabled", True))
        self.debug_mode = bool(config.get("debug_mode", False))
        self.debug_voice_player = str(config.get("debug_voice_player", "")).strip()
        self.debug_display_page = str(config.get("debug_display_page", "task")).lower()
        if self.debug_display_page not in ("task", "quiz"):
            self.debug_display_page = "task"
        self.config["debug_mode"] = self.debug_mode
        self.config["debug_voice_player"] = self.debug_voice_player
        self.config["debug_display_page"] = self.debug_display_page
        self.config["quiz_tv_display_enabled"] = self.quiz_tv_display_enabled
        self.quiz_enabled = bool(config.get("quiz_enabled", False))
        self.quiz_reveal_choices_after_wrong = bool(config.get("quiz_reveal_choices_after_wrong", False))
        self.config["quiz_reveal_choices_after_wrong"] = self.quiz_reveal_choices_after_wrong
        self.quiz_child_attempts = max(1, min(10, int(config.get("quiz_child_attempts", 3))))
        self.quiz_adult_attempts = max(1, min(10, int(config.get("quiz_adult_attempts", 2))))
        self.config["quiz_child_attempts"] = self.quiz_child_attempts
        self.config["quiz_adult_attempts"] = self.quiz_adult_attempts
        self.quiz_subject_mode = str(config.get("quiz_subject_mode", "variabel"))
        if self.quiz_subject_mode not in ("variabel", "fest"):
            self.quiz_subject_mode = "variabel"
        self.quiz_subject = str(config.get("quiz_subject", "Allgemeinwissen")).strip() or "Allgemeinwissen"
        history = config.get("quiz_question_history", [])
        self._quiz_question_history = (
            [str(item).strip() for item in history if str(item).strip()][-100:]
            if isinstance(history, list)
            else []
        )
        raw_quiz_players = config.get("quiz_players", [])
        if not isinstance(raw_quiz_players, list):
            raw_quiz_players = []
        self.quiz_players = []
        for index in range(6):
            source = raw_quiz_players[index] if index < len(raw_quiz_players) and isinstance(raw_quiz_players[index], dict) else {}
            role = str(source.get("role", "kind" if index == 0 else "erwachsen"))
            if role not in ("kind", "erwachsen"):
                role = "erwachsen"
            try:
                age = min(17, max(4, int(source.get("age", 9))))
            except (TypeError, ValueError):
                age = 9
            difficulty = str(source.get("difficulty", "mittel")).lower()
            if difficulty == "normal":
                difficulty = "mittel"
            if difficulty not in ("leicht", "mittel", "schwer"):
                difficulty = "mittel"
            self.quiz_players.append({
                "enabled": bool(source.get("enabled", index == 0)),
                "name": str(source.get("name", "Alex" if index == 0 else f"Spieler {index + 1}")).strip() or f"Spieler {index + 1}",
                "role": role,
                "age": age,
                "difficulty": difficulty,
            })
        self.config["quiz_enabled"] = self.quiz_enabled
        self.config["quiz_subject_mode"] = self.quiz_subject_mode
        self.config["quiz_subject"] = self.quiz_subject
        self.config["quiz_players"] = self.quiz_players
        self.dummy_mode = bool(config.get("dummy_mode", False))
        self.configured_media_players = [x for x in config.get("media_players", []) if x]
        self.media_players = (
            [self.DUMMY_PLAYER]
            if self.debug_mode or self.dummy_mode
            else list(self.configured_media_players)
        )
        self.voice_player = config.get("voice_player", "")
        self.speech_engine = config.get("speech_engine", "tts.piper")
        self.speech_voice = str(config.get("speech_voice", ""))
        self.agent_id = config.get("conversation_agent", "")
        self.language = config.get("language", "de")
        self.release_interval = max(1, int(config.get("release_interval_minutes", 20)))
        self.maximum_releases = max(0, int(config.get("maximum_releases", 6)))
        self.answer_timeout = max(1, int(config.get("answer_timeout_minutes", 5)))
        self.maximum_attempts = max(1, int(config.get("maximum_attempts", 2)))
        self.allow_new_question = bool(config.get("allow_new_question", True))
        self.parent_pin = str(config.get("parent_pin", "")).strip()
        self.base_prompt = str(config.get("base_prompt", ""))
        self.language_style_prompt = str(config.get(
            "language_style_prompt",
            "Sprich locker, freundlich und natürlich. Formuliere für Kinder kindgerecht, motivierend und ohne steife Wendungen; bei Erwachsenen ungezwungen, aber nicht kindlich.",
        )).strip()
        self.config["language_style_prompt"] = self.language_style_prompt
        self.footer_prompt = str(config.get("footer_prompt", ""))
        self.footer_prompt_enabled = bool(config.get("footer_prompt_enabled", True))
        self.wrong_answer_prompt = str(config.get("wrong_answer_prompt", ""))
        self.correct_answer_prompt = str(config.get("correct_answer_prompt", ""))
        self.topics = self._topics_with_defaults(config.get("topics", []))
        self.config["topics"] = self.topics
        self.adult_topics = self._adult_topics_with_defaults(config.get("adult_topics", []))
        self.config["adult_topics"] = self.adult_topics

    def _register_listeners(self) -> None:
        controls = {
            "input_button.ki_kinderschutz_aktivieren": self._ui_lock,
            "input_button.ki_bedingt_aktivieren": self._ui_conditional,
            "input_button.ki_kinderschutz_deaktivieren": self._ui_unlock,
            "input_button.ki_aufgabe_freigeben": self._ui_release,
            "input_button.ki_aufgabe_ablehnen": self._ui_reject,
            "input_button.ki_neue_aufgabe": self._ui_new_question,
            "input_button.ki_log_leeren": self._ui_clear_log,
            "input_button.ki_konfiguration_speichern": self._ui_save,
            "input_button.ki_konfiguration_neuladen": self._ui_reload,
        }
        for entity, callback in controls.items():
            self._handles.append(self.listen_state(callback, entity))

        self._handles.append(
            self.listen_state(self._answer_changed, "input_text.ki_kinderschutz_antwort")
        )
        self._handles.append(
            self.listen_state(
                self._voice_devices_changed,
                "sensor.kindersicherung_sprachgerate",
                attribute="all",
            )
        )
        self._event_handles.append(
            self.listen_event(self._command_event, "ki_kinderschutz_sprachbefehl")
        )
        self._refresh_media_listeners()
        self._refresh_voice_listeners()
        self.run_in(self._sync_voice_device_options, 3)

    def _refresh_media_listeners(self) -> None:
        for handle in self._media_handles:
            try:
                self.cancel_listen_state(handle)
            except Exception:
                pass
        self._media_handles = [
            self.listen_state(self._media_state_changed, entity)
            for entity in self.media_players
        ]

    def _refresh_voice_listeners(self) -> None:
        for handle in self._voice_handles:
            try:
                self.cancel_listen_state(handle)
            except Exception:
                pass
        satellites = self.get_state("assist_satellite") or {}
        self._voice_handles = []
        if isinstance(satellites, dict):
            self._voice_handles = [
                self.listen_state(self._assist_satellite_changed, entity)
                for entity in satellites
            ]

    def _assist_satellite_changed(self, entity, attribute, old, new, kwargs) -> None:
        if str(new).lower() in ("listening", "processing", "responding"):
            self._last_assist_satellite = str(entity)
            self._last_assist_seen = self.datetime()

    def _voice_devices_changed(self, entity, attribute, old, new, kwargs) -> None:
        self._refresh_voice_listeners()
        self._sync_voice_device_options()

    def _voice_device_mappings(self) -> List[Dict[str, str]]:
        mappings = self.get_state(
            "sensor.kindersicherung_sprachgerate",
            attribute="devices",
        ) or []
        if not isinstance(mappings, list):
            return []
        return [item for item in mappings if isinstance(item, dict)]

    def _sync_voice_device_options(self, kwargs: Optional[Dict[str, Any]] = None) -> None:
        players = [
            str(item.get("media_player") or "")
            for item in self._voice_device_mappings()
            if item.get("media_player")
        ]
        if self.voice_player and self.voice_player not in players:
            players.append(self.voice_player)
        if not players:
            return
        try:
            self.call_service(
                "input_select/set_options",
                entity_id="input_select.ki_standard_sprachgeraet",
                options=players,
            )
        except Exception as exc:
            self.error(f"Sprachgeräteliste konnte nicht aktualisiert werden: {exc}")

    def _resolve_voice_player(self, device_hint: str = "") -> str:
        hint = str(device_hint or "").strip()
        mappings = self._voice_device_mappings()
        if hint and hint != "home_assistant":
            for item in mappings:
                if hint in {
                    str(item.get("satellite") or ""),
                    str(item.get("device_id") or ""),
                    str(item.get("media_player") or ""),
                }:
                    return str(item.get("media_player") or self.voice_player)
        if (
            self._last_assist_satellite
            and self._last_assist_seen
            and (self.datetime() - self._last_assist_seen).total_seconds() <= 120
        ):
            for item in mappings:
                if str(item.get("satellite") or "") == self._last_assist_satellite:
                    return str(item.get("media_player") or self.voice_player)
        return self.voice_player

    def _media_state_changed(self, entity, attribute, old, new, kwargs) -> None:
        if (
            self._restoring_media
            or self._mode != self.MODE_CONDITIONAL
            or not self._question
            or str(new) not in ("playing", "buffering")
        ):
            return
        if entity not in self._media_before_lock:
            self._media_before_lock[entity] = {"state": str(old or "idle"), "source": None}
        try:
            if entity == self.DUMMY_PLAYER:
                self._set_dummy_state("paused")
            else:
                self.call_service("media_player/media_pause", entity_id=entity)
            self._log_event(f"Manuellen Wiedergabestart verhindert: {entity}")
        except Exception as exc:
            self.error(f"Konnte erneute Wiedergabe auf {entity} nicht pausieren: {exc}")

    def _register_admin_web(self) -> None:
        """Registriert HTML ausschließlich als Webroute und Daten als JSON-Endpunkte."""
        self.register_route(self._admin_page, "ki_kindersicherung_admin")
        self.register_route(self._task_display_page, "ki_kindersicherung_aufgabe")
        self.register_route(self._quiz_display_page, "ki_kindersicherung_quiz")
        self.register_route(self._debug_display_page, "ki_kindersicherung_debug")
        self.register_endpoint(self._admin_status, "ki_kindersicherung_admin_status")
        self.register_endpoint(self._admin_config, "ki_kindersicherung_admin_config")
        self.register_endpoint(self._admin_action, "ki_kindersicherung_admin_action")
        self.register_endpoint(self._admin_logs, "ki_kindersicherung_admin_logs")
        self.register_endpoint(self._admin_conversation, "ki_kindersicherung_admin_conversation")
        self.log("Admin-Seite registriert: /app/ki_kindersicherung_admin")
        self.log("TV-Aufgabenseite registriert: /app/ki_kindersicherung_aufgabe")
        self.log("TV-Wissensquiz registriert: /app/ki_kindersicherung_quiz")
        self.log("Debug-Webausgabe registriert: /app/ki_kindersicherung_debug")

    async def _admin_page(self, request: Any, kwargs: Dict[str, Any]) -> web.Response:
        return web.Response(text=ADMIN_HTML, content_type="text/html")

    async def _task_display_page(self, request: Any, kwargs: Dict[str, Any]) -> web.Response:
        return web.Response(text=TASK_DISPLAY_HTML, content_type="text/html")

    async def _quiz_display_page(self, request: Any, kwargs: Dict[str, Any]) -> web.Response:
        return web.Response(text=QUIZ_DISPLAY_HTML, content_type="text/html")

    async def _debug_display_page(self, request: Any, kwargs: Dict[str, Any]) -> web.Response:
        return web.Response(text=DEBUG_DISPLAY_HTML, content_type="text/html")

    def _admin_status(self, args: Dict[str, Any], request_args: Dict[str, Any]):
        active_quiz_players = [player for player in self.quiz_players if player["enabled"]]
        quiz_player_index = (
            self._quiz_player_index % len(active_quiz_players) if active_quiz_players else 0
        )
        current_quiz_player = (
            active_quiz_players[quiz_player_index]
            if self._quiz_running and active_quiz_players
            else None
        )
        return {
            "status": "ok",
            "time": self.datetime().strftime("%d.%m.%Y %H:%M:%S"),
            "enabled": self.enabled,
            "tv_display_enabled": self.tv_display_enabled or self.debug_mode,
            "tv_display_configured": self.tv_display_enabled,
            "debug_mode": self.debug_mode,
            "debug_voice_player": self.debug_voice_player,
            "debug_display_page": self.debug_display_page,
            "debug_display_url": self.DEBUG_DISPLAY_URL,
            "tv_display_url": self.TV_TASK_URL,
            "quiz_display_url": self.TV_QUIZ_URL,
            "quiz_tv_display_enabled": self.quiz_tv_display_enabled,
            "mode": self._mode,
            "mode_label": {
                self.MODE_OFF: "-",
                self.MODE_LOCKED: "Kindersicherung",
                self.MODE_CONDITIONAL: "Bedingte Kindersicherung",
                self.MODE_SINGLE_QUESTION: "Eine Aufgabe",
                self.MODE_FREE_QUESTION: "Freie Aufgabe",
            }.get(self._mode, self._mode),
            "active": self._mode in (self.MODE_LOCKED, self.MODE_CONDITIONAL),
            "media_status": self._combined_media_state(),
            "media_players": self.media_players,
            "voice_player": self.voice_player,
            "speech_engine": self.speech_engine,
            "conversation_agent": self.agent_id,
            "question": self._question,
            "question_id": self._question_id,
            "question_topic": self._question_topic,
            "question_subtopic": self._question_subtopic,
            "tv_speech_text": self._tv_speech_text,
            "tv_speech_id": self._tv_speech_id,
            "tv_audio_url": self._tv_audio_url,
            "tv_audio_id": self._tv_audio_id,
            "tv_footer_prompt": (
                self.footer_prompt if self.footer_prompt_enabled and self.tv_display_enabled else ""
            ),
            "quiz": {
                "ready": self._quiz_running,
                "question": self._quiz_question,
                "question_id": self._quiz_question_id,
                "solution": self._quiz_solution if not self._quiz_running else "",
                "choices": (
                    self._quiz_choices
                    if not self.quiz_reveal_choices_after_wrong or self._quiz_attempts > 0 or self._quiz_question_needs_choices()
                    else []
                ),
                "choices_hidden_until_wrong": self.quiz_reveal_choices_after_wrong,
                "attempts": self._quiz_attempts,
                "topic": self._quiz_topic,
                "feedback": self._quiz_feedback,
                "scores": self._quiz_scores,
                "winner": self._quiz_winner,
                "finale_message": self._quiz_finale_message,
                "players": active_quiz_players,
                "current_player_index": quiz_player_index,
                "current_player": current_quiz_player,
                "round": self._quiz_round,
                "configured": self.quiz_enabled,
                "player_count": len([player for player in self.quiz_players if player["enabled"]]),
                "subject_mode": self.quiz_subject_mode,
                "subject": self.quiz_subject,
                "child_topics": [topic for topic in self.topics if int(topic.get("weight", 0)) > 0],
                "adult_topics": [topic for topic in self.adult_topics if topic.get("enabled") and int(topic.get("weight", 0)) > 0],
            },
            "answer_until": self._answer_deadline_text(),
            "attempts": self._attempts,
            "maximum_attempts": self.maximum_attempts,
            "releases": self._releases,
            "maximum_releases": self.maximum_releases,
            "release_interval_minutes": self.release_interval,
            "answer_timeout_minutes": self.answer_timeout,
            "time_limit": self._time_limit_text,
            "summary": self.get_state("sensor.ki_kinderschutz_status") or "Bereit",
        }, 200

    def _admin_config(self, args: Dict[str, Any], request_args: Dict[str, Any]):
        payload = args or {}
        if not payload:
            return {"status": "ok", "config": self._admin_config_data()}, 200
        try:
            allowed = {
                "enabled", "tv_display_enabled", "quiz_tv_display_enabled", "debug_mode", "debug_voice_player", "debug_display_page", "quiz_enabled", "quiz_reveal_choices_after_wrong", "quiz_child_attempts", "quiz_adult_attempts", "quiz_subject_mode", "quiz_subject", "quiz_players", "dummy_mode", "media_players", "voice_player", "speech_engine", "speech_voice", "conversation_agent",
                "release_interval_minutes", "maximum_releases", "answer_timeout_minutes",
                "maximum_attempts", "allow_new_question", "base_prompt", "language_style_prompt", "footer_prompt", "footer_prompt_enabled",
                "wrong_answer_prompt", "correct_answer_prompt", "topics", "adult_topics", "parent_pin",
            }
            for key in allowed:
                if key in payload:
                    self.config[key] = payload[key]
            self._write_config()
            self._load_config()
            self._refresh_media_listeners()
            self._log_event("Konfiguration über Verwaltungsseite gespeichert")
            return {"status": "ok", "message": "Konfiguration gespeichert.", "config": self._admin_config_data()}, 200
        except Exception as exc:
            self.error(f"Admin-Konfiguration fehlgeschlagen: {exc}")
            return {"status": "error", "message": str(exc)}, 500

    def _admin_config_data(self) -> Dict[str, Any]:
        result = dict(self.config)
        discovered = self.get_state("media_player") or {}
        room_sensor = "sensor.kindersicherung_sprachraum_media_player"
        room_players = self.get_state(room_sensor, attribute="media_players") or []
        room_area = str(self.get_state(room_sensor) or "kein_bereich")
        room_name = str(self.get_state(room_sensor, attribute="area_name") or room_area)
        if not isinstance(room_players, list):
            room_players = []
        permitted = {str(entity) for entity in room_players}
        permitted.update(self.configured_media_players)
        available = []
        if isinstance(discovered, dict):
            for entity, state in discovered.items():
                if not str(entity).startswith("media_player.") or str(entity) not in permitted:
                    continue
                details = self.get_state(str(entity), attribute="all") or {}
                attributes = details.get("attributes", {}) if isinstance(details, dict) else {}
                if isinstance(state, dict):
                    state = state.get("state", "unbekannt")
                available.append({
                    "entity_id": str(entity),
                    "name": str(attributes.get("friendly_name") or entity),
                    "state": str(state or "unbekannt"),
                    "in_voice_area": str(entity) in {str(item) for item in room_players},
                })
        result["available_media_players"] = sorted(available, key=lambda item: item["name"].lower())
        result["available_voice_players"] = sorted(
            self._voice_device_mappings(),
            key=lambda item: str(item.get("name") or item.get("media_player") or "").lower(),
        )
        result["media_player_scope_area"] = room_area
        result["media_player_scope_name"] = room_name
        available_speech_engines = []
        discovered_tts = self.get_state("tts") or {}
        if isinstance(discovered_tts, dict):
            for entity, state in discovered_tts.items():
                if not str(entity).startswith("tts."):
                    continue
                details = self.get_state(str(entity), attribute="all") or {}
                attributes = details.get("attributes", {}) if isinstance(details, dict) else {}
                if isinstance(state, dict):
                    state = state.get("state", "unbekannt")
                available_speech_engines.append({
                    "entity_id": str(entity),
                    "name": str(attributes.get("friendly_name") or entity),
                    "state": str(state or "unbekannt"),
                })
        result["available_speech_engines"] = sorted(
            available_speech_engines,
            key=lambda item: item["name"].lower(),
        )
        result["available_speech_voices"] = {
            engine: [{"voice_id": voice_id, "name": name} for voice_id, name in voices]
            for engine, voices in self.TTS_VOICE_CATALOG.items()
        }
        return result

    def _admin_action(self, args: Dict[str, Any], request_args: Dict[str, Any]):
        payload = args or {}
        action = str(payload.get("action") or "")
        try:
            if action == "activate_lock":
                self.activate_lock()
            elif action == "activate_conditional":
                self.activate_conditional()
            elif action == "single_question":
                self.start_single_question(str(payload.get("kind") or "allgemein"))
            elif action == "adult_question":
                self.start_single_question("erwachsen")
            elif action == "free_question":
                self.start_free_question(str(payload.get("command") or "Aufgabe"))
            elif action == "deactivate":
                self.deactivate("Über Verwaltungsseite deaktiviert")
            elif action == "approve":
                self._release_temporarily()
            elif action in ("reject", "new_question"):
                self.request_new_question()
            elif action == "repeat_question":
                self.repeat_question()
            elif action == "end_question":
                if self._mode == self.MODE_FREE_QUESTION:
                    self._finish_free_question("Freie Aufgabe über TV-Seite beendet")
                elif self._mode == self.MODE_SINGLE_QUESTION:
                    self._finish_single_question("Einzelaufgabe über TV-Seite beendet")
            elif action == "set_tv_display":
                self.config["tv_display_enabled"] = bool(payload.get("enabled"))
                self._write_config()
                self._load_config()
                self._log_event(
                    "TV-Aufgabenausgabe aktiviert"
                    if self.tv_display_enabled
                    else "TV-Aufgabenausgabe deaktiviert"
                )
                if not self.tv_display_enabled:
                    self._hide_tv_task_page()
            elif action == "set_quiz_tv_display":
                self.config["quiz_tv_display_enabled"] = bool(payload.get("enabled"))
                self._write_config()
                self._load_config()
                self._log_event(
                    "Quiz-TV-Ausgabe aktiviert"
                    if self.quiz_tv_display_enabled
                    else "Quiz-TV-Ausgabe deaktiviert; reiner Sprachmodus"
                )
            elif action == "show_tv_display":
                self._show_tv_task_page()
            elif action == "show_quiz_tv":
                if not self.quiz_tv_display_enabled and not self.debug_mode:
                    return {"status": "error", "message": "Die Quiz-TV-Ausgabe ist deaktiviert."}, 409
                self._show_tv_quiz_page()
            elif action == "stop_tv_display":
                self._hide_tv_task_page()
            elif action == "quiz_demo_start":
                if not self._start_quiz():
                    return {
                        "status": "error",
                        "message": self._quiz_feedback or "Klugscheißer konnte nicht gestartet werden.",
                    }, 409
            elif action == "quiz_next_player":
                if not self._next_quiz_player():
                    return {"status": "error", "message": "Klugscheißer ist nicht gestartet."}, 409
            elif action == "quiz_repeat_question":
                if not self._repeat_quiz_question():
                    return {"status": "error", "message": "Es gibt keine Quizfrage zum Wiederholen."}, 409
            elif action == "quiz_answer":
                answer = str(payload.get("answer") or "").strip()
                if not answer or not self._submit_quiz_answer(answer):
                    return {"status": "error", "message": "Die Quizantwort konnte nicht verarbeitet werden."}, 409
            elif action == "quiz_demo_reset":
                self._finish_quiz("Klugscheißer zurückgesetzt")
            elif action == "answer":
                self.submit_answer(str(payload.get("answer") or ""))
            elif action == "reload_config":
                self._load_config()
                self._log_event("Konfiguration neu geladen")
            elif action == "command":
                self.process_command(str(payload.get("command") or ""))
            elif action == "test_speech":
                message = str(payload.get("message") or "").strip()
                if not message:
                    return {"status": "error", "message": "Bitte einen Testtext eingeben."}, 400
                self.call_service("tts/clear_cache")
                self.run_in(
                    self._test_speech_callback,
                    0.6,
                    message=message,
                    voice_player=str(payload.get("voice_player") or self.voice_player),
                    speech_engine=str(payload.get("speech_engine") or self.speech_engine),
                    speech_voice=str(payload.get("speech_voice") or ""),
                )
            elif action == "test_tv_audio":
                message = str(payload.get("message") or "Dies ist ein Test der TV-Sprachausgabe.").strip()
                if not self._prepare_tv_audio(message):
                    return {"status": "error", "message": "TV-Audio konnte nicht erzeugt werden."}, 500
            elif action.startswith("dummy_"):
                if self._mode != self.MODE_OFF:
                    return {
                        "status": "error",
                        "message": "Der Dummy-Zustand kann nur bei ausgeschalteter Kindersicherung geändert werden.",
                    }, 409
                dummy_state = action.removeprefix("dummy_")
                if dummy_state not in ("playing", "paused", "idle", "off"):
                    return {"status": "error", "message": "Unbekannter Dummy-Zustand."}, 400
                self._set_dummy_state(dummy_state)
                self._publish_runtime(f"Dummy-Media-Player manuell auf {dummy_state} gesetzt")
            else:
                return {"status": "error", "message": "Unbekannte Aktion."}, 400
            return {"status": "ok", "message": "Aktion ausgeführt."}, 200
        except Exception as exc:
            self.error(f"Admin-Aktion fehlgeschlagen: {exc}")
            return {"status": "error", "message": str(exc)}, 500

    def _admin_logs(self, args: Dict[str, Any], request_args: Dict[str, Any]):
        payload = args or {}
        if payload.get("action") == "clear":
            self._history = []
            self._publish_log()
            return {"status": "ok", "message": "Log gelöscht.", "logs": ""}, 200
        lines = max(1, min(500, int(payload.get("lines", 300))))
        return {"status": "ok", "logs": "\n".join(reversed(self._history[:lines]))}, 200

    def _admin_conversation(self, args: Dict[str, Any], request_args: Dict[str, Any]):
        payload = args or {}
        if payload.get("action") == "clear":
            self._conversation_history = []
            self._save_conversation_history()
            return {"status": "ok", "message": "Konversationsverlauf gelöscht.", "entries": []}, 200
        return {"status": "ok", "entries": self._conversation_history}, 200

    def _write_config(self) -> None:
        config_file = Path(self.args.get("config_file", "/config/ki_kindersicherung/config.yaml"))
        temporary = config_file.with_suffix(".yaml.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(self.config, stream, allow_unicode=True, sort_keys=False)
        temporary.replace(config_file)

    def _publish_initial_state(self) -> None:
        self.set_state(
            "sensor.ki_kinderschutz_status",
            state="Bereit" if self.enabled else "Deaktiviert",
            attributes={"friendly_name": "Kindersicherung Status"},
        )
        self._publish_runtime()

    def _publish_runtime(self, status: Optional[str] = None) -> None:
        now = self.datetime().isoformat(timespec="seconds")
        media_state = self._combined_media_state()
        attrs = {
            "friendly_name": "Kindersicherung Laufzeitstatus",
            "modus": self._mode,
            "kindersicherung_aktiv": self._mode in (self.MODE_LOCKED, self.MODE_CONDITIONAL),
            "media_status": media_state,
            "letzte_ausfuehrung": now,
            "frage": self._question,
            "antwort_moeglich_bis": self._answer_deadline_text(),
            "zeitliche_begrenzung": self._time_limit_text,
            "versuche": self._attempts,
            "maximale_versuche": self.maximum_attempts,
            "freigaben": self._releases,
            "maximale_freigaben": self.maximum_releases,
        }
        self.set_state("sensor.ki_kinderschutz_laufzeit", state=self._mode, attributes=attrs)
        if status:
            self.set_state(
                "sensor.ki_kinderschutz_status",
                state=status[:255],
                attributes={"friendly_name": "Kindersicherung Status", "details": status},
            )

    # ------------------------------------------------------------------
    # Betriebsarten
    # ------------------------------------------------------------------
    def activate_lock(
        self,
        delay_minutes: int = 0,
        until: Optional[datetime] = None,
        limit_label: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            self._publish_runtime("Skript ist deaktiviert")
            return
        self._cancel_timer("_activation_timer")
        if delay_minutes > 0:
            self._activation_timer = self.run_in(self._activate_lock_callback, delay_minutes * 60, until=until)
            self._publish_runtime(f"Kindersicherung startet in {delay_minutes} Minuten")
            return
        self._mode = self.MODE_LOCKED
        self._locked_until = until
        self._time_limit_text = limit_label or (
            f"bis {until.strftime('%H:%M')} Uhr" if until else "Keine"
        )
        self._lock_media()
        if until and until > self.datetime():
            seconds = max(1, int((until - self.datetime()).total_seconds()))
            self._activation_timer = self.run_in(self._scheduled_unlock, seconds)
        self._log_event("Kindersicherung aktiviert")
        self._publish_runtime("Medien gesperrt")
        self._speak("Die Kindersicherung ist aktiviert.")

    def activate_conditional(self) -> None:
        if not self.enabled:
            self._publish_runtime("Skript ist deaktiviert")
            return
        self._mode = self.MODE_CONDITIONAL
        self._releases = 0
        self._attempts = 0
        self._log_event("Bedingte Kindersicherung aktiviert")
        self._start_question("Die bedingte Kindersicherung ist aktiviert. Hier ist deine Aufgabe.")

    def start_single_question(self, kind: str = "allgemein", speech_delay: float = 0.35) -> None:
        if not self.enabled:
            self._publish_runtime("Skript ist deaktiviert")
            return
        self._cancel_timer("_answer_timer")
        self._mode = self.MODE_SINGLE_QUESTION
        self._attempts = 0
        self._single_question_kind = kind
        self._log_event(f"Einzelaufgabe angefordert ({kind})")
        self._start_question(speech_delay=speech_delay)

    def start_free_question(self, command: str = "", speech_delay: float = 0.35) -> None:
        if not self.enabled:
            self._publish_runtime("Skript ist deaktiviert")
            return
        if self._mode == self.MODE_CONDITIONAL:
            message = "Die Pflichtaufgabe der bedingten Kindersicherung ist bereits aktiv."
            self._speak(message)
            self._publish_runtime(message)
            return
        if self._mode != self.MODE_FREE_QUESTION:
            self._mode_before_free = self.MODE_LOCKED if self._mode == self.MODE_LOCKED else self.MODE_OFF
            self._cancel_timer("_answer_timer")
        self._mode = self.MODE_FREE_QUESTION
        self._free_topic, self._free_subtopic = self._requested_topic(command)
        self._attempts = 0
        label = " / ".join(x for x in (self._free_topic, self._free_subtopic) if x) or "gewichtete Auswahl"
        self._log_event(f"Freie Aufgabe angefordert ({label})")
        self._start_question(speech_delay=speech_delay)

    def _finish_free_question(self, status: str = "Freie Aufgabe beendet") -> None:
        self._cancel_timer("_answer_timer")
        self._cancel_timer("_question_speech_timer")
        self._question = ""
        self._solution = ""
        self._attempts = 0
        self._free_topic = ""
        self._free_subtopic = ""
        self._mode = self._mode_before_free if self._mode_before_free == self.MODE_LOCKED else self.MODE_OFF
        self._mode_before_free = self.MODE_OFF
        self._session_voice_player = ""
        self._hide_tv_task_page(after_speech=True)
        self._log_event(status)
        self._publish_runtime(status)

    def deactivate(self, reason: str = "Manuell deaktiviert") -> None:
        self._mode = self.MODE_OFF
        self._time_limit_text = "Keine"
        self._locked_until = None
        self._question = ""
        self._solution = ""
        self._session_voice_player = ""
        self._hide_tv_task_page()
        self._cancel_timer("_release_timer")
        self._cancel_timer("_answer_timer")
        self._cancel_timer("_activation_timer")
        self._unlock_media()
        self._log_event(reason)
        self._publish_runtime("Kindersicherung aus")

    def _activate_lock_callback(self, kwargs: Dict[str, Any]) -> None:
        self.activate_lock(until=kwargs.get("until"))

    def _scheduled_unlock(self, kwargs: Dict[str, Any]) -> None:
        self.deactivate("Zeitliche Sperre beendet")

    # ------------------------------------------------------------------
    # Aufgaben-Dialog
    # ------------------------------------------------------------------
    def _active_quiz_players(self) -> List[Dict[str, Any]]:
        return [player for player in self.quiz_players if player.get("enabled")]

    def _quiz_question_needs_choices(self) -> bool:
        text = self._normalized_lookup(self._quiz_question)
        return any(phrase in text for phrase in (
            "der folgenden", "die folgenden", "den folgenden",
            "welche der", "welcher der", "welches der",
            "aus den antwortmoglichkeiten", "aus den antwortmöglichkeiten",
        ))

    def _quiz_screen_output_active(self) -> bool:
        return bool(self.quiz_tv_display_enabled and (self.debug_mode or self.tv_display_enabled))

    @staticmethod
    def _weighted_topic(topics: List[Dict[str, Any]]) -> Dict[str, Any]:
        valid = [topic for topic in topics if int(topic.get("weight", 0)) > 0]
        if not valid:
            return {}
        return random.choices(valid, weights=[int(topic.get("weight", 0)) for topic in valid], k=1)[0]

    def _start_quiz(self, show_on_tv: bool = False, voice_player: str = "") -> bool:
        players = self._active_quiz_players()
        if not players:
            self._quiz_feedback = "Kein Quizspieler ist aktiviert."
            return False
        if self.debug_mode:
            self.debug_display_page = "quiz"
            self.config["debug_display_page"] = "quiz"
        self._quiz_voice_player = voice_player or self.voice_player
        self._quiz_running = True
        self._quiz_player_index = 0
        self._quiz_round = 1
        self._quiz_scores = {player["name"]: 0 for player in players}
        self._quiz_winner = ""
        self._quiz_finale_message = ""
        self._quiz_feedback = ""
        self._cancel_timer("_quiz_advance_timer")
        self._quiz_attempts = 0
        if show_on_tv and self.tv_display_enabled and self.quiz_tv_display_enabled:
            self._show_tv_quiz_page()
        if not self._generate_quiz_question():
            self._quiz_running = False
            self._quiz_player_index = 0
            self._quiz_round = 0
            self._log_event(f"Klugscheißer konnte nicht gestartet werden: {self._quiz_feedback}")
            return False
        self._log_event("Klugscheißer gestartet")
        return True

    def _quiz_topic_for_player(self, player: Dict[str, Any]) -> Dict[str, Any]:
        if player.get("role") == "kind":
            topic = self._weighted_topic(self.topics)
            return {
                **topic,
                "difficulty": f"altersgerecht für ein {int(player.get('age', 9))}-jähriges Kind",
            }
        topics = self.adult_topics
        if self.quiz_subject_mode == "fest" and self.quiz_subject:
            wanted = self._normalized_lookup(self.quiz_subject)
            matches = [topic for topic in topics if wanted in self._normalized_lookup(topic.get("name", ""))]
            if matches:
                topics = matches
        topic = self._weighted_topic(topics)
        if not topic:
            return {}
        return {
            **topic,
            "difficulty": str(player.get("difficulty") or "mittel"),
        }

    def _local_math_quiz_question(self, topic: Dict[str, Any]) -> Dict[str, Any]:
        """Erzeugt bei KI-Ausfall eine eindeutige, bisher unbenutzte Rechenfrage."""
        subtopics = [
            self._normalized_lookup(item.get("name", ""))
            for item in topic.get("subtopics", [])
            if item.get("enabled", True)
        ]
        operations = []
        if any("einmaleins" in name or "multiplik" in name for name in subtopics):
            operations.append("mul")
        if any("addition" in name for name in subtopics):
            operations.append("add")
        if any("subtraktion" in name for name in subtopics):
            operations.append("sub")
        operations = operations or ["mul", "add", "sub"]
        history = {self._normalized_question(item) for item in self._quiz_question_history}
        for _ in range(60):
            operation = random.choice(operations)
            if operation == "mul":
                left, right = random.randint(2, 10), random.randint(2, 10)
                result = left * right
                question = f"Was ist das Ergebnis von {left} x {right}?"
                offsets = (-left, right, left, 10)
            elif operation == "add":
                left, right = random.randint(11, 69), random.randint(6, 30)
                result = left + right
                question = f"Was ist das Ergebnis von {left} + {right}?"
                offsets = (-10, -1, 1, 10)
            else:
                left, right = random.randint(30, 99), random.randint(6, 29)
                if right > left:
                    left, right = right, left
                result = left - right
                question = f"Was ist das Ergebnis von {left} - {right}?"
                offsets = (-10, -1, 1, 10)
            if self._normalized_question(question) in history:
                continue
            wrong = []
            for offset in offsets:
                candidate = max(0, result + offset)
                if candidate != result and candidate not in wrong:
                    wrong.append(candidate)
                if len(wrong) == 3:
                    break
            while len(wrong) < 3:
                candidate = max(0, result + random.choice((-12, -7, -3, 3, 7, 12)))
                if candidate != result and candidate not in wrong:
                    wrong.append(candidate)
            choices = [str(result), *(str(value) for value in wrong)]
            random.shuffle(choices)
            return {"question": question, "solution": str(result), "choices": choices}
        return {}

    def _generate_quiz_question(self) -> bool:
        players = self._active_quiz_players()
        if not self._quiz_running or not players:
            return False
        self._quiz_player_index %= len(players)
        player = players[self._quiz_player_index]
        topic = self._quiz_topic_for_player(player)
        if not topic:
            self._quiz_feedback = "Für diesen Spieler ist kein aktives Wissensgebiet konfiguriert."
            return False
        self._quiz_topic = str(topic.get("name") or "Allgemeinwissen")
        difficulty = str(topic.get("difficulty") or "gemischt")
        prompt = (
            "Erzeuge genau eine faire Wissensquizfrage auf Deutsch. "
            "Liefere vier kurze Antwortmöglichkeiten, davon genau eine richtige. "
            "Die Musterlösung muss wortgleich einer Antwortmöglichkeit entsprechen. "
            "Antworte ausschließlich als gültiges JSON mit question, solution und choices. "
            "choices ist eine Liste aus genau vier unterschiedlichen Texten.\n"
            f"Spieler: {player['name']}\nRolle: {player['role']}\n"
            f"Fachgebiet: {self._quiz_topic}\nSchwierigkeit: {difficulty}\n"
            f"Unterthemen: {topic.get('subtopics', '')}\nVorgabe: {topic.get('prompt', '')}\n"
            f"Sprachstil: {self.language_style_prompt}\n"
        )
        if player.get("role") == "kind":
            prompt += (
                f"Passe Wortwahl, Schulwissen und Komplexität an ein Kind im Alter von {player.get('age', 9)} Jahren an. "
                "Diese Altersangabe des Spielers ist verbindlich und überschreibt sämtliche abweichenden "
                "Alters-, Klassenstufen- oder Schwierigkeitsangaben aus Themen- und Unterthemenvorgaben.\n"
            )
            if "mathe" in self._normalized_lookup(self._quiz_topic):
                prompt += (
                    "Schreibe Rechenoperationen mit diesen gut sichtbaren Zeichen: Multiplikation mit kleinem x, "
                    "Division mit Doppelpunkt (:), Addition mit + und Subtraktion mit -. "
                    "Verwende nicht die ausgeschriebenen Wörter mal, geteilt durch, plus oder minus.\n"
                )
        else:
            prompt += (
                f"Der persönliche Schwierigkeitsgrad dieses erwachsenen Spielers ist {difficulty}. "
                "Er überschreibt abweichende Schwierigkeitsangaben des Fachgebiets.\n"
            )
        if self.quiz_reveal_choices_after_wrong:
            prompt += (
                "Die Antwortmöglichkeiten bleiben zunächst verborgen. Formuliere die Frage deshalb vollständig "
                "und ohne Bezug auf eine Auswahlliste. Verwende insbesondere keine Formulierungen wie "
                "‚welches der folgenden‘, ‚welche der folgenden‘ oder ‚wähle aus‘.\n"
            )
        if self._quiz_question_history:
            prompt += (
                "Folgende Fragen wurden in dieser Partie bereits gestellt und dürfen weder wörtlich noch "
                "inhaltlich wiederholt werden:\n- "
                + "\n- ".join(self._quiz_question_history[-20:])
                + "\n"
            )
        valid_question = False
        service_failed = False
        rejected_questions: List[str] = []
        for attempt in range(3):
            retry_instruction = ""
            if rejected_questions:
                retry_instruction = (
                    "Die folgenden Kandidaten wurden in diesem Erzeugungsvorgang bereits abgelehnt. "
                    "Verwende zwingend eine andere Aufgabenart beziehungsweise deutlich andere Zahlen und Formulierung:\n- "
                    + "\n- ".join(rejected_questions)
                    + f"\nVariationskennung: {random.randint(100000, 999999)}.\n"
                )
            ai_text = self._ask_ai(
                prompt
                + retry_instruction
                + ("Erzeuge jetzt zwingend eine andere, bisher nicht verwendete Frage.\n" if attempt else "")
            )
            if not ai_text:
                service_failed = True
                break
            result = self._parse_json(ai_text)
            choices = result.get("choices") if isinstance(result.get("choices"), list) else []
            choices = [str(choice).strip() for choice in choices if str(choice).strip()][:4]
            question = str(result.get("question") or "").strip()
            solution = str(result.get("solution") or "").strip()
            if player.get("role") == "kind" and "mathe" in self._normalized_lookup(self._quiz_topic):
                question = self._normalize_math_notation(question)
                solution = self._normalize_math_notation(solution)
                choices = [self._normalize_math_notation(choice) for choice in choices]
            normalized = self._normalized_question(question)
            complete = bool(
                question
                and solution
                and len(choices) == 4
                and len(set(choices)) == 4
                and solution in choices
            )
            if complete and normalized not in {
                self._normalized_question(item) for item in self._quiz_question_history
            }:
                self._quiz_question = question
                self._quiz_solution = solution
                self._quiz_choices = choices
                valid_question = True
                break
            if complete:
                rejected_questions.append(question)
                self._log_event("Wiederholte Quizfrage erkannt; neue Frage wird angefordert")
        if not valid_question and player.get("role") == "kind" and "mathe" in self._normalized_lookup(self._quiz_topic):
            fallback = self._local_math_quiz_question(topic)
            if fallback:
                self._quiz_question = str(fallback["question"])
                self._quiz_solution = str(fallback["solution"])
                self._quiz_choices = list(fallback["choices"])
                valid_question = True
                self._log_event("Lokale Mathematikfrage als KI-Ausfallsicherung erzeugt")
        if not valid_question:
            self._quiz_question = ""
            self._quiz_solution = ""
            self._quiz_choices = []
            self._quiz_feedback = (
                "Die Quizfrage konnte gerade nicht von der KI erzeugt werden. Bitte versuche es in einem Moment erneut."
                if service_failed
                else "Die KI hat auch nach mehreren Versuchen keine neue, vollständig auswertbare Quizfrage geliefert."
            )
            return False
        self._quiz_question_history.append(self._quiz_question)
        self._quiz_question_history = self._quiz_question_history[-100:]
        self.config["quiz_question_history"] = self._quiz_question_history
        self._write_config()
        self._quiz_feedback = ""
        self._quiz_attempts = 0
        self._quiz_question_id += 1
        spoken_choices = " ".join(
            f"{letter}: {choice}." for letter, choice in zip("ABCD", self._quiz_choices)
        )
        choices_for_speech = (
            ""
            if self._quiz_screen_output_active()
            or (self.quiz_reveal_choices_after_wrong and not self._quiz_question_needs_choices())
            else spoken_choices
        )
        self._quiz_speak(
            f"{player['name']}, hier ist deine Frage aus {self._quiz_topic}: "
            f"{self._quiz_question} "
            f"{choices_for_speech}"
        )
        self._log_event(f"Quizfrage für {player['name']} ({self._quiz_topic}, {difficulty})")
        return True

    def _quiz_speak(self, message: str) -> None:
        self._record_conversation("assistant", message)
        if self.tv_display_enabled and self.quiz_tv_display_enabled and not self.debug_mode:
            if not self._prepare_tv_audio(message):
                self._log_event("Quiz-TV-TTS konnte nicht erzeugt werden")
        else:
            self._speak(
                message,
                voice_player=self._quiz_voice_player or self.voice_player,
                record_conversation=False,
            )

    def _submit_quiz_answer(self, answer: str, record_conversation: bool = True) -> bool:
        players = self._active_quiz_players()
        if not self._quiz_running or not players or not self._quiz_question:
            return False
        player = players[self._quiz_player_index % len(players)]
        attempt_limit = self.quiz_child_attempts if player.get("role") == "kind" else self.quiz_adult_attempts
        clean_answer = answer.strip()
        letter_match = re.fullmatch(r"(?:antwort\s+)?([a-d])(?:[\s:.,-]+.*)?", clean_answer.lower())
        if letter_match and self._quiz_choices:
            clean_answer = self._quiz_choices[ord(letter_match.group(1)) - ord("a")]
        quick_correct = self._normalized_question(clean_answer) == self._normalized_question(self._quiz_solution)
        if quick_correct:
            correct, feedback = True, f"Richtig, {player['name']}! Die Lösung ist {self._quiz_solution}."
        else:
            result = self._parse_json(self._ask_ai(
                "Bewerte eine Antwort in einem Wissensquiz tolerant gegenüber gleichbedeutenden Formulierungen. "
                "Antworte ausschließlich als JSON mit correct als booleschem Wert und feedback als kurzer Erklärung. "
                "Wenn die Antwort falsch ist, darf feedback weder die Musterlösung noch die richtige Antwort verraten.\n"
                f"Sprachstil: {self.language_style_prompt}\n"
                f"Frage: {self._quiz_question}\nMusterlösung: {self._quiz_solution}\nAntwort: {clean_answer}"
            ))
            correct = bool(result.get("correct", False))
            feedback = str(result.get("feedback") or "").strip()
            if not feedback:
                feedback = (
                    f"Richtig, {player['name']}!" if correct
                    else f"Leider nicht richtig. Die Lösung ist {self._quiz_solution}."
                )
        if correct:
            self._quiz_scores[player["name"]] = min(10, self._quiz_scores.get(player["name"], 0) + 1)
            if self._quiz_scores[player["name"]] >= 10:
                self._quiz_winner = player["name"]
                self._quiz_finale_message = random.choice([
                    "Das Toilettenhäuschen ist auf dem Weg zum Mond!",
                    "Das Toilettenhäuschen erobert das Universum!",
                    "Houston, wir haben ein Kloproblem – das Häuschen hebt ab!",
                    "Zehn Punkte! Dieses stille Örtchen ist jetzt ziemlich schnell unterwegs!",
                ])
                feedback = (
                    f"Richtig, {player['name']}! Countdown zehn ist erreicht. "
                    f"{self._quiz_finale_message}"
                )
                self._quiz_question = ""
                self._quiz_solution = ""
                self._quiz_choices = []
        else:
            self._quiz_attempts += 1
            if self._quiz_attempts >= attempt_limit:
                feedback = (
                    f"Das war leider noch nicht richtig, {player['name']}. Die richtige Lösung ist {self._quiz_solution}."
                    if player.get("role") == "erwachsen"
                    else f"Das war der letzte Versuch, {player['name']}. Die richtige Lösung ist {self._quiz_solution}."
                )
            else:
                feedback = (
                    f"Leider noch nicht richtig, {player['name']}. Probiere es bitte noch einmal."
                    if player.get("role") == "erwachsen"
                    else f"Leider noch nicht richtig, {player['name']}. Das war Versuch {self._quiz_attempts} von {attempt_limit}. Probiere es noch einmal."
                )
                if player.get("role") == "kind" and self._quiz_attempts == 2 and self._quiz_attempts < attempt_limit:
                    hint = self._ask_ai(
                        "Gib einem Kind nach zwei falschen Antworten genau einen kurzen, verständlichen Denkanstoß. "
                        "Verrate weder die Lösung noch den Buchstaben der richtigen Auswahl. Antworte nur mit der Hilfestellung.\n"
                        f"Sprachstil: {self.language_style_prompt}\n"
                        f"Frage: {self._quiz_question}\n"
                        f"Musterlösung (nicht nennen): {self._quiz_solution}\n"
                        f"Letzte Antwort des Kindes: {clean_answer}"
                    ).strip()
                    if hint and self._normalized_lookup(self._quiz_solution) not in self._normalized_lookup(hint):
                        feedback += f" Kleiner Tipp: {hint}"
                    else:
                        feedback += " Kleiner Tipp: Denk noch einmal Schritt für Schritt darüber nach, worauf die Frage besonders hinauswill."
            if self.quiz_reveal_choices_after_wrong and self._quiz_choices and self._quiz_attempts < attempt_limit and not self._quiz_screen_output_active():
                spoken_choices = " ".join(
                    f"{letter}: {choice}." for letter, choice in zip("ABCD", self._quiz_choices)
                )
                feedback += f" Hier sind jetzt die Auswahlmöglichkeiten: {spoken_choices}"
        self._quiz_feedback = feedback
        if record_conversation:
            self._record_conversation("user", answer)
        self._quiz_speak(
            feedback
            if self._quiz_winner
            else feedback
        )
        if not self._quiz_winner and (correct or self._quiz_attempts >= attempt_limit):
            self._cancel_timer("_quiz_advance_timer")
            delay = max(4, min(14, int(len(feedback.split()) * 0.48 + 3)))
            self._quiz_advance_timer = self.run_in(self._next_quiz_player_callback, delay)
        self._log_event(f"Quizantwort von {player['name']}: {'richtig' if correct else 'falsch'}")
        return True

    def _next_quiz_player(self) -> bool:
        self._cancel_timer("_quiz_advance_timer")
        players = self._active_quiz_players()
        if not self._quiz_running or not players or self._quiz_winner:
            return False
        self._quiz_player_index = (self._quiz_player_index + 1) % len(players)
        if self._quiz_player_index == 0:
            self._quiz_round += 1
        return self._generate_quiz_question()

    def _next_quiz_player_callback(self, kwargs: Dict[str, Any]) -> None:
        self._quiz_advance_timer = None
        self._next_quiz_player()

    def _repeat_quiz_question(self) -> bool:
        players = self._active_quiz_players()
        if not self._quiz_running or not players or not self._quiz_question:
            return False
        player = players[self._quiz_player_index % len(players)]
        choices = " ".join(f"{letter}: {choice}." for letter, choice in zip("ABCD", self._quiz_choices))
        visible_choices = "" if self._quiz_screen_output_active() or (self.quiz_reveal_choices_after_wrong and self._quiz_attempts == 0 and not self._quiz_question_needs_choices()) else choices
        self._quiz_speak(f"Gerne, {player['name']}. {self._quiz_question} {visible_choices}")
        return True

    def _finish_quiz(self, reason: str = "Klugscheißer beendet") -> None:
        self._cancel_timer("_quiz_advance_timer")
        scores = ", ".join(f"{name}: {score} Punkte" for name, score in self._quiz_scores.items())
        if self._quiz_running and scores:
            self._quiz_speak(f"Klugscheißer ist beendet. Punktestand: {scores}.")
        self._quiz_running = False
        self._quiz_player_index = 0
        self._quiz_round = 0
        self._quiz_question = ""
        self._quiz_solution = ""
        self._quiz_choices = []
        self._quiz_topic = ""
        self._quiz_attempts = 0
        self._quiz_feedback = reason
        self._quiz_winner = ""
        self._quiz_finale_message = ""
        self._quiz_voice_player = ""
        self._log_event(reason)

    def _show_tv_task_page(self) -> None:
        if self.debug_mode:
            self.debug_display_page = "task"
            self.config["debug_display_page"] = "task"
            self._log_event("Debug-Modus: separate Webausgabe auf Aufgabenseite umgestellt")
            return
        if not self.tv_display_enabled:
            return
        self._show_tv_page(self.TV_TASK_URL, "TV-Aufgabenseite")

    def _show_tv_quiz_page(self) -> None:
        if self.debug_mode:
            self.debug_display_page = "quiz"
            self.config["debug_display_page"] = "quiz"
            self._log_event("Debug-Modus: separate Webausgabe auf Quizseite umgestellt")
            return
        if not self.quiz_tv_display_enabled:
            self._log_event("Quiz-TV-Ausgabe ist deaktiviert; Quiz läuft im Sprachmodus")
            return
        if not self.tv_display_enabled:
            return
        self._show_tv_page(self.TV_QUIZ_URL, "TV-Wissensquiz")

    def _show_tv_page(self, url: str, label: str) -> None:
        if not self.tv_display_supported:
            return
        if self.debug_mode:
            self._log_event(f"Debug-Modus: {label} nicht an den Fernseher übergeben")
            return
        try:
            self._cancel_timer("_tv_hide_timer")
            self.call_service(
                "input_boolean/turn_off",
                entity_id=[
                    "input_boolean.tv_webseiten_anzeigetest",
                    "input_boolean.tv_webseiten_sprachtest",
                ],
            )
            self.call_service(
                "script/tv_display_anzeigen",
                url=url,
                duration_seconds=0,
                wake=True,
                remote_control=True,
                remote_mode="keys",
            )
            self._log_event(f"{label} zur Anzeige übergeben")
        except Exception as exc:
            self.error(f"{label} konnte nicht angezeigt werden: {exc}")
            self._log_event(f"{label} konnte nicht angezeigt werden")

    def _hide_tv_task_page(self, after_speech: bool = False) -> None:
        if not self.tv_display_supported:
            return
        if self.debug_mode:
            self._log_event("Debug-Modus: Kein Beenden-Befehl an die TV-Webseiten-Schnittstelle gesendet")
            return
        if after_speech and self.tv_display_enabled and self._tv_speech_text:
            self._cancel_timer("_tv_hide_timer")
            delay = max(4, min(45, int(len(self._tv_speech_text.split()) * 0.55 + 3)))
            self._tv_hide_timer = self.run_in(self._hide_tv_task_page_callback, delay)
            return
        try:
            self.call_service("script/tv_display_beenden")
            self._log_event("TV-Aufgabenseite beendet")
        except Exception as exc:
            self.error(f"TV-Aufgabenseite konnte nicht beendet werden: {exc}")

    def _hide_tv_task_page_callback(self, kwargs: Dict[str, Any]) -> None:
        self._tv_hide_timer = None
        self._hide_tv_task_page()

    def _start_question(self, introduction: str = "", speech_delay: float = 0.35) -> None:
        if self._mode not in (self.MODE_CONDITIONAL, self.MODE_SINGLE_QUESTION, self.MODE_FREE_QUESTION):
            return
        # Eine bereits laufende Freigabe darf keine inzwischen gestartete Aufgabe
        # durch ihren alten Ablauf-Timer ersetzen.
        self._cancel_timer("_release_timer")
        if (
            self._mode == self.MODE_CONDITIONAL
            and self.maximum_releases > 0
            and self._releases >= self.maximum_releases
        ):
            self.activate_lock()
            self._publish_runtime("Maximale Freigaben erreicht; dauerhaft gesperrt")
            return

        if self._mode == self.MODE_CONDITIONAL:
            self._lock_media(pause_only=True)
        self._attempts = 0
        kind = getattr(self, "_single_question_kind", "allgemein") if self._mode == self.MODE_SINGLE_QUESTION else "allgemein"
        self._question_audience = "adult" if kind == "erwachsen" else "kind"
        topic = (
            self._choose_adult_question_topic()
            if self._question_audience == "adult"
            else self._choose_topic(
                kind,
                requested_topic=self._free_topic if self._mode == self.MODE_FREE_QUESTION else "",
                requested_subtopic=self._free_subtopic if self._mode == self.MODE_FREE_QUESTION else "",
            )
        )
        self._question_topic = str(topic.get("name") or "")
        self._question_subtopic = str((topic.get("selected_subtopic") or {}).get("name") or "")
        previous_question = self._question
        parsed = {}
        result = ""
        for _ in range(2):
            prompt = (
                self._adult_question_prompt(topic, previous_question)
                if self._question_audience == "adult"
                else self._question_prompt(topic, previous_question)
            )
            result = self._ask_ai(prompt)
            parsed = self._parse_question_result(result)
            candidate = parsed.get("question", result or "")
            if not previous_question or self._normalized_question(candidate) != self._normalized_question(previous_question):
                break
            self._log_event("KI hat die vorherige Aufgabe wiederholt; erneute Erzeugung")
        self._question = parsed.get("question", result or "Bitte löse eine passende Aufgabe.")
        self._question_id += 1
        self._solution = parsed.get("solution", "")
        if "mathe" in self._normalized_lookup(self._question_topic):
            self._question = self._normalize_math_notation(self._question)
            self._solution = self._normalize_math_notation(self._solution)
        self._tv_speech_text = ""
        self._tv_audio_url = ""
        self._show_tv_task_page()
        active_footer_prompt = (
            self.footer_prompt
            if self.footer_prompt_enabled and not self.tv_display_enabled
            else ""
        )
        spoken_text = "\n\n".join(
            part for part in (introduction, self._question, active_footer_prompt) if part
        )
        self._cancel_timer("_question_speech_timer")
        if speech_delay > 0:
            self._question_speech_timer = self.run_in(
                self._speak_question_callback,
                speech_delay,
                message=spoken_text,
            )
        else:
            self._speak(spoken_text)
        if self._mode != self.MODE_FREE_QUESTION or not self._answer_timer:
            self._start_answer_timer()
        subtopic = topic.get("selected_subtopic") or {}
        topic_label = topic.get("name", "Allgemein")
        if subtopic.get("name"):
            topic_label += f" / {subtopic['name']}"
        self._log_event(f"Neue Aufgabe ({topic_label})")
        self._publish_runtime("Antwort wird erwartet")

    def submit_answer(self, answer: str, record_conversation: bool = True) -> None:
        answer = answer.strip()
        if self._mode not in (self.MODE_CONDITIONAL, self.MODE_SINGLE_QUESTION, self.MODE_FREE_QUESTION) or not self._question:
            self._publish_runtime("Derzeit ist keine Antwort offen")
            return
        if not answer:
            return
        if record_conversation:
            self._record_conversation("user", answer)
        self._attempts += 1
        evaluation = self._evaluate_answer(answer)
        answer_role = "Antwort des Erwachsenen" if self._question_audience == "adult" else "Antwort des Kindes"
        if self._mode == self.MODE_FREE_QUESTION:
            if evaluation.get("correct") is True:
                feedback = self._ensure_explanatory_feedback(answer, evaluation.get("feedback", ""))
                self._speak(feedback)
                self._log_event("Freie Aufgabe richtig beantwortet")
                self._publish_runtime("Richtig beantwortet; neue Aufgabe oder Beenden möglich")
            else:
                hint = evaluation.get("feedback") or self._ask_ai(
                    f"Aufgabe: {self._question}\n{answer_role}: {answer}\n{self.wrong_answer_prompt}"
                )
                self._speak(hint)
                self._log_event("Freie Aufgabe noch nicht richtig beantwortet")
                self._publish_runtime("Ein weiterer Versuch ist möglich")
            return
        if evaluation.get("correct") is True:
            feedback = self._ensure_explanatory_feedback(answer, evaluation.get("feedback", ""))
            self._speak(feedback)
            if self._mode == self.MODE_SINGLE_QUESTION:
                self._finish_single_question("Einzelaufgabe richtig beantwortet")
            else:
                self._release_temporarily()
            return

        if self._attempts < self.maximum_attempts:
            hint = evaluation.get("feedback") or self._ask_ai(
                f"Aufgabe: {self._question}\n{answer_role}: {answer}\n{self.wrong_answer_prompt}"
            )
            self._speak(hint)
            self._start_answer_timer()
            self._log_event(f"Antwort falsch; Versuch {self._attempts}/{self.maximum_attempts}")
            self._publish_runtime("Nicht richtig; ein neuer Versuch ist möglich")
            return

        explanation = evaluation.get("feedback") or f"Die Lösung lautet: {self._solution}"
        if self._solution and self._solution.lower() not in explanation.lower():
            explanation += f" Die Musterlösung lautet: {self._solution}"
        self._speak(explanation)
        if self._mode == self.MODE_SINGLE_QUESTION:
            self._finish_single_question("Einzelaufgabe beendet; Versuche aufgebraucht")
        else:
            self._log_event("Versuche aufgebraucht; neue Aufgabe")
            self._start_question()

    def _finish_single_question(self, status: str) -> None:
        self._cancel_timer("_answer_timer")
        self._mode = self.MODE_OFF
        self._session_voice_player = ""
        self._hide_tv_task_page(after_speech=True)
        self._log_event(status)
        self._publish_runtime(status)

    def repeat_question(self, speech_delay: float = 0.0) -> None:
        if self._question:
            repeated_question = re.sub(
                r"^\s*hallo\s+david\s*[,!.:-]?\s*",
                "",
                self._question,
                flags=re.IGNORECASE,
            ).strip()
            label = "Frage" if self._question_audience == "adult" else "Aufgabe"
            spoken_text = f"Gerne, ich wiederhole die {label} für dich. " + repeated_question
            self._cancel_timer("_question_speech_timer")
            if speech_delay > 0:
                self._question_speech_timer = self.run_in(
                    self._speak_question_callback,
                    speech_delay,
                    message=spoken_text,
                )
                self._log_event(
                    f"Aufgabenwiederholung in {speech_delay:.1f} Sekunden eingeplant"
                )
            else:
                self._speak(spoken_text)
                self._log_event("Aufgabenwiederholung an Sprachausgabe übergeben")
            self._publish_runtime(f"{label} wird wiederholt")

    def request_new_question(self, speech_delay: float = 0.35) -> None:
        if not self.allow_new_question:
            self._speak("Eine neue Aufgabe ist derzeit nicht erlaubt.")
            self._log_event("Neue Aufgabe abgelehnt: Funktion ist deaktiviert")
            self._publish_runtime("Neue Aufgabe ist derzeit nicht erlaubt")
            return
        if self._mode in (self.MODE_SINGLE_QUESTION, self.MODE_FREE_QUESTION):
            self._start_question(speech_delay=speech_delay)
            return
        if self._mode != self.MODE_CONDITIONAL:
            if self.maximum_releases > 0 and self._releases >= self.maximum_releases:
                message = "Es sind bereits alle Freigaben verbraucht. Deshalb kann ich keine neue Aufgabe mehr stellen."
            else:
                message = "Derzeit ist keine bedingte Kindersicherung mit einer offenen Aufgabe aktiv."
            self._speak(message)
            self._log_event(f"Neue Aufgabe abgelehnt: {message}")
            self._publish_runtime(message)
            return
        self._start_question(speech_delay=speech_delay)

    def _release_temporarily(self) -> None:
        self._cancel_timer("_answer_timer")
        self._question = ""
        self._solution = ""
        self._hide_tv_task_page(after_speech=True)
        self._unlock_media()
        self._releases += 1
        self._release_timer = self.run_in(self._release_expired, self.release_interval * 60)
        maximum_label = str(self.maximum_releases) if self.maximum_releases > 0 else "unbegrenzt"
        self._log_event(f"Freigabe {self._releases}/{maximum_label}")
        self._publish_runtime(f"Für {self.release_interval} Minuten freigegeben")

    def _release_expired(self, kwargs: Dict[str, Any]) -> None:
        self._release_timer = None
        self._start_question()

    def _start_answer_timer(self) -> None:
        self._cancel_timer("_answer_timer")
        self._answer_timer = self.run_in(self._answer_expired, self.answer_timeout * 60)

    def _answer_expired(self, kwargs: Dict[str, Any]) -> None:
        if self._mode == self.MODE_CONDITIONAL:
            self._speak("Die Antwortzeit ist abgelaufen. Ich stelle eine neue Aufgabe.")
            self._log_event("Antwortzeit abgelaufen")
            self._start_question()
        elif self._mode == self.MODE_SINGLE_QUESTION:
            self._speak(f"Die Antwortzeit ist abgelaufen. Die Musterlösung lautet: {self._solution}")
            self._finish_single_question("Einzelaufgabe beendet; Antwortzeit abgelaufen")
        elif self._mode == self.MODE_FREE_QUESTION:
            self._speak("Die Zeit für die freie Aufgabe ist abgelaufen.")
            self._finish_free_question("Freie Aufgabe automatisch beendet; Zeit abgelaufen")

    # ------------------------------------------------------------------
    # KI, Sprache und Befehle
    # ------------------------------------------------------------------
    def _ask_ai(self, text: str) -> str:
        try:
            result = self.call_service(
                "conversation/process",
                text=text,
                agent_id=self.agent_id,
                language=self.language,
            )
            self.log(f"KI-Antwortstruktur: {type(result).__name__} {str(result)[:800]}")
            error_text = self._extract_ai_error(result)
            if error_text:
                self.error(f"KI-Dienst meldet einen Fehler: {error_text}")
                self._log_event("KI-Dienst vorübergehend nicht verfügbar")
                return ""
            return self._extract_ai_text(result)
        except Exception as exc:
            self.error(f"KI-Aufruf fehlgeschlagen: {exc}")
            self._log_event("KI-Aufruf fehlgeschlagen")
            return ""

    @staticmethod
    def _extract_ai_error(result: Any) -> str:
        if isinstance(result, list):
            for value in result:
                error = KiKindersicherung._extract_ai_error(value)
                if error:
                    return error
            return ""
        if not isinstance(result, dict):
            return ""
        if str(result.get("response_type") or "").lower() == "error":
            return KiKindersicherung._extract_ai_text(result) or "Unbekannter Fehler des KI-Dienstes"
        if result.get("success") is False:
            return str(result.get("message") or result.get("error") or "KI-Aufruf fehlgeschlagen")
        for key in ("response", "service_response", "result", "data"):
            if key in result:
                error = KiKindersicherung._extract_ai_error(result[key])
                if error:
                    return error
        return ""

    @staticmethod
    def _extract_ai_text(result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, list):
            for value in result:
                text = KiKindersicherung._extract_ai_text(value)
                if text:
                    return text
            return ""
        if not isinstance(result, dict):
            return ""
        speech = result.get("speech", {})
        if isinstance(speech, dict):
            plain = speech.get("plain", {})
            if isinstance(plain, dict) and plain.get("speech"):
                return str(plain["speech"])
        for key in ("text", "content", "message"):
            if isinstance(result.get(key), str) and result[key].strip():
                return str(result[key])
        for key in ("response", "service_response", "result", "data"):
            if key in result:
                text = KiKindersicherung._extract_ai_text(result[key])
                if text:
                    return text
        return ""

    def _question_prompt(self, topic: Dict[str, Any], previous_question: str = "") -> str:
        subtopic = topic.get("selected_subtopic") or {}
        different_instruction = ""
        if previous_question:
            different_instruction = (
                f'\nVorherige Aufgabe: "{previous_question}"\n'
                "Erzeuge zwingend eine in Inhalt oder Zahlen deutlich andere Aufgabe. "
                "Wiederhole die vorherige Aufgabe nicht.\n"
            )
        math_instruction = (
            "Schreibe Rechenoperationen immer mit gut sichtbaren mathematischen Zeichen: "
            "Multiplikation mit kleinem x, Division mit Doppelpunkt (:), Addition mit + und Subtraktion mit -. "
            "Verwende dafür nicht die Wörter mal, geteilt durch, plus oder minus.\n"
            if "mathe" in self._normalized_lookup(topic.get("name", "")) else ""
        )
        return (
            f"{self.base_prompt}\n\nThemenbereich: {topic.get('name', 'Allgemein')}\n"
            f"Vorgabe zum Themenbereich: {topic.get('prompt', '')}\n"
            f"Ausgewähltes Unterthema: {subtopic.get('name', 'Kein Unterthema')}\n"
            f"Vorgabe zum Unterthema: {subtopic.get('prompt', '')}\n\n"
            f"Sprachstil: {self.language_style_prompt}\n"
            "Halte dich bei der Aufgabe gezielt an das ausgewählte Unterthema. "
            f"{math_instruction}"
            f"{different_instruction}"
            "Antworte ausschließlich als gültiges JSON mit den Feldern question und solution. "
            "question enthält nur die Aufgabenstellung, solution eine kurze Musterlösung."
        )

    def _adult_question_prompt(self, topic: Dict[str, Any], previous_question: str = "") -> str:
        different_instruction = ""
        if previous_question:
            different_instruction = (
                f'\nVorherige Frage: "{previous_question}"\n'
                "Erzeuge zwingend eine deutlich andere Frage.\n"
            )
        return (
            "Erzeuge genau eine Wissensfrage für einen Erwachsenen auf Deutsch. "
            "Die Frage muss eindeutig beantwortbar sein und zum eingestellten Schwierigkeitsgrad passen.\n"
            f"Fachgebiet: {topic.get('name', 'Allgemeinwissen')}\n"
            f"Schwierigkeitsgrad: {topic.get('difficulty', 'gemischt')}\n"
            f"Unterthemen: {topic.get('subtopics', '')}\n"
            f"Vorgabe: {topic.get('prompt', '')}\n"
            f"Sprachstil: {self.language_style_prompt}\n"
            f"{different_instruction}"
            "Antworte ausschließlich als gültiges JSON mit den Feldern question und solution. "
            "question enthält nur die Frage, solution eine kurze Musterlösung."
        )

    def _evaluate_answer(self, answer: str) -> Dict[str, Any]:
        adult = self._question_audience == "adult"
        prompt = (
            f"Bewerte die Antwort {'eines Erwachsenen' if adult else 'eines Kindes'} sachlich und tolerant gegenüber Formulierungsvarianten.\n"
            f"Aufgabe: {self._question}\nMusterlösung: {self._solution}\nAntwort: {answer}\n"
            f"Sprachstil: {self.language_style_prompt}\n"
            "Wenn die Antwort richtig ist, gestalte das Feedback nach dieser Vorgabe: "
            f"{self.correct_answer_prompt or ('Bestätige kurz und erkläre die Lösung knapp.' if adult else 'Lobe kurz und erkläre die Lösung knapp und kindgerecht.')}\n"
            "Wenn die Antwort falsch ist, verrate im Feedback nicht unnötig die vollständige Lösung.\n"
            "Antworte ausschließlich als gültiges JSON: "
            '{"correct": true oder false, "feedback": "kurze erklärende Rückmeldung"}'
        )
        raw = self._ask_ai(prompt)
        parsed = self._parse_json(raw)
        return parsed if isinstance(parsed.get("correct"), bool) else {"correct": False, "feedback": raw}

    def _ensure_explanatory_feedback(self, answer: str, feedback: str) -> str:
        """Ersetzt knappe Bestätigungen durch eine nachvollziehbare Begründung."""
        clean_feedback = str(feedback or "").strip()
        normalized = re.sub(r"[^a-zäöüß]+", " ", clean_feedback.lower()).strip()
        generic = {
            "ok", "okay", "richtig", "gut", "stimmt", "korrekt", "gut gemacht",
            "das ist richtig", "deine antwort ist richtig",
        }
        if normalized not in generic and len(clean_feedback.split()) >= 8:
            return clean_feedback

        adult = self._question_audience == "adult"
        expanded = self._ask_ai(
            f"Formuliere eine freundliche, {'sachliche' if adult else 'kindgerechte'} Rückmeldung in zwei bis drei Sätzen. "
            "Bestätige zuerst die richtige Antwort und erkläre anschließend nachvollziehbar, "
            "warum sie richtig ist oder wie man auf die Lösung kommt. Antworte nur mit der Rückmeldung.\n"
            f"Aufgabe: {self._question}\n"
            f"Musterlösung: {self._solution}\n"
            f"Richtige Antwort {'des Erwachsenen' if adult else 'des Kindes'}: {answer}\n"
            f"Zusätzliche Vorgabe: {self.correct_answer_prompt}"
            f"\nSprachstil: {self.language_style_prompt}"
        ).strip()
        if len(expanded.split()) >= 8:
            return expanded

        solution_text = self._solution or answer
        return (
            f"Richtig, {answer} passt als Antwort. "
            f"Die Musterlösung ist {solution_text}; daran kannst du erkennen, wie die Aufgabe gelöst wird."
        )

    @staticmethod
    def _prepare_speech_text(value: Any) -> str:
        """Formuliert Rechenzeichen zwischen Zahlen natürlich für jede TTS-Engine."""
        text = str(value or "")
        protected: List[str] = []

        def protect(match: re.Match) -> str:
            protected.append(match.group(0))
            return f"__KI_SPEECH_PROTECTED_{len(protected) - 1}__"

        # Uhrzeiten und Datumsangaben sind keine Divisionen beziehungsweise Subtraktionen.
        text = re.sub(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", protect, text)
        text = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", protect, text)
        text = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", protect, text)

        number = r"\d+(?:[.,]\d+)?"
        operations = (
            (r"[xX×·*]", "mal"),
            (r"[÷/:]", "geteilt durch"),
            (r"\+", "plus"),
            (r"[−–-]", "minus"),
            (r"=", "ist gleich"),
        )
        for symbol, spoken in operations:
            text = re.sub(
                rf"({number})\s*{symbol}\s*(?=-?{number})",
                rf"\1 {spoken} ",
                text,
            )
        for index, original in enumerate(protected):
            text = text.replace(f"__KI_SPEECH_PROTECTED_{index}__", original)
        return re.sub(r"[ \t]+", " ", text).strip()

    def _speak(
        self,
        message: str,
        voice_player: Optional[str] = None,
        speech_engine: Optional[str] = None,
        speech_voice: Optional[str] = None,
        use_cache: bool = True,
        record_conversation: bool = True,
    ) -> None:
        if not message:
            return
        if record_conversation:
            self._record_conversation("assistant", message)
        spoken_message = self._prepare_speech_text(message)
        if (
            self.tv_display_enabled
            and not self.debug_mode
            and record_conversation
            and self._mode in (
                self.MODE_CONDITIONAL,
                self.MODE_SINGLE_QUESTION,
                self.MODE_FREE_QUESTION,
            )
        ):
            if self._prepare_tv_audio(spoken_message):
                self._log_event("Sprachausgabe mit eingestellter TTS-Stimme an TV-Webseite übergeben")
            else:
                self._tv_speech_text = ""
                self._log_event("TV-TTS konnte nicht erzeugt werden; keine abweichende Systemstimme verwendet")
            return
        if self.debug_mode:
            target_player = self.debug_voice_player
            if not target_player:
                self._log_event("Debug-Modus: Keine Sprachausgabe, da kein Debug-Sprachgerät gewählt ist")
                return
        else:
            target_player = voice_player or (
                self._session_voice_player
                if self._mode in (self.MODE_SINGLE_QUESTION, self.MODE_FREE_QUESTION)
                and self._session_voice_player
                else self.voice_player
            )
        target_engine = speech_engine or self.speech_engine
        target_voice = self.speech_voice if speech_voice is None else speech_voice
        if target_player:
            try:
                service_data = {
                    "entity_id": target_engine,
                    "media_player_entity_id": target_player,
                    "message": spoken_message,
                    "cache": use_cache,
                }
                if target_voice:
                    service_data["options"] = {"voice": target_voice}
                self.call_service("tts/speak", **service_data)
            except Exception as exc:
                self.error(f"Sprachausgabe fehlgeschlagen: {exc}")

    def _prepare_tv_audio(self, message: str) -> bool:
        """Erzeugt TTS über Home Assistant und veröffentlicht nur die lokale Audio-URL."""
        message = self._prepare_speech_text(message)
        token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
        if not token:
            self.error("TV-TTS fehlgeschlagen: SUPERVISOR_TOKEN ist nicht verfügbar")
            return False
        options: Dict[str, Any] = {
            "preferred_format": "mp3",
            "preferred_sample_rate": 44100,
        }
        if self.speech_voice:
            options["voice"] = self.speech_voice
        payload: Dict[str, Any] = {
            "engine_id": self.speech_engine,
            "message": message,
            "cache": False,
            "options": options,
        }
        try:
            response = requests.post(
                "http://supervisor/core/api/tts_get_url",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=40,
            )
            response.raise_for_status()
            result = response.json()
            path = str(result.get("path") or "").strip()
            url = str(result.get("url") or "").strip()
            if path.startswith("/"):
                url = f"__HOME_ASSISTANT_URL__{path}"
            elif url:
                url = re.sub(
                    r"^https?://(?:homeassistant(?:\.local)?|supervisor|127\.0\.0\.1|localhost)(?::8123)?",
                    "__HOME_ASSISTANT_URL__",
                    url,
                    flags=re.IGNORECASE,
                )
            if not url:
                raise ValueError("Home Assistant hat keine TTS-Audioadresse geliefert")
            self._tv_speech_text = message
            self._tv_speech_id += 1
            self._tv_audio_url = url
            self._tv_audio_id += 1
            return True
        except Exception as exc:
            self.error(f"TV-TTS-Erzeugung fehlgeschlagen: {exc}")
            self._tv_audio_url = ""
            return False

    def _speak_question_callback(self, kwargs: Dict[str, Any]) -> None:
        self._question_speech_timer = None
        self._speak(str(kwargs.get("message") or ""))

    def _test_speech_callback(self, kwargs: Dict[str, Any]) -> None:
        self._speak(
            str(kwargs.get("message") or ""),
            voice_player=str(kwargs.get("voice_player") or self.voice_player),
            speech_engine=str(kwargs.get("speech_engine") or self.speech_engine),
            speech_voice=str(kwargs.get("speech_voice") or ""),
            use_cache=False,
            record_conversation=False,
        )

    def process_command(
        self,
        command: str,
        speech_delay: float = 0.35,
        voice_player: str = "",
    ) -> None:
        text = re.sub(r"\s+", " ", command.strip().lower())
        if not text:
            return
        # Assist/STT versteht „Antwort“ gelegentlich als „Anwort“, „Anfort“ oder
        # „Anfalt“. Während eine Aufgabe offen ist behandeln wir diese eng
        # begrenzten Lautvarianten ebenfalls als Antwortmarker.
        answer_match = re.match(
            r"^(?:ich glaube[ ,]+)?(?:(?:die|meine)\s+)?"
            r"(?:antwort|anwort|anfort|anfalt|lösung|loesung)"
            r"(?:\s+(?:ist|lautet))?(?:\s+(.*))?$",
            text,
        )
        answer_command = bool(answer_match)
        answer_text = str(answer_match.group(1) or "").strip() if answer_match else ""
        quiz_command = any(
            phrase in text
            for phrase in (
                "wissensquiz", "klugscheißer", "klugscheisser", "quiz starten", "quiz beginnen", "quiz beenden",
                "quiz stoppen", "nächster spieler", "naechster spieler",
                "nächste frage", "naechste frage", "frage wiederholen",
            )
        )
        adult_question_command = any(
            phrase in text
            for phrase in (
                "erwachsenenfrage",
                "frage für erwachsene",
                "frage fuer erwachsene",
                "frage an einen erwachsenen",
                "frage an erwachsene",
                "wissensfrage für erwachsene",
                "wissensfrage fuer erwachsene",
            )
        )
        open_question = (
            self._mode in (self.MODE_CONDITIONAL, self.MODE_SINGLE_QUESTION, self.MODE_FREE_QUESTION)
            and bool(self._question)
        )
        task_control_command = any(
            phrase in text
            for phrase in (
                "aufgabe beenden", "aufgabe stoppen", "keine aufgabe mehr",
                "freie aufgabe beenden", "aufgabe wiederholen", "andere aufgabe",
                "neue aufgabe",
            )
        )
        relevant_command = (
            (answer_command and (open_question or self._quiz_running))
            or quiz_command
            or adult_question_command
            or task_control_command
            or "knobelaufgabe" in text
            or "schulaufgabe" in text
            or self._is_free_question_command(text)
            or "kindersicherung" in text
        )
        if not relevant_command:
            self.log(f"Nicht zur Kindersicherung gehörender Befehl ignoriert: {command}")
            return
        if "bedingte kindersicherung" in text:
            self._session_voice_player = ""
        elif (
            self._mode != self.MODE_CONDITIONAL
            and (
                "knobelaufgabe" in text
                or "schulaufgabe" in text
                or adult_question_command
                or self._is_free_question_command(text)
            )
        ):
            self._session_voice_player = voice_player or self.voice_player
        self._record_conversation("user", command.strip())
        quiz_name_used = any(x in text for x in ("wissensquiz", "quiz", "klugscheißer", "klugscheisser"))
        if quiz_name_used and any(x in text for x in ("start", "beginn")):
            if not self.quiz_enabled:
                self._speak("Klugscheißer ist in der Konfiguration nicht aktiviert.")
            elif not self._start_quiz(show_on_tv=True, voice_player=voice_player):
                self._speak("Für Klugscheißer ist noch kein Spieler aktiviert.")
        elif self._quiz_running and quiz_name_used and any(x in text for x in ("beenden", "stoppen")):
            self._finish_quiz("Klugscheißer per Sprachbefehl beendet")
        elif self._quiz_running and any(x in text for x in ("nächster spieler", "naechster spieler", "nächste frage", "naechste frage")):
            self._next_quiz_player()
        elif self._quiz_running and "frage wiederholen" in text:
            self._repeat_quiz_question()
        elif self._quiz_running and answer_command:
            if not answer_text:
                self._quiz_speak("Bitte sage deine vollständige Quizantwort, zum Beispiel: Antwort B.")
            else:
                self._submit_quiz_answer(answer_text, record_conversation=False)
        elif answer_command and not answer_text:
            message = (
                "Ich habe nur das Wort Antwort verstanden, aber noch nicht deine Lösung. "
                "Bitte sage deine Antwort noch einmal vollständig, zum Beispiel: Antwort 24."
            )
            self._cancel_timer("_question_speech_timer")
            if speech_delay > 0:
                self._question_speech_timer = self.run_in(
                    self._speak_question_callback,
                    speech_delay,
                    message=message,
                )
            else:
                self._speak(message)
            self._log_event("Unvollständige Antwort erkannt; erneute Eingabe angefordert")
            self._publish_runtime("Antwortinhalt fehlt; vollständige Antwort wird erwartet")
        elif answer_command:
            self.submit_answer(answer_text, record_conversation=False)
        elif any(phrase in text for phrase in ("aufgabe beenden", "aufgabe stoppen", "keine aufgabe mehr", "freie aufgabe beenden")):
            if self._mode == self.MODE_FREE_QUESTION:
                self._speak("Gerne, die freie Aufgabe ist beendet.")
                self._finish_free_question("Freie Aufgabe per Sprachbefehl beendet")
            else:
                self._publish_runtime("Derzeit ist keine freie Aufgabe aktiv")
        elif "aufgabe wiederholen" in text:
            # Das Sprachgerät beendet nach dem lokalen Intent noch seine Assist-Sitzung.
            # Eine längere Übergabepause verhindert, dass dieser Abschluss die bereits
            # begonnene Wiederholung nach dem Einleitungssatz abschneidet.
            self.repeat_question(speech_delay=max(speech_delay, 5.5))
        elif "andere aufgabe" in text or "neue aufgabe" in text:
            self.request_new_question(speech_delay=speech_delay)
        elif "knobelaufgabe" in text:
            self.start_single_question("knobel", speech_delay=speech_delay)
        elif "schulaufgabe" in text:
            self.start_single_question("schule", speech_delay=speech_delay)
        elif adult_question_command:
            self.start_single_question("erwachsen", speech_delay=speech_delay)
        elif self._is_free_question_command(text):
            self.start_free_question(text, speech_delay=speech_delay)
        elif "bedingte kindersicherung" in text and any(x in text for x in ("aktiv", "einschalten", "starte")):
            self.activate_conditional()
        elif "kindersicherung" in text and any(x in text for x in ("deaktiv", "ausschalten", "freigeben")):
            if self.parent_pin and re.search(rf"(?<!\d){re.escape(self.parent_pin)}(?!\d)", text):
                self.deactivate("Per geschütztem Sprachbefehl deaktiviert")
            else:
                self._speak("Zum Deaktivieren ist die Eltern-PIN erforderlich.")
                self._log_event("Sprachliche Deaktivierung ohne gültige Eltern-PIN abgelehnt")
                self._publish_runtime("Deaktivierung abgelehnt: Eltern-PIN fehlt oder ist falsch")
        elif "kindersicherung" in text:
            delay = self._minutes_from_text(text)
            until = self._until_from_text(text)
            duration = self._duration_from_text(text)
            limit_label = None
            if duration and not until and delay == 0:
                until = self.datetime() + duration
                limit_label = self._duration_label(duration)
            self.activate_lock(delay_minutes=delay, until=until, limit_label=limit_label)
        else:
            self._publish_runtime("Befehl nicht erkannt")

    # ------------------------------------------------------------------
    # Mediensteuerung
    # ------------------------------------------------------------------
    def _ensure_dummy_player(self) -> None:
        self.set_state(
            self.DUMMY_PLAYER,
            state="idle",
            attributes={
                "friendly_name": "Kindersicherung Dummy-Media-Player",
                "supported_features": 152461,
                "media_title": "Simuliertes Testprogramm",
                "simulation": True,
            },
        )

    def _set_dummy_state(self, state: str) -> None:
        attributes = self.get_state(self.DUMMY_PLAYER, attribute="all") or {}
        current_attributes = attributes.get("attributes", {}) if isinstance(attributes, dict) else {}
        current_attributes.update(
            {
                "friendly_name": "Kindersicherung Dummy-Media-Player",
                "supported_features": 152461,
                "media_title": "Simuliertes Testprogramm",
                "simulation": True,
                "last_simulated_action": state,
            }
        )
        self.set_state(self.DUMMY_PLAYER, state=state, attributes=current_attributes)
        self._log_event(f"Dummy-Media-Player → {state}")

    def _lock_media(self, pause_only: bool = False) -> None:
        for entity in self.media_players:
            details = self.get_state(entity, attribute="all")
            if not isinstance(details, dict) or details.get("state") is None:
                self.error(f"Player nicht verfügbar und wird übersprungen: {entity}")
                continue
            state = str(details.get("state"))
            if entity not in self._media_before_lock:
                self._media_before_lock[entity] = {
                    "state": state,
                    "source": (details.get("attributes") or {}).get("source"),
                }
                self._log_event(f"Playerzustand gemerkt: {entity} = {state}")
            try:
                if entity == self.DUMMY_PLAYER:
                    if state in ("playing", "buffering"):
                        self._set_dummy_state("paused")
                else:
                    if state in ("playing", "buffering"):
                        self.call_service("media_player/media_pause", entity_id=entity)
                        self._log_event(f"Player pausiert: {entity}")
                if not pause_only:
                    if entity == self.DUMMY_PLAYER:
                        self._set_dummy_state("off")
                    elif state != "off":
                        self.call_service("media_player/turn_off", entity_id=entity)
            except Exception as exc:
                self.error(f"Konnte {entity} nicht sperren: {exc}")

    def _unlock_media(self) -> None:
        self._restoring_media = True
        try:
            for entity in self.media_players:
                snapshot = self._media_before_lock.get(entity)
                previous = snapshot.get("state") if isinstance(snapshot, dict) else snapshot
                if previous is None:
                    self.log(f"Kein vorheriger Zustand für {entity}; keine Wiederherstellung", level="WARNING")
                    continue
                try:
                    if entity == self.DUMMY_PLAYER:
                        self._set_dummy_state(str(previous))
                    else:
                        current = str(self.get_state(entity) or "unavailable")
                        if previous == "playing":
                            if current in ("off", "unavailable", "unknown"):
                                self.call_service("media_player/turn_on", entity_id=entity)
                            self.call_service("media_player/media_play", entity_id=entity)
                        elif previous == "paused":
                            if current == "playing":
                                self.call_service("media_player/media_pause", entity_id=entity)
                            elif current in ("off", "unavailable", "unknown"):
                                self.call_service("media_player/turn_on", entity_id=entity)
                                self.call_service("media_player/media_pause", entity_id=entity)
                        elif previous in ("idle", "on", "standby"):
                            if current == "off":
                                self.call_service("media_player/turn_on", entity_id=entity)
                            elif current == "playing":
                                self.call_service("media_player/media_stop", entity_id=entity)
                        elif previous == "off":
                            if current != "off":
                                self.call_service("media_player/turn_off", entity_id=entity)
                        else:
                            self.log(f"Playerzustand {previous} von {entity} wird nicht verändert")
                    if previous is not None:
                        self._log_event(f"Playerzustand wiederhergestellt: {entity} = {previous}")
                except Exception as exc:
                    self.error(f"Konnte {entity} nicht freigeben: {exc}")
        finally:
            self._media_before_lock.clear()
            self._restoring_media = False

    def _configure_speech_pause(self, kwargs: Dict[str, Any]) -> None:
        """Wählt auf dem Voice-Gerät eine eindeutig bezeichnete lange Sprechpause."""
        try:
            details = self.get_state(self.SPEECH_PAUSE_SELECT, attribute="all") or {}
            attributes = details.get("attributes", {}) if isinstance(details, dict) else {}
            options = [str(value) for value in attributes.get("options", [])]
            current = str(details.get("state") or "") if isinstance(details, dict) else ""
            preferred = next(
                (
                    option for option in options
                    if any(word in option.casefold() for word in ("lang", "long", "extended", "relaxed"))
                ),
                "",
            )
            self._log_event(
                f"Sprechpausen-Erkennung: aktuell {current or 'unbekannt'}; Optionen {', '.join(options) or 'unbekannt'}"
            )
            if preferred and preferred != current:
                self.call_service(
                    "select/select_option",
                    entity_id=self.SPEECH_PAUSE_SELECT,
                    option=preferred,
                )
                self._log_event(f"Sprechpausen-Erkennung auf {preferred} verlängert")
            elif preferred:
                self._log_event(f"Lange Sprechpausen-Erkennung ist bereits aktiv: {preferred}")
            else:
                self.log("Keine eindeutig lange Option für die Sprechpausen-Erkennung gefunden", level="WARNING")
        except Exception as exc:
            self.error(f"Sprechpausen-Erkennung konnte nicht angepasst werden: {exc}")

    def _combined_media_state(self) -> str:
        states = [str(self.get_state(x) or "unbekannt") for x in self.media_players]
        if self._mode == self.MODE_LOCKED:
            return "gesperrt"
        if self._mode == self.MODE_CONDITIONAL and self._question:
            return "pausiert"
        return ", ".join(states) if states else "nicht konfiguriert"

    # ------------------------------------------------------------------
    # UI-Callbacks
    # ------------------------------------------------------------------
    def _ui_lock(self, entity, attribute, old, new, kwargs) -> None:
        self.activate_lock()

    def _ui_conditional(self, entity, attribute, old, new, kwargs) -> None:
        self.activate_conditional()

    def _ui_unlock(self, entity, attribute, old, new, kwargs) -> None:
        self.deactivate()

    def _ui_release(self, entity, attribute, old, new, kwargs) -> None:
        if self._mode == self.MODE_CONDITIONAL:
            self._release_temporarily()

    def _ui_reject(self, entity, attribute, old, new, kwargs) -> None:
        if self._mode == self.MODE_CONDITIONAL:
            self._start_question()

    def _ui_new_question(self, entity, attribute, old, new, kwargs) -> None:
        self.request_new_question()

    def _ui_clear_log(self, entity, attribute, old, new, kwargs) -> None:
        self._history = []
        self._publish_log()

    def _ui_save(self, entity, attribute, old, new, kwargs) -> None:
        """Übernimmt die Dashboard-Helfer atomar in die App-Konfiguration."""
        try:
            self.config["enabled"] = self.get_state("input_boolean.ki_kinderschutz_aktiviert") == "on"
            player_1 = str(self.get_state("input_select.ki_medienplayer_1") or "")
            player_2 = str(self.get_state("input_select.ki_medienplayer_2") or "")
            self.config["media_players"] = [
                value for value in (player_1, player_2) if value and value != "keine"
            ]
            self.config["voice_player"] = str(
                self.get_state("input_select.ki_standard_sprachgeraet") or self.voice_player
            )
            self.config["speech_engine"] = str(
                self.get_state("input_select.ki_sprachsynthese") or self.speech_engine
            )
            self.config["conversation_agent"] = str(
                self.get_state("input_select.ki_ki_agent") or self.agent_id
            )
            self.config["release_interval_minutes"] = self._helper_int(
                "input_number.ki_freigabeintervall", self.release_interval
            )
            self.config["maximum_releases"] = self._helper_int(
                "input_number.ki_maximale_freigaben", self.maximum_releases
            )
            self.config["answer_timeout_minutes"] = self._helper_int(
                "input_number.ki_antwortfrist", self.answer_timeout
            )
            self.config["maximum_attempts"] = self._helper_int(
                "input_number.ki_maximale_versuche", self.maximum_attempts
            )
            prompt_mapping = {
                "base_prompt": "input_text.ki_basis_prompt",
                "footer_prompt": "input_text.ki_hinweis_prompt",
                "wrong_answer_prompt": "input_text.ki_hilfe_prompt",
            }
            for key, helper in prompt_mapping.items():
                value = str(self.get_state(helper) or "").strip()
                if value:
                    self.config[key] = value
            for index in range(4):
                if index >= len(self.config.get("topics", [])):
                    break
                name = str(self.get_state(f"input_text.ki_thema_{index + 1}") or "").strip()
                weight = self._helper_int(f"input_number.ki_gewicht_{index + 1}", 0)
                if name:
                    self.config["topics"][index]["name"] = name
                self.config["topics"][index]["weight"] = weight

            config_file = Path(
                self.args.get("config_file", "/config/apps/ki_kindersicherung/config.yaml")
            )
            temporary = config_file.with_suffix(".yaml.tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                yaml.safe_dump(self.config, stream, allow_unicode=True, sort_keys=False)
            temporary.replace(config_file)
            self._load_config()
            self._log_event("Konfiguration gespeichert")
            self._publish_runtime("Konfiguration gespeichert und übernommen")
        except Exception as exc:
            self.error(f"Konfiguration konnte nicht gespeichert werden: {exc}")
            self._publish_runtime("Speichern der Konfiguration fehlgeschlagen")

    def _ui_reload(self, entity, attribute, old, new, kwargs) -> None:
        self._load_config()
        self._log_event("Konfiguration neu geladen")
        self._publish_runtime("Konfiguration neu geladen")

    def _answer_changed(self, entity, attribute, old, new, kwargs) -> None:
        if new and new != old:
            self.submit_answer(str(new))

    def _command_changed(self, entity, attribute, old, new, kwargs) -> None:
        if new and new != old:
            self.process_command(str(new))

    def _command_event(self, event_name, data, kwargs) -> None:
        """Verarbeitet jeden Sprachbefehl als eigenes Ereignis, auch Wiederholungen."""
        command = str((data or {}).get("text") or (data or {}).get("befehl") or "").strip()
        if not command:
            return
        source = str((data or {}).get("source") or "assist")
        device_hint = str((data or {}).get("device") or "")
        target_player = self._resolve_voice_player(device_hint)
        self._log_event(
            f"Sprachbefehl empfangen ({source}, Ausgabe {target_player or 'Standard'}): {command}"
        )
        # Der Assist-Sprachkanal muss zunächst seine Intent-Bestätigung beenden,
        # bevor Piper die neue Aufgabe auf demselben Gerät ausgibt.
        self.process_command(command, speech_delay=3.0, voice_player=target_player)

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------
    def _helper_int(self, entity: str, fallback: int) -> int:
        try:
            return int(float(self.get_state(entity)))
        except (TypeError, ValueError):
            return fallback

    def _choose_topic(
        self,
        kind: str = "allgemein",
        requested_topic: str = "",
        requested_subtopic: str = "",
    ) -> Dict[str, Any]:
        valid = [topic for topic in self.topics if int(topic.get("weight", 0)) > 0]
        if not valid:
            return {"name": "Allgemein", "prompt": "Eine altersgerechte Wissensfrage."}
        if requested_subtopic:
            matching_topics = [
                topic for topic in valid
                if any(
                    subtopic.get("enabled", True)
                    and self._normalized_lookup(subtopic.get("name", "")) == self._normalized_lookup(requested_subtopic)
                    for subtopic in topic.get("subtopics", [])
                )
            ]
            if matching_topics:
                valid = matching_topics
        elif requested_topic:
            matching_topics = [
                topic for topic in valid
                if self._normalized_lookup(topic.get("name", "")) == self._normalized_lookup(requested_topic)
            ]
            if matching_topics:
                valid = matching_topics
        if kind == "knobel":
            creative = [topic for topic in valid if "kreat" in str(topic.get("name", "")).lower()]
            if creative:
                valid = creative
        selected = dict(random.choices(valid, weights=[int(x["weight"]) for x in valid], k=1)[0])
        if selected.get("subtopics_enabled", True) is False:
            selected["selected_subtopic"] = None
            return selected
        active_subtopics = [
            subtopic
            for subtopic in selected.get("subtopics", [])
            if subtopic.get("enabled", True)
            and (str(subtopic.get("name", "")).strip() or str(subtopic.get("prompt", "")).strip())
        ]
        requested = [
            subtopic for subtopic in active_subtopics
            if requested_subtopic
            and self._normalized_lookup(subtopic.get("name", "")) == self._normalized_lookup(requested_subtopic)
        ]
        selected["selected_subtopic"] = (
            requested[0] if requested else random.choice(active_subtopics) if active_subtopics else None
        )
        return selected

    def _choose_adult_question_topic(self) -> Dict[str, Any]:
        valid = [
            dict(topic)
            for topic in self.adult_topics
            if topic.get("enabled", True) and int(topic.get("weight", 0)) > 0
        ]
        if not valid:
            return {
                "name": "Allgemeinwissen",
                "weight": 100,
                "difficulty": "gemischt",
                "subtopics": "",
                "prompt": "Stelle eine allgemein verständliche Wissensfrage für Erwachsene.",
            }
        return dict(
            random.choices(
                valid,
                weights=[int(topic.get("weight", 0)) for topic in valid],
                k=1,
            )[0]
        )

    @staticmethod
    def _normalized_lookup(value: Any) -> str:
        return re.sub(r"[^a-z0-9äöüß]+", " ", str(value).lower()).strip()

    @staticmethod
    def _normalize_math_notation(value: Any) -> str:
        text = str(value or "")
        text = re.sub(r"\bgeteilt\s+durch\b", ":", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmal\b", "x", text, flags=re.IGNORECASE)
        text = re.sub(r"\bplus\b", "+", text, flags=re.IGNORECASE)
        text = re.sub(r"\bminus\b", "-", text, flags=re.IGNORECASE)
        return text.replace("×", "x").replace("÷", ":")

    def _requested_topic(self, command: str) -> tuple[str, str]:
        text = self._normalized_lookup(command)
        aliases = {
            "mathematikaufgabe": "mathematik",
            "matheaufgabe": "mathematik",
            "deutschaufgabe": "deutsch",
            "kreativaufgabe": "kreativität",
            "sachaufgabe": "sachkunde",
            "sachkundeaufgabe": "sachkunde",
        }
        requested_alias = next((topic for alias, topic in aliases.items() if alias in text), "")
        for topic in self.topics:
            if int(topic.get("weight", 0)) <= 0:
                continue
            for subtopic in topic.get("subtopics", []):
                name = str(subtopic.get("name", "")).strip()
                if subtopic.get("enabled", True) and name and self._normalized_lookup(name) in text:
                    return str(topic.get("name", "")), name
        for topic in self.topics:
            name = str(topic.get("name", "")).strip()
            normalized_name = self._normalized_lookup(name)
            if (
                int(topic.get("weight", 0)) > 0
                and name
                and (normalized_name in text or normalized_name == requested_alias)
            ):
                return name, ""
        return "", ""

    def _is_free_question_command(self, text: str) -> bool:
        normalized = self._normalized_lookup(text)
        # Ein bloß erwähntes Thema darf das Werkzeug nicht aktivieren. Das verhindert,
        # dass fremde Medien- oder Alltagsbefehle durch zufällige Themenwörter als
        # Aufgabenanforderung behandelt und im Kindersicherungsverlauf gespeichert werden.
        return "aufgabe" in normalized

    @staticmethod
    def _normalized_question(question: str) -> str:
        return re.sub(r"[^a-z0-9äöüß]+", " ", str(question).lower()).strip()

    @classmethod
    def _parse_question_result(cls, raw: str) -> Dict[str, Any]:
        data = cls._parse_json(raw)
        return data if data.get("question") else {}

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        if not raw:
            return {}
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _minutes_from_text(text: str) -> int:
        match = re.search(r"(?:in|nach)\s+(\d+)\s+min", text)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _number_from_german(value: str) -> Optional[int]:
        words = {
            "eine": 1, "einer": 1, "einem": 1, "ein": 1, "eins": 1,
            "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
            "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
            "elf": 11, "zwölf": 12, "zwoelf": 12,
        }
        return int(value) if value.isdigit() else words.get(value)

    @classmethod
    def _duration_from_text(cls, text: str) -> Optional[timedelta]:
        number = r"\d+|eine|einer|einem|ein|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|elf|zwölf|zwoelf"
        hour_match = re.search(rf"(?:für\s+)?({number})\s*(?:stunden?|std\.?)(?:\s+lang)?", text)
        if hour_match:
            value = cls._number_from_german(hour_match.group(1))
            return timedelta(hours=value) if value else None
        minute_match = re.search(rf"für\s+({number})\s*minuten?(?:\s+lang)?", text)
        if minute_match:
            value = cls._number_from_german(minute_match.group(1))
            return timedelta(minutes=value) if value else None
        return None

    @staticmethod
    def _duration_label(duration: timedelta) -> str:
        minutes = int(duration.total_seconds() // 60)
        if minutes % 60 == 0:
            hours = minutes // 60
            return f"{hours} Stunde" if hours == 1 else f"{hours} Stunden"
        return f"{minutes} Minuten"

    def _until_from_text(self, text: str) -> Optional[datetime]:
        match = re.search(r"bis\s+(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?", text)
        if not match:
            return None
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        now = self.datetime()
        target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        return target + timedelta(days=1) if target <= now else target

    def _answer_deadline_text(self) -> str:
        if not self._answer_timer:
            return "-"
        try:
            return self.info_timer(self._answer_timer).get("timestamp", "-")
        except Exception:
            return "-"

    def _cancel_timer(self, attribute: str) -> None:
        handle = getattr(self, attribute, None)
        if handle:
            try:
                self.cancel_timer(handle)
            except Exception:
                pass
            setattr(self, attribute, None)

    def _log_event(self, message: str) -> None:
        stamp = self.datetime().strftime("%d.%m.%Y %H:%M:%S")
        self._history.insert(0, f"{stamp} – {message}")
        self._history = self._history[:100]
        self.log(message)
        self._publish_log()

    def _load_conversation_history(self) -> None:
        try:
            if self._conversation_file.exists():
                data = json.loads(self._conversation_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._conversation_history = [item for item in data if isinstance(item, dict)][-300:]
        except Exception as exc:
            self.warning(f"Konversationsverlauf konnte nicht geladen werden: {exc}")

    def _save_conversation_history(self) -> None:
        try:
            temporary = self._conversation_file.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(self._conversation_history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self._conversation_file)
        except Exception as exc:
            self.warning(f"Konversationsverlauf konnte nicht gespeichert werden: {exc}")

    def _record_conversation(self, role: str, text: str) -> None:
        clean_text = str(text or "").strip()
        if not clean_text:
            return
        self._conversation_history.append({
            "time": self.datetime().strftime("%d.%m.%Y %H:%M:%S"),
            "role": "user" if role == "user" else "assistant",
            "text": clean_text,
        })
        self._conversation_history = self._conversation_history[-300:]
        self._save_conversation_history()

    def _publish_log(self) -> None:
        self.set_state(
            "sensor.ki_kinderschutz_log",
            state=self._history[0] if self._history else "Leer",
            attributes={"friendly_name": "Kindersicherung Live-Log", "entries": self._history},
        )


TASK_DISPLAY_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>Alexs Aufgaben</title>
  <style>
    :root { color-scheme: dark; font-family: "Segoe UI", Arial, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; overflow: hidden; color: #f8fbff; background: #101722; }
    .screen { min-height: 100vh; padding: clamp(28px,4vw,72px); display: grid; grid-template-rows: auto 1fr auto; gap: clamp(22px,3vh,42px); }
    header { display:flex; align-items:center; justify-content:space-between; gap:24px; }
    .brand { display:flex; align-items:center; gap:18px; font-size:clamp(24px,2.4vw,42px); font-weight:800; }
    .brand-icon { width:1.65em; height:1.65em; border-radius:18px; display:grid; place-items:center; background:#287fd1; }
    .mode { padding:12px 22px; border:1px solid #ffffff36; border-radius:999px; background:#ffffff12; font-size:clamp(16px,1.25vw,23px); }
    .card { align-self:center; width:min(1500px,100%); margin:auto; padding:clamp(30px,4vw,66px); border:1px solid #ffffff24; border-radius:28px; background:#182331; display:grid; grid-template-columns:minmax(0,1.75fr) minmax(270px,.7fr); gap:clamp(28px,4vw,70px); align-items:center; }
    .question-copy { min-width:0; }
    .illustration { min-height:310px; display:grid; place-items:center; border-left:1px solid #ffffff1d; padding-left:clamp(24px,3vw,50px); }
    .illustration svg { width:min(100%,360px); height:auto; display:block; }
    .eyebrow { color:#8fdcff; text-transform:uppercase; letter-spacing:.16em; font-size:clamp(14px,1.15vw,22px); font-weight:800; }
    .question { margin:22px 0 28px; white-space:pre-wrap; font-size:clamp(32px,3.45vw,64px); line-height:1.2; font-weight:720; text-wrap:balance; }
    .empty { color:#cbd7e6; }
    .meta { display:flex; flex-wrap:wrap; gap:14px 28px; color:#c9d7e8; font-size:clamp(16px,1.35vw,25px); }
    .hint { margin-top:28px; color:#aebfd2; font-size:clamp(15px,1.15vw,21px); }
    .task-footer { display:grid; gap:18px; }
    .footer-actions { display:flex; justify-content:center; flex-wrap:wrap; gap:18px; }
    .footer-prompt { padding:16px 24px 0; border-top:1px solid #ffffff24; color:#c9d7e8; text-align:center; font-size:clamp(15px,1.25vw,23px); line-height:1.35; }
    .footer-prompt:empty { display:none; }
    button { min-width:220px; padding:18px 28px; border:2px solid transparent; border-radius:18px; color:#fff; background:#ffffff18; font:700 clamp(17px,1.35vw,24px)/1.2 inherit; cursor:pointer; transition:.15s ease; }
    button.primary { background:#287fd1; }
    button.danger { background:#b43b48; }
    button:focus { outline:none; transform:scale(1.06); border-color:#fff; box-shadow:0 0 0 7px #68b9ff55,0 16px 40px #0007; }
    button[hidden] { display:none; }
    .offline { position:fixed; right:24px; bottom:22px; padding:10px 16px; border-radius:12px; background:#a82d38; font-weight:700; display:none; }
    @media(max-width:900px){ body{overflow:auto}.screen{padding:22px}.card{padding:28px;grid-template-columns:1fr}.illustration{border-left:0;border-top:1px solid #ffffff1d;padding:24px 0 0;min-height:220px}.question{font-size:clamp(28px,7vw,48px)}button{min-width:100%} }
  </style>
</head>
<body>
  <div class="screen">
    <header>
      <div class="brand"><span class="brand-icon">★</span><span>Alexs Aufgabe</span></div>
      <div id="mode" class="mode">Bereit</div>
    </header>
    <main class="card">
      <div class="question-copy">
        <div id="eyebrow" class="eyebrow">Aufgabenmodus</div>
        <div id="question" class="question empty">Ich warte auf eine neue Aufgabe.</div>
        <div class="meta"><span id="timer">Keine Antwortfrist</span><span id="attempts"></span></div>
        <div class="hint">Antworte über das Sprachgerät. Mit dem Steuerkreuz navigieren und mit OK auswählen. <span id="audioStatus"></span></div>
      </div>
      <div id="illustration" class="illustration" aria-label="Illustration zur Aufgabe"></div>
    </main>
    <footer class="task-footer">
      <div class="footer-actions">
        <button id="start" class="primary" onclick="run('single_question')">Neue Aufgabe</button>
        <button id="repeat" onclick="run('repeat_question')" hidden>Wiederholen</button>
        <button id="next" class="primary" onclick="run('new_question')" hidden>Andere Aufgabe</button>
        <button id="end" class="danger" onclick="run('end_question')" hidden>Beenden</button>
      </div>
      <div id="footerPrompt" class="footer-prompt"></div>
    </footer>
  </div>
  <audio id="tvAudio" preload="auto"></audio>
  <div id="offline" class="offline">Verbindung wird wiederhergestellt …</div>
  <script>
    const endpoint=name=>`/api/appdaemon/${name}`;
    async function post(name,data={}){const r=await fetch(endpoint(name),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok)throw new Error(await r.text());return r.json();}
    const buttons=()=>[...document.querySelectorAll('button:not([hidden])')];
    let focusIndex=0,lastQuestionId=-1,lastAudioId=-1;
    function focusButton(delta=0){const list=buttons();if(!list.length)return;focusIndex=(focusIndex+delta+list.length)%list.length;list[focusIndex].focus();}
    async function playTvAudio(url,id){
      if(!url||id===lastAudioId)return;
      lastAudioId=id;
      const status=document.getElementById('audioStatus');
      const audio=document.getElementById('tvAudio');
      audio.pause();audio.src=url;audio.load();
      audio.onplay=()=>status.textContent='Die eingestellte Home-Assistant-Stimme wird über den Fernseher ausgegeben.';
      audio.onended=()=>status.textContent='';
      audio.onerror=()=>status.textContent='Die erzeugte TV-Sprachausgabe konnte nicht geladen werden.';
      try{await audio.play()}catch(e){status.textContent='TV-Audio wartet auf eine Freigabe durch das Gerät.';}
    }
    function artFor(topic=''){
      const t=topic.toLowerCase(), common='viewBox="0 0 360 300" role="img" aria-hidden="true"';
      if(t.includes('mathe'))return `<svg ${common}><rect x="52" y="35" width="256" height="230" rx="28" fill="#24354a"/><circle cx="125" cy="105" r="42" fill="#287fd1"/><text x="125" y="118" text-anchor="middle" font-size="44" fill="white">+</text><circle cx="235" cy="105" r="42" fill="#39a37b"/><text x="235" y="118" text-anchor="middle" font-size="44" fill="white">×</text><text x="180" y="220" text-anchor="middle" font-size="62" font-weight="700" fill="#dcecff">1 2 3</text></svg>`;
      if(t.includes('deutsch'))return `<svg ${common}><path d="M55 64q65-24 125 14v166q-58-34-125-10z" fill="#287fd1"/><path d="M305 64q-65-24-125 14v166q58-34 125-10z" fill="#39a37b"/><path d="M180 78v166" stroke="#dcecff" stroke-width="6"/><text x="180" y="157" text-anchor="middle" font-size="54" font-weight="700" fill="white">A B C</text></svg>`;
      if(t.includes('sach'))return `<svg ${common}><circle cx="180" cy="145" r="100" fill="#287fd1"/><path d="M105 106q45-58 88-18 38-8 62 22-20 20-47 16-18 42-60 22-22-16-43-42zM148 188q55-25 94 10-33 42-90 44-22-20-4-54z" fill="#55b889"/><path d="M180 45v200M80 145h200" stroke="#dcecff" stroke-width="5" opacity=".55"/><ellipse cx="180" cy="145" rx="48" ry="100" fill="none" stroke="#dcecff" stroke-width="5" opacity=".55"/></svg>`;
      if(t.includes('kreat'))return `<svg ${common}><path d="M180 42c-61 0-105 49-105 105 0 39 21 66 53 87 12 8 16 15 17 28h70c1-13 5-20 17-28 32-21 53-48 53-87 0-56-44-105-105-105z" fill="#e4a93c"/><path d="M142 264h76M151 282h58" stroke="#dcecff" stroke-width="12" stroke-linecap="round"/><path d="M180 6v22M66 51l18 16M294 51l-18 16M38 150h26M296 150h26" stroke="#e4a93c" stroke-width="9" stroke-linecap="round"/></svg>`;
      return `<svg ${common}><circle cx="180" cy="145" r="108" fill="#287fd1"/><text x="180" y="190" text-anchor="middle" font-size="150" font-weight="700" fill="white">?</text></svg>`;
    }
    async function load(){try{const d=await post('ki_kindersicherung_admin_status');const enabled=d.tv_display_enabled!==false;const active=enabled&&!!d.question;document.getElementById('mode').textContent=enabled?(d.mode_label||'Bereit'):'TV-Ausgabe aus';document.getElementById('eyebrow').textContent=enabled?(d.question_subtopic||d.question_topic||'Aufgabenmodus'):'Kindersicherung';document.getElementById('question').textContent=enabled?(d.question||'Ich warte auf eine neue Aufgabe.'):'Die TV-Aufgabenausgabe ist in der Kindersicherung deaktiviert.';document.getElementById('illustration').innerHTML=artFor(enabled?d.question_topic:'');document.getElementById('question').classList.toggle('empty',!active);document.getElementById('timer').textContent=enabled?(active?(d.answer_until||'Antwortzeit läuft'):'Keine Antwortfrist'):'';document.getElementById('attempts').textContent=active&&d.maximum_attempts?`Versuch ${Math.min((d.attempts||0)+1,d.maximum_attempts)} von ${d.maximum_attempts}`:'';document.getElementById('footerPrompt').textContent=active?(d.tv_footer_prompt||''):'';document.getElementById('start').hidden=!enabled||active;document.getElementById('repeat').hidden=!active;document.getElementById('next').hidden=!active;document.getElementById('end').hidden=!active||d.mode==='bedingt';document.getElementById('offline').style.display='none';if(enabled)playTvAudio(d.tv_audio_url||'',Number(d.tv_audio_id)||0);if(lastQuestionId!==d.question_id){lastQuestionId=d.question_id;focusIndex=0;focusButton(0)}}catch(e){document.getElementById('offline').style.display='block'}}
    async function run(action){try{await post('ki_kindersicherung_admin_action',{action});setTimeout(load,350)}catch(e){document.getElementById('offline').style.display='block'}}
    addEventListener('keydown',e=>{if(['ArrowRight','ArrowDown'].includes(e.key)){e.preventDefault();focusButton(1)}else if(['ArrowLeft','ArrowUp'].includes(e.key)){e.preventDefault();focusButton(-1)}else if(e.key==='Enter'){const el=document.activeElement;if(el?.tagName==='BUTTON'){e.preventDefault();el.click()}}else if(e.key.toLowerCase()==='r')run('repeat_question');else if(e.key.toLowerCase()==='n')run('new_question')});
    load();setInterval(load,1000);
  </script>
</body>
</html>"""


QUIZ_DISPLAY_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>Klugscheißer</title>
  <style>
    :root{color-scheme:dark;font-family:"Segoe UI",Arial,sans-serif}*{box-sizing:border-box}
    body{margin:0;min-height:100vh;background:#101722;color:#f8fbff}.screen{min-height:100vh;padding:clamp(24px,4vw,68px);display:grid;grid-template-rows:auto 1fr auto;gap:24px}
    header{display:flex;justify-content:space-between;align-items:center;gap:20px}.brand{font-size:clamp(28px,3vw,52px);font-weight:800}.badge{padding:10px 18px;border:1px solid #ffffff38;border-radius:999px;background:#ffffff12}
    main{align-self:center;display:block}.card{padding:clamp(24px,3vw,48px);border:1px solid #ffffff24;border-radius:24px;background:#182331}.question-card{min-height:min(66vh,720px);display:grid;grid-template-columns:minmax(0,1fr) minmax(150px,240px);gap:clamp(20px,4vw,64px);align-items:center}.question-content{min-width:0}.quiz-art{align-self:center;width:100%;max-width:230px;justify-self:end;opacity:.96}.quiz-art svg{display:block;width:100%;height:auto;filter:drop-shadow(0 12px 20px #0005)}
    .eyebrow{color:#8fdcff;text-transform:uppercase;letter-spacing:.14em;font-weight:800}.player{margin:14px 0;font-size:clamp(38px,5vw,78px);font-weight:800}.info{color:#c9d7e8;font-size:clamp(18px,1.6vw,28px);line-height:1.45}
    .question{margin:22px 0;font-size:clamp(27px,3vw,50px);font-weight:700;line-height:1.25}.choices{display:grid;grid-template-columns:1fr 1fr;gap:12px}.choice{min-width:0;text-align:left}.feedback{margin-top:18px;padding:14px;border-radius:12px;background:#ffffff0d;color:#bfe5ff;font-size:clamp(17px,1.4vw,25px)}.scores{margin-top:18px;color:#dcecff}
    .topics{display:grid;gap:10px;margin-top:20px}.topic{display:flex;justify-content:space-between;gap:16px;padding:12px 14px;border-radius:12px;background:#ffffff0d}.difficulty{color:#8fdcff}
    .game-head{display:flex;align-items:center;gap:18px;min-width:0}.roll-logo{width:66px;height:58px;flex:0 0 auto}.wordmark{position:relative;display:inline-block;font-size:clamp(30px,4vw,62px);font-weight:900;letter-spacing:-.04em;color:#fff}.wordmark:after{content:"";position:absolute;left:0;right:-45vw;bottom:-9px;height:9px;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='9' viewBox='0 0 160 9'%3E%3Cpath d='M0 5 Q8 1 16 5 T32 5 T48 5 T64 5 T80 5 T96 5 T112 5 T128 5 T144 5 T160 5' fill='none' stroke='%23f3d36a' stroke-width='3' stroke-linecap='round'/%3E%3C/svg%3E") repeat-x left center/160px 9px}.launch-track{position:relative;overflow:hidden;padding:22px 18px 8px;border:1px solid #ffffff22;border-radius:22px;background:linear-gradient(180deg,#172635,#101822)}.track-title{display:flex;justify-content:space-between;gap:16px;color:#c8d8e8;font-weight:700}.track{position:relative;height:178px;margin-top:6px}.track-line{position:absolute;left:2%;right:2%;bottom:18px;height:5px;border-radius:50%;background:#f3d36a;transform:rotate(-.35deg);box-shadow:0 2px 0 #8b6b28}.milestones{position:absolute;inset:0;display:grid;grid-template-columns:repeat(10,1fr);align-items:end;gap:4px}.milestone{position:relative;height:150px;display:flex;align-items:flex-end;justify-content:center}.outhouse{width:min(7.4vw,72px);height:auto;filter:grayscale(.7) brightness(.72);opacity:.55;transform-origin:center bottom}.milestone.reached .outhouse{filter:none;opacity:1}.milestone.active .outhouse{filter:none;opacity:1;drop-shadow:0 0 12px #f3d36a88}.step{position:absolute;bottom:-3px;right:4px;width:25px;height:25px;border-radius:50%;display:grid;place-items:center;background:#223246;border:2px solid #f3d36a;color:white;font-size:12px;font-weight:900}.smoke{position:absolute;left:50%;bottom:11px;width:42px;height:35px;transform:translateX(-50%);opacity:0}.active.stage-1 .smoke,.active.stage-2 .smoke,.active.stage-3 .smoke,.active.stage-4 .smoke,.active.stage-5 .smoke,.active.stage-6 .smoke,.active.stage-7 .smoke,.active.stage-8 .smoke,.active.stage-9 .smoke,.active.stage-10 .smoke{opacity:1}.smoke i{position:absolute;bottom:0;width:17px;height:17px;border-radius:50%;background:#c7d1d8;animation:puff 1.2s infinite ease-out}.smoke i:nth-child(2){left:14px;animation-delay:.25s}.smoke i:nth-child(3){left:27px;animation-delay:.5s}.stage-4 .outhouse,.stage-5 .outhouse,.stage-6 .outhouse,.stage-7 .outhouse,.stage-8 .outhouse,.stage-9 .outhouse{animation:rumble .18s infinite}.stage-7 .smoke i,.stage-8 .smoke i,.stage-9 .smoke i{background:#eef3f6;transform:scale(1.5)}.stage-10 .outhouse{animation:launch 2.4s ease-in forwards}.stage-10 .smoke{height:82px;background:linear-gradient(90deg,transparent,#ffb126,#fff6b0,#ff6a21,transparent);clip-path:polygon(42% 0,62% 0,87% 100%,9% 100%);animation:flame .16s infinite alternate}.mascot{position:absolute;bottom:23px;z-index:5;width:34px;height:68px;opacity:0;color:#05080b}.milestone.active .mascot{opacity:1;animation:walkIn 1.1s ease-out both}.mascot.child{height:54px;width:29px}.mascot svg{width:100%;height:100%}.launch-message{position:absolute;inset:12px;display:none;place-items:center;text-align:center;font-size:clamp(30px,5vw,74px);font-weight:900;color:#fff;text-shadow:0 4px 20px #000;z-index:8}.track.launched .launch-message{display:grid;animation:pop 1s both}.score-chip{display:inline-flex;gap:7px;align-items:center;padding:7px 12px;border-radius:999px;background:#ffffff12}.score-chip.current{outline:2px solid #f3d36a;background:#f3d36a20}.score-row{display:flex;flex-wrap:wrap;gap:9px;margin-top:18px}.question-card{min-height:min(48vh,560px);margin-top:16px}.quiz-art{display:none}@keyframes puff{0%{transform:translateY(0) scale(.5);opacity:.9}100%{transform:translateY(-42px) scale(1.8);opacity:0}}@keyframes rumble{0%,100%{transform:rotate(-1deg) translateX(-1px)}50%{transform:rotate(1deg) translateX(1px)}}@keyframes launch{0%{transform:translateY(0)}18%{transform:translateY(5px)}100%{transform:translateY(-390px)}}@keyframes flame{to{filter:brightness(1.45);transform:scaleX(.86)}}@keyframes walkIn{from{transform:translateX(-85px);opacity:0}70%{opacity:1}to{transform:translateX(0);opacity:1}}@keyframes pop{from{opacity:0;transform:scale(.65)}to{opacity:1;transform:scale(1)}}
    footer{display:flex;justify-content:center;flex-wrap:wrap;gap:16px}button{min-width:210px;padding:17px 25px;border:2px solid transparent;border-radius:16px;background:#ffffff18;color:white;font:700 clamp(17px,1.3vw,23px)/1.2 inherit}button.primary{background:#287fd1}button.danger{background:#a93845}button:focus{outline:none;border-color:#fff;box-shadow:0 0 0 7px #68b9ff55;transform:scale(1.05)}
    header{position:relative;min-height:92px;align-items:flex-start}.game-head{position:relative;z-index:4;padding-top:8px}.header-course{position:relative;left:auto;right:auto;top:auto;height:160px;margin-top:20px;border-radius:18px;background:#15202c}.course-line{position:absolute;left:2%;right:2%;bottom:21px;height:5px;background:#f3d36a;transform:rotate(-.25deg);border-radius:50%;box-shadow:0 2px 0 #866722}.player-houses{position:absolute;inset:0;display:flex;flex-direction:row-reverse;align-items:flex-end;justify-content:flex-start;gap:clamp(14px,3vw,54px);padding:0 24px 0 30px}.player-house{position:relative;width:clamp(64px,7vw,100px);height:128px;display:flex;align-items:flex-end;justify-content:center;transform-origin:center bottom}.player-house .outhouse{width:clamp(58px,6vw,88px);filter:none;opacity:1}.player-house.current .outhouse{filter:drop-shadow(0 0 13px #f3d36aaa)}.player-house .house-name{position:absolute;bottom:-9px;left:50%;transform:translate(-50%,100%);max-width:110px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:800;color:#f8fbff}.player-house .house-score{position:absolute;right:-8px;top:7px;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:#f3d36a;color:#17202a;font-weight:900;border:3px solid #fff}.player-house .mascot{bottom:24px;left:-18px}.player-house.current .mascot{opacity:1;animation:walkIn 1.1s ease-out both}.player-house .smoke{bottom:10px}.player-house.stage-4 .outhouse,.player-house.stage-5 .outhouse,.player-house.stage-6 .outhouse,.player-house.stage-7 .outhouse,.player-house.stage-8 .outhouse,.player-house.stage-9 .outhouse{animation:rumble .18s infinite}.player-house.stage-10{z-index:20;animation:launchAcross 3.2s ease-in forwards}.player-house.stage-10 .outhouse{animation:none}.player-house.stage-10 .smoke{height:82px;opacity:1;background:linear-gradient(90deg,transparent,#ffb126,#fff6b0,#ff6a21,transparent);clip-path:polygon(42% 0,62% 0,87% 100%,9% 100%);animation:flame .16s infinite alternate}.player-house.winner:after{content:"ABGEHOBEN!";position:absolute;top:20px;left:50%;transform:translateX(-50%);font-weight:900;color:#fff;text-shadow:0 3px 12px #000;white-space:nowrap}.launch-track{display:none}.question-card{min-height:min(57vh,620px);margin-top:0;grid-template-columns:minmax(0,1.35fr) minmax(250px,.65fr);background:#f6f0df;color:#17202a;border-color:#decda9}.question-card .eyebrow{color:#7c542d}.question-card .info{color:#526171}.question-card .question{color:#17202a}.question-card .choice{background:#fff;color:#17202a;border-color:#cfb98e}.question-card .choice:focus{border-color:#287fd1;box-shadow:0 0 0 7px #287fd144}.question-card .feedback{background:#e7dcc5;color:#243345}.quiz-art{display:block;max-width:360px;padding:24px;border-left:2px dashed #bba77c}.score-row{margin:14px 0 0}.score-chip{background:#e5d9c0;color:#243345}.score-chip.current{outline-color:#8d6037;background:#f3d36a}.wordmark:after{display:none}@keyframes launchAcross{0%{transform:translate(0,0) rotate(0)}14%{transform:translate(0,8px) rotate(-2deg)}35%{transform:translate(-22vw,-18vh) rotate(-18deg)}100%{transform:translate(-120vw,-88vh) rotate(-38deg)}}
    .player-house.stage-1 .smoke,.player-house.stage-2 .smoke,.player-house.stage-3 .smoke,.player-house.stage-4 .smoke,.player-house.stage-5 .smoke,.player-house.stage-6 .smoke,.player-house.stage-7 .smoke,.player-house.stage-8 .smoke,.player-house.stage-9 .smoke,.player-house.stage-10 .smoke{opacity:1}.player-house.stage-1 .smoke{transform:translateX(-50%) scale(.65)}.player-house.stage-2 .smoke{transform:translateX(-50%) scale(.8)}.player-house.stage-3 .smoke{transform:translateX(-50%) scale(1)}.player-house.stage-7 .smoke,.player-house.stage-8 .smoke,.player-house.stage-9 .smoke{transform:translateX(-50%) scale(1.35)}
    .arrival-figure{position:absolute;z-index:10;left:50%;bottom:22px;width:34px;height:68px;color:#05080b;pointer-events:none;animation:walkFromScreenEdge 2.8s ease-in-out forwards}.arrival-figure.child{width:29px;height:54px}.arrival-figure svg{width:100%;height:100%}.seated-mascot{position:absolute;z-index:6;left:50%;bottom:17px;width:32px;height:54px;transform:translateX(-50%);color:#05080b;opacity:1}.seated-mascot svg{width:100%;height:100%}.player-house.celebrate .seated-mascot{animation:happyHop .72s ease-out}.answer-puff{position:absolute;z-index:9;left:50%;bottom:34px;width:14px;height:14px;border-radius:50%;background:#fff;opacity:0;box-shadow:-18px 7px 0 #dce5ea,18px 5px 0 #eef4f7;animation:answerPuff .8s ease-out forwards}@keyframes walkFromScreenEdge{0%{transform:translateX(-105vw);opacity:1}70%{transform:translateX(-38px);opacity:1}88%{transform:translateX(-4px) scale(.9);opacity:1}100%{transform:translateX(0) scale(.68);opacity:0}}@keyframes happyHop{0%,100%{transform:translateX(-50%) translateY(0) rotate(0)}38%{transform:translateX(-50%) translateY(-25px) rotate(-6deg)}68%{transform:translateX(-50%) translateY(-7px) rotate(5deg)}}@keyframes answerPuff{0%{transform:translate(-50%,0) scale(.35);opacity:0}20%{opacity:.95}100%{transform:translate(-50%,-55px) scale(2.2);opacity:0}}
    .player-house.winner:after{display:none}.winner-quip{position:fixed;z-index:30;left:50%;top:18%;width:min(88vw,960px);transform:translateX(-50%);padding:18px 28px;border-radius:22px;background:#172331e8;color:#fff;text-align:center;font-size:clamp(28px,4.4vw,68px);font-weight:900;text-shadow:0 3px 12px #000;box-shadow:0 18px 60px #0009;animation:pop .7s both}
    @media(max-width:850px){body{overflow:auto}.screen{padding:20px}header{min-height:84px}.header-course{height:145px}.player-houses{gap:8px}.player-house{width:58px}.player-house .outhouse{width:50px}.player-house .house-name{font-size:11px}.question-card{grid-template-columns:1fr;min-height:auto}.quiz-art{max-width:210px;justify-self:center;border-left:0;border-top:2px dashed #bba77c}button{min-width:100%}}
  </style>
</head>
<body>
  <div class="screen">
    <header><div class="game-head"><svg class="roll-logo" viewBox="0 0 90 76" aria-hidden="true"><ellipse cx="30" cy="35" rx="27" ry="29" fill="#f7f4e8" stroke="#d5cfc0" stroke-width="4"/><ellipse cx="30" cy="35" rx="10" ry="11" fill="#172331"/><path d="M30 6h34c15 0 23 12 23 29S79 64 64 64H30c17-7 17-51 0-58z" fill="#fffdf4" stroke="#d5cfc0" stroke-width="4"/><path d="M63 64v10l-10-5-10 5-10-5-9 5V50" fill="#fffdf4" stroke="#d5cfc0" stroke-width="4" stroke-linejoin="round"/><path d="M47 18v32M66 18v32" stroke="#e5dfd0" stroke-width="2" stroke-dasharray="4 5"/></svg><span class="wordmark">Klugscheißer</span></div></header>
    <main>
      <section class="card question-card"><div class="question-content"><div class="eyebrow" id="round">Noch nicht gestartet</div><div class="player" id="player">Bereit für Klugscheißer</div><div class="info" id="playerInfo">Die Spieler- und Themenkonfiguration wird aus Home Assistant geladen.</div><div id="scoreRow" class="score-row"></div><div id="question" class="question"></div><div id="choices" class="choices"></div><div id="feedback" class="feedback" hidden></div><div id="scores" class="scores"></div></div><div id="quizArt" class="quiz-art" aria-label="Illustration zum Wissensgebiet"></div></section><section class="header-course"><div class="course-line"></div><div id="playerHouses" class="player-houses"></div></section>
      <section hidden><div id="topics"></div></section>
    </main>
    <footer><button id="start" class="primary" onclick="run('quiz_demo_start')">Klugscheißer starten</button><button id="repeat" onclick="run('quiz_repeat_question')">Frage wiederholen</button><button id="next" onclick="run('quiz_next_player')">Nächster Spieler</button><button id="reset" class="danger" onclick="run('quiz_demo_reset')">Spiel beenden</button></footer>
  </div>
  <audio id="quizAudio" preload="auto"></audio>
  <script>
    const endpoint=name=>`/api/appdaemon/${name}`;let focusIndex=0,lastAudioId=-1;
    async function post(name,data={}){const r=await fetch(endpoint(name),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok||d.status==='error')throw new Error(d.message||'Fehler');return d}
    function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
    function artFor(topic=''){
      const t=topic.toLowerCase(),common='viewBox="0 0 240 240" role="img" aria-hidden="true"';
      if(/geo|land|welt|europa/.test(t))return `<svg ${common}><circle cx="120" cy="120" r="96" fill="#287fd1"/><path d="M55 82q38-47 76-16 36-10 60 18-21 24-52 17-13 34-48 19-22-10-36-38zm56 73q51-25 83 12-34 38-85 39-18-21 2-51z" fill="#55b889"/><ellipse cx="120" cy="120" rx="45" ry="96" fill="none" stroke="#dcecff" stroke-width="5" opacity=".5"/></svg>`;
      if(/geschicht|antike|mittelalter|zeit/.test(t))return `<svg ${common}><path d="M42 70h156l-18 132H60z" fill="#b4773e"/><path d="M58 70q62-55 124 0" fill="#e6bd71"/><path d="M82 97h76M76 126h88M72 155h70" stroke="#fff1cf" stroke-width="9" stroke-linecap="round"/><circle cx="174" cy="169" r="30" fill="#287fd1"/><path d="M174 150v21l15 10" stroke="white" stroke-width="7" fill="none" stroke-linecap="round"/></svg>`;
      if(/wissenschaft|technik|natur|medizin/.test(t))return `<svg ${common}><path d="M89 35h62M103 35v64l-50 82q-14 24 15 24h104q29 0 15-24l-50-82V35" fill="#24354a" stroke="#8fdcff" stroke-width="8"/><path d="M75 158h90l22 36q5 11-15 11H68q-20 0-15-11z" fill="#39a37b"/><circle cx="105" cy="145" r="9" fill="#dcecff"/><circle cx="137" cy="178" r="12" fill="#dcecff"/></svg>`;
      if(/kunst|literatur|musik|buch/.test(t))return `<svg ${common}><path d="M43 55q42-18 77 8v139q-34-25-77-10z" fill="#287fd1"/><path d="M197 55q-42-18-77 8v139q34-25 77-10z" fill="#39a37b"/><path d="M120 63v139" stroke="#dcecff" stroke-width="6"/><circle cx="176" cy="89" r="17" fill="#e4a93c"/><path d="M176 89v54q-31-8-31 17 0 22 25 14 15-5 12-27" fill="#e4a93c"/></svg>`;
      if(/sport|freizeit|spiel/.test(t))return `<svg ${common}><circle cx="120" cy="120" r="96" fill="#f4f6f8"/><path d="M120 24v192M24 120h192M52 55q68 64 136 0M52 185q68-64 136 0" fill="none" stroke="#e06a47" stroke-width="8"/></svg>`;
      if(/unterhaltung|film|fernseh|pop/.test(t))return `<svg ${common}><rect x="28" y="55" width="184" height="135" rx="18" fill="#287fd1"/><path d="M101 91l58 32-58 32z" fill="white"/><path d="M76 214h88" stroke="#8fdcff" stroke-width="12" stroke-linecap="round"/></svg>`;
      if(/mathe/.test(t))return `<svg ${common}><rect x="30" y="34" width="180" height="172" rx="28" fill="#287fd1"/><text x="120" y="102" text-anchor="middle" font-size="62" fill="white">+</text><text x="120" y="174" text-anchor="middle" font-size="54" fill="#dcecff">1 2 3</text></svg>`;
      return `<svg ${common}><path d="M120 28c-55 0-94 39-94 88 0 35 19 57 46 75 11 7 15 13 16 24h64c1-11 5-17 16-24 27-18 46-40 46-75 0-49-39-88-94-88z" fill="#e4a93c"/><path d="M88 218h64" stroke="#dcecff" stroke-width="12" stroke-linecap="round"/><text x="120" y="151" text-anchor="middle" font-size="92" font-weight="700" fill="white">?</text></svg>`;
    }
    function outhouseSvg(){return `<svg class="outhouse" viewBox="0 0 110 150" aria-hidden="true"><defs><linearGradient id="wood" x1="0" x2="1"><stop stop-color="#8d6037"/><stop offset=".5" stop-color="#ba8450"/><stop offset="1" stop-color="#76502f"/></linearGradient></defs><path d="M12 32L57 12l45 20-8 10H18z" fill="#403326"/><path d="M21 39h72v101H21z" fill="url(#wood)" stroke="#4d3422" stroke-width="3"/><path d="M32 48h48v92H32z" fill="#9a683d" stroke="#4d3422" stroke-width="3"/><path d="M45 61q11-15 22 0-4 11-11 17-8-6-11-17z" fill="#251d18"/><path d="M73 94h7" stroke="#2d241d" stroke-width="4" stroke-linecap="round"/><path d="M27 52h61M27 69h12M73 69h15M27 87h12M73 87h15M27 105h12M73 105h15M27 123h12M73 123h15" stroke="#d6aa73" stroke-width="1.6" opacity=".55"/></svg>`}
    function mascotSvg(role){const child=role==='kind';return `<svg viewBox="0 0 40 80" aria-hidden="true"><circle cx="20" cy="${child?18:14}" r="${child?10:11}" fill="currentColor"/><path d="M${child?11:9} ${child?29:27}q9-7 ${child?18:22} 0l4 ${child?27:32}-8 18h-7l-2-26-3 26h-7l-8-18z" fill="currentColor"/><path d="M12 38L2 54M28 38l10 16" stroke="currentColor" stroke-width="6" stroke-linecap="round"/></svg>`}
    function seatedSvg(role){const child=role==='kind';return `<svg viewBox="0 0 44 64" aria-hidden="true"><circle cx="22" cy="${child?13:11}" r="${child?9:10}" fill="currentColor"/><path d="M12 24q10-8 20 0v19H12z" fill="currentColor"/><path d="M13 39L5 53h15l2-10 3 10h15l-9-14" fill="currentColor"/><path d="M8 54h12M25 54h13" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>`}
    let lastPlayerKey='',lastTrackState='',previousScores=null,animationStates={};
    function renderLaunchTrack(q,p){const scores=q.scores||{},players=q.players||[],key=p?`${p.name}-${q.current_player_index}`:'',now=Date.now();if(previousScores!==null){for(const player of players){const before=Number(previousScores[player.name]||0),value=Number(scores[player.name]||0);if(before===0&&value===1)animationStates[player.name]={type:'arrive',until:now+3300};else if(before>=1&&value>before)animationStates[player.name]={type:'celebrate',until:now+1100}}}for(const name of Object.keys(animationStates)){if(animationStates[name].until<=now)delete animationStates[name]}const trackState=JSON.stringify([players.map(x=>[x.name,x.role]),scores,key,q.winner||'',q.finale_message||'',animationStates]);const houses=document.getElementById('playerHouses');if(trackState!==lastTrackState){lastTrackState=trackState;houses.innerHTML=players.map(player=>{const score=Math.min(10,Number(scores[player.name]||0)),current=p&&player.name===p.name,winner=q.winner===player.name,animation=animationStates[player.name]?.type||'';return `<div class="player-house stage-${score}${current?' current':''}${winner?' winner':''}${animation==='celebrate'?' celebrate':''}" title="${esc(player.name)}: ${score} von 10">${animation==='arrive'?`<div class="arrival-figure ${player.role==='kind'?'child':'adult'}">${mascotSvg(player.role)}</div>`:''}${score>0?'<div class="smoke"><i></i><i></i><i></i></div>':''}${outhouseSvg()}${score>0?`<div class="seated-mascot ${player.role==='kind'?'child':'adult'}">${seatedSvg(player.role)}</div>`:''}${animation==='celebrate'?'<div class="answer-puff"></div>':''}${winner?`<div class="winner-quip">${esc(q.finale_message||'Das Toilettenhäuschen erobert das Universum!')}</div>`:''}<span class="house-score">${score}</span><span class="house-name">${esc(player.name)}</span></div>`}).join('')}previousScores={...scores};lastPlayerKey=key;document.getElementById('scoreRow').innerHTML=Object.entries(scores).map(([name,value])=>`<span class="score-chip ${p&&name===p.name?'current':''}">🧻 <strong>${esc(name)}</strong> ${Math.min(10,Number(value)||0)}/10</span>`).join('');document.getElementById('quizArt').innerHTML=artFor(q.topic||'')}
    function updateArt(){document.getElementById('quizArt').innerHTML=artFor(document.getElementById('round').textContent)}
    async function playAudio(url,id){if(!url||id===lastAudioId)return;lastAudioId=id;const a=document.getElementById('quizAudio');a.pause();a.src=url;a.load();try{await a.play()}catch(e){}}
    async function load(){try{const d=await post('ki_kindersicherung_admin_status'),q=d.quiz||{},p=q.current_player;document.getElementById('round').textContent=q.ready?`Runde ${q.round} · ${q.topic||'Thema wird gewählt'}`:'Noch nicht gestartet';document.getElementById('player').textContent=p?`${p.name} ist an der Reihe`:'Bereit für Klugscheißer';document.getElementById('playerInfo').textContent=p?(p.role==='kind'?`Kinderfrage, Alter ${p.age}`:`Erwachsenenfrage, ${p.difficulty||'mittel'}`):`${q.player_count||0} Spieler konfiguriert`;document.getElementById('question').textContent=q.question||'';document.getElementById('choices').innerHTML=(q.choices||[]).map((c,i)=>`<button class="choice" onclick="answer('${String.fromCharCode(65+i)}')"><strong>${String.fromCharCode(65+i)}</strong> · ${esc(c)}</button>`).join('');const feedback=document.getElementById('feedback');feedback.textContent=q.feedback||'';feedback.hidden=!q.feedback;document.getElementById('scores').textContent='';renderLaunchTrack(q,p);const list=p?.role==='kind'?(q.child_topics||[]):(q.adult_topics||[]);document.getElementById('topics').innerHTML=list.length?list.map(t=>`<div class="topic"><span>${esc(t.name)}</span><span class="difficulty">${esc(p?.role==='kind'?`${t.weight||0} %`:(p?.difficulty||'mittel'))}</span></div>`).join(''):'<div class="info">Keine aktiven Themen konfiguriert.</div>';document.getElementById('start').disabled=q.ready;document.getElementById('repeat').disabled=!q.ready||!q.question;document.getElementById('next').disabled=!q.ready||!!q.winner;playAudio(d.tv_audio_url||'',Number(d.tv_audio_id)||0)}catch(e){document.getElementById('playerInfo').textContent=e.message}}
    async function run(action){const info=document.getElementById('playerInfo'),button=document.activeElement?.tagName==='BUTTON'?document.activeElement:null,oldText=button?.textContent||'';if(button){button.disabled=true;if(action==='quiz_demo_start')button.textContent='Frage wird erstellt …'}if(action==='quiz_demo_start')info.textContent='Die erste KI-Frage wird vorbereitet. Das kann einige Sekunden dauern …';try{await post('ki_kindersicherung_admin_action',{action});await load()}catch(e){info.textContent=e.message}finally{if(button){button.disabled=false;button.textContent=oldText}}}
    async function answer(value){try{await post('ki_kindersicherung_admin_action',{action:'quiz_answer',answer:value});await load()}catch(e){document.getElementById('playerInfo').textContent=e.message}}
    const buttons=()=>[...document.querySelectorAll('button:not([disabled])')];function focusButton(delta=0){const b=buttons();if(!b.length)return;focusIndex=(focusIndex+delta+b.length)%b.length;b[focusIndex].focus()}
    addEventListener('keydown',e=>{if(['ArrowRight','ArrowDown'].includes(e.key)){e.preventDefault();focusButton(1)}else if(['ArrowLeft','ArrowUp'].includes(e.key)){e.preventDefault();focusButton(-1)}else if(e.key==='Enter'&&document.activeElement?.tagName==='BUTTON'){e.preventDefault();document.activeElement.click()}});
    load();focusButton();setInterval(load,1500);
  </script>
</body>
</html>"""


DEBUG_DISPLAY_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Kindersicherung – Debug-Ausgabe</title>
  <style>
    html,body{width:100%;height:100%;margin:0;overflow:hidden;background:#101722;font-family:"Segoe UI",Arial,sans-serif}
    iframe{width:100%;height:100%;border:0;background:#101722}
    .state{position:fixed;z-index:10;right:14px;top:14px;padding:8px 12px;border-radius:999px;background:#17202acc;color:#fff;font-size:13px;box-shadow:0 2px 8px #0006;pointer-events:none}
    .state.off{background:#8a2d2dcc}
  </style>
</head>
<body>
  <div id="state" class="state">Debug-Ausgabe wird verbunden …</div>
  <iframe id="output" title="Debug-Ausgabe der Kindersicherung" allow="autoplay"></iframe>
  <script>
    const endpoint='/api/appdaemon/ki_kindersicherung_admin_status';
    const urls={task:'/app/ki_kindersicherung_aufgabe',quiz:'/app/ki_kindersicherung_quiz'};
    let current='';
    async function sync(){
      try{
        const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const data=await response.json();
        const page=data.debug_display_page==='quiz'?'quiz':'task';
        if(page!==current){current=page;document.getElementById('output').src=urls[page]}
        const state=document.getElementById('state');
        state.textContent=data.debug_mode?`Debug-Modus · ${page==='quiz'?'Quizseite':'Aufgabenseite'}`:'Debug-Modus ist ausgeschaltet';
        state.classList.toggle('off',!data.debug_mode);
      }catch(error){const state=document.getElementById('state');state.textContent='Verbindung wird wiederhergestellt …';state.classList.add('off')}
    }
    sync();setInterval(sync,400);
  </script>
</body>
</html>"""


ADMIN_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KI-Kindersicherung</title>
  <style>
    :root { color-scheme: light dark; font-family: Segoe UI, Arial, sans-serif; }
    body { margin: 0; background: #f5f7fa; color: #17202a; }
    main { max-width: 1500px; margin: 0 auto; padding: 22px; }
    h1 { margin: 0 0 16px; font-size: 28px; }
    .debug-header-badge { display:inline-block; margin-left:12px; color:#d32f2f; font-size:.72em; font-weight:800; vertical-align:baseline; }
    .debug-header-badge[hidden] { display:none; }
    h2 { margin: 0 0 12px; font-size: 18px; }
    section { background: #fff; border: 1px solid #d8e0e8; border-radius: 8px; padding: 16px; margin-bottom: 14px; }
    .top-navigation { position: sticky; top: 0; z-index: 20; background: #fff; border-bottom: 1px solid #d8e0e8; box-shadow: 0 1px 3px rgba(15,23,32,.08); }
    body.embedded .top-navigation { display: none; }
    body.embedded main { padding-top: 14px; }
    .tabs { max-width: 1500px; margin: 0 auto; display: flex; gap: 2px; min-height: 56px; align-items: stretch; padding: 0 22px; }
    .tabs button { position: relative; display: flex; align-items: center; justify-content: center; gap: 8px; min-width: 138px; border-radius: 0; background: transparent; color: #465463; padding: 10px 16px; font-weight: 600; }
    .tabs button::after { content: ""; position: absolute; left: 14px; right: 14px; bottom: 0; height: 3px; border-radius: 3px 3px 0 0; background: transparent; }
    .tabs button.active { background: transparent; color: #111827; }
    .tabs button.active::after { background: #1f6feb; }
    .tab-icon { width: 22px; height: 22px; display: inline-grid; place-items: center; font-size: 20px; line-height: 1; }
    .panel { display: none; }
    .panel.active { display: block; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    label { display: grid; gap: 6px; font-size: 13px; color: #465463; }
    input, select, textarea { box-sizing: border-box; width: 100%; border: 1px solid #b9c4cf; border-radius: 6px; padding: 9px 10px; font: inherit; background: #fff; color: #17202a; }
    input:focus, select:focus, textarea:focus { outline: 2px solid #03a9f4; outline-offset: 1px; border-color:#03a9f4; }
    textarea { min-height: 105px; resize: vertical; }
    button { border: 0; border-radius: 6px; background: #1f6feb; color: #fff; padding: 10px 14px; font: inherit; cursor: pointer; }
    button.secondary { background: #56616d; }
    button.danger { background: #b42318; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
    .action-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 10px; }
    .secondary-row { margin-top: 12px; }
    .status { padding: 10px 12px; border-radius: 6px; background: #eef4ff; border: 1px solid #c8dcff; margin-bottom: 12px; }
    .error { background: #fff0f0; border-color: #ffc8c8; }
    .question { min-height: 70px; padding: 14px; white-space: pre-wrap; border-radius: 6px; background: #e9f7ef; border: 1px solid #9fd8b5; margin-bottom: 12px; font-weight: 600; }
    .details { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .detail { border: 1px solid #d8e0e8; border-radius: 6px; padding: 10px 12px; background: #fbfcfe; }
    .detail strong { display: block; font-size: 12px; color: #5d6b78; margin-bottom: 4px; }
    .detail span { word-break: break-word; }
    pre { white-space: pre-wrap; word-break: break-word; background: #f7f9fb; border: 1px solid #d8e0e8; border-radius: 6px; padding: 12px; overflow: auto; }
    .log-window { background: #0f1720; color: #d7e2ed; min-height: 360px; max-height: 600px; font-family: Consolas, monospace; font-size: 13px; }
    .conversation { display: grid; gap: 12px; min-height: 260px; }
    .conversation-empty { color: #687684; text-align: center; padding: 42px 12px; }
    .message-row { display: flex; }
    .message-row.user { justify-content: flex-end; }
    .message-bubble { max-width: min(78%, 760px); border: 1px solid #d8e0e8; border-radius: 12px; padding: 11px 13px; background: #f3f6f9; white-space: pre-wrap; }
    .message-row.user .message-bubble { background: #dcecff; border-color: #a9cdf5; }
    .message-meta { display: flex; gap: 12px; justify-content: space-between; margin-bottom: 5px; color: #617181; font-size: 11px; }
    .help-intro { padding: 20px; }
    .help-intro h2 { font-size: 26px; }
    .help-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: start; }
    .help-card { margin: 0; min-height: 100%; box-sizing: border-box; }
    .help-card h2 { font-size: 20px; }
    .help-card h3 { margin: 16px 0 7px; font-size: 15px; }
    .help-card p { line-height: 1.55; }
    .help-card ul { margin: 8px 0 0; padding-left: 21px; }
    .help-card li { margin: 7px 0; line-height: 1.45; }
    .command { font-weight: 700; }
    .help-note { border-left: 4px solid #1f6feb; padding: 9px 12px; background: #eef4ff; border-radius: 0 6px 6px 0; }
    .topic-card { border: 1px solid #d8e0e8; border-radius: 8px; padding: 14px; background: #fbfcfe; }
    .topic-header { display: grid; grid-template-columns: 1fr 130px 165px; gap: 10px; align-items: end; }
    .subtopics { display: grid; gap: 10px; margin-top: 14px; }
    .subtopic { border-top: 1px solid #d8e0e8; padding-top: 10px; }
    .subtopic-head { display: grid; grid-template-columns: 180px 1fr; gap: 10px; align-items: end; }
    .subtopic textarea { min-height: 54px; }
    .subtopics.disabled { opacity: .42; filter: grayscale(1); }
    .adult-topic-header { display:grid; grid-template-columns:110px minmax(180px,1fr) 120px 170px; gap:10px; align-items:end; }
    .adult-topic-card.disabled { opacity:.55; }
    .adult-topic-card textarea { min-height:72px; }
    .check { display:flex; align-items:center; gap:8px; }
    .check input { width:auto; }
    .tv-toggle { display:flex; align-items:center; justify-content:space-between; gap:24px; padding:18px 20px; border:1px solid #c9d7e5; border-radius:12px; background:#f7fbff; }
    .tv-toggle input { width:28px; height:28px; flex:0 0 auto; }
    .quiz-players { display:grid; gap:10px; margin-top:14px; }
    .quiz-player { display:grid; grid-template-columns:70px minmax(160px,1fr) 170px 120px; gap:10px; align-items:end; padding:12px; border:1px solid #d8e0e8; border-radius:8px; background:#fbfcfe; }
    .ha-settings-card { padding:0; overflow:hidden; border-radius:12px; }
    .ha-settings-title { padding:18px 20px 10px; font-size:20px; font-weight:600; }
    .ha-setting-row { display:flex; align-items:center; gap:18px; min-height:64px; padding:10px 20px; border-top:1px solid #e2e6ea; }
    .ha-setting-row:first-of-type { border-top:0; }
    .ha-setting-info { flex:1; min-width:0; }
    .ha-setting-name { display:block; color:inherit; font-size:16px; font-weight:500; margin-bottom:3px; }
    .ha-setting-description { display:block; color:#66737f; font-size:13px; line-height:1.4; }
    .ha-setting-control { width:min(430px,45%); }
    .ha-switch { position:relative; width:40px; height:24px; flex:0 0 40px; }
    .ha-switch input { position:absolute; opacity:0; pointer-events:none; }
    .ha-switch span { position:absolute; inset:0; border-radius:12px; background:#72777d; transition:.18s; cursor:pointer; }
    .ha-switch span::after { content:""; position:absolute; width:20px; height:20px; left:2px; top:2px; border-radius:50%; background:#fff; box-shadow:0 1px 3px #0006; transition:.18s; }
    .ha-switch input:checked + span { background:#03a9f4; }
    .ha-switch input:checked + span::after { transform:translateX(16px); }
    .debug-preview-actions { display:flex; flex-wrap:wrap; gap:8px; padding:14px 20px 0; }
    @media (max-width: 1050px) { .help-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 850px) { .grid, .details, .grid.two { grid-template-columns: 1fr 1fr; } .tabs button { min-width: 0; flex: 1; } }
    @media (max-width: 620px) { .help-grid { grid-template-columns: 1fr; } .tab-label { display: none; } .tabs { padding: 0 6px; } .tabs button { padding: 10px 8px; } }
    @media (max-width: 700px) { .quiz-player { grid-template-columns:1fr 1fr; } .ha-setting-row { align-items:flex-start; flex-wrap:wrap; } .ha-setting-control { width:100%; } }
    @media (max-width: 850px) { .adult-topic-header { grid-template-columns:1fr 1fr; } }
    @media (max-width: 520px) { main { padding: 10px; } .grid, .details, .grid.two, .topic-header, .subtopic-head, .quiz-player, .adult-topic-header { grid-template-columns: 1fr; } }
    @media (prefers-color-scheme: dark) {
      body { background: #101418; color: #e8edf2; }
      section, input, select, textarea { background: #171d23; color: #e8edf2; border-color: #34414d; }
      label { color: #b9c4cf; }
      pre { background: #11171d; border-color: #34414d; }
      .status { background: #14243d; border-color: #275187; }
      .error { background: #3a1717; border-color: #733333; }
      .question { background: #12311f; border-color: #2f7d4b; }
      .top-navigation { background: #171d23; border-color: #34414d; }
      .tabs button { background: transparent; color: #b9c4cf; }
      .tabs button.active { color: #fff; }
      .detail, .topic-card { background: #141a20; border-color: #34414d; }
      .help-note { background: #14243d; }
      .message-bubble { background: #1b232b; border-color: #34414d; }
      .message-row.user .message-bubble { background: #173354; border-color: #285b91; }
      .subtopic { border-color: #34414d; }
      .detail strong { color: #a8b5c4; }
      .tv-toggle { background:#141a20; border-color:#34414d; }
      .quiz-player { background:#141a20; border-color:#34414d; }
      .ha-setting-row { border-color:#34414d; }
      .ha-setting-description { color:#9ca9b5; }
    }
  </style>
</head>
<body>
<nav class="top-navigation" aria-label="Bereiche der Kindersicherung">
  <div class="tabs">
    <button class="active" data-tab="overview" title="Übersicht"><span class="tab-icon" aria-hidden="true">⌂</span><span class="tab-label">Übersicht</span></button>
    <button data-tab="config" title="Konfiguration"><span class="tab-icon" aria-hidden="true">⚙</span><span class="tab-label">Konfiguration</span></button>
    <button data-tab="topics" title="Wissensgebiete für Kinder"><span class="tab-icon" aria-hidden="true">💡</span><span class="tab-label">Wissensgebiete für Kinder</span></button>
    <button data-tab="adult-topics" title="Erwachsenenwissen"><span class="tab-icon" aria-hidden="true">🧠</span><span class="tab-label">Erwachsenenwissen</span></button>
    <button data-tab="tv" title="Fragestellung"><span class="tab-icon" aria-hidden="true">📝</span><span class="tab-label">Fragestellung</span></button>
    <button data-tab="quiz" title="Klugscheißer"><span class="tab-icon" aria-hidden="true">🧻</span><span class="tab-label">Klugscheißer</span></button>
    <button data-tab="conversation" title="Konversation"><span class="tab-icon" aria-hidden="true">☵</span><span class="tab-label">Konversation</span></button>
    <button data-tab="help" title="Hilfe und Sprachbefehle"><span class="tab-icon" aria-hidden="true">?</span><span class="tab-label">Hilfe</span></button>
  </div>
</nav>
<main>
  <h1>KI-Kindersicherung <span id="debugHeaderBadge" class="debug-header-badge" hidden>Debug-Modus</span></h1>
  <div id="message" class="status">Lade...</div>

  <div id="overview" class="panel active">
    <section class="ha-settings-card">
      <div class="ha-settings-title">Debug-Modus</div>
      <div class="ha-setting-row">
        <div class="ha-setting-info"><span class="ha-setting-name">Sicheren Testbetrieb aktivieren</span><span class="ha-setting-description">Unterdrückt sämtliche TV-Befehle, verwendet ausschließlich den Dummy-Player und leitet die Ausgabe auf die separate Debug-Webseite um.</span></div>
        <label class="ha-switch" title="Debug-Modus"><input id="debugMode" type="checkbox" onchange="saveDebugSettings()"><span></span></label>
      </div>
      <div class="ha-setting-row">
        <div class="ha-setting-info"><span class="ha-setting-name">Sprachausgabe im Debug-Modus</span><span class="ha-setting-description">Nur dieses Gerät erhält Testansagen. Das Standard-Sprachgerät und das ursprüngliche Eingabegerät bleiben unberührt.</span></div>
        <div class="ha-setting-control"><select id="debugVoicePlayer" onchange="saveDebugSettings()"><option value="">Keine Sprachausgabe</option></select></div>
      </div>
      <div id="debugPreviewArea" hidden>
        <div class="ha-setting-row">
          <div class="ha-setting-info"><span class="ha-setting-name">Angezeigte Debug-Seite</span><span class="ha-setting-description">Ein bereits geöffneter Debug-Tab wechselt unmittelbar auf die gewählte Ansicht.</span></div>
          <div class="ha-setting-control"><select id="debugDisplayPage" onchange="showDebugPreview(this.value)"><option value="task">Aufgabenseite</option><option value="quiz">Quizseite</option></select></div>
        </div>
        <div class="debug-preview-actions"><button onclick="openDebugOutput()">Debug-Ausgabe in neuem Tab öffnen</button></div>
      </div>
    </section>
    <section>
      <h2>Steuerung</h2>
      <div class="action-row">
        <button onclick="action('approve')">Fragestellung freigeben</button>
        <button class="danger" onclick="action('reject')">Fragestellung ablehnen</button>
        <button onclick="action('activate_lock')">Kindersicherung aktivieren</button>
        <button class="danger" onclick="action('deactivate')">Kindersicherung deaktivieren</button>
      </div>
      <div class="action-row secondary-row">
        <button class="secondary" onclick="action('activate_lock')">Test Kindersicherung</button>
        <button class="secondary" onclick="action('activate_conditional')">Test bedingte Kindersicherung</button>
        <button class="secondary" onclick="action('repeat_question')">Aufgabe wiederholen</button>
        <button class="secondary" onclick="action('new_question')">Andere Aufgabe</button>
      </div>
      <h3 style="margin:18px 0 8px">Dummy-Player testen</h3>
      <p>Vor dem Aktivieren einen Ausgangszustand setzen und nach der Freigabe vergleichen.</p>
      <div class="action-row">
        <button onclick="action('dummy_playing')">Play</button>
        <button class="secondary" onclick="action('dummy_paused')">Pause</button>
        <button class="secondary" onclick="action('dummy_idle')">Idle</button>
        <button class="danger" onclick="action('dummy_off')">Aus</button>
      </div>
    </section>

    <section>
      <h2>Fragestellung und Status</h2>
      <div id="question" class="question">Derzeit keine Fragestellung.</div>
      <div id="statusText" class="status">Status wird geladen...</div>
      <div id="details" class="details"></div>
      <div class="actions" style="margin-top:12px">
        <label style="min-width:260px;flex:1">Antwort<input id="answer" placeholder="Antwort als Text oder Zahl eingeben"></label>
        <button onclick="submitAnswer()">Antwort senden</button>
      </div>
    </section>

    <section>
      <div class="actions">
        <h2 style="margin-right:auto">Live-Log</h2>
        <label class="check"><input id="autoLog" type="checkbox" checked> Auto-Refresh</label>
        <button class="secondary" onclick="loadLogs()">Aktualisieren</button>
        <button class="danger" onclick="clearLogs()">Log löschen</button>
      </div>
      <pre id="logText" class="log-window">Noch keine Logdaten.</pre>
    </section>
  </div>

  <div id="tv" class="panel">
    <section>
      <h2>Fragestellung</h2>
      <div class="action-row">
        <button onclick="action('single_question')">Eine Aufgabe</button>
        <button onclick="action('free_question')">Freie Aufgabe</button>
        <button onclick="action('adult_question')">Erwachsenenfrage</button>
      </div>
    </section>
    <section>
      <label class="tv-toggle">
        <span><strong style="display:block;font-size:18px;margin-bottom:5px">TV-Ausgabe aktiv</strong><span>Erlaubt eigenständigen Webseiten, über die Schnittstelle „TV-Webseiten“ auf dem Fernseher angezeigt zu werden.</span></span>
        <input id="tvDisplayEnabled" type="checkbox" onchange="setTvDisplay(this.checked)">
      </label>
    </section>
    <section>
      <div class="actions">
        <div style="margin-right:auto"><h2>TV-Webseite</h2><code id="tvDisplayUrl">__APPDAEMON_URL__/app/ki_kindersicherung_aufgabe</code></div>
        <button class="primary" onclick="action('show_tv_display')">Jetzt auf TV anzeigen</button>
        <button class="danger" onclick="action('stop_tv_display')">TV-Anzeige beenden</button>
        <button onclick="window.open(document.getElementById('tvDisplayUrl').textContent,'_blank')">In neuem Fenster öffnen</button>
      </div>
    </section>
  </div>

  <div id="quiz" class="panel">
    <section>
      <label class="tv-toggle" style="margin-bottom:16px">
        <span><strong style="display:block;font-size:18px;margin-bottom:5px">Klugscheißer auf dem TV-Gerät ausgeben</strong><span>Aktiviert die Spiel-Webseite auf dem Fernseher. Ohne Häkchen läuft Klugscheißer ausschließlich als Sprach- und Antwortdialog.</span></span>
        <input id="quizTvDisplayEnabled" type="checkbox" onchange="setQuizTvDisplay(this.checked)">
      </label>
      <div class="actions">
        <div style="margin-right:auto"><h2>TV-Webseite Klugscheißer</h2><code id="quizDisplayUrl">__APPDAEMON_URL__/app/ki_kindersicherung_quiz</code></div>
        <button class="primary" onclick="action('show_quiz_tv')">Jetzt auf TV anzeigen</button>
        <button class="danger" onclick="action('stop_tv_display')">TV-Anzeige beenden</button>
        <button onclick="window.open(document.getElementById('quizDisplayUrl').textContent,'_blank')">In neuem Fenster öffnen</button>
      </div>
    </section>
    <section>
      <div class="actions">
        <h2 style="margin-right:auto">Steuerung</h2>
        <button id="quizStartButton" class="primary" onclick="action('quiz_demo_start',this)">Klugscheißer starten</button>
        <button onclick="action('quiz_next_player')">Nächster Spieler</button>
        <button class="danger" onclick="action('quiz_demo_reset')">Zurücksetzen</button>
      </div>
    </section>
    <section>
      <div class="actions">
        <div style="margin-right:auto"><h2>Klugscheißer – Entwicklung</h2><span>Eigenständiger Mehrspieler-Modus, getrennt von der Kindersicherung.</span></div>
        <button onclick="saveQuizConfig()">Quiz-Konfiguration speichern</button>
      </div>
      <div class="actions" style="margin:16px 0;justify-content:flex-start">
        <label class="check"><input id="quizEnabled" type="checkbox"> Klugscheißer verfügbar</label>
        <label class="check"><input id="quizRevealChoices" type="checkbox"> Knifflig: Auswahl erst nach dem ersten Fehlversuch</label>
      </div>
      <div class="grid two">
        <label>Themenauswahl<select id="quizSubjectMode" onchange="updateQuizSubjectState()"><option value="variabel">Variabel – Thema wechselt</option><option value="fest">Festes Sachgebiet</option></select></label>
        <label>Sachgebiet<input id="quizSubject" placeholder="z. B. Tiere, Europa oder Technik"></label>
      </div>
      <div class="grid two" style="margin-top:12px">
        <label>Versuche für Kinder<input id="quizChildAttempts" type="number" min="1" max="10" value="3"></label>
        <label>Versuche für Erwachsene<input id="quizAdultAttempts" type="number" min="1" max="10" value="2"></label>
      </div>
      <h3 style="margin:18px 0 6px">Spieler (1 bis 6)</h3>
      <p>Bei Kindern bestimmt das eingetragene Alter verbindlich die Schwierigkeit und überschreibt abweichende Alters- oder Klassenstufenangaben der Wissensgebiete für Kinder. Bei Erwachsenen gilt der persönliche Schwierigkeitsgrad; Kategorien und Gewichtungen stammen aus „Erwachsenenwissen“.</p>
      <div id="quizPlayers" class="quiz-players"></div>
    </section>
  </div>

  <div id="conversation" class="panel">
    <section>
      <div class="actions">
        <h2 style="margin-right:auto">Konversationsverlauf</h2>
        <label class="check"><input id="autoConversation" type="checkbox" checked> Automatisch aktualisieren</label>
        <button class="secondary" onclick="loadConversation()">Aktualisieren</button>
        <button class="danger" onclick="clearConversation()">Verlauf löschen</button>
      </div>
      <p>Dokumentiert erkannte Äußerungen und die tatsächlich an die Sprachausgabe übergebenen Antworten.</p>
      <div id="conversationList" class="conversation"><div class="conversation-empty">Noch kein Gespräch aufgezeichnet.</div></div>
    </section>
  </div>

  <div id="help" class="panel">
    <section class="help-intro">
      <h2>Befehle &amp; Beispiele</h2>
      <p>Sprich einen der folgenden Sätze über den eingerichteten Home-Assistant-Sprachassistenten. Wörter in den Beispielen wie <strong>30 Minuten</strong>, <strong>20 Uhr</strong>, <strong>Mathematik</strong> oder <strong>neun</strong> kannst du durch passende eigene Angaben ersetzen.</p>
      <p class="help-note"><strong>Wichtig:</strong> Bei Antworten muss das Wort <strong>Antwort</strong> oder <strong>Lösung</strong> am Anfang stehen. Zum sprachlichen Ausschalten ist die in der Konfiguration hinterlegte Eltern-PIN erforderlich.</p>
    </section>

    <div class="help-grid">
      <section class="help-card">
        <h2>Kindersicherung aktivieren</h2>
        <ul>
          <li><span class="command">„Aktiviere die Kindersicherung.“</span></li>
          <li><span class="command">„Starte die Kindersicherung.“</span></li>
          <li><span class="command">„Schalte die Kindersicherung ein.“</span></li>
        </ul>
        <p>Die normale Kindersicherung sperrt die konfigurierten Media-Player unmittelbar.</p>
      </section>

      <section class="help-card">
        <h2>Zeitlich begrenzen</h2>
        <ul>
          <li><span class="command">„Kindersicherung zwei Stunden aktivieren.“</span></li>
          <li><span class="command">„Kindersicherung für 45 Minuten aktivieren.“</span></li>
          <li><span class="command">„Kindersicherung bis 20 Uhr aktivieren.“</span></li>
          <li><span class="command">„Aktiviere die Kindersicherung in 30 Minuten.“</span></li>
        </ul>
        <p><strong>Für/bis</strong> bestimmt die Laufzeit der Sperre. <strong>In 30 Minuten</strong> startet die Sperre erst nach Ablauf dieser Zeit. Ausführliche Zeitformulierungen laufen über das freigegebene Kindersicherungs-Skript des Konversationsagenten.</p>
      </section>

      <section class="help-card">
        <h2>Bedingte Kindersicherung</h2>
        <ul>
          <li><span class="command">„Aktiviere die bedingte Kindersicherung.“</span></li>
          <li><span class="command">„Starte die bedingte Kindersicherung.“</span></li>
          <li><span class="command">„Bedingte Kindersicherung einschalten.“</span></li>
        </ul>
        <p>Die Wiedergabe wird pausiert und eine Aufgabe gestellt. Eine richtige Antwort gibt die Player für das konfigurierte Freigabeintervall frei.</p>
      </section>

      <section class="help-card">
        <h2>Freie Aufgabe</h2>
        <ul>
          <li><span class="command">„Aufgabe.“</span></li>
          <li><span class="command">„Eine Aufgabe bitte.“</span></li>
          <li><span class="command">„Eine Aufgabe für Alex.“</span></li>
          <li><span class="command">„Stelle mir bitte eine Aufgabe.“</span></li>
          <li><span class="command">„Stelle Alex bitte eine Aufgabe.“</span></li>
        </ul>
        <p>Die Themenauswahl folgt den Gewichten aus der Konfiguration. Dieser Modus funktioniert unabhängig vom Zustand der Kindersicherung und erlaubt beliebig viele Antwortversuche.</p>
      </section>

      <section class="help-card">
        <h2>Aufgabe nach Hauptthema</h2>
        <ul>
          <li><span class="command">„Eine Mathematikaufgabe für Alex.“</span></li>
          <li><span class="command">„Eine Deutschaufgabe.“</span></li>
          <li><span class="command">„Eine Sachkundeaufgabe.“</span> oder <span class="command">„Eine Sachaufgabe.“</span></li>
          <li><span class="command">„Eine Kreativaufgabe.“</span></li>
          <li><span class="command">„Stelle bitte eine Aufgabe aus Mathematik.“</span></li>
          <li><span class="command">„Eine Aufgabe zu Deutsch für Alex.“</span></li>
        </ul>
        <p>Es können alle in der Konfiguration angelegten Hauptthemen angesprochen werden. Mathematik, Deutsch, Sachkunde und Kreativität besitzen zusätzlich feste Kurzformen.</p>
      </section>

      <section class="help-card">
        <h2>Aufgabe nach Unterthema</h2>
        <ul>
          <li><span class="command">„Eine Aufgabe zum Einmaleins.“</span></li>
          <li><span class="command">„Eine Aufgabe zur Addition.“</span></li>
          <li><span class="command">„Eine Deutschaufgabe zur Rechtschreibung.“</span></li>
          <li><span class="command">„Eine Aufgabe zu Natur und Umwelt.“</span></li>
          <li><span class="command">„Stelle Alex eine Aufgabe zum logischen Denken.“</span></li>
        </ul>
        <p>Der genannte Begriff wird mit den aktiven Haupt- und Unterthemen abgeglichen. Deaktivierte Unterthemen werden bei der automatischen Auswahl nicht verwendet.</p>
      </section>

      <section class="help-card">
        <h2>Knobel- und Schulaufgabe</h2>
        <ul>
          <li><span class="command">„Eine Knobelaufgabe bitte.“</span></li>
          <li><span class="command">„Stelle mir eine Knobelaufgabe.“</span></li>
          <li><span class="command">„Eine Schulaufgabe bitte.“</span></li>
          <li><span class="command">„Stelle mir eine Schulaufgabe.“</span></li>
        </ul>
        <p>Hier wird genau eine Aufgabe gestellt und ausgewertet. Die in der Konfiguration festgelegte Zahl der Versuche gilt auch für diese Variante.</p>
      </section>

      <section class="help-card">
        <h2>Wissensfrage für Erwachsene</h2>
        <ul>
          <li><span class="command">„Eine Erwachsenenfrage bitte.“</span></li>
          <li><span class="command">„Stelle mir bitte eine Frage für Erwachsene.“</span></li>
          <li><span class="command">„Eine Wissensfrage für Erwachsene.“</span></li>
        </ul>
        <p>Es wird genau eine Frage aus den aktivierten Erwachsenen-Themen gestellt. Themengewichtung und Schwierigkeitsgrad werden aus der Registerkarte für Erwachsenenfragen übernommen.</p>
      </section>

      <section class="help-card">
        <h2>Antworten geben</h2>
        <ul>
          <li><span class="command">„Antwort neun.“</span></li>
          <li><span class="command">„Lösung 24.“</span></li>
          <li><span class="command">„Die Antwort ist Garten.“</span></li>
          <li><span class="command">„Meine Antwort lautet bellt.“</span></li>
          <li><span class="command">„Die Lösung ist dunkel.“</span></li>
          <li><span class="command">„Ich glaube, die Antwort ist sieben.“</span></li>
        </ul>
        <p>Die Antwort darf aus Zahlen, einzelnen Wörtern oder ganzen Sätzen bestehen. Wird nur „Antwort“ verstanden, bittet die Kindersicherung automatisch um die vollständige Wiederholung.</p>
      </section>

      <section class="help-card">
        <h2>Während einer Aufgabe</h2>
        <ul>
          <li><span class="command">„Aufgabe bitte wiederholen.“</span></li>
          <li><span class="command">„Wiederhole bitte die Aufgabe.“</span></li>
          <li><span class="command">„Andere Aufgabe.“</span></li>
          <li><span class="command">„Stelle bitte eine neue Aufgabe.“</span></li>
          <li><span class="command">„Aufgabe beenden.“</span></li>
          <li><span class="command">„Freie Aufgabe stoppen.“</span></li>
          <li><span class="command">„Keine Aufgabe mehr.“</span></li>
        </ul>
        <p>„Andere Aufgabe“ erzeugt eine neue Aufgabe. „Beenden“ wirkt auf die freie Aufgabenrunde; eine aktive Kindersicherung wird dadurch nicht ausgeschaltet.</p>
      </section>

      <section class="help-card">
        <h2>Kindersicherung ausschalten</h2>
        <ul>
          <li><span class="command">„Deaktiviere die Kindersicherung mit PIN 2468.“</span></li>
          <li><span class="command">„Beende die Kindersicherung 2468.“</span></li>
          <li><span class="command">„Stoppe die Kindersicherung mit 2468.“</span></li>
        </ul>
        <p>Ersetze 2468 durch die konfigurierte Eltern-PIN. Ohne richtige PIN wird die sprachliche Deaktivierung abgelehnt.</p>
      </section>

      <section class="help-card">
        <h2>Was die Modi unterscheiden</h2>
        <h3>Normale Kindersicherung</h3>
        <p>Sperrt die ausgewählten Player für die vorgegebene Zeit.</p>
        <h3>Bedingte Kindersicherung</h3>
        <p>Pausiert die Player bis zur richtigen Antwort und stellt nach dem Freigabeintervall eine neue Aufgabe.</p>
        <h3>Eine Aufgabe</h3>
        <p>Eine einzelne Aufgabe mit begrenzten Versuchen, ohne dauerhafte Mediensperre.</p>
        <h3>Freie Aufgabe</h3>
        <p>Beliebige Aufgabenrunde ohne Versuchslimit; neue Aufgabe oder Beenden erfolgt per Sprachbefehl.</p>
      </section>

      <section class="help-card">
        <h2>Tipps zur Erkennung</h2>
        <ul>
          <li>Nach dem Aktivierungswort kurz warten, bis der Assistent zuhört.</li>
          <li><strong>Antwort</strong> und Inhalt möglichst in einem Satz sprechen.</li>
          <li>Bei längeren Antworten ruhig sprechen; die lange Sprechpausen-Erkennung ist aktiviert.</li>
          <li>Wenn etwas fehlt: <span class="command">„Aufgabe wiederholen.“</span></li>
          <li>Wenn eine Aufgabe ungeeignet ist: <span class="command">„Andere Aufgabe.“</span></li>
        </ul>
        <p>Die Registerkarte „Konversation“ zeigt, welcher Wortlaut erkannt und welcher Text tatsächlich gesprochen wurde.</p>
      </section>
    </div>
  </div>

  <div id="config" class="panel">
    <section>
      <div class="actions">
        <h2 style="margin-right:auto">Konfiguration</h2>
        <button onclick="saveConfig()">Speichern</button>
        <button class="secondary" onclick="loadConfig()">Neu laden</button>
      </div>
      <div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin:12px 0">
        <label class="check"><input id="enabled" type="checkbox"> Skript und alle zugehörigen Funktionen aktiv</label>
        <label class="check"><input id="dummyMode" type="checkbox"> Nur Dummy-Player verwenden</label>
      </div>
      <div class="grid">
        <label>Erster Medienplayer<select id="player1"></select></label>
        <label>Zweiter Medienplayer<select id="player2"></select></label>
        <label>Dritter Medienplayer<select id="player3"></select></label>
        <div class="detail"><strong>Automatische Player-Suche</strong><span id="playerScope">Bereich wird ermittelt …</span></div>
        <label>Standardsprachgerät<select id="voicePlayer"></select></label>
        <label>Sprachsynthese<select id="speechEngine" onchange="renderSpeechVoices()"></select></label>
        <label>Stimme<select id="speechVoice"></select></label>
        <label>Externe KI<select id="agent"></select></label>
      </div>
      <div class="grid" style="margin-top:12px">
        <label>Freigabeintervall (Min.)<input id="releaseInterval" type="number" min="1" max="180"></label>
        <label>Maximale Freigaben<input id="maximumReleases" type="number" min="0" max="999"><small>0 = unendlich viele Freigaben</small></label>
        <label>Antwortfrist (Min.)<input id="answerTimeout" type="number" min="1" max="30"></label>
        <label>Maximale Versuche<input id="maximumAttempts" type="number" min="1" max="10"></label>
      </div>
      <label style="margin-top:12px;max-width:280px">Eltern-PIN für sprachliches Deaktivieren<input id="parentPin" type="password" inputmode="numeric" autocomplete="new-password" placeholder="Nicht gesetzt – Sprachdeaktivierung gesperrt"></label>
      <div class="topic-card" style="margin-top:16px">
        <h2 style="margin-top:0">Sprachausgabe testen</h2>
        <label>Testtext<textarea id="speechTestText">Hallo! So klingt die Sprachausgabe der Kindersicherung.</textarea></label>
        <button type="button" style="margin-top:10px" onclick="testSpeech()">Sprachausgabe testen</button>
        <small>Verwendet das oben ausgewählte Standardsprachgerät und die ausgewählte Sprachsynthese.</small>
      </div>
      <label style="margin-top:12px">Basis-Prompt<textarea id="basePrompt"></textarea></label>
      <label style="margin-top:12px">Sprachstil<textarea id="languageStylePrompt" rows="3" placeholder="z. B. locker, freundlich, kindgerecht und motivierend"></textarea><small>Gilt für Aufgaben, Quizfragen sowie richtige und falsche Rückmeldungen.</small></label>
      <div style="display:flex;align-items:center;gap:14px;margin-top:12px">
        <strong style="font-size:13px">Hinweis-Prompt</strong>
        <label class="check"><input id="footerPromptEnabled" type="checkbox"> Hinweis-Prompt aktiv</label>
      </div>
      <textarea id="footerPrompt" style="margin-top:6px"></textarea>
      <label style="margin-top:12px">Hinweis bei falscher Antwort oder Hilfe<textarea id="wrongPrompt"></textarea></label>
      <label style="margin-top:12px">Hinweis bei richtiger Antwort<textarea id="correctPrompt"></textarea></label>
    </section>
  </div>

  <div id="topics" class="panel">
    <section>
      <div class="actions">
        <div style="margin-right:auto"><h2>Wissensgebiete für Kinder</h2><span>Diese Themen und Gewichtungen werden für Kinderaufgaben und Klugscheißer verwendet.</span></div>
        <button onclick="saveConfig()">Speichern</button>
        <button class="secondary" onclick="loadConfig()">Neu laden</button>
      </div>
      <div id="topicsList" class="grid two" style="margin-top:16px"></div>
    </section>
  </div>

  <div id="adult-topics" class="panel">
    <section>
      <div class="actions">
        <div style="margin-right:auto"><h2>Wissensgebiete für Erwachsene</h2><span>Klassische Kategorien für Klugscheißer. Gewichtung und Schwierigkeit gelten je Fachgebiet.</span></div>
        <button onclick="saveAdultTopics()">Speichern</button>
        <button class="secondary" onclick="loadConfig()">Neu laden</button>
      </div>
      <p class="help-note" style="margin-top:16px"><strong>Schwierigkeitsgrad:</strong> „Gemischt“ variiert innerhalb des Fachgebiets. Bei „Leicht“, „Mittel“ oder „Schwer“ wird die KI für dieses Gebiet gezielt auf die gewählte Stufe festgelegt.</p>
      <div id="adultTopicsList" class="grid two" style="margin-top:16px"></div>
    </section>
  </div>
</main>
<script>
const endpoint = name => `/api/appdaemon/${name}`;
let playerOptions = ['media_player.ki_kinderschutz_dummy'];
let voiceOptions = [];
let speechOptions = [];
const agentOptions = ['conversation.google_ai_conversation','conversation.openai_conversation'];
let currentConfig = {};
let statusTimer = null;
let logTimer = null;

const activeTabStorageKey='ki_kindersicherung_active_tab';
function selectTab(tabName, persist=true) {
  const button=document.querySelector(`.tabs button[data-tab="${tabName}"]`);
  const panel=document.getElementById(tabName);
  if(!button||!panel)return;
  document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
  button.classList.add('active'); panel.classList.add('active');
  if(persist){
    try{localStorage.setItem(activeTabStorageKey,tabName)}catch(e){}
    try{
      const url=new URL(window.location.href);
      url.searchParams.set('tab',tabName);
      window.history.replaceState(null,'',url);
    }catch(e){}
  }
}
const pageParams=new URLSearchParams(window.location.search);
if(pageParams.get('embedded')==='1')document.body.classList.add('embedded');
let savedTab='';
try{savedTab=localStorage.getItem(activeTabStorageKey)||''}catch(e){}
selectTab(pageParams.get('tab')||savedTab||'overview');
document.querySelectorAll('.tabs button').forEach(button => button.addEventListener('click', () => selectTab(button.dataset.tab)));

async function post(name, body={}) {
  const response = await fetch(endpoint(name), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok || data.status === 'error') throw new Error(data.message || `HTTP ${response.status}`);
  return data;
}
function message(text, error=false) { const n=document.getElementById('message'); n.textContent=text; n.className=error?'status error':'status'; }
function esc(v) { return String(v ?? '-').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function setOptions(id, options, selected, allowNone=false) {
  const node=document.getElementById(id); const values=allowNone?['keine',...options]:options;
  node.innerHTML=values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(v)}</option>`).join('');
}
async function loadStatus() {
  try {
    const d=await post('ki_kindersicherung_admin_status');
    document.getElementById('question').textContent=d.question || 'Derzeit keine Fragestellung.\n\nStatus: '+d.summary;
    document.getElementById('statusText').textContent=d.summary;
    const maximumReleases=d.maximum_releases===0?'∞':d.maximum_releases;
    const fields=[['Letzte Ausführung',d.time],['Debug-Modus',d.debug_mode?`Aktiv · ${d.debug_voice_player||'ohne Sprache'}`:'Aus'],['Kindersicherung',d.active?'Ja':'Nein'],['Media Player',d.media_status],['Sperrmodus',d.mode_label],['Zeitliche Begrenzung',d.time_limit||'Keine'],['Antwort möglich bis',d.answer_until],['Freigaben benutzt',`${d.releases} / ${maximumReleases}`],['Versuche',`${d.attempts} / ${d.maximum_attempts}`]];
    document.getElementById('details').innerHTML=fields.map(x=>`<div class="detail"><strong>${esc(x[0])}</strong><span>${esc(x[1])}</span></div>`).join('');
    const tvToggle=document.getElementById('tvDisplayEnabled');if(tvToggle)tvToggle.checked=d.tv_display_configured!==false;
    const tvUrl=document.getElementById('tvDisplayUrl');if(tvUrl&&d.tv_display_url)tvUrl.textContent=d.tv_display_url;
    const quizUrl=document.getElementById('quizDisplayUrl');if(quizUrl&&d.quiz_display_url)quizUrl.textContent=d.quiz_display_url;
    const quizTvToggle=document.getElementById('quizTvDisplayEnabled');if(quizTvToggle)quizTvToggle.checked=d.quiz_tv_display_enabled!==false;
    const debugBadge=document.getElementById('debugHeaderBadge');if(debugBadge)debugBadge.hidden=!d.debug_mode;
  } catch(e) { message('Statusfehler: '+e.message,true); }
}
async function action(name,sourceButton=null) {
  const originalText=sourceButton?.textContent||'';
  if(sourceButton){sourceButton.disabled=true;sourceButton.textContent=name==='quiz_demo_start'?'Frage wird erstellt …':'Bitte warten …';}
  if(name==='quiz_demo_start')message('Klugscheißer wird gestartet. Die erste KI-Frage wird vorbereitet …');
  try {
    const d=await post('ki_kindersicherung_admin_action',{action:name});
    message(d.message);
    await Promise.all([loadStatus(),loadLogs()]);
  } catch(e){message(e.message,true);}
  finally {if(sourceButton){sourceButton.disabled=false;sourceButton.textContent=originalText;}}
}
async function setTvDisplay(enabled){try{await post('ki_kindersicherung_admin_action',{action:'set_tv_display',enabled});message(enabled?'TV-Ausgabe aktiviert.':'TV-Ausgabe deaktiviert.');await loadStatus();}catch(e){message('TV-Ausgabe konnte nicht geändert werden: '+e.message,true);}}
async function setQuizTvDisplay(enabled){try{await post('ki_kindersicherung_admin_action',{action:'set_quiz_tv_display',enabled});message(enabled?'Quiz-TV-Ausgabe aktiviert.':'Quiz läuft jetzt ausschließlich über Sprache und Antworten.');await loadStatus();}catch(e){message('Quiz-TV-Ausgabe konnte nicht geändert werden: '+e.message,true);await loadStatus();}}
async function showDebugPreview(kind){
  try{
    const d=await post('ki_kindersicherung_admin_config',{debug_display_page:kind==='quiz'?'quiz':'task'});
    currentConfig=d.config||currentConfig;
    message(kind==='quiz'?'Debug-Ausgabe auf Quizseite umgestellt.':'Debug-Ausgabe auf Aufgabenseite umgestellt.');
  }catch(e){message('Debug-Seite konnte nicht gewechselt werden: '+e.message,true);}
}
function openDebugOutput(){
  const debugWindow=window.open('__APPDAEMON_URL__/app/ki_kindersicherung_debug','ki_kindersicherung_debug');
  if(debugWindow)debugWindow.focus();else message('Der Browser hat das neue Fenster blockiert. Bitte Pop-ups für Home Assistant erlauben.',true);
}
function updateDebugUi(){
  const enabled=document.getElementById('debugMode').checked;
  document.getElementById('debugPreviewArea').hidden=!enabled;
}
async function saveDebugSettings(){
  const enabled=document.getElementById('debugMode').checked;
  const debugVoicePlayer=document.getElementById('debugVoicePlayer').value;
  try{
    const d=await post('ki_kindersicherung_admin_config',{debug_mode:enabled,debug_voice_player:debugVoicePlayer});
    currentConfig=d.config||currentConfig;
    updateDebugUi();
    message(enabled?'Debug-Modus aktiv: TV gesperrt, Dummy-Player aktiv.':'Debug-Modus deaktiviert.');
    await loadStatus();
  }catch(e){message('Debug-Modus: '+e.message,true);await loadConfig();}
}
function renderQuizPlayers(players=[]){
  const defaults=Array.from({length:6},(_,i)=>({enabled:i===0,name:i===0?'Alex':`Spieler ${i+1}`,role:i===0?'kind':'erwachsen',age:9,difficulty:'mittel'}));
  const rows=defaults.map((fallback,i)=>({...fallback,...(players[i]||{})}));
  document.getElementById('quizPlayers').innerHTML=rows.map((player,i)=>`<div class="quiz-player">
    <label class="check"><input data-quiz-enabled="${i}" type="checkbox" ${player.enabled?'checked':''}>Aktiv</label>
    <label>Name<input data-quiz-name="${i}" value="${esc(player.name)}" maxlength="40"></label>
    <label>Einstufung<select data-quiz-role="${i}" onchange="updateQuizPlayerLevel(${i})"><option value="kind" ${player.role==='kind'?'selected':''}>Kind</option><option value="erwachsen" ${player.role==='erwachsen'?'selected':''}>Erwachsener</option></select></label>
    <label data-quiz-age-wrap="${i}">Alter<input data-quiz-age="${i}" type="number" min="4" max="17" value="${Number(player.age)||9}"></label>
    <label data-quiz-difficulty-wrap="${i}">Schwierigkeitsgrad<select data-quiz-difficulty="${i}"><option value="leicht" ${player.difficulty==='leicht'?'selected':''}>Leicht</option><option value="mittel" ${!player.difficulty||player.difficulty==='mittel'||player.difficulty==='normal'?'selected':''}>Mittel</option><option value="schwer" ${player.difficulty==='schwer'?'selected':''}>Schwer</option></select></label>
  </div>`).join('');
  rows.forEach((_,i)=>updateQuizPlayerLevel(i));
}
function updateQuizPlayerLevel(i){const isChild=document.querySelector(`[data-quiz-role="${i}"]`)?.value==='kind';const age=document.querySelector(`[data-quiz-age-wrap="${i}"]`);const difficulty=document.querySelector(`[data-quiz-difficulty-wrap="${i}"]`);if(age)age.hidden=!isChild;if(difficulty)difficulty.hidden=isChild;}
function updateQuizSubjectState(){const fixed=document.getElementById('quizSubjectMode').value==='fest';document.getElementById('quizSubject').disabled=!fixed;}
async function saveQuizConfig(){
  try{
    const players=Array.from({length:6},(_,i)=>({enabled:document.querySelector(`[data-quiz-enabled="${i}"]`).checked,name:document.querySelector(`[data-quiz-name="${i}"]`).value.trim(),role:document.querySelector(`[data-quiz-role="${i}"]`).value,age:Number(document.querySelector(`[data-quiz-age="${i}"]`).value)||9,difficulty:document.querySelector(`[data-quiz-difficulty="${i}"]`).value||'mittel'}));
    if(!players.some(player=>player.enabled))throw new Error('Mindestens ein Spieler muss aktiviert sein.');
    if(players.some(player=>player.enabled&&!player.name))throw new Error('Jeder aktive Spieler benötigt einen Namen.');
    const body={quiz_enabled:document.getElementById('quizEnabled').checked,quiz_reveal_choices_after_wrong:document.getElementById('quizRevealChoices').checked,quiz_child_attempts:Number(document.getElementById('quizChildAttempts').value)||3,quiz_adult_attempts:Number(document.getElementById('quizAdultAttempts').value)||2,quiz_subject_mode:document.getElementById('quizSubjectMode').value,quiz_subject:document.getElementById('quizSubject').value.trim()||'Allgemeinwissen',quiz_players:players};
    await post('ki_kindersicherung_admin_config',body);message('Quiz-Konfiguration gespeichert.');await loadConfig();
  }catch(e){message('Quiz-Konfiguration: '+e.message,true);}
}
async function submitAnswer() { const answer=document.getElementById('answer').value.trim(); if(!answer)return message('Bitte eine Antwort eingeben.',true); try{await post('ki_kindersicherung_admin_action',{action:'answer',answer});document.getElementById('answer').value='';message('Antwort verarbeitet.');await Promise.all([loadStatus(),loadLogs()]);}catch(e){message(e.message,true);} }
async function loadLogs(){try{const d=await post('ki_kindersicherung_admin_logs',{lines:300});const n=document.getElementById('logText');n.textContent=d.logs||'Noch keine Logeinträge.';n.scrollTop=n.scrollHeight;}catch(e){message('Logfehler: '+e.message,true);}}
async function clearLogs(){try{await post('ki_kindersicherung_admin_logs',{action:'clear'});await loadLogs();message('Log gelöscht.');}catch(e){message(e.message,true);}}
async function loadConversation(){try{const d=await post('ki_kindersicherung_admin_conversation');const n=document.getElementById('conversationList');const entries=[...(d.entries||[])].reverse();n.innerHTML=entries.length?entries.map(item=>`<div class="message-row ${item.role==='user'?'user':'assistant'}"><div class="message-bubble"><div class="message-meta"><strong>${item.role==='user'?'Alex / User':'Kindersicherung / KI'}</strong><span>${esc(item.time)}</span></div>${esc(item.text)}</div></div>`).join(''):'<div class="conversation-empty">Noch kein Gespräch aufgezeichnet.</div>';}catch(e){message('Konversationsfehler: '+e.message,true);}}
async function clearConversation(){if(!confirm('Konversationsverlauf wirklich löschen?'))return;try{const d=await post('ki_kindersicherung_admin_conversation',{action:'clear'});await loadConversation();message(d.message);}catch(e){message(e.message,true);}}
async function loadConfig(){try{const d=await post('ki_kindersicherung_admin_config');currentConfig=d.config||{};const c=currentConfig;document.getElementById('enabled').checked=!!c.enabled;setOptions('player1',playerOptions,(c.media_players||[])[0]);setOptions('player2',playerOptions,(c.media_players||[])[1]||'keine',true);setOptions('voicePlayer',voiceOptions,c.voice_player);setOptions('agent',agentOptions,c.conversation_agent);document.getElementById('releaseInterval').value=c.release_interval_minutes||20;document.getElementById('maximumReleases').value=c.maximum_releases||6;document.getElementById('answerTimeout').value=c.answer_timeout_minutes||5;document.getElementById('maximumAttempts').value=c.maximum_attempts||2;document.getElementById('parentPin').value=c.parent_pin||'';document.getElementById('basePrompt').value=c.base_prompt||'';document.getElementById('languageStylePrompt').value=c.language_style_prompt||'';document.getElementById('footerPrompt').value=c.footer_prompt||'';document.getElementById('wrongPrompt').value=c.wrong_answer_prompt||'';document.getElementById('correctPrompt').value=c.correct_answer_prompt||'';document.getElementById('topicsList').innerHTML=(c.topics||[]).map((t,i)=>`<div class="topic"><label>Thema ${i+1}<input data-topic-name="${i}" value="${esc(t.name||'')}"></label><label>Gewichtung %<input data-topic-weight="${i}" type="number" min="0" max="100" value="${Number(t.weight)||0}"></label></div>`).join('');}catch(e){message('Konfigurationsfehler: '+e.message,true);}}
async function saveConfig(){try{const p1=document.getElementById('player1').value,p2=document.getElementById('player2').value;const topics=(currentConfig.topics||[]).map((t,i)=>({...t,name:document.querySelector(`[data-topic-name="${i}"]`).value,weight:Number(document.querySelector(`[data-topic-weight="${i}"]`).value)}));const body={enabled:document.getElementById('enabled').checked,media_players:[p1,p2].filter(x=>x&&x!=='keine'),voice_player:document.getElementById('voicePlayer').value,conversation_agent:document.getElementById('agent').value,release_interval_minutes:Number(document.getElementById('releaseInterval').value),maximum_releases:Number(document.getElementById('maximumReleases').value),answer_timeout_minutes:Number(document.getElementById('answerTimeout').value),maximum_attempts:Number(document.getElementById('maximumAttempts').value),parent_pin:document.getElementById('parentPin').value.trim(),base_prompt:document.getElementById('basePrompt').value,footer_prompt:document.getElementById('footerPrompt').value,wrong_answer_prompt:document.getElementById('wrongPrompt').value,topics};const d=await post('ki_kindersicherung_admin_config',body);message(d.message);await loadConfig();}catch(e){message(e.message,true);}}
async function testSpeech(){
  const testText=document.getElementById('speechTestText').value.trim();
  if(!testText)return message('Bitte einen Testtext eingeben.',true);
  try{
    const d=await post('ki_kindersicherung_admin_action',{action:'test_speech',message:testText,voice_player:document.getElementById('voicePlayer').value,speech_engine:document.getElementById('speechEngine').value,speech_voice:document.getElementById('speechVoice').value});
    message(d.message||'Testtext wird gesprochen.');
  }catch(e){message('Sprachtest fehlgeschlagen: '+e.message,true);}
}
const loadConfigBase=loadConfig;
loadConfig=async function(){await loadConfigBase();setOptions('speechEngine',speechOptions,currentConfig.speech_engine||'tts.piper');};
const saveConfigBase=saveConfig;
saveConfig=async function(){await saveConfigBase();await post('ki_kindersicherung_admin_config',{speech_engine:document.getElementById('speechEngine').value});await loadConfig();};
function renderTopics(topics) {
  document.getElementById('topicsList').innerHTML=(topics||[]).map((topic,i)=>`
    <div class="topic-card">
      <div class="topic-header">
        <label>Hauptthema ${i+1}<input data-topic-name="${i}" value="${esc(topic.name||'')}"></label>
        <label>Gewichtung %<input data-topic-weight="${i}" type="number" min="0" max="100" value="${Number(topic.weight)||0}"></label>
        <label class="check"><input data-subtopics-enabled="${i}" type="checkbox" ${topic.subtopics_enabled!==false?'checked':''} onchange="toggleSubtopics(${i},this.checked)">Unterthemen aktiv</label>
      </div>
      <label style="margin-top:10px">Prompt Hauptthema (eine Zeile)<input data-topic-prompt="${i}" value="${esc(topic.prompt||'')}"></label>
      <div class="subtopics ${topic.subtopics_enabled===false?'disabled':''}" data-subtopics="${i}">${(topic.subtopics||[]).map((subtopic,j)=>`
        <div class="subtopic">
          <div class="subtopic-head">
            <label class="check"><input data-subtopic-enabled="${i}-${j}" type="checkbox" ${subtopic.enabled!==false?'checked':''}>Unterthema aktiv</label>
            <label>Unterthema ${j+1}<input data-subtopic-name="${i}-${j}" value="${esc(subtopic.name||'')}"></label>
          </div>
          <label style="margin-top:8px">Prompt Unterthema (zwei Zeilen)<textarea data-subtopic-prompt="${i}-${j}" rows="2">${esc(subtopic.prompt||'')}</textarea></label>
        </div>`).join('')}
      </div>
    </div>`).join('');
}
function readTopics() {
  return (currentConfig.topics||[]).map((topic,i)=>({
    ...topic,
    name:document.querySelector(`[data-topic-name="${i}"]`).value.trim(),
    weight:Number(document.querySelector(`[data-topic-weight="${i}"]`).value),
    prompt:document.querySelector(`[data-topic-prompt="${i}"]`).value.trim(),
    subtopics_enabled:document.querySelector(`[data-subtopics-enabled="${i}"]`).checked,
    subtopics:(topic.subtopics||[]).map((subtopic,j)=>({
      ...subtopic,
      enabled:document.querySelector(`[data-subtopic-enabled="${i}-${j}"]`).checked,
      name:document.querySelector(`[data-subtopic-name="${i}-${j}"]`).value.trim(),
      prompt:document.querySelector(`[data-subtopic-prompt="${i}-${j}"]`).value.trim()
    }))
  }));
}
function toggleSubtopics(index, enabled) {
  const node=document.querySelector(`[data-subtopics="${index}"]`);
  if(node)node.classList.toggle('disabled',!enabled);
}
function renderAdultTopics(topics=[]) {
  document.getElementById('adultTopicsList').innerHTML=topics.map((topic,i)=>`
    <div class="topic-card adult-topic-card ${topic.enabled===false?'disabled':''}" data-adult-card="${i}">
      <div class="adult-topic-header">
        <label class="check"><input data-adult-enabled="${i}" type="checkbox" ${topic.enabled!==false?'checked':''} onchange="toggleAdultTopic(${i},this.checked)">Aktiv</label>
        <label>Fachgebiet<input data-adult-name="${i}" value="${esc(topic.name||'')}"></label>
        <label>Gewichtung %<input data-adult-weight="${i}" type="number" min="0" max="100" value="${Number(topic.weight)||0}"></label>
        <label>Schwierigkeit<select data-adult-difficulty="${i}">
          <option value="gemischt" ${topic.difficulty==='gemischt'?'selected':''}>Gemischt</option>
          <option value="leicht" ${topic.difficulty==='leicht'?'selected':''}>Leicht</option>
          <option value="mittel" ${topic.difficulty==='mittel'?'selected':''}>Mittel</option>
          <option value="schwer" ${topic.difficulty==='schwer'?'selected':''}>Schwer</option>
        </select></label>
      </div>
      <label style="margin-top:10px">Unterthemen<textarea data-adult-subtopics="${i}" rows="2" placeholder="Kommagetrennt">${esc(topic.subtopics||'')}</textarea></label>
      <label style="margin-top:10px">Prompt für dieses Fachgebiet<textarea data-adult-prompt="${i}" rows="2">${esc(topic.prompt||'')}</textarea></label>
    </div>`).join('');
}
function readAdultTopics() {
  return (currentConfig.adult_topics||[]).map((topic,i)=>({
    ...topic,
    enabled:document.querySelector(`[data-adult-enabled="${i}"]`).checked,
    name:document.querySelector(`[data-adult-name="${i}"]`).value.trim(),
    weight:Number(document.querySelector(`[data-adult-weight="${i}"]`).value),
    difficulty:document.querySelector(`[data-adult-difficulty="${i}"]`).value,
    subtopics:document.querySelector(`[data-adult-subtopics="${i}"]`).value.trim(),
    prompt:document.querySelector(`[data-adult-prompt="${i}"]`).value.trim()
  }));
}
function toggleAdultTopic(index, enabled) {
  const card=document.querySelector(`[data-adult-card="${index}"]`);
  if(card)card.classList.toggle('disabled',!enabled);
}
async function saveAdultTopics(){
  try{
    const topics=readAdultTopics();
    if(!topics.some(topic=>topic.enabled&&topic.weight>0))throw new Error('Mindestens ein Fachgebiet mit einer Gewichtung größer als null muss aktiv sein.');
    const d=await post('ki_kindersicherung_admin_config',{adult_topics:topics});
    message(d.message);await loadConfig();
  }catch(e){message('Erwachsenenwissen: '+e.message,true);}
}
function renderSpeechVoices(selected) {
  const engine=document.getElementById('speechEngine').value;
  const voices=(currentConfig.available_speech_voices||{})[engine]||[];
  const node=document.getElementById('speechVoice');
  if(!voices.length){
    node.innerHTML='<option value="">Standardstimme der Sprachsynthese</option>';
    node.disabled=true;
    return;
  }
  node.disabled=false;
  const wanted=selected!==undefined?selected:node.value;
  node.innerHTML=voices.map(voice=>`<option value="${esc(voice.voice_id)}" ${voice.voice_id===wanted?'selected':''}>${esc(voice.name)}</option>`).join('');
  if(!node.value&&voices.length)node.value=voices[0].voice_id;
}
const loadConfigWithSpeech=loadConfig;
loadConfig=async function(){
  await loadConfigWithSpeech();
  document.getElementById('footerPromptEnabled').checked=currentConfig.footer_prompt_enabled!==false;
  const discoveredSpeech=(currentConfig.available_speech_engines||[]).map(item=>item.entity_id);
  speechOptions=[...new Set([...discoveredSpeech,currentConfig.speech_engine].filter(Boolean))].sort();
  setOptions('speechEngine',speechOptions,currentConfig.speech_engine||speechOptions[0]);
  renderSpeechVoices(currentConfig.speech_voice||'');
  document.getElementById('dummyMode').checked=!!currentConfig.dummy_mode;
  const discovered=(currentConfig.available_media_players||[]).map(item=>item.entity_id);
  playerOptions=[...new Set([...discovered,...(currentConfig.media_players||[])])].sort();
  setOptions('player1',playerOptions,(currentConfig.media_players||[])[0]||'keine',true);
  setOptions('player2',playerOptions,(currentConfig.media_players||[])[1]||'keine',true);
  setOptions('player3',playerOptions,(currentConfig.media_players||[])[2]||'keine',true);
  document.getElementById('playerScope').textContent=`Nur neue Media-Player im Bereich „${currentConfig.media_player_scope_name||currentConfig.media_player_scope_area||'unbekannt'}“`;
  const discoveredVoices=(currentConfig.available_voice_players||[]).map(item=>item.media_player);
  voiceOptions=[...new Set([...discoveredVoices,currentConfig.voice_player,currentConfig.debug_voice_player].filter(Boolean))].sort();
  setOptions('voicePlayer',voiceOptions,currentConfig.voice_player);
  const debugVoice=document.getElementById('debugVoicePlayer');
  const voiceItems=currentConfig.available_voice_players||[];
  const voiceNames=Object.fromEntries(voiceItems.map(item=>[item.media_player,item.name||item.media_player]));
  debugVoice.innerHTML='<option value="">Keine Sprachausgabe</option>'+voiceOptions.map(value=>`<option value="${esc(value)}" ${value===currentConfig.debug_voice_player?'selected':''}>${esc(voiceNames[value]||value)}</option>`).join('');
  document.getElementById('debugMode').checked=!!currentConfig.debug_mode;
  document.getElementById('debugDisplayPage').value=currentConfig.debug_display_page==='quiz'?'quiz':'task';
  updateDebugUi();
  document.getElementById('maximumReleases').value=currentConfig.maximum_releases??6;
  document.getElementById('quizEnabled').checked=!!currentConfig.quiz_enabled;
  document.getElementById('quizRevealChoices').checked=!!currentConfig.quiz_reveal_choices_after_wrong;
  document.getElementById('quizChildAttempts').value=currentConfig.quiz_child_attempts??3;
  document.getElementById('quizAdultAttempts').value=currentConfig.quiz_adult_attempts??2;
  document.getElementById('quizSubjectMode').value=currentConfig.quiz_subject_mode||'variabel';
  document.getElementById('quizSubject').value=currentConfig.quiz_subject||'Allgemeinwissen';
  renderQuizPlayers(currentConfig.quiz_players||[]);
  updateQuizSubjectState();
  renderTopics(currentConfig.topics||[]);
  renderAdultTopics(currentConfig.adult_topics||[]);
};
saveConfig=async function(){
  try {
    const p1=document.getElementById('player1').value,p2=document.getElementById('player2').value,p3=document.getElementById('player3').value;
    const body={enabled:document.getElementById('enabled').checked,media_players:[p1,p2,p3].filter(x=>x&&x!=='keine'),voice_player:document.getElementById('voicePlayer').value,speech_engine:document.getElementById('speechEngine').value,conversation_agent:document.getElementById('agent').value,release_interval_minutes:Number(document.getElementById('releaseInterval').value),maximum_releases:Number(document.getElementById('maximumReleases').value),answer_timeout_minutes:Number(document.getElementById('answerTimeout').value),maximum_attempts:Number(document.getElementById('maximumAttempts').value),parent_pin:document.getElementById('parentPin').value.trim(),base_prompt:document.getElementById('basePrompt').value,language_style_prompt:document.getElementById('languageStylePrompt').value.trim(),footer_prompt:document.getElementById('footerPrompt').value,wrong_answer_prompt:document.getElementById('wrongPrompt').value,correct_answer_prompt:document.getElementById('correctPrompt').value,topics:readTopics()};
    body.footer_prompt_enabled=document.getElementById('footerPromptEnabled').checked;
    body.dummy_mode=document.getElementById('dummyMode').checked;
    body.speech_voice=document.getElementById('speechVoice').value;
    const d=await post('ki_kindersicherung_admin_config',body);message(d.message);await loadConfig();
  } catch(e) { message(e.message,true); }
};
async function loadAll(){await Promise.allSettled([loadStatus(),loadConfig(),loadLogs(),loadConversation()]);message('Bereit.');statusTimer=setInterval(()=>{loadStatus();if(document.getElementById('autoConversation').checked)loadConversation();},5000);logTimer=setInterval(()=>{if(document.getElementById('autoLog').checked)loadLogs();},2000);}
loadAll();
</script>
</body>
</html>"""
