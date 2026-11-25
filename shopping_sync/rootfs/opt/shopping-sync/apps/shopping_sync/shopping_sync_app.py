from __future__ import annotations

import html
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import appdaemon.plugins.hass.hassapi as hass
from aiohttp import web

from . import shopping_sync as core


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.yaml"
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "shopping_sync.log"


class ShoppingSyncApp(hass.Hass):
    def initialize(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.endpoint_handles: list[Any] = []
        self.sync_lock = threading.Lock()
        self.sync_running = False
        self.last_sync_result: dict[str, Any] | None = None
        self.last_sync_error = ""
        self.last_trigger_times: dict[str, float] = {}
        self.stop_requested = False
        self.realtime_stop_event = threading.Event()
        self.realtime_thread: threading.Thread | None = None
        self.realtime_connected = False
        self.pending_changed_todo_entities: set[str] = set()
        self.pending_removed_todo_item_names: dict[str, set[str]] = {}
        self.own_service_events: dict[tuple[str, str, str], float] = {}
        self.todo_item_snapshots: dict[str, dict[str, str]] = {}
        self.runtime_status: dict[str, Any] | None = None
        self.live_events: list[dict[str, Any]] = []
        self.live_log = self.live_events
        self.live_log_lock = threading.Lock()
        self.config_raw = self._read_config()
        self.status_entity_id = str(
            self.config_raw.get("appdaemon", {}).get("status_entity_id")
            or core.DEFAULT_STATUS_SENSOR
        )
        self.trigger_cooldown_seconds = int(
            self.config_raw.get("appdaemon", {}).get("trigger_cooldown_seconds", 30)
        )
        self.admin_route = str(
            self.config_raw.get("appdaemon", {}).get("admin_route")
            or "shopping_sync_admin"
        )
        self.shopping_sync_config = self._load_core_config()
        self._patch_core_home_assistant_access()
        self._configure_core_logging()
        self._refresh_all_todo_snapshots()
        self._register_routes()
        self.listen_event(self._ha_event_received, "call_service")
        self.listen_state(self._todo_state_changed)
        self.run_every(self._watchdog_check, "now+15", max(5, int(self.shopping_sync_config.runtime.ha_watchdog_seconds)))
        self.run_every(self._periodic_sync_check, "now+30", 60)
        self.run_every(self._realtime_health_check, "now+45", 30)
        self._last_watchdog_snapshot = self._build_watchdog_snapshot()
        self._last_periodic_sync = time.monotonic()
        self._write_status("idle", firebase_connected=False, home_assistant_connected=True)
        self._log_event("system", "ShoppingSync AppDaemon-App geladen.")
        self._reconcile_realtime_mode()
        self.log(f"ShoppingSync Admin-Seite: /app/{self.admin_route}")

    def terminate(self) -> None:
        self.stop_requested = True
        self.realtime_stop_event.set()
        self._write_status("offline", firebase_connected=False, home_assistant_connected=False)

    def _read_config(self) -> dict[str, Any]:
        if not CONFIG_PATH.exists():
            return {}
        data = core.read_config_file(CONFIG_PATH)
        return data if isinstance(data, dict) else {}

    def _load_core_config(self) -> core.AppConfig:
        raw = json.loads(json.dumps(self.config_raw))
        home_assistant = raw.setdefault("home_assistant", {})
        home_assistant.setdefault("url", "http://appdaemon.local")
        home_assistant.setdefault("token", "appdaemon")
        return core.load_config_from_dict(raw) if hasattr(core, "load_config_from_dict") else self._load_config_via_temp(raw)

    def _load_config_via_temp(self, raw: dict[str, Any]) -> core.AppConfig:
        temp_path = APP_DIR / ".runtime_config.yaml"
        core.write_config_file(temp_path, raw)
        return core.load_config(temp_path)

    def _save_config(self, config: dict[str, Any]) -> None:
        sanitized = json.loads(json.dumps(config))
        home_assistant = sanitized.get("home_assistant")
        if isinstance(home_assistant, dict):
            home_assistant.pop("url", None)
            home_assistant.pop("token", None)
        core.write_config_file(CONFIG_PATH, sanitized)
        self.config_raw = sanitized
        self.shopping_sync_config = self._load_core_config()

    def _runtime_config(self) -> dict[str, Any]:
        runtime = self.config_raw.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
            self.config_raw["runtime"] = runtime
        return runtime

    def _configured_list_names(self) -> list[str]:
        names = self.config_raw.get("list_names")
        if not isinstance(names, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in names:
            if not isinstance(item, str):
                continue
            name = item.strip()
            key = name.casefold()
            if name and key not in seen:
                result.append(name)
                seen.add(key)
        return result

    def _save_list_names(self, names: list[str] | None) -> None:
        config = json.loads(json.dumps(self.config_raw))
        if names is None:
            config.pop("list_names", None)
        else:
            clean: list[str] = []
            seen: set[str] = set()
            for item in names:
                name = str(item).strip()
                key = name.casefold()
                if name and key not in seen:
                    clean.append(name)
                    seen.add(key)
            if clean:
                config["list_names"] = clean
            else:
                config.pop("list_names", None)
        self._save_config(config)

    def _patch_core_home_assistant_access(self) -> None:
        core.get_home_assistant_states = self._core_get_states
        core.get_home_assistant_todo_entities = self._core_get_todo_entities
        core.get_home_assistant_entity_state = self._core_get_entity_state
        core.write_home_assistant_state = self._core_write_state
        core.call_home_assistant_service = self._core_call_service

    def _configure_core_logging(self) -> None:
        logger = logging.getLogger("shopping_sync")
        logger.setLevel(logging.INFO)
        for handler in list(logger.handlers):
            if getattr(handler, "shopping_sync_handler", False) or handler.__class__.__name__ == "AppDaemonLogHandler":
                logger.removeHandler(handler)
        logger.addHandler(AppDaemonLogHandler(self))

    def _register_routes(self) -> None:
        routes = {
            self.admin_route: self._route_admin,
            f"{self.admin_route}_status": self._route_status,
            f"{self.admin_route}_config": self._route_config,
            f"{self.admin_route}_logs": self._route_logs,
            f"{self.admin_route}_command": self._route_command,
        }
        for name, callback in routes.items():
            try:
                self.endpoint_handles.append(self.register_route(callback, name, methods=["GET", "POST"]))
            except Exception as exc:
                self.warning(f"ShoppingSync Webroute {name} konnte nicht registriert werden: {exc}")

    def _core_get_states(self, home_assistant: core.HomeAssistantConfig) -> list[dict[str, Any]]:
        states = self.get_state()
        if not isinstance(states, dict):
            return []
        result: list[dict[str, Any]] = []
        for entity_id, value in states.items():
            if isinstance(value, dict):
                state_value = value.get("state")
                attributes = value.get("attributes") if isinstance(value.get("attributes"), dict) else {}
                last_changed = value.get("last_changed", "")
                last_updated = value.get("last_updated", "")
            else:
                state_value = value
                attributes = {}
                last_changed = ""
                last_updated = ""
            result.append(
                {
                    "entity_id": entity_id,
                    "state": state_value,
                    "attributes": attributes,
                    "last_changed": last_changed,
                    "last_updated": last_updated,
                }
            )
        return result

    def _core_get_todo_entities(self, home_assistant: core.HomeAssistantConfig) -> set[str]:
        return {
            item["entity_id"]
            for item in self._core_get_states(home_assistant)
            if str(item.get("entity_id", "")).startswith("todo.")
        }

    def _core_get_entity_state(self, home_assistant: core.HomeAssistantConfig, entity_id: str) -> dict[str, Any] | None:
        state = self.get_state(entity_id, attribute="all")
        if isinstance(state, dict) and str(state.get("state", "")).lower() not in {"", "unknown", "unavailable"}:
            return {
                "entity_id": entity_id,
                "state": state.get("state"),
                "attributes": state.get("attributes") if isinstance(state.get("attributes"), dict) else {},
                "last_changed": state.get("last_changed", ""),
                "last_updated": state.get("last_updated", ""),
            }
        if entity_id == self.status_entity_id and isinstance(self.runtime_status, dict):
            return dict(self.runtime_status)
        return None

    def _core_write_state(
        self,
        home_assistant: core.HomeAssistantConfig,
        entity_id: str,
        state: str,
        attributes: dict[str, Any],
    ) -> None:
        if entity_id == self.status_entity_id:
            self.runtime_status = {
                "entity_id": entity_id,
                "state": state,
                "attributes": dict(attributes or {}),
                "last_changed": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        self.set_state(entity_id, state=state, attributes=attributes or {})

    def _core_call_service(
        self,
        home_assistant: core.HomeAssistantConfig,
        domain: str,
        service: str,
        payload: dict[str, Any],
        return_response: bool = False,
    ) -> Any:
        service_name = f"{domain}/{service}"
        kwargs = dict(payload or {})
        entity_id = str(kwargs.get("entity_id") or "")
        item_name = str(kwargs.get("item") or kwargs.get("summary") or "").strip().casefold()
        if domain == "todo" and service in {"add_item", "update_item", "remove_item"} and entity_id:
            self.own_service_events[(service, entity_id, item_name)] = time.monotonic() + 10
        if return_response:
            return self._call_ha_service_with_response(domain, service, kwargs)
        self.call_service(service_name, **kwargs)
        return None

    def _call_ha_service_with_response(self, domain: str, service: str, payload: dict[str, Any]) -> dict[str, Any]:
        requests = core.require_module("requests", "requests")
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise core.FirebaseError("SUPERVISOR_TOKEN fehlt; Home-Assistant-Serviceantwort kann nicht gelesen werden.")
        response = requests.post(
            f"http://supervisor/core/api/services/{domain}/{service}?return_response",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        if response.status_code not in {200, 201}:
            detail = response.text.strip()
            if len(detail) > 300:
                detail = detail[:300] + "..."
            suffix = f": {detail}" if detail else ""
            raise core.FirebaseError(f"Home-Assistant-Service {domain}.{service} fehlgeschlagen: HTTP {response.status_code}{suffix}")
        if not response.text.strip():
            return {"service_response": {}}
        data = response.json()
        return data if isinstance(data, dict) and "service_response" in data else {"service_response": data if isinstance(data, dict) else {}}

    def _normalize_service_response(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict) and "service_response" in response:
            return response
        if isinstance(response, dict):
            return {"service_response": response}
        return {"service_response": {}}

    def _read_todo_snapshot(self, entity_id: str) -> dict[str, str]:
        try:
            response = self._call_ha_service_with_response("todo", "get_items", {"entity_id": entity_id})
        except Exception as exc:
            self.warning(f"Todo-Inhalt fuer {entity_id} konnte nicht gelesen werden: {exc}")
            return {}
        payload = response.get("service_response", {}) if isinstance(response, dict) else {}
        entity_payload = payload.get(entity_id, payload) if isinstance(payload, dict) else {}
        items = entity_payload.get("items", []) if isinstance(entity_payload, dict) else []
        snapshot: dict[str, str] = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("summary") or item.get("item") or "").strip()
            if not name:
                continue
            snapshot[name.casefold()] = name
            uid = str(item.get("uid") or item.get("id") or "").strip()
            if uid:
                snapshot[uid.casefold()] = name
        return snapshot

    def _refresh_all_todo_snapshots(self) -> None:
        for entity_id in sorted(self._core_get_todo_entities(self.shopping_sync_config.home_assistant)):
            self.todo_item_snapshots[entity_id] = self._read_todo_snapshot(entity_id)

    def _refresh_todo_snapshot_callback(self, kwargs: dict[str, Any]) -> None:
        entity_id = str(kwargs.get("entity_id") or "")
        if entity_id:
            self.todo_item_snapshots[entity_id] = self._read_todo_snapshot(entity_id)

    def _todo_state_changed(self, entity, attribute, old, new, kwargs) -> None:
        entity_id = str(entity)
        if old == new or not entity_id.startswith("todo."):
            return
        previous = self.todo_item_snapshots.get(entity_id, {})
        current = self._read_todo_snapshot(entity_id)
        previous_names = {name for name in previous.values()}
        current_names = {name for name in current.values()}
        self.todo_item_snapshots[entity_id] = current
        for removed_name in sorted(previous_names - current_names):
            own_key = ("remove_item", entity_id, removed_name.casefold())
            if self.own_service_events.get(own_key, 0) > time.monotonic():
                continue
            self._handle_sync_trigger({
                "kind": "call_service",
                "summary": f"todo.remove_item: {entity_id} / {removed_name}",
                "domain": "todo",
                "service": "remove_item",
                "entity_id": entity_id,
                "item": removed_name,
            })
        event = {"kind": "state_changed", "summary": f"{entity_id}: {old} -> {new}", "entity_id": entity_id}
        self._handle_sync_trigger(event)

    def _ha_event_received(self, event_name: str, data: dict[str, Any], kwargs: dict[str, Any]) -> None:
        domain = str(data.get("domain", ""))
        service = str(data.get("service", ""))
        service_data = data.get("service_data") if isinstance(data.get("service_data"), dict) else {}
        entity_value = service_data.get("entity_id", "")
        if isinstance(entity_value, list):
            entity_id = ", ".join(str(item) for item in entity_value)
        else:
            entity_id = str(entity_value or "")
        if domain != "todo" or service not in {"add_item", "update_item", "remove_item"}:
            return
        raw_item = service_data.get("item") or service_data.get("summary") or ""
        raw_items = raw_item if isinstance(raw_item, list) else [raw_item]
        snapshot = self.todo_item_snapshots.get(entity_id, {})
        item_names = []
        for raw_value in raw_items:
            token = str(raw_value or "").strip()
            if token:
                item_names.append(snapshot.get(token.casefold(), token))
        item_name = item_names[0] if item_names else ""
        own_event_key = (service, entity_id, item_name.casefold())
        now = time.monotonic()
        self.own_service_events = {key: expiry for key, expiry in self.own_service_events.items() if expiry > now}
        if self.own_service_events.get(own_event_key, 0) > now:
            return
        event = {
            "kind": "call_service",
            "summary": f"{domain}.{service}: {entity_id}".strip(),
            "domain": domain,
            "service": service,
            "entity_id": entity_id,
            "item": item_name,
        }
        self._handle_sync_trigger(event)
        for resolved_name in item_names[1:]:
            extra_event = dict(event)
            extra_event["item"] = resolved_name
            extra_event["summary"] = f"{domain}.{service}: {entity_id} / {resolved_name}"
            self._handle_sync_trigger(extra_event)
        for target_entity in core.todo_entities_from_live_event(event):
            self.run_in(self._refresh_todo_snapshot_callback, 1, entity_id=target_entity)

    def _handle_sync_trigger(self, event: dict[str, Any]) -> None:
        self._append_live_event(event)
        entity_ids = core.todo_entities_from_live_event(event)
        self.pending_changed_todo_entities.update(entity_ids)
        for entity_id, names in core.removed_todo_item_names_from_live_event(event).items():
            self.pending_removed_todo_item_names.setdefault(entity_id, set()).update(names)
        if self._realtime_is_running():
            self._append_live_event({"kind": "sync_trigger", "summary": "Aenderung wird von der laufenden Echtzeitverbindung verarbeitet."})
            return
        if not self._watchdog_enabled():
            self._append_live_event({"kind": "sync_trigger", "summary": "Trigger ignoriert, Watchdog ist deaktiviert."})
            return
        core.start_triggered_firebase_window(self, event)

    def _watchdog_check(self, kwargs: dict[str, Any]) -> None:
        if self.stop_requested or not self.shopping_sync_config.runtime.ha_watchdog_enabled:
            return
        if not self._watchdog_enabled():
            self._last_watchdog_snapshot = self._build_watchdog_snapshot()
            return
        snapshot = self._build_watchdog_snapshot()
        if snapshot != getattr(self, "_last_watchdog_snapshot", {}):
            self._last_watchdog_snapshot = snapshot
            self._append_live_event({"kind": "sync_trigger", "summary": "Watchdog hat Todo-Aenderung erkannt."})
            self._start_manual_sync("watchdog")

    def _realtime_health_check(self, kwargs: dict[str, Any]) -> None:
        if (
            self.stop_requested
            or self.shopping_sync_config.runtime.idle_mode
            or self._realtime_is_running()
            or self.sync_running
        ):
            return
        self._append_live_event({
            "kind": "system",
            "summary": "Echtzeitverbindung ist nicht aktiv und wird automatisch neu gestartet.",
        })
        self.realtime_thread = None
        self.realtime_connected = False
        self.realtime_stop_event.clear()
        self._reconcile_realtime_mode()

    def _periodic_sync_check(self, kwargs: dict[str, Any]) -> None:
        if self._realtime_is_running():
            return
        minutes = int(self.shopping_sync_config.runtime.ha_periodic_sync_minutes)
        if minutes <= 0 or self.stop_requested:
            return
        if time.monotonic() - self._last_periodic_sync < minutes * 60:
            return
        self._last_periodic_sync = time.monotonic()
        self._start_manual_sync("periodic")

    def _build_watchdog_snapshot(self) -> dict[str, str]:
        return core.build_home_assistant_watchdog_snapshot_from_content(
            self.shopping_sync_config.home_assistant,
            self._core_get_states(self.shopping_sync_config.home_assistant),
        )

    def _watchdog_enabled(self) -> bool:
        return core.home_assistant_watchdog_enabled(self._core_get_states(self.shopping_sync_config.home_assistant))

    def _realtime_is_running(self) -> bool:
        return bool(
            self.realtime_thread
            and self.realtime_thread.is_alive()
            and not self.realtime_stop_event.is_set()
        )

    def _reconcile_realtime_mode(self) -> None:
        if self.shopping_sync_config.runtime.idle_mode or self.stop_requested:
            self.realtime_stop_event.set()
            return
        if self._realtime_is_running():
            return
        self.realtime_stop_event.clear()
        self.realtime_thread = threading.Thread(
            target=self._run_realtime_watch,
            name="shopping-sync-realtime",
            daemon=True,
        )
        self.realtime_thread.start()

    def _restart_realtime_watch(self) -> None:
        thread = self.realtime_thread
        self.realtime_stop_event.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=12.0)
        if thread is not None and thread.is_alive():
            self._append_live_event(
                {"kind": "system", "summary": "Firebase-Verbindung wird nach dem laufenden Trennvorgang neu aufgebaut."}
            )

            def restart_after_shutdown() -> None:
                thread.join()
                if self.realtime_thread is thread and not self.stop_requested:
                    self.realtime_thread = None
                    self.realtime_connected = False
                    self._reconcile_realtime_mode()

            threading.Thread(
                target=restart_after_shutdown,
                name="shopping-sync-realtime-restart",
                daemon=True,
            ).start()
            return
        self.realtime_thread = None
        self.realtime_connected = False
        self._reconcile_realtime_mode()

    def _run_realtime_watch(self) -> None:
        reconnect_count = 0
        self._append_live_event({"kind": "system", "summary": "Firebase-Echtzeitverbindung wird gestartet."})
        while not self.realtime_stop_event.is_set() and not self.stop_requested:
            try:
                config = self.shopping_sync_config
                session = core.sign_in(config.firebase)
                self.realtime_connected = True
                core.watch_lists_via_websocket_once(
                    config,
                    session,
                    configured_list_names=config.list_names,
                    sync_todo=True,
                    prune_todo=True,
                    sync_back=True,
                    ha_poll_seconds=2,
                    status_entity_id=self.status_entity_id,
                    todo_refresh_seconds=60,
                    reconnect_count=reconnect_count,
                    changed_todo_entities=self.pending_changed_todo_entities,
                    removed_todo_item_names=self.pending_removed_todo_item_names,
                    stop_event=self.realtime_stop_event,
                )
                if self.realtime_stop_event.is_set() or self.stop_requested:
                    break
            except Exception as exc:
                self.realtime_connected = False
                self.last_sync_error = str(exc)
                self._append_live_event({"kind": "system", "summary": f"Firebase-Echtzeitverbindung verloren: {exc}"})
                if not self.shopping_sync_config.runtime.firebase_auto_reconnect_enabled:
                    self._write_status("error", firebase_connected=False, home_assistant_connected=True)
                    break
                reconnect_count += 1
                if self.realtime_stop_event.wait(10):
                    break
            finally:
                self.realtime_connected = False
        if not self.stop_requested:
            self._write_status("idle", firebase_connected=False, home_assistant_connected=True)
        self._append_live_event({"kind": "system", "summary": "Firebase-Echtzeitverbindung wurde beendet."})
    def _start_manual_sync(self, source: str = "manual") -> dict[str, Any]:
        if self._realtime_is_running():
            return {"status": "ok", "message": "Firebase-Echtzeitverbindung ist bereits aktiv.", "sync_running": False}
        with self.sync_lock:
            if self.sync_running:
                return {"status": "ok", "message": "Synchronisation laeuft bereits.", "sync_running": True}
            self.sync_running = True
            self.last_sync_result = None
            self.last_sync_error = ""
        thread = threading.Thread(target=self._run_sync_thread, args=(source,), name=f"shopping-sync-{source}", daemon=True)
        thread.start()
        return {"status": "ok", "message": "Synchronisation gestartet.", "sync_running": True}

    def _run_sync_thread(self, source: str) -> None:
        try:
            self._append_live_event({"kind": "sync_trigger", "summary": f"Synchronisation gestartet: {source}"})
            result = core.perform_on_demand_sync(self.shopping_sync_config, self.status_entity_id, sync_back=False)
            self.last_sync_result = result
            self.last_sync_error = ""
            self._append_live_event({"kind": "sync_trigger", "summary": str(result.get("message", "Synchronisation abgeschlossen."))})
        except Exception as exc:
            self.last_sync_error = str(exc)
            self._append_live_event({"kind": "sync_trigger", "summary": f"Synchronisation fehlgeschlagen: {exc}"})
            self.error(f"ShoppingSync Synchronisation fehlgeschlagen: {type(exc).__name__}: {exc}")
        finally:
            with self.sync_lock:
                self.sync_running = False

    def _write_status(self, state: str, firebase_connected: bool, home_assistant_connected: bool) -> None:
        core.write_shopping_sync_status(
            self.shopping_sync_config.home_assistant,
            self.status_entity_id,
            state,
            firebase_connected=firebase_connected,
            home_assistant_connected=home_assistant_connected,
        )

    def _append_live_event(self, event: dict[str, Any]) -> None:
        item = dict(event)
        item.setdefault("time", datetime.now(timezone.utc).isoformat())
        item.setdefault("kind", "event")
        item.setdefault("summary", "")
        self.live_events.append(item)
        self.live_events = self.live_events[-500:]
        self._write_log_line(f"{item['time']} | {item['kind']} | {item['summary']}")

    def _log_event(self, kind: str, summary: str) -> None:
        self._append_live_event({"kind": kind, "summary": summary})

    def _write_log_line(self, line: str) -> None:
        try:
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass

    async def _route_admin(self, request: web.Request, args: dict[str, Any] | None = None) -> web.Response:
        return web.Response(text=self._admin_html(), content_type="text/html")

    async def _route_status(self, request: web.Request, args: dict[str, Any] | None = None) -> web.Response:
        return web.json_response(self._status_payload())

    async def _route_logs(self, request: web.Request, args: dict[str, Any] | None = None) -> web.Response:
        if request.method == "POST":
            self.live_events.clear()
            try:
                LOG_FILE.write_text("", encoding="utf-8")
            except Exception:
                pass
        return web.json_response({"status": "ok", "events": self.live_events[-200:]})

    async def _route_config(self, request: web.Request, args: dict[str, Any] | None = None) -> web.Response:
        if request.method == "POST":
            body = await request.json()
            config = body.get("config", body) if isinstance(body, dict) else {}
            if not isinstance(config, dict):
                return web.json_response({"status": "error", "message": "Ungueltige Konfiguration."}, status=400)
            incoming_firebase = config.get("firebase")
            current_firebase = self.config_raw.get("firebase", {})
            if isinstance(incoming_firebase, dict) and isinstance(current_firebase, dict):
                for secret_name in ("api_key", "password"):
                    if incoming_firebase.get(secret_name) == "***":
                        incoming_firebase[secret_name] = current_firebase.get(secret_name, "")
            self._save_config(config)
            self._restart_realtime_watch()
            return web.json_response({"status": "ok", "config": core.redact_config_value(self.config_raw)})
        return web.json_response({"status": "ok", "config": core.redact_config_value(self.config_raw)})

    async def _route_command(self, request: web.Request, args: dict[str, Any] | None = None) -> web.Response:
        body: dict[str, Any] = {}
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                body = {}
        action = str(body.get("action") or request.query.get("action") or "").strip()
        if action in {"sync", "sync_now"}:
            return web.json_response(self._start_manual_sync("manual"))
        if action == "reload":
            self.config_raw = self._read_config()
            self.shopping_sync_config = self._load_core_config()
            self._restart_realtime_watch()
            return web.json_response({"status": "ok", "message": "Konfiguration neu geladen."})
        if action == "clear_logs":
            self.live_events.clear()
            try:
                LOG_FILE.write_text("", encoding="utf-8")
            except Exception:
                pass
            return web.json_response({"status": "ok", "message": "Logs geloescht."})
        if action == "set_mode":
            mode = str(body.get("mode") or request.query.get("mode") or "").strip().lower()
            if mode not in {"idle", "realtime"}:
                return web.json_response({"status": "error", "message": "Modus muss idle oder realtime sein."}, status=400)
            config = json.loads(json.dumps(self.config_raw))
            runtime = config.setdefault("runtime", {})
            if not isinstance(runtime, dict):
                runtime = {}
                config["runtime"] = runtime
            runtime["idle_mode"] = mode == "idle"
            self._save_config(config)
            self._restart_realtime_watch()
            return web.json_response({"status": "ok", "message": "Betriebsart gespeichert.", "idle_mode": mode == "idle"})
        if action == "add_list":
            name = str(body.get("name") or request.query.get("name") or "").strip()
            if not name:
                return web.json_response({"status": "error", "message": "Listenname fehlt."}, status=400)
            names = self._configured_list_names()
            if name.casefold() not in {item.casefold() for item in names}:
                names.append(name)
            self._save_list_names(names)
            self._restart_realtime_watch()
            return web.json_response({"status": "ok", "message": "Liste verknuepft.", "list_names": names})
        if action == "remove_list":
            name = str(body.get("name") or request.query.get("name") or "").strip()
            names = [item for item in self._configured_list_names() if item.casefold() != name.casefold()]
            self._save_list_names(names)
            self._restart_realtime_watch()
            return web.json_response({"status": "ok", "message": "Liste entfernt.", "list_names": names})
        if action == "use_all_lists":
            self._save_list_names(None)
            self._restart_realtime_watch()
            return web.json_response({"status": "ok", "message": "Alle Firebase-Listen werden verwendet."})
        return web.json_response({"status": "error", "message": f"Unbekannte Aktion: {action}"}, status=400)

    def _status_payload(self) -> dict[str, Any]:
        status_sensor = self._core_get_entity_state(self.shopping_sync_config.home_assistant, self.status_entity_id)
        attrs = (status_sensor or {}).get("attributes", {}) if isinstance(status_sensor, dict) else {}
        watched_lists = attrs.get("watched_lists") if isinstance(attrs, dict) else None
        if not isinstance(watched_lists, list):
            watched_lists = self.shopping_sync_config.list_names or []
        configured_lists = self._configured_list_names()
        todo_entities = sorted(self._core_get_todo_entities(self.shopping_sync_config.home_assistant))
        if not todo_entities and isinstance(attrs, dict):
            synced_entities = attrs.get("synced_todo_entities")
            if isinstance(synced_entities, list):
                todo_entities = sorted(str(item) for item in synced_entities if str(item).startswith("todo."))
        runtime = self.config_raw.get("runtime")
        idle_mode = runtime.get("idle_mode", False) if isinstance(runtime, dict) else False
        return {
            "status": "ok",
            "state": "syncing" if self.sync_running else ("online" if self._realtime_is_running() else "idle"),
            "sync_running": self.sync_running,
            "last_sync_result": self.last_sync_result,
            "last_sync_error": self.last_sync_error,
            "status_sensor": status_sensor or {"state": "unknown", "attributes": {}},
            "config_path": str(CONFIG_PATH),
            "idle_mode": bool(idle_mode),
            "sync_mode": "Bei Bedarf" if bool(idle_mode) else "Echtzeit",
            "configured_lists": configured_lists,
            "configured_list_count": len(configured_lists),
            "uses_all_firebase_lists": not bool(configured_lists),
            "watched_lists": watched_lists,
            "watched_list_count": len(watched_lists),
            "todo_entities": todo_entities,
            "todo_entity_count": len(todo_entities),
            "log_count": len(self.live_events),
        }

    def _admin_html(self) -> str:
        title = "Shopping Sync"
        return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cpath fill='%232563eb' d='M18 50a6 6 0 1 0 0 12 6 6 0 0 0 0-12Zm30 0a6 6 0 1 0 0 12 6 6 0 0 0 0-12ZM10 8H2V2h12l5 30h31l7-20H22l-1-6h40a3 3 0 0 1 3 4l-9 27a3 3 0 0 1-3 2H20l1 5h35v6H18a3 3 0 0 1-3-2L10 8Z'/%3E%3C/svg%3E">
  <style>
    :root {{ color-scheme: light dark; font-family: Segoe UI, system-ui, sans-serif; }}
    body {{ margin: 0; background: #f5f7f9; color: #1f2933; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 22px; }}
    h1 {{ display: flex; align-items: center; gap: 10px; font-size: 26px; margin: 0 0 16px; }}
    h2 {{ font-size: 17px; margin: 0 0 12px; }}
    .cart-icon {{ width: 28px; height: 28px; fill: #2563eb; flex: 0 0 auto; }}
    .version-badge {{ font-size: 12px; font-weight: 600; color: #52606d; background: #e8eef5; border-radius: 999px; padding: 4px 8px; }}
    section {{ background: #fff; border: 1px solid #d8e0e8; border-radius: 8px; padding: 16px; margin-bottom: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .tile {{ border: 1px solid #d8e0e8; border-radius: 6px; padding: 12px; background: #f9fbfd; min-height: 46px; }}
    .label {{ color: #596673; font-size: 12px; margin-bottom: 4px; }}
    .value {{ font-size: 15px; font-weight: 600; overflow-wrap: anywhere; }}
    .banner {{ padding: 12px; border-radius: 6px; border: 1px solid #fed7aa; background: #fff7ed; margin: 12px 0; }}
    .banner.ok {{ border-color: #bbf7d0; background: #ecfdf5; }}
    .banner.error {{ border-color: #fecaca; background: #fef2f2; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    button {{ border: 0; border-radius: 6px; background: #2563eb; color: #fff; padding: 9px 13px; font: inherit; cursor: pointer; }}
    button.secondary {{ background: #52606d; }}
    button.active {{ background: #2563eb; }}
    .mode-buttons button {{ background: #52606d; }}
    input, textarea {{ border: 1px solid #b8c4d0; border-radius: 6px; padding: 9px 10px; font: inherit; box-sizing: border-box; }}
    input {{ min-width: 240px; }}
    textarea {{ width: 100%; min-height: 330px; font: 13px Consolas, monospace; resize: vertical; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f8fafc; border: 1px solid #d8e0e8; border-radius: 6px; padding: 12px; max-height: 300px; overflow: auto; }}
    .muted {{ color: #64748b; font-size: 13px; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    .chip {{ display: inline-flex; align-items: center; gap: 6px; border: 1px solid #cbd5e1; border-radius: 999px; padding: 5px 8px; background: #f8fafc; }}
    .chip button {{ border: 0; background: transparent; color: #b42318; padding: 0 2px; font-weight: 700; }}
    #message {{ min-height: 22px; margin: 8px 0 0; }}
    .tabs {{ display: flex; gap: 2px; border-bottom: 1px solid #d8e0e8; margin: 0 0 18px; }}
    .tab-button {{ display: inline-flex; align-items: center; gap: 8px; border: 0; border-bottom: 3px solid transparent; border-radius: 0; background: transparent; color: #52606d; padding: 11px 16px 10px; font-weight: 600; }}
    .tab-button:hover {{ background: #eef3f8; }}
    .tab-button.active {{ background: transparent; color: #111827; border-bottom-color: #2563eb; }}
    .tab-icon {{ width: 21px; height: 21px; fill: currentColor; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    body.embedded .tabs {{ display: none; }}
    .help-intro {{ margin: 0 0 16px; max-width: 820px; line-height: 1.55; }}
    .help-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-items: start; }}
    .help-card {{ background: #fff; border: 1px solid #d8e0e8; border-radius: 8px; padding: 16px; line-height: 1.5; }}
    .help-card h2 {{ font-size: 18px; margin-bottom: 10px; }}
    .help-card p {{ margin: 8px 0; }}
    .help-card ul {{ margin: 8px 0; padding-left: 22px; }}
    .help-card li {{ margin: 5px 0; }}
    .command {{ font-weight: 700; }}
    .note {{ border-left: 3px solid #2563eb; padding-left: 10px; }}
    @media (max-width: 900px) {{ .help-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 620px) {{
      main {{ padding: 14px; }}
      .tabs {{ overflow-x: auto; }}
      .tab-button {{ padding: 10px 12px; white-space: nowrap; }}
      .help-grid {{ grid-template-columns: 1fr; }}
    }}
    details {{ margin-top: 14px; }}
    summary {{ cursor: pointer; font-weight: 600; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #11161c; color: #e6edf3; }}
      section, textarea, input, .help-card {{ background: #171d24; color: #e6edf3; border-color: #344250; }}
      .tile, pre, .chip {{ background: #111820; border-color: #344250; }}
      .label, .muted {{ color: #aab6c2; }}
      .version-badge {{ background: #273444; color: #d6e0ea; }}
      .tabs {{ border-color: #344250; }}
      .tab-button {{ color: #aab6c2; }}
      .tab-button:hover {{ background: #1e2935; }}
      .tab-button.active {{ color: #ffffff; }}
      .banner {{ background: #332414; border-color: #7a4b18; }}
      .banner.ok {{ background: #133226; border-color: #246b4a; }}
      .banner.error {{ background: #371818; border-color: #7a3030; }}
    }}
  </style>
</head>
<body>
<main>
  <h1><svg class="cart-icon" viewBox="0 0 64 64" aria-hidden="true"><path d="M18 50a6 6 0 1 0 0 12 6 6 0 0 0 0-12Zm30 0a6 6 0 1 0 0 12 6 6 0 0 0 0-12ZM10 8H2V2h12l5 30h31l7-20H22l-1-6h40a3 3 0 0 1 3 4l-9 27a3 3 0 0 1-3 2H20l1 5h35v6H18a3 3 0 0 1-3-2L10 8Z"/></svg>{title}<span class="version-badge">AppDaemon | intern</span></h1>
  <nav class="tabs" aria-label="Shopping-Sync-Bereiche">
    <button id="tabButtonStatus" class="tab-button active" type="button" onclick="showTab('status')"><svg class="tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 13h4l3-9 4 16 3-7h4v2h-3l-4 9-4-16-2 7H3z"/></svg>Status</button>
    <button id="tabButtonConfig" class="tab-button" type="button" onclick="showTab('config')"><svg class="tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.14 12.94a7.5 7.5 0 0 0 .05-.94 7.5 7.5 0 0 0-.05-.94l2.03-1.58-1.92-3.32-2.39.96a7.3 7.3 0 0 0-1.63-.94L14.87 3h-3.84l-.36 3.18c-.58.24-1.12.55-1.63.94l-2.39-.96-1.92 3.32 2.03 1.58a7.5 7.5 0 0 0-.05.94c0 .32.02.63.05.94l-2.03 1.58 1.92 3.32 2.39-.96c.51.39 1.05.7 1.63.94l.36 3.18h3.84l.36-3.18c.58-.24 1.12-.55 1.63-.94l2.39.96 1.92-3.32zM12.95 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/></svg>Konfiguration</button>
    <button id="tabButtonHelp" class="tab-button" type="button" onclick="showTab('help')"><svg class="tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 18h2v-2h-2v2zm1-16a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm0-14a4 4 0 0 0-4 4h2a2 2 0 1 1 3.17 1.62C12.15 12.3 11 13.09 11 15h2c0-.85.45-1.19 1.28-1.76A4 4 0 0 0 12 6z"/></svg>Hilfe</button>
  </nav>
  <div id="tab-status" class="tab-panel active">

  <section>
    <div class="grid">
      <div class="tile"><div class="label">Laufzeit</div><div class="value">Home Assistant AppDaemon</div></div>
      <div class="tile"><div class="label">Anbindung</div><div class="value">Internes Home Assistant API</div></div>
      <div class="tile"><div class="label">Firebase</div><div class="value" id="overviewFirebase">Status wird geladen</div></div>
    </div>
  </section>

  <section>
    <div class="actions">
      <h2 style="margin-right:auto">Status</h2>
      <button onclick="refreshAll()">Aktualisieren</button>
      <button onclick="syncNow()">Jetzt synchronisieren</button>
      <button class="secondary" onclick="reloadConfig()">Neu laden</button>
    </div>
    <p id="message"></p>
    <div id="statusBanner" class="banner">Status noch nicht geladen.</div>
    <div class="grid">
      <div class="tile"><div class="label">Firebase</div><div id="tileFirebase" class="value">-</div></div>
      <div class="tile"><div class="label">Home Assistant</div><div id="tileHa" class="value">-</div></div>
      <div class="tile"><div class="label">Beobachtete Listen</div><div id="tileWatchedLists" class="value">-</div></div>
      <div class="tile"><div class="label">Todo-Listen</div><div id="tileTodoEntities" class="value">-</div></div>
      <div class="tile"><div class="label">Letzter Kontakt</div><div id="tileLastContact" class="value">-</div></div>
      <div class="tile"><div class="label">Letzter Fehler</div><div id="tileLastError" class="value">-</div></div>
      <div class="tile"><div class="label">Live-Monitor</div><div id="tileLiveMonitor" class="value">-</div></div>
      <div class="tile"><div class="label">Sync</div><div id="tileSync" class="value">-</div></div>
      <div class="tile"><div class="label">Betriebsart</div><div id="tileMode" class="value">-</div></div>
    </div>
    <div class="actions mode-buttons" style="margin-top:12px">
      <button id="modeIdle" type="button" onclick="setSyncMode(true)">Bei Bedarf</button>
      <button id="modeRealtime" type="button" onclick="setSyncMode(false)">Echtzeit</button>
    </div>
    <div class="actions" style="margin-top:16px">
      <h2 style="margin-right:auto">Live-Logs</h2>
      <button class="secondary" onclick="clearLogs()">Log loeschen</button>
    </div>
    <pre id="logs">Noch keine Logs.</pre>
  </section>

  </div>

  <div id="tab-config" class="tab-panel">
  <section>
    <div class="actions"><h2 style="margin-right:auto">Listen verknuepfen</h2></div>
    <p class="muted" id="listModeHint">Status wird geladen.</p>
    <div class="actions">
      <input id="newListName" type="text" placeholder="Listenname, z. B. Aldi">
      <button onclick="addList()">Liste verknuepfen</button>
      <button class="secondary" onclick="useAllLists()">Alle Firebase-Listen verwenden</button>
    </div>
    <div class="label" style="margin-top:12px">Konfigurierte Listen</div>
    <div id="configuredLists" class="chips"></div>
  </section>

  <section>
    <div class="actions">
      <h2 style="margin-right:auto">Konfiguration</h2>
      <button class="secondary" onclick="loadConfig()">Einlesen</button>
      <button onclick="saveConfig()">Speichern</button>
    </div>
    <textarea id="config" spellcheck="false"></textarea>
    <details><summary>Diagnose</summary><pre id="diagnostics">Noch keine Daten.</pre></details>
</section>
  </div>

  <div id="tab-help" class="tab-panel">
    <p class="help-intro"><strong>Sprachbefehle &amp; Beispiele</strong><br>Sprich die Beispiele ueber deine eingerichtete Home-Assistant-Sprachsteuerung. Home Assistant schreibt den Auftrag in die Todo-Liste; Shopping Sync uebertraegt die Aenderung zur verbundenen Einkaufslisten-App.</p>
    <div class="help-grid">
      <article class="help-card"><h2>Artikel hinzufuegen</h2><ul><li><span class="command">„Setze Milch auf die Aldi-Liste.“</span></li><li><span class="command">„Fuege Milch zur Aldi-Liste hinzu.“</span></li><li><span class="command">„Schreibe Milch auf die Aldi-Liste.“</span></li></ul><p>Die genaue Formulierung wird von deiner Home-Assistant-Sprachpipeline bestimmt. Entscheidend ist, dass der Artikel in der passenden Todo-Liste ankommt.</p></article>
      <article class="help-card"><h2>Mehrere Artikel mit „und“</h2><ul><li><span class="command">„Setze Bier und Birnen auf die Aldi-Liste.“</span></li><li><span class="command">„Fuege Obst und Gemuese zur Einkaufsliste hinzu.“</span></li></ul><p>Shopping Sync zerlegt einen neuen Home-Assistant-Eintrag am alleinstehenden Wort <strong>und</strong>. Aus „Bier und Birnen“ werden daher zwei getrennte Artikel.</p><p class="note"><strong>Beachte:</strong> Ein Produktname wie „Salz und Pfeffer“ wird ebenfalls in zwei Artikel getrennt.</p></article>
      <article class="help-card"><h2>Artikel erledigen</h2><ul><li><span class="command">„Markiere Milch auf der Aldi-Liste als erledigt.“</span></li><li><span class="command">„Hake Milch auf der Aldi-Liste ab.“</span></li></ul><p>Der Erledigt-Status wird zwischen Home Assistant und Firebase abgeglichen. Welche Formulierung erkannt wird, haengt von Home Assistant Assist ab.</p></article>
      <article class="help-card"><h2>Artikel entfernen</h2><ul><li><span class="command">„Entferne Milch von der Aldi-Liste.“</span></li><li><span class="command">„Loesche Milch aus der Aldi-Liste.“</span></li></ul><p>Loeschungen werden bei aktivierter Rueckschreibung zur jeweils anderen Seite uebertragen. Bei gleichzeitigen Aenderungen wird der zusammengefuehrte Datenstand verwendet.</p></article>
      <article class="help-card"><h2>Mengen und doppelte Eintraege</h2><p>Mehrfach vorhandene, gleichnamige Artikel werden nach der bestehenden Synchronisationslogik zusammengefuehrt und als Menge dargestellt.</p><ul><li>„Milch“ einmal vorhanden: Menge 1.</li><li>„Milch“ mehrfach vorhanden: Menge 2, 3 usw.</li></ul><p class="note">Unterschiedliche Schreibweisen gelten als unterschiedliche Artikel, sofern sie sich nicht nur durch Gross- und Kleinschreibung unterscheiden.</p></article>
      <article class="help-card"><h2>Listen richtig zuordnen</h2><p>Am einfachsten ist eine gleichnamige Todo-Liste in Home Assistant, zum Beispiel Firebase-Liste <strong>Aldi</strong> und Entitaet <strong>todo.aldi</strong>.</p><p>Unter <strong>Konfiguration → Listen verknuepfen</strong> kannst du einzelne Listen festlegen oder alle von Firebase gemeldeten Listen beruecksichtigen lassen. Synchronisiert werden nur Listen, fuer die eine passende Home-Assistant-Todo-Liste existiert.</p></article>
      <article class="help-card"><h2>Echtzeit und Bei Bedarf</h2><p><strong>Echtzeit</strong> haelt die Firebase-WebSocket-Verbindung offen und verarbeitet Aenderungen laufend.</p><p><strong>Bei Bedarf</strong> arbeitet ohne dauerhafte Firebase-Verbindung. Eine Synchronisation wird manuell oder durch einen erkannten Home-Assistant-Listen-Trigger angestossen.</p></article>
      <article class="help-card"><h2>Wenn ein Befehl nicht ankommt</h2><ul><li>Pruefe zuerst, ob Home Assistant den Artikel in der Todo-Liste angelegt hat.</li><li>Pruefe unter Status, ob Firebase und Home Assistant verbunden sind.</li><li>Vergleiche Listenname und Todo-Entitaet.</li><li>Sieh im Live-Log nach dem erkannten Listenereignis.</li><li>Nutze „Jetzt synchronisieren“ fuer einen unmittelbaren Test.</li></ul></article>
    </div>
  </div>
</main>
<script>
const base = './';
const route = '{html.escape(self.admin_route)}';
let currentStatus = null;

function showTab(name) {{
  const valid = ['status', 'config', 'help'];
  const selected = valid.includes(name) ? name : 'status';
  valid.forEach(tab => {{
    document.getElementById(`tab-${{tab}}`).classList.toggle('active', tab === selected);
    const button = document.getElementById(`tabButton${{tab.charAt(0).toUpperCase() + tab.slice(1)}}`);
    button.classList.toggle('active', tab === selected);
    button.setAttribute('aria-selected', tab === selected ? 'true' : 'false');
  }});
  history.replaceState(null, '', `#${{selected}}`);
}}
async function j(url, options) {{
  const response = await fetch(base + url, options || {{}});
  const data = await response.json();
  if (!response.ok || data.status === 'error') throw new Error(data.message || `HTTP ${{response.status}}`);
  return data;
}}
function showMessage(text, error=false) {{
  const box = document.getElementById('message');
  box.textContent = text || '';
  box.style.color = error ? '#b42318' : '';
}}
function listText(items) {{ return (items || []).length ? items.join(', ') : 'keine'; }}
function formatDate(value) {{
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('de-DE');
}}
function renderLists(status) {{
  const configured = status.configured_lists || [];
  const box = document.getElementById('configuredLists');
  box.innerHTML = '';
  document.getElementById('listModeHint').textContent = status.uses_all_firebase_lists
    ? 'Alle von Firebase gemeldeten Listen werden beruecksichtigt; synchronisiert werden passende Home-Assistant-Todo-Listen.'
    : `${{configured.length}} Liste(n) explizit verknuepft.`;
  if (!configured.length) {{ box.innerHTML = '<span class="muted">Keine feste Auswahl konfiguriert.</span>'; return; }}
  configured.forEach(name => {{
    const chip = document.createElement('span'); chip.className = 'chip';
    const label = document.createElement('span'); label.textContent = name;
    const remove = document.createElement('button'); remove.type = 'button'; remove.title = 'Liste entfernen'; remove.textContent = 'x'; remove.onclick = () => removeList(name);
    chip.append(label, remove); box.appendChild(chip);
  }});
}}
function renderStatus(status) {{
  currentStatus = status;
  const attrs = (status.status_sensor && status.status_sensor.attributes) || {{}};
  const state = status.state || '-';
  const connected = attrs.firebase_connected === true;
  const banner = document.getElementById('statusBanner');
  banner.textContent = `Status: ${{state}}`;
  banner.className = state === 'error' ? 'banner error' : ((state === 'idle' || state === 'online') ? 'banner ok' : 'banner');
  document.getElementById('overviewFirebase').textContent = connected ? 'verbunden' : 'nicht verbunden';
  document.getElementById('tileFirebase').textContent = connected ? 'verbunden' : 'nicht verbunden';
  document.getElementById('tileHa').textContent = attrs.home_assistant_connected === false ? 'nicht verbunden' : 'verbunden';
  document.getElementById('tileWatchedLists').textContent = `${{status.watched_list_count || 0}}: ${{listText(status.watched_lists)}}`;
  document.getElementById('tileTodoEntities').textContent = `${{status.todo_entity_count || 0}}: ${{listText(status.todo_entities)}}`;
  document.getElementById('tileLastContact').textContent = formatDate(attrs.last_contact || attrs.last_seen || attrs.last_sync);
  document.getElementById('tileLastError').textContent = status.last_sync_error || attrs.last_error || '-';
  document.getElementById('tileLiveMonitor').textContent = connected ? 'verbunden' : (state === 'idle' ? 'bereit' : 'nicht verbunden');
  document.getElementById('tileSync').textContent = status.sync_running ? 'laeuft' : 'bereit';
  document.getElementById('tileMode').textContent = status.sync_mode || '-';
  document.getElementById('modeIdle').classList.toggle('active', status.idle_mode === true);
  document.getElementById('modeRealtime').classList.toggle('active', status.idle_mode === false);
  document.getElementById('diagnostics').textContent = JSON.stringify(status, null, 2);
  renderLists(status);
}}
async function refresh() {{
  const status = await j(route + '_status'); renderStatus(status);
  const logs = await j(route + '_logs');
  const box = document.getElementById('logs');
  box.textContent = (logs.events || []).length ? (logs.events || []).map(e => `${{e.time || ''}} | ${{e.kind || ''}} | ${{e.summary || ''}}`).join('\\n') : 'Noch keine Logs.';
  box.scrollTop = box.scrollHeight;
}}
async function loadConfig() {{
  const data = await j(route + '_config');
  document.getElementById('config').value = JSON.stringify(data.config || {{}}, null, 2);
}}
async function refreshAll() {{ try {{ await Promise.all([loadConfig(), refresh()]); showMessage('Aktualisiert.'); }} catch (error) {{ showMessage(error.message, true); }} }}
async function saveConfig() {{
  try {{ const config = JSON.parse(document.getElementById('config').value || '{{}}'); await j(route + '_config', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{config}})}}); await refreshAll(); showMessage('Konfiguration gespeichert.'); }}
  catch (error) {{ showMessage(error.message, true); }}
}}
async function syncNow() {{ try {{ const data = await j(route + '_command?action=sync_now'); showMessage(data.message); await refresh(); }} catch (error) {{ showMessage(error.message, true); }} }}
async function reloadConfig() {{ try {{ const data = await j(route + '_command?action=reload'); showMessage(data.message); await refreshAll(); }} catch (error) {{ showMessage(error.message, true); }} }}
async function clearLogs() {{ try {{ await j(route + '_command?action=clear_logs'); await refresh(); }} catch (error) {{ showMessage(error.message, true); }} }}
async function setSyncMode(idleMode) {{ try {{ await j(route + `_command?action=set_mode&mode=${{idleMode ? 'idle' : 'realtime'}}`); await refreshAll(); }} catch (error) {{ showMessage(error.message, true); }} }}
async function addList() {{ const input=document.getElementById('newListName'); const name=input.value.trim(); if(!name)return; try {{ await j(route + `_command?action=add_list&name=${{encodeURIComponent(name)}}`); input.value=''; await refreshAll(); }} catch(error) {{ showMessage(error.message,true); }} }}
async function removeList(name) {{ try {{ await j(route + `_command?action=remove_list&name=${{encodeURIComponent(name)}}`); await refreshAll(); }} catch(error) {{ showMessage(error.message,true); }} }}
async function useAllLists() {{ try {{ await j(route + '_command?action=use_all_lists'); await refreshAll(); }} catch(error) {{ showMessage(error.message,true); }} }}

if (new URLSearchParams(location.search).get('embedded') === '1') document.body.classList.add('embedded');
showTab(location.hash.replace('#', '') || 'status');
refreshAll();
setInterval(() => refresh().catch(error => showMessage(error.message, true)), 2000);
</script>
</body>
</html>"""

class AppDaemonLogHandler(logging.Handler):
    def __init__(self, app: ShoppingSyncApp) -> None:
        super().__init__(logging.INFO)
        self.app = app
        self.shopping_sync_handler = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.app._append_live_event({"kind": "log", "summary": self.format(record)})
        except Exception:
            pass













