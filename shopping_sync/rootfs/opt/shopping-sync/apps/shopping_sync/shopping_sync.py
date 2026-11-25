from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import logging
import os
import re
import threading
import unicodedata
from collections import deque
from datetime import datetime, timezone
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


LOGGER = logging.getLogger("shopping_sync")
DEFAULT_STATUS_SENSOR = "sensor.shopping_sync_status"
DEFAULT_RESET_BUTTON = "input_button.shopping_sync_reset"
TOOL_ID = "shopping_sync"
TOOL_NAME = "Shopping Sync"
TOOL_VERSION = "0.1.1"
API_VERSION = "1"
CONFIG_SCHEMA_VERSION = "1"
RECENT_LOG_LINES: deque[str] = deque(maxlen=300)
SECRET_KEYS = {"token", "password", "api_key", "api_token", "id_token"}


def safe_text(value: Any) -> str:
    return str(value).encode("cp1252", errors="backslashreplace").decode("cp1252")


def safe_print(value: Any = "") -> None:
    print(safe_text(value), flush=True)


class RecentLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            RECENT_LOG_LINES.append(redact_text(self.format(record)))
        except Exception:
            pass


def redact_text(value: str) -> str:
    text = str(value)
    for pattern in (
        r'("?(?:token|password|api_key|api_token|id_token)"?\s*[:=]\s*)("[^"]*"|[^,\s}]+)',
        r"(Bearer\s+)[A-Za-z0-9._~+/=-]+",
    ):
        text = re.sub(pattern, r"\1***", text, flags=re.IGNORECASE)
    return text


def redact_config_value(value: Any, key: str = "") -> Any:
    if key.lower() in SECRET_KEYS:
        return "***" if value else ""
    if isinstance(value, dict):
        return {item_key: redact_config_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_config_value(item) for item in value]
    return value


def merge_preserving_masked_secrets(new_value: Any, old_value: Any, key: str = "") -> Any:
    if key.lower() in SECRET_KEYS and new_value == "***":
        return old_value
    if isinstance(new_value, dict) and isinstance(old_value, dict):
        merged: dict[str, Any] = {}
        for item_key, item_value in new_value.items():
            merged[item_key] = merge_preserving_masked_secrets(
                item_value,
                old_value.get(item_key),
                str(item_key),
            )
        return merged
    if isinstance(new_value, list) and isinstance(old_value, list):
        return [
            merge_preserving_masked_secrets(item, old_value[index] if index < len(old_value) else None, key)
            for index, item in enumerate(new_value)
        ]
    return new_value

IDENTITY_TOOLKIT_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
)


class ConfigError(Exception):
    """Raised when the local configuration is incomplete or invalid."""


class FirebaseError(Exception):
    """Raised when Firebase login or synchronization fails."""


class DependencyError(Exception):
    """Raised when a required third-party package is missing."""


@dataclass(frozen=True)
class FirebaseConfig:
    api_key: str
    email: str
    password: str
    database_url: str
    project_id: str = ""
    app_id: str = ""


@dataclass(frozen=True)
class HomeAssistantConfig:
    url: str
    token: str
    sensor_prefix: str = "sensor.shopping_liste_"
    sync_list_sensors: bool = False


@dataclass(frozen=True)
class AdminConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8095
    public_url: str = ""
    api_token: str = ""


@dataclass(frozen=True)
class RuntimeConfig:
    idle_mode: bool = False
    ha_watchdog_enabled: bool = True
    ha_watchdog_seconds: int = 30
    ha_watchdog_debounce_seconds: int = 15
    ha_periodic_sync_minutes: int = 10
    ha_realtime_burst_seconds: int = 10


@dataclass(frozen=True)
class AppConfig:
    firebase: FirebaseConfig
    list_name: str = ""
    list_names: list[str] | None = None
    websocket_timeout_seconds: int = 30
    home_assistant: HomeAssistantConfig | None = None
    admin: AdminConfig = AdminConfig()
    runtime: RuntimeConfig = RuntimeConfig()


@dataclass(frozen=True)
class FirebaseSession:
    id_token: str
    uid: str


def require_module(module_name: str, package_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise DependencyError(
            f"Python-Paket fehlt: {package_name}. Bitte zuerst requirements.txt installieren."
        ) from exc


def default_config_path() -> Path:
    yaml_path = Path(__file__).with_name("config.yaml")
    return yaml_path if yaml_path.exists() else Path(__file__).with_name("config.json")


def read_config_file(config_path: Path) -> dict[str, Any]:
    config_path = resolve_config_path(config_path)
    try:
        text = config_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ConfigError(f"Konfigurationsdatei nicht gefunden: {config_path}") from exc

    suffix = config_path.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            data = parse_simple_yaml(text)
        else:
            raise ConfigError("Konfigurationsdatei muss .yaml, .yml oder .json sein.")
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Konfigurationsdatei ist kein gueltiges JSON: {exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"Konfigurationsdatei ist kein gueltiges YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Konfigurationsdatei muss ein Objekt enthalten.")
    return data


def resolve_config_path(config_path: Path) -> Path:
    if config_path.exists():
        return config_path
    if config_path.suffix.lower() == ".json":
        yaml_path = config_path.with_suffix(".yaml")
        yml_path = config_path.with_suffix(".yml")
        if yaml_path.exists():
            return yaml_path
        if yml_path.exists():
            return yml_path
    return config_path


def write_config_file(config_path: Path, config: dict[str, Any]) -> None:
    config_path = resolve_config_path(config_path)
    suffix = config_path.suffix.lower()
    if suffix == ".json":
        content = json.dumps(config, indent=4, ensure_ascii=False) + "\n"
    elif suffix in {".yaml", ".yml"}:
        content = dump_simple_yaml(config)
    else:
        raise ConfigError("Konfigurationsdatei muss .yaml, .yml oder .json sein.")
    config_path.write_text(content, encoding="utf-8")


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = [
        (len(line) - len(line.lstrip(" ")), line.strip())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    index = 0
    while index < len(lines):
        indent, content = lines[index]
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError("Listeneintrag ohne Liste.")
            parent.append(parse_yaml_scalar(content[2:].strip()))
            index += 1
            continue

        key, separator, value = content.partition(":")
        if not separator:
            raise ValueError(f"Ungueltige Zeile: {content}")
        key = key.strip()
        value = value.strip()
        if not isinstance(parent, dict):
            raise ValueError("Schluessel in einer Liste wird nicht unterstuetzt.")

        if value:
            parent[key] = parse_yaml_scalar(value)
            index += 1
            continue

        next_container: Any = {}
        for next_indent, next_content in lines[index + 1 :]:
            if next_indent <= indent:
                break
            next_container = [] if next_content.startswith("- ") else {}
            break
        parent[key] = next_container
        stack.append((indent, next_container))
        index += 1
    return root


def parse_yaml_scalar(value: str) -> Any:
    if value in {"''", '""'}:
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return json.loads(value) if value.startswith('"') else value[1:-1].replace("''", "'")
    try:
        return int(value)
    except ValueError:
        return value


def dump_simple_yaml(data: dict[str, Any]) -> str:
    return "\n".join(dump_yaml_lines(data, 0)) + "\n"


def dump_yaml_lines(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {format_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        return [f"{prefix}- {format_yaml_scalar(item)}" for item in value]
    return [f"{prefix}{format_yaml_scalar(value)}"]


def format_yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def load_config(config_path: Path) -> AppConfig:
    raw_config = read_config_file(config_path)

    firebase = raw_config.get("firebase")
    if not isinstance(firebase, dict):
        raise ConfigError("In der Konfiguration fehlt der Abschnitt 'firebase'.")

    api_key = require_text(firebase, "api_key", "firebase")
    email = require_text(firebase, "email", "firebase")
    password = require_text(firebase, "password", "firebase")
    database_url = normalize_database_url(
        require_text(firebase, "database_url", "firebase")
    )
    project_id = optional_text(firebase, "project_id")
    app_id = optional_text(firebase, "app_id")
    list_name = optional_text(raw_config, "list_name")
    list_names = optional_text_list(raw_config, "list_names")

    websocket_config = raw_config.get("websocket", {})
    timeout_seconds = 30
    if isinstance(websocket_config, dict):
        timeout_seconds = int(websocket_config.get("timeout_seconds", 30))

    if timeout_seconds <= 0:
        raise ConfigError("websocket.timeout_seconds muss groesser als 0 sein.")

    home_assistant = load_home_assistant_config(raw_config)
    admin = load_admin_config(raw_config)
    runtime = load_runtime_config(raw_config)

    return AppConfig(
        firebase=FirebaseConfig(
            api_key=api_key,
            email=email,
            password=password,
            database_url=database_url,
            project_id=project_id,
            app_id=app_id,
        ),
        list_name=list_name,
        list_names=list_names,
        websocket_timeout_seconds=timeout_seconds,
        home_assistant=home_assistant,
        admin=admin,
        runtime=runtime,
    )


def require_text(source: dict[str, Any], key: str, section_name: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"In {section_name} fehlt der Textwert '{key}'.")
    return value.strip()


def optional_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def optional_text_list(source: dict[str, Any], key: str) -> list[str] | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ConfigError(f"In der Konfiguration muss '{key}' eine Liste sein.")
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not result:
        raise ConfigError(f"In der Konfiguration ist '{key}' leer.")
    return result


def load_home_assistant_config(raw_config: dict[str, Any]) -> HomeAssistantConfig | None:
    home_assistant = raw_config.get("home_assistant")
    if home_assistant is None:
        return None
    if not isinstance(home_assistant, dict):
        raise ConfigError("In der Konfiguration muss 'home_assistant' ein Objekt sein.")

    url = normalize_home_assistant_url(
        require_text(home_assistant, "url", "home_assistant")
    )
    token = require_text(home_assistant, "token", "home_assistant")
    if token == "HIER_LONG_LIVED_ACCESS_TOKEN_EINTRAGEN":
        raise ConfigError("Bitte in der Konfiguration den Home-Assistant-Token eintragen.")

    sensor_prefix = optional_text(home_assistant, "sensor_prefix") or "sensor.shopping_liste_"
    sync_list_sensors = home_assistant.get("sync_list_sensors", False)
    if not isinstance(sync_list_sensors, bool):
        raise ConfigError("home_assistant.sync_list_sensors muss true oder false sein.")
    return HomeAssistantConfig(
        url=url,
        token=token,
        sensor_prefix=sensor_prefix,
        sync_list_sensors=sync_list_sensors,
    )


def load_admin_config(raw_config: dict[str, Any]) -> AdminConfig:
    admin = raw_config.get("admin", {})
    if admin is None:
        return AdminConfig()
    if not isinstance(admin, dict):
        raise ConfigError("In der Konfiguration muss 'admin' ein Objekt sein.")

    enabled = admin.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError("admin.enabled muss true oder false sein.")

    host = optional_text(admin, "host") or "0.0.0.0"
    port = int(admin.get("port", 8095))
    if port <= 0 or port > 65535:
        raise ConfigError("admin.port muss zwischen 1 und 65535 liegen.")

    public_url = optional_text(admin, "public_url")
    if public_url:
        public_url = normalize_admin_public_url(public_url, port)
    api_token = optional_text(admin, "api_token")

    return AdminConfig(
        enabled=enabled,
        host=host,
        port=port,
        public_url=public_url,
        api_token=api_token,
    )


def load_runtime_config(raw_config: dict[str, Any]) -> RuntimeConfig:
    runtime = raw_config.get("runtime", {})
    if runtime is None:
        return RuntimeConfig()
    if not isinstance(runtime, dict):
        raise ConfigError("In der Konfiguration muss 'runtime' ein Objekt sein.")
    idle_mode = runtime.get("idle_mode", False)
    if not isinstance(idle_mode, bool):
        raise ConfigError("runtime.idle_mode muss true oder false sein.")
    ha_watchdog_enabled = runtime.get("ha_watchdog_enabled", True)
    if not isinstance(ha_watchdog_enabled, bool):
        raise ConfigError("runtime.ha_watchdog_enabled muss true oder false sein.")
    ha_watchdog_seconds = int(runtime.get("ha_watchdog_seconds", 30))
    if ha_watchdog_seconds <= 0:
        raise ConfigError("runtime.ha_watchdog_seconds muss groesser als 0 sein.")
    ha_watchdog_debounce_seconds = int(runtime.get("ha_watchdog_debounce_seconds", 15))
    if ha_watchdog_debounce_seconds < 0:
        raise ConfigError("runtime.ha_watchdog_debounce_seconds darf nicht kleiner als 0 sein.")
    ha_periodic_sync_minutes = int(runtime.get("ha_periodic_sync_minutes", 10))
    if ha_periodic_sync_minutes < 0:
        raise ConfigError("runtime.ha_periodic_sync_minutes darf nicht kleiner als 0 sein.")
    ha_realtime_burst_seconds = int(runtime.get("ha_realtime_burst_seconds", 10))
    if ha_realtime_burst_seconds < 0:
        raise ConfigError("runtime.ha_realtime_burst_seconds darf nicht kleiner als 0 sein.")
    return RuntimeConfig(
        idle_mode=idle_mode,
        ha_watchdog_enabled=ha_watchdog_enabled,
        ha_watchdog_seconds=ha_watchdog_seconds,
        ha_watchdog_debounce_seconds=ha_watchdog_debounce_seconds,
        ha_periodic_sync_minutes=ha_periodic_sync_minutes,
        ha_realtime_burst_seconds=ha_realtime_burst_seconds,
    )


def normalize_admin_public_url(url: str, port: int) -> str:
    if "://" not in url:
        url = f"http://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("admin.public_url muss eine gueltige http- oder https-URL sein.")
    netloc = parsed.netloc
    if ":" not in netloc:
        netloc = f"{netloc}:{port}"
    path = parsed.path.rstrip("/") or "/admin"
    return f"{parsed.scheme}://{netloc}{path}"


def normalize_home_assistant_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("home_assistant.url muss eine gueltige URL sein.")
    return url.rstrip("/")


def normalize_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("firebase.database_url muss eine gueltige URL sein.")
    return database_url.rstrip("/")


def sign_in(firebase: FirebaseConfig) -> FirebaseSession:
    requests = require_module("requests", "requests")
    response = requests.post(
        IDENTITY_TOOLKIT_URL,
        params={"key": firebase.api_key},
        json={
            "email": firebase.email,
            "password": firebase.password,
            "returnSecureToken": True,
        },
        timeout=20,
    )

    if response.status_code != 200:
        message = parse_firebase_error(response)
        raise FirebaseError(f"Firebase-Login fehlgeschlagen: {message}")

    data = response.json()
    id_token = data.get("idToken")
    uid = data.get("localId")
    if not id_token or not uid:
        raise FirebaseError("Firebase-Login-Antwort enthaelt keine UID oder Token.")

    return FirebaseSession(id_token=id_token, uid=uid)


def parse_firebase_error(response: Any) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"

    error = payload.get("error", {})
    if isinstance(error, dict):
        return str(error.get("message") or f"HTTP {response.status_code}")
    return f"HTTP {response.status_code}"


def build_websocket_url(firebase: FirebaseConfig) -> str:
    parsed = urlparse(firebase.database_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    query_parts = ["v=5"]
    if firebase.app_id:
        query_parts.append(f"p={quote(firebase.app_id, safe='')}")
    if firebase.project_id:
        query_parts.append(f"ns={quote(firebase.project_id, safe='')}")
    return f"{scheme}://{parsed.netloc}/.ws?{'&'.join(query_parts)}"


def build_lists_path(uid: str) -> str:
    return f"/sync/{uid}/lists"


def build_list_names_path(uid: str) -> str:
    return f"/sync/{uid}/list_names"


def build_list_path(uid: str, list_name: str) -> str:
    return f"{build_lists_path(uid)}/{list_name}"


def send_firebase_init(ws: Any) -> None:
    send_ws(
        ws,
        {
            "t": "d",
            "d": {
                "r": 2,
                "a": "s",
                "b": {"c": {"sdk.js.12-14-0": 1}},
            },
        },
    )


def fetch_path_via_websocket(
    config: AppConfig,
    session: FirebaseSession,
    path: str,
    request_number: int = 3,
) -> Any:
    websocket = require_module("websocket", "websocket-client")
    ws_url = build_websocket_url(config.firebase)

    LOGGER.info("Verbinde mit Firebase WebSocket.")
    ws = websocket.create_connection(
        ws_url,
        timeout=config.websocket_timeout_seconds,
        enable_multithread=False,
    )

    try:
        send_ws(
            ws,
            {"t": "d", "d": {"r": 1, "a": "auth", "b": {"cred": session.id_token}}},
        )
        wait_for_request_ok(
            ws,
            request_number=1,
            timeout_seconds=config.websocket_timeout_seconds,
        )
        send_firebase_init(ws)

        LOGGER.info("Lade Firebase-Pfad: %s", path)
        send_ws(
            ws,
            {"t": "d", "d": {"r": request_number, "a": "q", "b": {"p": path, "h": ""}}},
        )
        return wait_for_data(
            ws,
            request_number=request_number,
            timeout_seconds=config.websocket_timeout_seconds,
        )
    finally:
        ws.close()


def fetch_list_via_websocket(config: AppConfig, session: FirebaseSession, list_name: str) -> Any:
    return fetch_path_via_websocket(config, session, build_list_path(session.uid, list_name))


def fetch_list_names_via_websocket(config: AppConfig, session: FirebaseSession) -> list[str]:
    payload = fetch_path_via_websocket(
        config,
        session,
        build_list_names_path(session.uid),
    )
    return extract_list_names(payload)


def fetch_all_lists_via_websocket(config: AppConfig, session: FirebaseSession) -> dict[str, list[str]]:
    lists: dict[str, list[str]] = {}
    for list_name in fetch_list_names_via_websocket(config, session):
        try:
            lists[list_name] = extract_items(fetch_list_via_websocket(config, session, list_name))
        except FirebaseError as exc:
            LOGGER.warning("Liste wird uebersprungen: %s (%s)", list_name, exc)
    return lists


def fetch_all_raw_lists_via_websocket(config: AppConfig, session: FirebaseSession) -> dict[str, Any]:
    raw_lists: dict[str, Any] = {}
    for list_name in fetch_list_names_via_websocket(config, session):
        try:
            raw_lists[list_name] = fetch_list_via_websocket(config, session, list_name)
        except FirebaseError as exc:
            LOGGER.warning("Liste wird uebersprungen: %s (%s)", list_name, exc)
    return raw_lists


def send_firebase_puts_via_websocket(
    config: AppConfig,
    session: FirebaseSession,
    updates: list[tuple[str, Any]],
) -> None:
    if not updates:
        return

    websocket = require_module("websocket", "websocket-client")
    ws_url = build_websocket_url(config.firebase)
    ws = websocket.create_connection(
        ws_url,
        timeout=config.websocket_timeout_seconds,
        enable_multithread=False,
    )

    try:
        send_ws(
            ws,
            {"t": "d", "d": {"r": 1, "a": "auth", "b": {"cred": session.id_token}}},
        )
        wait_for_request_ok(
            ws,
            request_number=1,
            timeout_seconds=config.websocket_timeout_seconds,
        )
        send_firebase_init(ws)

        request_number = 2
        for path, data in updates:
            send_ws(
                ws,
                {
                    "t": "d",
                    "d": {
                        "r": request_number,
                        "a": "p",
                        "b": {"p": path, "d": data},
                    },
                },
            )
            wait_for_request_ok(
                ws,
                request_number=request_number,
                timeout_seconds=config.websocket_timeout_seconds,
            )
            request_number += 1
    finally:
        ws.close()


def extract_list_names(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        names = payload
    elif isinstance(payload, dict):
        names = [value for _, value in sorted(payload.items(), key=lambda pair: str(pair[0]))]
    else:
        raise FirebaseError("Der Firebase-Pfad list_names enthaelt keine Listenstruktur.")

    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name.strip():
            continue
        clean_name = name.strip()
        if clean_name in seen:
            continue
        seen.add(clean_name)
        result.append(clean_name)
    return result


def watch_lists_via_websocket_once(
    config: AppConfig,
    session: FirebaseSession,
    configured_list_names: list[str] | None = None,
    sync_todo: bool = False,
    prune_todo: bool = False,
    sync_back: bool = False,
    ha_poll_seconds: int = 2,
    status_entity_id: str = DEFAULT_STATUS_SENSOR,
    reset_button_entity_id: str = DEFAULT_RESET_BUTTON,
    todo_refresh_seconds: int = 60,
    reconnect_count: int = 0,
    max_runtime_seconds: float | None = None,
    changed_todo_entities: set[str] | None = None,
    removed_todo_item_names: dict[str, set[str]] | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    if config.home_assistant is None:
        raise ConfigError("In der Konfiguration fehlt der Abschnitt home_assistant.")
    if sync_back and not sync_todo:
        raise ConfigError("--sync-back benoetigt --sync-todo.")

    websocket = require_module("websocket", "websocket-client")
    ws_url = build_websocket_url(config.firebase)
    list_names_path = build_list_names_path(session.uid)
    list_names_request = 3
    next_request_number = 4
    request_to_list_name: dict[int, str] = {}
    path_to_list_name: dict[str, str] = {}
    current_payloads: dict[str, Any] = {}
    watched_list_names: list[str] = []
    allowed_list_names = set(configured_list_names) if configured_list_names else None
    todo_entities: set[str] = set()
    synced_todo_entities: set[str] = set()
    next_ha_poll = time.monotonic() + ha_poll_seconds
    next_todo_refresh = time.monotonic() + max(1, todo_refresh_seconds)
    stop_at = time.monotonic() + max_runtime_seconds if max_runtime_seconds else None
    trigger_synced_entities: set[str] = set()
    reset_marker = get_home_assistant_entity_marker(
        config.home_assistant,
        reset_button_entity_id,
    )
    if sync_todo:
        todo_entities = get_home_assistant_todo_entities(config.home_assistant)

    LOGGER.info("Verbinde mit Firebase WebSocket im Watch-Modus.")
    write_shopping_sync_status(
        config.home_assistant,
        status_entity_id,
        "starting",
        watched_lists=watched_list_names,
        synced_todo_entities=synced_todo_entities,
        reconnect_count=reconnect_count,
        firebase_connected=False,
        home_assistant_connected=True,
    )
    ws = websocket.create_connection(ws_url, timeout=1, enable_multithread=False)

    def subscribe_list(list_name: str) -> None:
        nonlocal next_request_number
        if list_name in watched_list_names:
            return
        list_path = build_list_path(session.uid, list_name)
        request_number = next_request_number
        next_request_number += 1
        request_to_list_name[request_number] = list_name
        path_to_list_name[list_path] = list_name
        watched_list_names.append(list_name)
        LOGGER.info("Abonniere Firebase-Pfad: %s", list_path)
        send_ws(ws, {"t": "d", "d": {"r": request_number, "a": "q", "b": {"p": list_path, "h": ""}}})
        safe_print(f"Liste abonniert: {list_name}")

    def send_firebase_put(path: str, data: Any) -> None:
        nonlocal next_request_number
        request_number = next_request_number
        next_request_number += 1
        send_ws(ws, {"t": "d", "d": {"r": request_number, "a": "p", "b": {"p": path, "d": data}}})

    def sync_home_assistant_changes_to_firebase(
        allow_add: bool = True,
        allow_delete: bool = False,
        only_ha_duplicates: bool = False,
    ) -> None:
        if not sync_back:
            return
        for list_name, list_payload in list(current_payloads.items()):
            if list_name == "__list_names__" or list_name not in watched_list_names:
                continue
            entity_id = match_todo_entity(config.home_assistant, list_name, todo_entities)
            if not entity_id:
                continue
            if changed_todo_entities is not None and not only_ha_duplicates and entity_id not in changed_todo_entities:
                continue
            firebase_items = firebase_items_by_name(list_payload)
            ha_rows = get_home_assistant_todo_item_rows(config.home_assistant, entity_id)
            split_source_names = split_source_home_assistant_item_names(ha_rows)
            ha_duplicate_keys = duplicate_home_assistant_keys(ha_rows)
            if only_ha_duplicates and not ha_duplicate_keys:
                continue
            if ha_duplicate_keys:
                LOGGER.info(
                    "HA-Dubletten werden als Menge zusammengefuehrt in %s: %s.",
                    entity_id,
                    ", ".join(sorted(ha_duplicate_keys)),
                )
            ha_items = aggregate_home_assistant_todo_rows(
                ha_rows,
                merge_duplicate_quantities=True,
            )
            ha_items = expand_home_assistant_items_for_firebase(ha_items)
            firebase_names = {item["name"].casefold() for item in firebase_items.values()}

            removed_items = []
            if allow_delete:
                allowed_removed_names = (removed_todo_item_names or {}).get(entity_id, set())
                removed_items = [
                    (item_key, item)
                    for item_key, item in firebase_items.items()
                    if item["name"].casefold() not in ha_items
                    and (
                        item["name"].casefold() in allowed_removed_names
                    )
                ]
            if removed_items:
                current_payloads[list_name] = compact_firebase_list_without_keys(
                    current_payloads.get(list_name),
                    [item_key for item_key, _ in removed_items],
                )
                send_firebase_put(build_list_path(session.uid, list_name), current_payloads[list_name])
                firebase_items = firebase_items_by_name(current_payloads[list_name])
                firebase_names = {item["name"].casefold() for item in firebase_items.values()}
                for _, item in removed_items:
                    safe_print(f"{datetime.now().strftime('%H:%M:%S')} Firebase geloescht: {list_name} / {item['name']}")

            for item_key, item in list(firebase_items.items()):
                item_name_key = item["name"].casefold()
                if only_ha_duplicates and item_name_key not in ha_duplicate_keys:
                    continue
                ha_item = ha_items.get(item["name"].casefold())
                if not ha_item:
                    continue
                status_changed = item.get("status") != ha_item.get("status")
                quantity_changed = item.get("quantity", "") != ha_item.get("quantity", "")
                quantity_unit_changed = firebase_quantity_unit_needs_normalization(item.get("payload"))
                if not status_changed and not quantity_changed and not quantity_unit_changed:
                    continue
                item_path = f"{build_list_path(session.uid, list_name)}/{item_key}"
                updated_item = build_firebase_item_from_ha_update(
                    item.get("payload"),
                    ha_item.get("status", "needs_action"),
                    ha_item.get("quantity", ""),
                )
                send_firebase_put(item_path, updated_item)
                current_payloads[list_name] = apply_firebase_update(
                    current_payloads.get(list_name),
                    item_path,
                    updated_item,
                    build_list_path(session.uid, list_name),
                )
                safe_print(f"{datetime.now().strftime('%H:%M:%S')} Firebase Artikel geaendert: {list_name} / {item['name']}")

            if allow_add:
                for ha_item in ha_items.values():
                    if ha_item["name"].casefold() in firebase_names:
                        continue
                    item_key = next_firebase_item_key(current_payloads.get(list_name))
                    item_path = f"{build_list_path(session.uid, list_name)}/{item_key}"
                    new_item = build_firebase_item_from_ha(
                        ha_item["name"],
                        item_key,
                        current_payloads.get(list_name),
                        ha_item.get("quantity", ""),
                    )
                    send_firebase_put(item_path, new_item)
                    current_payloads[list_name] = apply_firebase_update(current_payloads.get(list_name), item_path, new_item, build_list_path(session.uid, list_name))
                    firebase_names.add(ha_item["name"].casefold())
                    safe_print(f"{datetime.now().strftime('%H:%M:%S')} Firebase hinzugefuegt: {list_name} / {ha_item['name']}")

            for source_name in sorted(split_source_names):
                source_parts = split_home_assistant_shopping_item_name(source_name)
                if all(part.casefold() in firebase_names for part in source_parts):
                    if remove_home_assistant_todo_item(config.home_assistant, entity_id, source_name):
                        safe_print(
                            f"{datetime.now().strftime('%H:%M:%S')} HA-Eintrag aufgeteilt: {entity_id} / {source_name}"
                        )

            if changed_todo_entities is not None:
                changed_todo_entities.discard(entity_id)
            if removed_todo_item_names is not None:
                removed_todo_item_names.pop(entity_id, None)

    try:
        send_ws(ws, {"t": "d", "d": {"r": 1, "a": "auth", "b": {"cred": session.id_token}}})
        wait_for_request_ok(ws, request_number=1, timeout_seconds=config.websocket_timeout_seconds)
        send_firebase_init(ws)
        LOGGER.info("Abonniere Firebase-Pfad: %s", list_names_path)
        send_ws(ws, {"t": "d", "d": {"r": list_names_request, "a": "q", "b": {"p": list_names_path, "h": ""}}})

        if configured_list_names:
            for list_name in configured_list_names:
                subscribe_list(list_name)

        write_shopping_sync_status(
            config.home_assistant,
            status_entity_id,
            "online",
            watched_lists=watched_list_names,
            synced_todo_entities=synced_todo_entities,
            reconnect_count=reconnect_count,
            firebase_connected=True,
            home_assistant_connected=True,
        )

        safe_print("Watch-Modus laeuft. Abbrechen mit Strg+C.")
        safe_print("Listennamen werden aus Firebase /list_names gelesen.")
        if sync_back:
            safe_print("Rueckschreiben aktiv: HA-Loeschungen und neue HA-Eintraege werden nach Firebase uebernommen.")

        while True:
            if stop_event is not None and stop_event.is_set():
                safe_print("Firebase-Watch wurde angehalten.")
                return
            if stop_at is not None and time.monotonic() >= stop_at:
                safe_print("Firebase-Echtzeitfenster beendet.")
                return
            if reset_button_was_pressed(
                config.home_assistant,
                reset_button_entity_id,
                reset_marker,
            ):
                write_shopping_sync_status(
                    config.home_assistant,
                    status_entity_id,
                    "restarting",
                    watched_lists=watched_list_names,
                    synced_todo_entities=synced_todo_entities,
                    reconnect_count=reconnect_count,
                    firebase_connected=True,
                    home_assistant_connected=True,
                )
                safe_print("Reset-Button erkannt. Skript beendet sich fuer Neustart.")
                return
            if sync_todo and time.monotonic() >= next_todo_refresh:
                todo_entities = get_home_assistant_todo_entities(config.home_assistant)
                next_todo_refresh = time.monotonic() + max(1, todo_refresh_seconds)
            try:
                message = receive_ws_message(ws)
            except Exception as exc:
                if "timed out" in str(exc).lower():
                    if sync_back and time.monotonic() >= next_ha_poll:
                        sync_home_assistant_changes_to_firebase()
                        next_ha_poll = time.monotonic() + ha_poll_seconds
                    continue
                raise
            if not message:
                continue
            body = message.get("d", {})
            request_number = body.get("r")
            if request_number == list_names_request:
                payload = body.get("b", {})
                status = payload.get("s")
                if status == "ok":
                    LOGGER.info("Abo bestaetigt: list_names")
                    continue
                raise FirebaseError(f"Listenamen-Abo fehlgeschlagen: {status}")
            if request_number in request_to_list_name:
                payload = body.get("b", {})
                status = payload.get("s")
                list_name = request_to_list_name[request_number]
                if status == "ok":
                    LOGGER.info("Abo bestaetigt: %s", list_name)
                    continue
                raise FirebaseError(f"Listenabo fuer {list_name} fehlgeschlagen: {status}")
            if body.get("a") not in {"d", "m"}:
                continue
            payload = body.get("b", {})
            if not isinstance(payload, dict):
                continue
            path = payload.get("p")
            data = payload.get("d")
            if not isinstance(path, str):
                continue
            if path_is_or_below(path, list_names_path):
                current_payloads["__list_names__"] = apply_firebase_update(current_payloads.get("__list_names__"), path, data, list_names_path)
                discovered_names = extract_list_names(current_payloads["__list_names__"])
                if discovered_names:
                    safe_print("Gefundene Listen:")
                    for list_name in discovered_names:
                        if allowed_list_names is not None and list_name not in allowed_list_names:
                            continue
                        safe_print(f"  {list_name}")
                        subscribe_list(list_name)
                    write_shopping_sync_status(
                        config.home_assistant,
                        status_entity_id,
                        "online",
                        watched_lists=watched_list_names,
                        synced_todo_entities=synced_todo_entities,
                        reconnect_count=reconnect_count,
                        firebase_connected=True,
                        home_assistant_connected=True,
                    )
                continue
            list_name = match_watched_list(path, path_to_list_name)
            if not list_name:
                continue
            current_payloads[list_name] = apply_firebase_update(current_payloads.get(list_name), path, data, build_list_path(session.uid, list_name))
            current_payloads[list_name], merged_duplicates = merge_duplicate_firebase_items(
                current_payloads[list_name]
            )
            if merged_duplicates:
                send_firebase_put(build_list_path(session.uid, list_name), current_payloads[list_name])
                for item_name in merged_duplicates:
                    safe_print(f"{datetime.now().strftime('%H:%M:%S')} Dublette zusammengefuehrt: {list_name} / {item_name}")
            if sync_back:
                todo_entity_id_for_list = match_todo_entity(config.home_assistant, list_name, todo_entities)
                if (
                    changed_todo_entities
                    and todo_entity_id_for_list in changed_todo_entities
                    and todo_entity_id_for_list not in trigger_synced_entities
                ):
                    safe_print(
                        f"{datetime.now().strftime('%H:%M:%S')} Trigger-Liste wird vor HA-Aktualisierung nach Firebase gemergt: {todo_entity_id_for_list}"
                    )
                    sync_home_assistant_changes_to_firebase(
                        allow_add=True,
                        allow_delete=bool((removed_todo_item_names or {}).get(todo_entity_id_for_list, set())),
                        only_ha_duplicates=False,
                    )
                    trigger_synced_entities.add(todo_entity_id_for_list)
            items = extract_items(current_payloads[list_name])
            entity_id = ""
            if config.home_assistant.sync_list_sensors:
                entity_id = sync_sensor_to_home_assistant(config.home_assistant, list_name, items)
            if sync_todo:
                todo_entity_id = sync_list_to_home_assistant_todo(config.home_assistant, list_name, current_payloads[list_name], todo_entities, prune_todo=prune_todo or sync_back)
                if todo_entity_id:
                    synced_todo_entities.add(todo_entity_id)
                    safe_print(f"{datetime.now().strftime('%H:%M:%S')} Todo aktualisiert: {todo_entity_id}")
            write_shopping_sync_status(
                config.home_assistant,
                status_entity_id,
                "online",
                watched_lists=watched_list_names,
                synced_todo_entities=synced_todo_entities,
                reconnect_count=reconnect_count,
                firebase_connected=True,
                home_assistant_connected=True,
            )
            if entity_id:
                safe_print(f"{datetime.now().strftime('%H:%M:%S')} aktualisiert: {entity_id} ({len(items)} Artikel)")
            else:
                safe_print(f"{datetime.now().strftime('%H:%M:%S')} verarbeitet: {list_name} ({len(items)} Artikel)")
    except KeyboardInterrupt:
        safe_print("Watch-Modus beendet.")
        raise
    finally:
        ws.close()


def watch_lists_via_websocket(
    config: AppConfig,
    session: FirebaseSession,
    configured_list_names: list[str] | None = None,
    sync_todo: bool = False,
    prune_todo: bool = False,
    sync_back: bool = False,
    ha_poll_seconds: int = 2,
    reconnect_seconds: int = 10,
    status_entity_id: str = DEFAULT_STATUS_SENSOR,
    reset_button_entity_id: str = DEFAULT_RESET_BUTTON,
    todo_refresh_seconds: int = 60,
) -> None:
    reconnect_count = 0
    while True:
        try:
            watch_lists_via_websocket_once(
                config,
                session,
                configured_list_names,
                sync_todo=sync_todo,
                prune_todo=prune_todo,
                sync_back=sync_back,
                ha_poll_seconds=ha_poll_seconds,
                status_entity_id=status_entity_id,
                reset_button_entity_id=reset_button_entity_id,
                todo_refresh_seconds=todo_refresh_seconds,
                reconnect_count=reconnect_count,
            )
            return
        except KeyboardInterrupt:
            return
        except (ConfigError, DependencyError):
            raise
        except Exception as exc:
            reconnect_count += 1
            if config.home_assistant is not None:
                try:
                    write_shopping_sync_status(
                        config.home_assistant,
                        status_entity_id,
                        "reconnecting",
                        reconnect_count=reconnect_count,
                        last_error=str(exc),
                        firebase_connected=False,
                        home_assistant_connected=True,
                    )
                except Exception:
                    LOGGER.debug("Statussensor konnte nicht geschrieben werden.", exc_info=True)
            safe_print(
                f"{datetime.now().strftime('%H:%M:%S')} Verbindung verloren: {exc}. "
                f"Neuer Versuch in {reconnect_seconds} Sekunden."
            )
            LOGGER.debug("Watch-Verbindung wird neu aufgebaut.", exc_info=True)
            time.sleep(max(1, reconnect_seconds))
            try:
                session = sign_in(config.firebase)
            except Exception as login_exc:
                if config.home_assistant is not None:
                    try:
                        write_shopping_sync_status(
                            config.home_assistant,
                            status_entity_id,
                            "error",
                            reconnect_count=reconnect_count,
                            last_error=str(login_exc),
                            firebase_connected=False,
                            home_assistant_connected=True,
                        )
                    except Exception:
                        LOGGER.debug("Statussensor konnte nicht geschrieben werden.", exc_info=True)
                safe_print(
                    f"{datetime.now().strftime('%H:%M:%S')} Firebase-Login fehlgeschlagen: {login_exc}. "
                    f"Neuer Versuch in {reconnect_seconds} Sekunden."
                )
                LOGGER.debug("Firebase-Login nach Verbindungsabbruch fehlgeschlagen.", exc_info=True)
                time.sleep(max(1, reconnect_seconds))


def load_config(config_path: Path) -> AppConfig:
    raw_config = read_config_file(config_path)

    firebase = raw_config.get("firebase")
    if not isinstance(firebase, dict):
        raise ConfigError("In der Konfiguration fehlt der Abschnitt 'firebase'.")

    api_key = require_text(firebase, "api_key", "firebase")
    email = require_text(firebase, "email", "firebase")
    password = require_text(firebase, "password", "firebase")
    database_url = normalize_database_url(
        require_text(firebase, "database_url", "firebase")
    )
    project_id = optional_text(firebase, "project_id")
    app_id = optional_text(firebase, "app_id")
    list_name = optional_text(raw_config, "list_name")
    list_names = optional_text_list(raw_config, "list_names")

    websocket_config = raw_config.get("websocket", {})
    timeout_seconds = 30
    if isinstance(websocket_config, dict):
        timeout_seconds = int(websocket_config.get("timeout_seconds", 30))

    if timeout_seconds <= 0:
        raise ConfigError("websocket.timeout_seconds muss groesser als 0 sein.")

    home_assistant = load_home_assistant_config(raw_config)
    admin = load_admin_config(raw_config)
    runtime = load_runtime_config(raw_config)

    return AppConfig(
        firebase=FirebaseConfig(
            api_key=api_key,
            email=email,
            password=password,
            database_url=database_url,
            project_id=project_id,
            app_id=app_id,
        ),
        list_name=list_name,
        list_names=list_names,
        websocket_timeout_seconds=timeout_seconds,
        home_assistant=home_assistant,
        admin=admin,
        runtime=runtime,
    )


def require_text(source: dict[str, Any], key: str, section_name: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"In {section_name} fehlt der Textwert '{key}'.")
    return value.strip()


def optional_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def optional_text_list(source: dict[str, Any], key: str) -> list[str] | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ConfigError(f"In der Konfiguration muss '{key}' eine Liste sein.")
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not result:
        raise ConfigError(f"In der Konfiguration ist '{key}' leer.")
    return result


def load_home_assistant_config(raw_config: dict[str, Any]) -> HomeAssistantConfig | None:
    home_assistant = raw_config.get("home_assistant")
    if home_assistant is None:
        return None
    if not isinstance(home_assistant, dict):
        raise ConfigError("In der Konfiguration muss 'home_assistant' ein Objekt sein.")

    url = normalize_home_assistant_url(
        require_text(home_assistant, "url", "home_assistant")
    )
    token = require_text(home_assistant, "token", "home_assistant")
    if token == "HIER_LONG_LIVED_ACCESS_TOKEN_EINTRAGEN":
        raise ConfigError("Bitte in der Konfiguration den Home-Assistant-Token eintragen.")

    sensor_prefix = optional_text(home_assistant, "sensor_prefix") or "sensor.shopping_liste_"
    sync_list_sensors = home_assistant.get("sync_list_sensors", False)
    if not isinstance(sync_list_sensors, bool):
        raise ConfigError("home_assistant.sync_list_sensors muss true oder false sein.")
    return HomeAssistantConfig(
        url=url,
        token=token,
        sensor_prefix=sensor_prefix,
        sync_list_sensors=sync_list_sensors,
    )


def normalize_home_assistant_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("home_assistant.url muss eine gueltige URL sein.")
    return url.rstrip("/")


def normalize_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("firebase.database_url muss eine gueltige URL sein.")
    return database_url.rstrip("/")


def sign_in(firebase: FirebaseConfig) -> FirebaseSession:
    requests = require_module("requests", "requests")
    response = requests.post(
        IDENTITY_TOOLKIT_URL,
        params={"key": firebase.api_key},
        json={
            "email": firebase.email,
            "password": firebase.password,
            "returnSecureToken": True,
        },
        timeout=20,
    )

    if response.status_code != 200:
        message = parse_firebase_error(response)
        raise FirebaseError(f"Firebase-Login fehlgeschlagen: {message}")

    data = response.json()
    id_token = data.get("idToken")
    uid = data.get("localId")
    if not id_token or not uid:
        raise FirebaseError("Firebase-Login-Antwort enthaelt keine UID oder Token.")

    return FirebaseSession(id_token=id_token, uid=uid)


def parse_firebase_error(response: Any) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"

    error = payload.get("error", {})
    if isinstance(error, dict):
        return str(error.get("message") or f"HTTP {response.status_code}")
    return f"HTTP {response.status_code}"


def build_websocket_url(firebase: FirebaseConfig) -> str:
    parsed = urlparse(firebase.database_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    query_parts = ["v=5"]
    if firebase.app_id:
        query_parts.append(f"p={quote(firebase.app_id, safe='')}")
    if firebase.project_id:
        query_parts.append(f"ns={quote(firebase.project_id, safe='')}")
    return f"{scheme}://{parsed.netloc}/.ws?{'&'.join(query_parts)}"


def build_lists_path(uid: str) -> str:
    return f"/sync/{uid}/lists"


def build_list_names_path(uid: str) -> str:
    return f"/sync/{uid}/list_names"


def build_list_path(uid: str, list_name: str) -> str:
    return f"{build_lists_path(uid)}/{list_name}"


def send_firebase_init(ws: Any) -> None:
    send_ws(
        ws,
        {
            "t": "d",
            "d": {
                "r": 2,
                "a": "s",
                "b": {"c": {"sdk.js.12-14-0": 1}},
            },
        },
    )


def fetch_path_via_websocket(
    config: AppConfig,
    session: FirebaseSession,
    path: str,
    request_number: int = 3,
) -> Any:
    websocket = require_module("websocket", "websocket-client")
    ws_url = build_websocket_url(config.firebase)

    LOGGER.info("Verbinde mit Firebase WebSocket.")
    ws = websocket.create_connection(
        ws_url,
        timeout=config.websocket_timeout_seconds,
        enable_multithread=False,
    )

    try:
        send_ws(
            ws,
            {"t": "d", "d": {"r": 1, "a": "auth", "b": {"cred": session.id_token}}},
        )
        wait_for_request_ok(
            ws,
            request_number=1,
            timeout_seconds=config.websocket_timeout_seconds,
        )
        send_firebase_init(ws)

        LOGGER.info("Lade Firebase-Pfad: %s", path)
        send_ws(
            ws,
            {"t": "d", "d": {"r": request_number, "a": "q", "b": {"p": path, "h": ""}}},
        )
        return wait_for_data(
            ws,
            request_number=request_number,
            timeout_seconds=config.websocket_timeout_seconds,
        )
    finally:
        ws.close()


def fetch_list_via_websocket(config: AppConfig, session: FirebaseSession, list_name: str) -> Any:
    return fetch_path_via_websocket(config, session, build_list_path(session.uid, list_name))


def fetch_list_names_via_websocket(config: AppConfig, session: FirebaseSession) -> list[str]:
    payload = fetch_path_via_websocket(
        config,
        session,
        build_list_names_path(session.uid),
    )
    return extract_list_names(payload)


def fetch_all_lists_via_websocket(config: AppConfig, session: FirebaseSession) -> dict[str, list[str]]:
    lists: dict[str, list[str]] = {}
    for list_name in fetch_list_names_via_websocket(config, session):
        try:
            lists[list_name] = extract_items(fetch_list_via_websocket(config, session, list_name))
        except FirebaseError as exc:
            LOGGER.warning("Liste wird uebersprungen: %s (%s)", list_name, exc)
    return lists


def fetch_all_raw_lists_via_websocket(config: AppConfig, session: FirebaseSession) -> dict[str, Any]:
    raw_lists: dict[str, Any] = {}
    for list_name in fetch_list_names_via_websocket(config, session):
        try:
            raw_lists[list_name] = fetch_list_via_websocket(config, session, list_name)
        except FirebaseError as exc:
            LOGGER.warning("Liste wird uebersprungen: %s (%s)", list_name, exc)
    return raw_lists

def extract_list_names(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        names = payload
    elif isinstance(payload, dict):
        names = [value for _, value in sorted(payload.items(), key=lambda pair: str(pair[0]))]
    else:
        raise FirebaseError("Der Firebase-Pfad list_names enthaelt keine Listenstruktur.")

    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name.strip():
            continue
        clean_name = name.strip()
        if clean_name in seen:
            continue
        seen.add(clean_name)
        result.append(clean_name)
    return result


def firebase_items_by_name(list_payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(list_payload, dict):
        return {}
    candidates = find_item_container(list_payload)
    if not isinstance(candidates, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for item_key, item in candidates.items():
        if not isinstance(item, dict):
            continue
        name = first_text_value(
            item,
            "name",
            "title",
            "text",
            "label",
            "value",
            "item",
            "product",
        )
        if name:
            result[str(item_key)] = {
                "name": name,
                "status": "completed" if item_status(item) == "erledigt" else "needs_action",
                "quantity": item_quantity(item),
                "payload": item,
            }
    return result


def next_firebase_item_key(list_payload: Any) -> str:
    if not isinstance(list_payload, dict):
        return "0"
    candidates = find_item_container(list_payload)
    if not isinstance(candidates, dict):
        return "0"
    numeric_keys = []
    for key in candidates:
        try:
            numeric_keys.append(int(key))
        except (TypeError, ValueError):
            pass
    next_number = max(numeric_keys, default=-1) + 1
    while str(next_number) in candidates:
        next_number += 1
    return str(next_number)


def next_firebase_item_id(list_payload: Any, item_key: str) -> int:
    try:
        fallback_id = int(item_key)
    except ValueError:
        fallback_id = int(time.time())
    if not isinstance(list_payload, dict):
        return fallback_id
    candidates = find_item_container(list_payload)
    if not isinstance(candidates, dict):
        return fallback_id
    numeric_ids = []
    for item in candidates.values():
        if not isinstance(item, dict):
            continue
        try:
            numeric_ids.append(int(item.get("id")))
        except (TypeError, ValueError):
            pass
    return max(numeric_ids, default=fallback_id - 1) + 1


def compact_firebase_list_without_keys(
    list_payload: Any,
    removed_keys: list[str],
) -> Any:
    if not isinstance(list_payload, dict):
        return list_payload

    container_key = ""
    candidates: Any = list_payload
    for key in ("items", "entries", "products", "listItems", "list_items"):
        value = list_payload.get(key)
        if isinstance(value, dict):
            container_key = key
            candidates = value
            break
    if not isinstance(candidates, dict):
        return list_payload

    removed = {str(key) for key in removed_keys}
    compacted: dict[str, Any] = {}
    for old_key, item in sorted(candidates.items(), key=firebase_item_sort_key):
        if str(old_key) in removed or item is None:
            continue
        compacted[str(len(compacted))] = item

    if not container_key:
        return compacted

    new_payload = json.loads(json.dumps(list_payload))
    new_payload[container_key] = compacted
    return new_payload


def firebase_item_update_path(list_path: str, list_payload: Any, item_key: str) -> str:
    if isinstance(list_payload, dict):
        for key in ("items", "entries", "products", "listItems", "list_items"):
            if isinstance(list_payload.get(key), dict):
                return f"{list_path}/{key}/{item_key}"
    return f"{list_path}/{item_key}"


def merge_duplicate_firebase_items(list_payload: Any) -> tuple[Any, list[str]]:
    if not isinstance(list_payload, dict):
        return list_payload, []

    candidates = find_item_container(list_payload)
    if not isinstance(candidates, dict):
        return list_payload, []

    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    display_names: dict[str, str] = {}
    for item_key, item in sorted(candidates.items(), key=firebase_item_sort_key):
        if not isinstance(item, dict):
            continue
        name = first_text_value(
            item,
            "name",
            "title",
            "text",
            "label",
            "value",
            "item",
            "product",
        )
        if not name:
            continue
        key = name.casefold()
        grouped.setdefault(key, []).append((str(item_key), item))
        display_names.setdefault(key, name)

    removed_keys: list[str] = []
    merged_names: list[str] = []
    for key, group in grouped.items():
        if len(group) < 2:
            continue
        first_key, first_item = group[0]
        merged_item = json.loads(json.dumps(first_item))
        count, unit = merged_duplicate_quantity([item for _, item in group])
        merged_item["count"] = count
        merged_item["counttyp"] = unit
        candidates[first_key] = merged_item
        removed_keys.extend(item_key for item_key, _ in group[1:])
        merged_names.append(display_names[key])

    if not removed_keys:
        return list_payload, []
    return compact_firebase_list_without_keys(list_payload, removed_keys), merged_names


def merged_duplicate_quantity(items: list[dict[str, Any]]) -> tuple[Any, str]:
    units = [normalized_count_unit(item) for item in items]
    unit = next((value for value in units if value != "null"), "null")
    total = 0.0
    for item in items:
        value = numeric_count_value(item)
        total += value if value > 0 else 1
    count: Any = int(total) if total.is_integer() else total
    return count, unit


def numeric_count_value(item: dict[str, Any]) -> float:
    raw_count = item.get("count", item.get("quantity", item.get("qty", item.get("amount"))))
    if raw_count in (None, "", "null"):
        return 0.0
    try:
        return float(str(raw_count).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def firebase_quantity_unit_needs_normalization(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return numeric_count_value(item) > 0 and normalized_count_unit(item) == "null"


def normalized_count_unit(item: dict[str, Any]) -> str:
    raw_unit = item.get("counttyp", item.get("unit", item.get("countType", "")))
    if raw_unit in (None, "", "null"):
        return "null"
    return str(raw_unit).strip() or "null"


def firebase_item_sort_key(pair: tuple[Any, Any]) -> tuple[int, int | str]:
    key = pair[0]
    try:
        return (0, int(key))
    except (TypeError, ValueError):
        return (1, str(key))


def quantity_from_home_assistant_description(description: str) -> str:
    if not description:
        return ""
    match = re.search(
        r"(?:^|\b)menge\s*:\s*(-?\d+(?:[,.]\d+)?\s*[^,\n;]*)",
        description,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return match.group(1).strip().rstrip(",")


def split_home_assistant_shopping_item_name(name: str) -> list[str]:
    parts = [
        part.strip()
        for part in re.split(r"\s+und\s+", name, flags=re.IGNORECASE)
        if part.strip()
    ]
    return parts if len(parts) > 1 else [name]


def expand_home_assistant_items_for_firebase(
    items: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    expanded: dict[str, dict[str, str]] = {}
    for item in items.values():
        names = split_home_assistant_shopping_item_name(item["name"])
        for name in names:
            expanded[name.casefold()] = {
                **item,
                "name": name,
            }
    return expanded


def split_source_home_assistant_item_names(rows: list[dict[str, str]]) -> set[str]:
    names: set[str] = set()
    for row in rows:
        name = row.get("name", "").strip()
        if len(split_home_assistant_shopping_item_name(name)) > 1:
            names.add(name)
    return names


def split_quantity(quantity: str) -> tuple[Any, str]:
    quantity = quantity.strip()
    if not quantity:
        return 0, "null"
    match = re.match(r"^\s*(-?\d+(?:[,.]\d+)?)\s*(.*?)\s*$", quantity)
    if not match:
        return quantity, "null"
    number_text = match.group(1).replace(",", ".")
    unit = match.group(2).strip() or "Stück"
    try:
        number = float(number_text)
    except ValueError:
        return quantity, "null"
    count: Any = int(number) if number.is_integer() else number
    return count, unit


def build_firebase_item_from_ha_update(
    item_payload: Any,
    ha_status: str,
    ha_quantity: str,
) -> Any:
    if not isinstance(item_payload, dict):
        return item_payload
    updated_item = json.loads(json.dumps(item_payload))
    updated_item["strike"] = ha_status == "completed"
    if "checked" in updated_item:
        updated_item["checked"] = False
    count, unit = split_quantity(ha_quantity)
    updated_item["count"] = count
    updated_item["counttyp"] = unit
    return updated_item


def build_firebase_item_with_status(item_payload: Any, ha_status: str) -> Any:
    return build_firebase_item_from_ha_update(item_payload, ha_status, item_quantity(item_payload) if isinstance(item_payload, dict) else "")


def build_firebase_item_from_ha(
    name: str,
    item_key: str,
    list_payload: Any | None = None,
    quantity: str = "",
) -> dict[str, Any]:
    item_id = next_firebase_item_id(list_payload, item_key)

    if isinstance(list_payload, dict):
        candidates = find_item_container(list_payload)
        if isinstance(candidates, dict):
            for template in candidates.values():
                if not isinstance(template, dict):
                    continue
                new_item = json.loads(json.dumps(template))
                new_item["id"] = item_id
                new_item["name"] = name
                if "checked" in new_item:
                    new_item["checked"] = False
                if "strike" in new_item:
                    new_item["strike"] = False
                if "visible" in new_item:
                    new_item["visible"] = True
                if quantity:
                    count, unit = split_quantity(quantity)
                    new_item["count"] = count
                    new_item["counttyp"] = unit
                return new_item

    count, unit = split_quantity(quantity)
    return {
        "checked": False,
        "color": 0,
        "count": count,
        "counttyp": unit,
        "id": item_id,
        "name": name,
        "price": 0,
        "strike": False,
        "type": 0,
        "visible": True,
    }


def normalize_firebase_path(path: str) -> str:
    return "/" + path.strip("/")


def path_matches(path: str, expected_path: str) -> bool:
    return normalize_firebase_path(path) == normalize_firebase_path(expected_path)


def path_is_or_below(path: str, expected_path: str) -> bool:
    normalized_path = normalize_firebase_path(path)
    normalized_expected = normalize_firebase_path(expected_path)
    return normalized_path == normalized_expected or normalized_path.startswith(f"{normalized_expected}/")


def match_watched_list(path: str, path_to_list_name: dict[str, str]) -> str:
    normalized_path = normalize_firebase_path(path)
    for list_path, list_name in path_to_list_name.items():
        normalized_list_path = normalize_firebase_path(list_path)
        if normalized_path == normalized_list_path or normalized_path.startswith(f"{normalized_list_path}/"):
            return list_name
    return ""


def apply_firebase_update(current_payload: Any, path: str, data: Any, list_path: str) -> Any:
    path = normalize_firebase_path(path)
    list_path = normalize_firebase_path(list_path)
    if path == list_path:
        return data

    if current_payload is None:
        current_payload = {}
    if not isinstance(current_payload, dict):
        return current_payload

    relative_path = path[len(list_path):].strip("/")
    if not relative_path:
        return data

    target = current_payload
    parts = [part for part in relative_path.split("/") if part]
    for part in parts[:-1]:
        next_target = target.setdefault(part, {})
        if not isinstance(next_target, dict):
            next_target = {}
            target[part] = next_target
        target = next_target

    leaf = parts[-1]
    if data is None:
        target.pop(leaf, None)
    else:
        target[leaf] = data
    return current_payload


def send_ws(ws: Any, message: dict[str, Any]) -> None:
    ws.send(json.dumps(message, separators=(",", ":")))


def wait_for_request_ok(ws: Any, request_number: int, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        message = receive_ws_message(ws)
        body = message.get("d", {})
        if body.get("r") != request_number:
            continue

        payload = body.get("b", {})
        status = payload.get("s")
        if status == "ok":
            return
        raise FirebaseError(f"Firebase-Anfrage {request_number} fehlgeschlagen: {status}")

    raise FirebaseError(f"Zeitueberschreitung bei Firebase-Anfrage {request_number}.")


def wait_for_data(ws: Any, request_number: int, timeout_seconds: int) -> Any:
    deadline = time.monotonic() + timeout_seconds
    latest_data: Any = None
    query_acknowledged = False
    acknowledged_at: float | None = None
    empty_path_grace_seconds = min(2.0, max(0.5, timeout_seconds / 10))

    while time.monotonic() < deadline:
        try:
            message = receive_ws_message(ws)
        except Exception as exc:
            if "timed out" in str(exc).lower():
                break
            raise

        body = message.get("d", {})

        if body.get("r") == request_number:
            payload = body.get("b", {})
            status = payload.get("s")
            if status != "ok":
                raise FirebaseError(f"Listenabfrage fehlgeschlagen: {status}")
            query_acknowledged = True
            acknowledged_at = time.monotonic()
            deadline = min(deadline, acknowledged_at + empty_path_grace_seconds)
            try:
                ws.settimeout(empty_path_grace_seconds)
            except Exception:
                pass
            LOGGER.debug("Firebase hat die Listenabfrage bestaetigt.")
            if latest_data is not None:
                return latest_data
            continue

        if body.get("a") in {"d", "m"}:
            payload = body.get("b", {})
            if isinstance(payload, dict) and "d" in payload:
                latest_data = payload.get("d")
                if query_acknowledged:
                    return latest_data

    if query_acknowledged:
        raise FirebaseError(
            "Firebase hat die Anfrage bestaetigt, aber keine Daten fuer diesen Pfad geliefert. "
            "Der Pfad ist wahrscheinlich leer oder nicht vorhanden."
        )
    raise FirebaseError("Keine Antwort auf die Listenabfrage ueber den WebSocket empfangen.")


def receive_ws_message(ws: Any) -> dict[str, Any]:
    raw_message = ws.recv()
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError:
        LOGGER.debug("Ignoriere Firebase-WebSocket-Steuernachricht ohne JSON-Struktur.")
        return {}

    if not isinstance(message, dict):
        LOGGER.debug("Ignoriere Firebase-WebSocket-Steuernachricht ohne Objektstruktur.")
        return {}

    if message.get("t") == "c":
        LOGGER.debug("Ignoriere Firebase-WebSocket-Kontrollnachricht.")
        return {}

    return message


def extract_lists(lists_payload: Any) -> dict[str, list[str]]:
    if lists_payload is None:
        return {}
    if not isinstance(lists_payload, dict):
        raise FirebaseError("Der Firebase-Listenpfad enthaelt keine Listenstruktur.")

    result: dict[str, list[str]] = {}
    for list_name, list_payload in sorted(lists_payload.items(), key=lambda pair: str(pair[0]).lower()):
        if isinstance(list_name, str) and list_name.strip():
            result[list_name] = extract_items(list_payload)
    return result


def extract_items(list_payload: Any) -> list[str]:
    if list_payload is None:
        return []

    if isinstance(list_payload, list):
        return [item_text for item in list_payload if (item_text := format_item(item))]

    if isinstance(list_payload, dict):
        candidates = find_item_container(list_payload)
        if isinstance(candidates, dict):
            return [
                item_text
                for _, item in sorted(candidates.items(), key=lambda pair: str(pair[0]))
                if (item_text := format_item(item))
            ]
        if isinstance(candidates, list):
            return [item_text for item in candidates if (item_text := format_item(item))]

    item = format_item(list_payload)
    return [item] if item else []


def find_item_container(list_payload: dict[str, Any]) -> Any:
    for key in ("items", "entries", "products", "listItems", "list_items"):
        value = list_payload.get(key)
        if isinstance(value, (dict, list)):
            return value
    return list_payload


def format_item(item: Any) -> str:
    if item is None:
        return ""

    if isinstance(item, str):
        return item.strip()

    if isinstance(item, (int, float)):
        return str(item)

    if isinstance(item, dict):
        name = first_text_value(
            item,
            "name",
            "title",
            "text",
            "label",
            "value",
            "item",
            "product",
        )
        quantity = item_quantity(item)
        status = item_status(item)

        if not name:
            return ""

        details = []
        if quantity:
            details.append(f"Menge: {quantity}")
        if status:
            details.append(f"Status: {status}")

        return f"{name} ({', '.join(details)})" if details else name

    return ""


def item_quantity(item: dict[str, Any]) -> str:
    raw_count = item.get("count", item.get("quantity", item.get("qty", item.get("amount"))))
    if raw_count in (None, "", "null"):
        return ""

    try:
        count_number = float(raw_count)
    except (TypeError, ValueError):
        count_text = str(raw_count).strip()
    else:
        if count_number == 0:
            return ""
        count_text = str(int(count_number)) if count_number.is_integer() else str(count_number)

    unit = str(item.get("counttyp") or item.get("unit") or "").strip()
    if unit.lower() == "null":
        unit = ""
    return f"{count_text} {unit}".strip()


def item_status(item: dict[str, Any]) -> str:
    # In dieser Shopping-App markiert `strike: true` erledigte bzw. gestrichene Artikel.
    done_keys = (
        "strike",
        "striked",
        "checked",
        "done",
        "completed",
        "isChecked",
        "isDone",
        "isCompleted",
        "purchased",
        "isPurchased",
    )
    for key in done_keys:
        if key not in item:
            continue
        value = item.get(key)
        if isinstance(value, bool):
            return "erledigt" if value else "aktiv"
        if isinstance(value, (int, float)):
            return "erledigt" if value != 0 else "aktiv"
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "ja", "done", "completed", "checked", "striked", "strike", "1"}:
                return "erledigt"
            if lowered in {"false", "no", "nein", "open", "active", "0"}:
                return "aktiv"

    timestamp_keys = ("checkedAt", "completedAt", "doneAt", "purchasedAt")
    if any(item.get(key) for key in timestamp_keys):
        return "erledigt"

    LOGGER.debug("Keine bekannte Status-Spalte gefunden. Artikelfelder: %s", sorted(item.keys()))
    return "unbekannt"


def first_text_value(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def print_items(list_name: str, items: list[str]) -> None:
    print(f"Artikel in '{list_name}':")
    if not items:
        print("  Keine Artikel gefunden.")
        return

    for index, item in enumerate(items, start=1):
        print(f"  {index}. {item}")


def print_lists(lists: dict[str, list[str]]) -> None:
    if not lists:
        print("Keine Listen gefunden.")
        return

    print(f"Gefundene Listen: {len(lists)}")
    for list_name, items in lists.items():
        print()
        print_items(list_name, items)


def slugify_entity_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", ascii_text).strip("_").lower()
    return slug or "liste"


def build_sensor_entity_id(sensor_prefix: str, list_name: str) -> str:
    prefix = sensor_prefix.strip() or "sensor.shopping_liste_"
    if "." not in prefix:
        prefix = f"sensor.{prefix}"
    return f"{prefix}{slugify_entity_part(list_name)}"


def sync_sensor_to_home_assistant(
    home_assistant: HomeAssistantConfig, list_name: str, items: list[str]
) -> str:
    requests = require_module("requests", "requests")
    entity_id = build_sensor_entity_id(home_assistant.sensor_prefix, list_name)
    active_count = sum(1 for item in items if "Status: aktiv" in item)
    completed_count = sum(1 for item in items if "Status: erledigt" in item)
    unknown_count = len(items) - active_count - completed_count
    state = f"{active_count} aktiv"
    payload = {
        "state": state,
        "attributes": {
            "friendly_name": f"Shopping Liste {list_name}",
            "items": items,
            "active_count": active_count,
            "completed_count": completed_count,
            "unknown_count": unknown_count,
            "item_count": len(items),
            "source": "firebase_shopping_sync",
            "last_sync": datetime.now(timezone.utc).isoformat(),
        },
    }
    headers = {
        "Authorization": f"Bearer {home_assistant.token}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        f"{home_assistant.url}/api/states/{entity_id}",
        headers=headers,
        json=payload,
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        raise FirebaseError(
            f"Home-Assistant-Sensor konnte nicht geschrieben werden: HTTP {response.status_code}"
        )

    verify_response = requests.get(
        f"{home_assistant.url}/api/states/{entity_id}",
        headers={"Authorization": f"Bearer {home_assistant.token}"},
        timeout=20,
    )
    if verify_response.status_code != 200:
        raise FirebaseError(
            f"Home-Assistant-Sensor wurde geschrieben, konnte aber nicht gelesen werden: HTTP {verify_response.status_code}"
        )

    verify_payload = verify_response.json()
    if verify_payload.get("state") != state:
        raise FirebaseError(
            f"Home-Assistant-Sensor hat unerwarteten Zustand: {verify_payload.get('state')} statt {state}"
        )

    return entity_id


def get_home_assistant_entity_state(
    home_assistant: HomeAssistantConfig,
    entity_id: str,
) -> dict[str, Any] | None:
    requests = require_module("requests", "requests")
    response = requests.get(
        f"{home_assistant.url}/api/states/{entity_id}",
        headers={"Authorization": f"Bearer {home_assistant.token}"},
        timeout=20,
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise FirebaseError(
            f"Home-Assistant-Entity {entity_id} konnte nicht gelesen werden: HTTP {response.status_code}"
        )
    data = response.json()
    return data if isinstance(data, dict) else None


def get_home_assistant_entity_marker(
    home_assistant: HomeAssistantConfig,
    entity_id: str,
) -> str:
    state = get_home_assistant_entity_state(home_assistant, entity_id)
    if not state:
        LOGGER.info("Reset-Button nicht gefunden: %s", entity_id)
        return ""
    return "|".join(
        str(state.get(key, ""))
        for key in ("state", "last_changed", "last_updated")
    )


def reset_button_was_pressed(
    home_assistant: HomeAssistantConfig,
    entity_id: str,
    previous_marker: str,
) -> bool:
    if not previous_marker:
        return False
    current_marker = get_home_assistant_entity_marker(home_assistant, entity_id)
    return bool(current_marker and current_marker != previous_marker)


def write_home_assistant_state(
    home_assistant: HomeAssistantConfig,
    entity_id: str,
    state: str,
    attributes: dict[str, Any],
) -> None:
    requests = require_module("requests", "requests")
    response = requests.post(
        f"{home_assistant.url}/api/states/{entity_id}",
        headers={
            "Authorization": f"Bearer {home_assistant.token}",
            "Content-Type": "application/json",
        },
        json={"state": state, "attributes": attributes},
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        raise FirebaseError(
            f"Home-Assistant-Statussensor konnte nicht geschrieben werden: HTTP {response.status_code}"
        )


def write_shopping_sync_status(
    home_assistant: HomeAssistantConfig,
    entity_id: str = DEFAULT_STATUS_SENSOR,
    state: str = "online",
    watched_lists: list[str] | None = None,
    synced_todo_entities: set[str] | None = None,
    last_error: str = "",
    reconnect_count: int = 0,
    firebase_connected: bool = False,
    home_assistant_connected: bool = True,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    write_home_assistant_state(
        home_assistant,
        entity_id,
        state,
        {
            "friendly_name": "Shopping Sync Status",
            "last_seen": now,
            "last_sync": now if state == "online" else "",
            "watched_lists": list(watched_lists or []),
            "synced_todo_entities": sorted(synced_todo_entities or set()),
            "last_error": last_error,
            "reconnect_count": reconnect_count,
            "firebase_connected": firebase_connected,
            "home_assistant_connected": home_assistant_connected,
            "source": "firebase_shopping_sync",
        },
    )


def sync_lists_to_home_assistant(
    home_assistant: HomeAssistantConfig, lists: dict[str, list[str]]
) -> list[str]:
    return [
        sync_sensor_to_home_assistant(home_assistant, list_name, items)
        for list_name, items in lists.items()
    ]

def extract_todo_items(list_payload: Any) -> list[dict[str, str]]:
    if list_payload is None:
        return []

    if isinstance(list_payload, list):
        candidates = list_payload
    elif isinstance(list_payload, dict):
        candidates = find_item_container(list_payload)
    else:
        candidates = [list_payload]

    if isinstance(candidates, dict):
        iterable = [item for _, item in sorted(candidates.items(), key=lambda pair: str(pair[0]))]
    elif isinstance(candidates, list):
        iterable = candidates
    else:
        iterable = [candidates]

    todo_items: list[dict[str, str]] = []
    for item in iterable:
        todo_item = format_todo_item(item)
        if todo_item:
            todo_items.append(todo_item)
    return todo_items


def format_todo_item(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        name = item.strip()
        return {"name": name, "status": "needs_action", "description": ""} if name else None

    if not isinstance(item, dict):
        return None

    name = first_text_value(
        item,
        "name",
        "title",
        "text",
        "label",
        "value",
        "item",
        "product",
    )
    if not name:
        return None

    quantity = item_quantity(item)
    status = "completed" if item_status(item) == "erledigt" else "needs_action"
    description = f"Menge: {quantity}" if quantity else ""
    return {"name": name, "status": status, "description": description}


def get_home_assistant_todo_entities(home_assistant: HomeAssistantConfig) -> set[str]:
    requests = require_module("requests", "requests")
    response = requests.get(
        f"{home_assistant.url}/api/states",
        headers={"Authorization": f"Bearer {home_assistant.token}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise FirebaseError(f"Home-Assistant-Entities konnten nicht gelesen werden: HTTP {response.status_code}")
    return {
        state.get("entity_id")
        for state in response.json()
        if isinstance(state, dict) and str(state.get("entity_id", "")).startswith("todo.")
    }


def get_home_assistant_states(home_assistant: HomeAssistantConfig) -> list[dict[str, Any]]:
    requests = require_module("requests", "requests")
    response = requests.get(
        f"{home_assistant.url}/api/states",
        headers={"Authorization": f"Bearer {home_assistant.token}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise FirebaseError(f"Home-Assistant-States konnten nicht gelesen werden: HTTP {response.status_code}")
    states = response.json()
    return states if isinstance(states, list) else []


def build_home_assistant_watchdog_snapshot(states: list[dict[str, Any]]) -> dict[str, str]:
    watched_prefixes = ("todo.",)
    watched_entities = {
        "input_button.shopping_sync_now",
        "input_button.shopping_sync_jetzt_synchronisieren",
    }
    snapshot: dict[str, str] = {}
    for state in states:
        if not isinstance(state, dict):
            continue
        entity_id = str(state.get("entity_id", ""))
        if not entity_id:
            continue
        if not entity_id.startswith(watched_prefixes) and entity_id not in watched_entities:
            continue
        snapshot[entity_id] = "|".join(
            str(state.get(key, ""))
            for key in ("state", "last_changed", "last_updated")
        )
    return snapshot


def build_home_assistant_todo_content_snapshot(home_assistant: HomeAssistantConfig) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for entity_id in sorted(get_home_assistant_todo_entities(home_assistant)):
        rows = get_home_assistant_todo_item_rows(home_assistant, entity_id)
        normalized_rows = sorted(
            [
                {
                    "name": row.get("name", ""),
                    "status": row.get("status", ""),
                    "description": row.get("description", ""),
                    "quantity": row.get("quantity", ""),
                }
                for row in rows
            ],
            key=lambda row: (
                row["name"].casefold(),
                row["status"],
                row["description"],
                row["quantity"],
            ),
        )
        snapshot[f"{entity_id}:items"] = json.dumps(
            normalized_rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return snapshot


def build_home_assistant_watchdog_snapshot_from_content(
    home_assistant: HomeAssistantConfig,
    states: list[dict[str, Any]],
) -> dict[str, str]:
    snapshot = build_home_assistant_watchdog_snapshot(states)
    snapshot.update(build_home_assistant_todo_content_snapshot(home_assistant))
    return snapshot


def home_assistant_watchdog_enabled(states: list[dict[str, Any]]) -> bool:
    candidates = {
        "input_boolean.shopping_sync_auto_on_todo_change",
        "input_boolean.shopping_sync_bei_todo_aenderungen",
    }
    for state in states:
        if not isinstance(state, dict):
            continue
        if state.get("entity_id") in candidates:
            return state.get("state") == "on"
    return True


def match_todo_entity(home_assistant: HomeAssistantConfig, list_name: str, todo_entities: set[str]) -> str:
    expected = f"todo.{slugify_entity_part(list_name)}"
    return expected if expected in todo_entities else ""


def call_home_assistant_service(
    home_assistant: HomeAssistantConfig,
    domain: str,
    service: str,
    payload: dict[str, Any],
    return_response: bool = False,
) -> Any:
    requests = require_module("requests", "requests")
    suffix = "?return_response" if return_response else ""
    response = requests.post(
        f"{home_assistant.url}/api/services/{domain}/{service}{suffix}",
        headers={
            "Authorization": f"Bearer {home_assistant.token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        detail = response.text.strip()
        if len(detail) > 300:
            detail = detail[:300] + "..."
        suffix = f": {detail}" if detail else ""
        raise FirebaseError(
            f"Home-Assistant-Service {domain}.{service} fehlgeschlagen: HTTP {response.status_code}{suffix}"
        )
    if not response.text.strip():
        return None
    return response.json()


def get_home_assistant_todo_item_rows(home_assistant: HomeAssistantConfig, entity_id: str) -> list[dict[str, str]]:
    item_rows: list[dict[str, str]] = []
    for status in ("needs_action", "completed"):
        response = call_home_assistant_service(
            home_assistant,
            "todo",
            "get_items",
            {"entity_id": entity_id, "status": status},
            return_response=True,
        )
        service_response = (response or {}).get("service_response", {})
        items = service_response.get(entity_id, {}).get("items", [])
        for item in items:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or item.get("item") or "").strip()
            if summary:
                description = str(item.get("description") or "").strip()
                item_rows.append({
                    "name": summary,
                    "status": status,
                    "description": description,
                    "quantity": quantity_from_home_assistant_description(description),
                })
    return item_rows


def get_home_assistant_todo_items(home_assistant: HomeAssistantConfig, entity_id: str) -> dict[str, dict[str, str]]:
    return aggregate_home_assistant_todo_rows(
        get_home_assistant_todo_item_rows(home_assistant, entity_id)
    )


def aggregate_home_assistant_todo_rows(
    rows: list[dict[str, str]],
    merge_duplicate_quantities: bool = True,
) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["name"].casefold(), []).append(row)

    result: dict[str, dict[str, str]] = {}
    for key, group in grouped.items():
        name = group[0]["name"]
        status = "completed" if all(item.get("status") == "completed" for item in group) else "needs_action"
        if len(group) > 1 and not merge_duplicate_quantities:
            quantity = next((item.get("quantity", "") for item in group if item.get("quantity", "")), "")
        else:
            quantity = merged_home_assistant_quantity(group)
        result[key] = {
            "name": name,
            "status": status,
            "description": f"Menge: {quantity}" if quantity else "",
            "quantity": quantity,
        }
    return result


def duplicate_home_assistant_keys(rows: list[dict[str, str]]) -> set[str]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row["name"].casefold()
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def merged_home_assistant_quantity(rows: list[dict[str, str]]) -> str:
    if len(rows) == 1:
        return rows[0].get("quantity", "")

    unit = "null"
    total = 0.0
    for row in rows:
        quantity = row.get("quantity", "")
        count, row_unit = split_quantity(quantity)
        if row_unit != "null":
            unit = str(row_unit)
        if quantity:
            try:
                total += float(str(count).replace(",", "."))
            except (TypeError, ValueError):
                total += 1
        else:
            total += 1

    count_text = str(int(total)) if total.is_integer() else str(total)
    return f"{count_text} {unit}".strip() if unit != "null" else count_text


def remove_home_assistant_todo_item(
    home_assistant: HomeAssistantConfig,
    entity_id: str,
    item_name: str,
) -> bool:
    try:
        call_home_assistant_service(
            home_assistant,
            "todo",
            "remove_item",
            {"entity_id": entity_id, "item": item_name},
        )
        return True
    except FirebaseError as exc:
        LOGGER.warning("Todo-Eintrag konnte nicht entfernt werden: %s", exc)
        return False


def sync_list_to_home_assistant_todo(
    home_assistant: HomeAssistantConfig,
    list_name: str,
    list_payload: Any,
    todo_entities: set[str],
    prune_todo: bool = False,
) -> str:
    entity_id = match_todo_entity(home_assistant, list_name, todo_entities)
    if not entity_id:
        return ""

    desired_items = extract_todo_items(list_payload)
    desired_keys = {item["name"].casefold() for item in desired_items}
    desired_by_key = {item["name"].casefold(): item for item in desired_items}
    existing_rows = get_home_assistant_todo_item_rows(home_assistant, entity_id)
    split_source_keys: set[str] = set()
    for row in existing_rows:
        source_name = row["name"]
        source_parts = split_home_assistant_shopping_item_name(source_name)
        if len(source_parts) <= 1:
            continue
        if all(part.casefold() in desired_keys for part in source_parts):
            if remove_home_assistant_todo_item(home_assistant, entity_id, source_name):
                split_source_keys.add(source_name.casefold())
                LOGGER.info("HA-Eintrag aufgeteilt und entfernt: %s / %s", entity_id, source_name)

    duplicate_keys = duplicate_home_assistant_keys(existing_rows)
    unresolved_duplicate_keys: set[str] = set()
    for key in duplicate_keys:
        if key not in desired_by_key:
            continue
        removed_all = True
        for item in [item for item in existing_rows if item["name"].casefold() == key]:
            removed_all = remove_home_assistant_todo_item(home_assistant, entity_id, item["name"]) and removed_all
        if not removed_all:
            unresolved_duplicate_keys.add(key)
            LOGGER.warning(
                "HA-Dubletten fuer %s / %s konnten nicht vollstaendig bereinigt werden; "
                "es wird kein weiterer gleichnamiger Todo-Eintrag angelegt.",
                entity_id,
                desired_by_key[key]["name"],
            )

    existing_items = aggregate_home_assistant_todo_rows(
        [
            item
            for item in existing_rows
            if item["name"].casefold() not in split_source_keys
            and (
                item["name"].casefold() not in duplicate_keys
                or item["name"].casefold() in unresolved_duplicate_keys
            )
        ],
        merge_duplicate_quantities=True,
    )

    for item in desired_items:
        key = item["name"].casefold()
        if key in unresolved_duplicate_keys:
            continue
        desired_status = item["status"]
        if key not in existing_items:
            payload: dict[str, Any] = {"entity_id": entity_id, "item": item["name"]}
            if item["description"]:
                payload["description"] = item["description"]
            call_home_assistant_service(home_assistant, "todo", "add_item", payload)
            existing_items[key] = {
                "name": item["name"],
                "status": "needs_action",
                "description": item["description"],
            }

        update_payload: dict[str, Any] = {"entity_id": entity_id, "item": item["name"]}
        needs_update = False
        if existing_items.get(key, {}).get("status") != desired_status:
            update_payload["status"] = desired_status
            needs_update = True
        if existing_items.get(key, {}).get("description", "") != item["description"]:
            update_payload["description"] = item["description"]
            needs_update = True

        if needs_update:
            try:
                call_home_assistant_service(
                    home_assistant,
                    "todo",
                    "update_item",
                    update_payload,
                )
            except FirebaseError as exc:
                LOGGER.warning("Todo-Eintrag konnte nicht aktualisiert werden: %s", exc)
                continue
            existing_items[key] = {
                "name": item["name"],
                "status": desired_status,
                "description": item["description"],
            }

    if prune_todo:
        for key, existing_item in list(existing_items.items()):
            if key in desired_keys:
                continue
            remove_home_assistant_todo_item(home_assistant, entity_id, existing_item["name"])

    return entity_id


def sync_lists_to_home_assistant_todos(
    home_assistant: HomeAssistantConfig,
    raw_lists: dict[str, Any],
    prune_todo: bool = False,
) -> list[str]:
    todo_entities = get_home_assistant_todo_entities(home_assistant)
    synced: list[str] = []
    missing: list[str] = []
    for list_name, list_payload in raw_lists.items():
        entity_id = sync_list_to_home_assistant_todo(
            home_assistant,
            list_name,
            list_payload,
            todo_entities,
            prune_todo=prune_todo,
        )
        if entity_id:
            synced.append(entity_id)
        else:
            missing.append(list_name)
    if missing:
        LOGGER.info("Keine gleichnamige HA-Todo-Liste fuer: %s", ", ".join(missing))
    return synced


def sync_home_assistant_changes_to_firebase_once(
    config: AppConfig,
    session: FirebaseSession,
    raw_lists: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    if config.home_assistant is None:
        return raw_lists, 0

    todo_entities = get_home_assistant_todo_entities(config.home_assistant)
    updates: list[tuple[str, Any]] = []
    ha_split_removals: list[tuple[str, str]] = []
    changed_count = 0

    for list_name, list_payload in raw_lists.items():
        entity_id = match_todo_entity(config.home_assistant, list_name, todo_entities)
        if not entity_id:
            continue

        list_path = build_list_path(session.uid, list_name)
        firebase_items = firebase_items_by_name(list_payload)
        firebase_by_key = {item["name"].casefold(): key for key, item in firebase_items.items()}
        ha_rows = get_home_assistant_todo_item_rows(config.home_assistant, entity_id)
        split_source_names = split_source_home_assistant_item_names(ha_rows)
        ha_duplicate_keys = duplicate_home_assistant_keys(ha_rows)
        if ha_duplicate_keys:
            LOGGER.warning(
                "HA-Dubletten erkannt in %s: %s. Dubletten werden nicht als Mengen nach Firebase geschrieben.",
                entity_id,
                ", ".join(sorted(ha_duplicate_keys)),
            )
        ha_items = aggregate_home_assistant_todo_rows(
            ha_rows,
            merge_duplicate_quantities=True,
        )
        ha_items = expand_home_assistant_items_for_firebase(ha_items)

        removed_keys = [
            item_key
            for item_key, item in firebase_items.items()
            if item["name"].casefold() not in ha_items
        ]
        if removed_keys:
            list_payload = compact_firebase_list_without_keys(list_payload, removed_keys)
            raw_lists[list_name] = list_payload
            updates.append((list_path, list_payload))
            changed_count += len(removed_keys)
            firebase_items = firebase_items_by_name(list_payload)
            firebase_by_key = {item["name"].casefold(): key for key, item in firebase_items.items()}

        for ha_key, ha_item in ha_items.items():
            item_key = firebase_by_key.get(ha_key)
            if item_key is None:
                item_key = next_firebase_item_key(list_payload)
                updated_item = build_firebase_item_from_ha(
                    ha_item["name"],
                    item_key,
                    list_payload,
                    ha_item.get("quantity", ""),
                )
            else:
                if ha_key in ha_duplicate_keys:
                    continue
                firebase_item = firebase_items[item_key]
                if (
                    firebase_item.get("status") == ha_item.get("status")
                    and firebase_item.get("quantity", "") == ha_item.get("quantity", "")
                    and not firebase_quantity_unit_needs_normalization(firebase_item.get("payload"))
                ):
                    continue
                updated_item = build_firebase_item_from_ha_update(
                    firebase_item.get("payload"),
                    ha_item.get("status", "needs_action"),
                    ha_item.get("quantity", ""),
                )

            item_path = firebase_item_update_path(list_path, list_payload, item_key)
            updates.append((item_path, updated_item))
            list_payload = apply_firebase_update(list_payload, item_path, updated_item, list_path)
            raw_lists[list_name] = list_payload
            firebase_items = firebase_items_by_name(list_payload)
            firebase_by_key = {item["name"].casefold(): key for key, item in firebase_items.items()}
            changed_count += 1

        for source_name in sorted(split_source_names):
            source_parts = split_home_assistant_shopping_item_name(source_name)
            if all(part.casefold() in firebase_by_key for part in source_parts):
                ha_split_removals.append((entity_id, source_name))

    send_firebase_puts_via_websocket(config, session, updates)
    for entity_id, source_name in ha_split_removals:
        if remove_home_assistant_todo_item(config.home_assistant, entity_id, source_name):
            LOGGER.info("HA-Eintrag aufgeteilt und entfernt: %s / %s", entity_id, source_name)
    return raw_lists, changed_count


def perform_on_demand_sync(
    config: AppConfig,
    status_entity_id: str = DEFAULT_STATUS_SENSOR,
    prune_todo: bool = True,
    sync_back: bool = False,
) -> dict[str, Any]:
    if config.home_assistant is None:
        raise ConfigError("In der Konfiguration fehlt der Abschnitt home_assistant.")

    write_shopping_sync_status(
        config.home_assistant,
        status_entity_id,
        "syncing",
        firebase_connected=False,
        home_assistant_connected=True,
    )
    synced_todo_entities: set[str] = set()
    try:
        session = sign_in(config.firebase)
        raw_lists = fetch_all_raw_lists_via_websocket(config, session)
        firebase_change_count = 0
        if sync_back:
            raw_lists, firebase_change_count = sync_home_assistant_changes_to_firebase_once(
                config,
                session,
                raw_lists,
            )
        synced_todo_entities = set(
            sync_lists_to_home_assistant_todos(
                config.home_assistant,
                raw_lists,
                prune_todo=prune_todo,
            )
        )
        write_shopping_sync_status(
            config.home_assistant,
            status_entity_id,
            "idle",
            watched_lists=sorted(raw_lists),
            synced_todo_entities=synced_todo_entities,
            firebase_connected=False,
            home_assistant_connected=True,
        )
        return {
            "message": (
                f"{len(raw_lists)} Listen gelesen, "
                f"{firebase_change_count} App-Aenderungen geschrieben, "
                f"{len(synced_todo_entities)} Todo-Listen aktualisiert."
            ),
            "list_count": len(raw_lists),
            "firebase_change_count": firebase_change_count,
            "synced_todo_entities": sorted(synced_todo_entities),
        }
    except Exception as exc:
        write_shopping_sync_status(
            config.home_assistant,
            status_entity_id,
            "error",
            synced_todo_entities=synced_todo_entities,
            last_error=str(exc),
            firebase_connected=False,
            home_assistant_connected=True,
        )
        raise


def append_admin_live_event(server: Any, event: dict[str, Any]) -> None:
    event.setdefault("time", datetime.now(timezone.utc).isoformat())
    with server.live_log_lock:
        server.live_log.append(event)


def summarize_home_assistant_event(message: dict[str, Any]) -> dict[str, Any] | None:
    event = message.get("event", {})
    if not isinstance(event, dict):
        return None
    event_type = str(event.get("event_type", ""))
    data = event.get("data", {})
    if not isinstance(data, dict):
        return None

    if event_type == "state_changed":
        entity_id = str(data.get("entity_id", ""))
        if not entity_id.startswith("todo.") and entity_id != DEFAULT_STATUS_SENSOR:
            return None
        old_state = data.get("old_state") or {}
        new_state = data.get("new_state") or {}
        old_value = old_state.get("state", "") if isinstance(old_state, dict) else ""
        new_value = new_state.get("state", "") if isinstance(new_state, dict) else ""
        return {
            "kind": "state_changed",
            "summary": f"{entity_id}: {old_value} -> {new_value}",
            "entity_id": entity_id,
            "old_state": old_value,
            "new_state": new_value,
        }

    if event_type == "call_service":
        domain = str(data.get("domain", ""))
        service = str(data.get("service", ""))
        service_data = data.get("service_data", {})
        entity_id = ""
        if isinstance(service_data, dict):
            entity_id_value = service_data.get("entity_id", "")
            if isinstance(entity_id_value, list):
                entity_id = ", ".join(str(item) for item in entity_id_value)
            else:
                entity_id = str(entity_id_value or "")
            item_name = str(service_data.get("item") or service_data.get("summary") or "").strip()
        else:
            item_name = ""
        is_todo_event = domain == "todo" and (
            service in {"add_item", "update_item", "remove_item"}
            or entity_id.startswith("todo.")
        )
        if not is_todo_event:
            return None
        return {
            "kind": "call_service",
            "summary": f"{domain}.{service}: {entity_id}".strip(),
            "domain": domain,
            "service": service,
            "entity_id": entity_id,
            "item": item_name,
        }

    return None


def is_live_event_sync_trigger(event: dict[str, Any]) -> bool:
    if event.get("kind") == "state_changed":
        return str(event.get("entity_id", "")).startswith("todo.")
    if event.get("kind") != "call_service":
        return False
    return event.get("domain") == "todo" and event.get("service") in {
        "add_item",
        "update_item",
        "remove_item",
    }


def todo_entities_from_live_event(event: dict[str, Any]) -> set[str]:
    entity_id = str(event.get("entity_id", ""))
    if not entity_id:
        return set()
    return {
        part.strip()
        for part in entity_id.split(",")
        if part.strip().startswith("todo.")
    }


def removed_todo_item_names_from_live_event(event: dict[str, Any]) -> dict[str, set[str]]:
    if event.get("kind") != "call_service" or event.get("service") != "remove_item":
        return {}
    item_name = str(event.get("item", "")).strip()
    if not item_name:
        return {}
    item_names = {
        name.casefold()
        for name in split_home_assistant_shopping_item_name(item_name)
    }
    return {
        entity_id: item_names
        for entity_id in todo_entities_from_live_event(event)
    }


def start_triggered_firebase_window(server: Any, event: dict[str, Any]) -> None:
    if not is_live_event_sync_trigger(event):
        return
    burst_seconds = server.shopping_sync_config.runtime.ha_realtime_burst_seconds
    if burst_seconds <= 0:
        append_admin_live_event(
            server,
            {"kind": "sync_trigger", "summary": "Firebase-Echtzeitfenster ist deaktiviert."},
        )
        return
    trigger_entities = todo_entities_from_live_event(event)
    trigger_key = ",".join(sorted(trigger_entities)) or str(event.get("summary", ""))
    now = time.monotonic()
    with server.sync_lock:
        last_trigger_times = getattr(server, "last_trigger_times", {})
        cooldown_seconds = getattr(server, "trigger_cooldown_seconds", 30)
        last_trigger_at = last_trigger_times.get(trigger_key)
        if last_trigger_at is not None and now - last_trigger_at < cooldown_seconds:
            append_admin_live_event(
                server,
                {
                    "kind": "sync_trigger",
                    "summary": (
                        "Trigger ignoriert, weil fuer diese Liste gerade erst ein "
                        "Firebase-Echtzeitfenster lief: " + trigger_key
                    ),
                },
            )
            return
        if server.sync_running:
            append_admin_live_event(
                server,
                {"kind": "sync_trigger", "summary": "Firebase-Echtzeitfenster laeuft bereits."},
            )
            return
        server.sync_running = True
        server.last_sync_result = None
        server.last_sync_error = ""
        last_trigger_times[trigger_key] = now
        server.last_trigger_times = last_trigger_times

    thread = threading.Thread(
        target=run_triggered_firebase_window,
        args=(server, event, burst_seconds),
        name="shopping-sync-triggered-firebase-window",
        daemon=True,
    )
    thread.start()


def run_triggered_firebase_window(server: Any, event: dict[str, Any], burst_seconds: int) -> None:
    changed_todo_entities = todo_entities_from_live_event(event)
    removed_todo_item_names = removed_todo_item_names_from_live_event(event)
    append_admin_live_event(
        server,
        {
            "kind": "sync_trigger",
            "summary": (
                f"Firebase-Echtzeitfenster fuer {burst_seconds} Sekunden gestartet: "
                f"{event.get('summary', '')}"
            ),
        },
    )
    if changed_todo_entities:
        append_admin_live_event(
            server,
            {
                "kind": "sync_trigger",
                "summary": "Trigger-Merge aktiv fuer: " + ", ".join(sorted(changed_todo_entities)),
            },
        )
    if removed_todo_item_names:
        removed_parts = [
            f"{entity_id}: {', '.join(sorted(names))}"
            for entity_id, names in sorted(removed_todo_item_names.items())
        ]
        append_admin_live_event(
            server,
            {
                "kind": "sync_trigger",
                "summary": "Gezielte HA-Loeschung nach Firebase erlaubt fuer: " + "; ".join(removed_parts),
            },
        )
    try:
        session = sign_in(server.shopping_sync_config.firebase)
        watch_lists_via_websocket_once(
            server.shopping_sync_config,
            session,
            sync_todo=True,
            prune_todo=True,
            sync_back=True,
            ha_poll_seconds=1,
            status_entity_id=server.status_entity_id,
            max_runtime_seconds=burst_seconds,
            changed_todo_entities=changed_todo_entities,
            removed_todo_item_names=removed_todo_item_names,
        )
        if server.shopping_sync_config.home_assistant is not None:
            write_shopping_sync_status(
                server.shopping_sync_config.home_assistant,
                server.status_entity_id,
                "idle",
                firebase_connected=False,
                home_assistant_connected=True,
            )
        result = {
            "message": f"Firebase-Echtzeitfenster nach HA-Trigger fuer {burst_seconds} Sekunden abgeschlossen.",
            "trigger": event.get("summary", ""),
        }
        with server.sync_lock:
            server.last_sync_result = result
            server.last_sync_error = ""
        append_admin_live_event(server, {"kind": "sync_trigger", "summary": result["message"]})
    except Exception as exc:
        LOGGER.exception("Firebase-Echtzeitfenster nach Home-Assistant-Trigger fehlgeschlagen.")
        with server.sync_lock:
            server.last_sync_error = str(exc)
        append_admin_live_event(
            server,
            {"kind": "sync_trigger", "summary": f"Firebase-Echtzeitfenster fehlgeschlagen: {exc}"},
        )
    finally:
        with server.sync_lock:
            server.sync_running = False


def run_home_assistant_event_monitor(server: Any) -> None:
    config = server.shopping_sync_config
    if config.home_assistant is None:
        return

    websocket = require_module("websocket", "websocket-client")
    parsed = urlparse(config.home_assistant.url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = f"{scheme}://{parsed.netloc}/api/websocket"

    while True:
        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=30)
            auth_required = json.loads(ws.recv())
            if auth_required.get("type") != "auth_required":
                raise FirebaseError("Home-Assistant-WebSocket erwartet keine Authentifizierung.")
            ws.send(json.dumps({"type": "auth", "access_token": config.home_assistant.token}))
            auth_ok = json.loads(ws.recv())
            if auth_ok.get("type") != "auth_ok":
                raise FirebaseError("Home-Assistant-WebSocket-Authentifizierung fehlgeschlagen.")

            for request in (
                {"id": 1, "type": "subscribe_events", "event_type": "state_changed"},
                {"id": 2, "type": "subscribe_events", "event_type": "call_service"},
            ):
                ws.send(json.dumps(request))
                result = json.loads(ws.recv())
                if result.get("type") == "result" and result.get("success") is False:
                    raise FirebaseError(f"Home-Assistant-Event-Abo fehlgeschlagen: {result.get('error')}")

            with server.live_log_lock:
                server.live_monitor_connected = True
                server.live_monitor_error = ""
            append_admin_live_event(server, {"kind": "monitor", "summary": "Home-Assistant-Event-Monitor verbunden."})

            while True:
                event = summarize_home_assistant_event(json.loads(ws.recv()))
                if event:
                    append_admin_live_event(server, event)
                    start_triggered_firebase_window(server, event)
        except Exception as exc:
            with server.live_log_lock:
                server.live_monitor_connected = False
                server.live_monitor_error = str(exc)
            LOGGER.warning("Home-Assistant-Event-Monitor getrennt: %s", exc)
            try:
                append_admin_live_event(server, {"kind": "monitor", "summary": f"Home-Assistant-Event-Monitor getrennt: {exc}"})
            except Exception:
                pass
            time.sleep(5)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass


SHOPPING_SYNC_ADMIN_HTML = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Shopping Sync</title>
  <style>
    :root { color-scheme: light dark; font-family: Segoe UI, Arial, sans-serif; }
    body { margin: 0; background: #f5f7f9; color: #1f2933; }
    main { max-width: 1120px; margin: 0 auto; padding: 22px; }
    h1 { font-size: 26px; margin: 0 0 16px; }
    h2 { font-size: 17px; margin: 0 0 12px; }
    section { background: #fff; border: 1px solid #d8e0e8; border-radius: 8px; padding: 16px; margin-bottom: 14px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
    .tile { border: 1px solid #d8e0e8; border-radius: 6px; padding: 12px; background: #f9fbfd; }
    .label { color: #596673; font-size: 12px; margin-bottom: 4px; }
    .value { font-size: 16px; font-weight: 600; word-break: break-word; }
    textarea { width: 100%; min-height: 390px; box-sizing: border-box; border: 1px solid #b8c4d0; border-radius: 6px; padding: 10px; font: 13px Consolas, monospace; resize: vertical; }
    button { border: 0; border-radius: 6px; background: #2563eb; color: white; padding: 10px 14px; font: inherit; cursor: pointer; }
    button.secondary { background: #52606d; }
    button.danger { background: #b42318; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .status { padding: 10px 12px; border-radius: 6px; background: #ecfdf5; border: 1px solid #bbf7d0; }
    .status.warn { background: #fff7ed; border-color: #fed7aa; }
    .status.error { background: #fef2f2; border-color: #fecaca; }
    pre { white-space: pre-wrap; word-break: break-word; background: #f8fafc; border: 1px solid #d8e0e8; border-radius: 6px; padding: 12px; max-height: 280px; overflow: auto; }
    #message { min-height: 22px; }
    @media (prefers-color-scheme: dark) {
      body { background: #11161c; color: #e6edf3; }
      section, textarea { background: #171d24; color: #e6edf3; border-color: #344250; }
      .tile, pre { background: #111820; border-color: #344250; }
      .label { color: #aab6c2; }
      .status { background: #133226; border-color: #246b4a; }
      .status.warn { background: #332414; border-color: #7a4b18; }
      .status.error { background: #371818; border-color: #7a3030; }
    }
  </style>
</head>
<body>
<main>
  <h1>Shopping Sync</h1>
  <section>
    <h2>Status</h2>
    <div id="statusBox" class="status">Lade Status...</div>
    <div class="grid" style="margin-top:12px">
      <div class="tile"><div class="label">Firebase</div><div id="firebase" class="value">-</div></div>
      <div class="tile"><div class="label">Home Assistant</div><div id="homeAssistant" class="value">-</div></div>
      <div class="tile"><div class="label">Beobachtete Listen</div><div id="watchedLists" class="value">-</div></div>
      <div class="tile"><div class="label">Todo-Listen</div><div id="todoEntities" class="value">-</div></div>
      <div class="tile"><div class="label">Letzter Kontakt</div><div id="lastSeen" class="value">-</div></div>
      <div class="tile"><div class="label">Neuverbunden</div><div id="reconnectCount" class="value">-</div></div>
    </div>
  </section>
  <section>
    <div class="actions">
      <h2 style="margin-right:auto">Konfiguration</h2>
      <button class="secondary" onclick="loadAll()">Neu einlesen</button>
      <button onclick="runSync()">Jetzt synchronisieren</button>
      <button onclick="saveConfig()">Speichern</button>
      <button class="danger" onclick="restartService()">Dienst neu starten</button>
    </div>
    <p id="configPath"></p>
    <textarea id="configJson" spellcheck="false"></textarea>
    <p id="message"></p>
  </section>
  <section>
    <h2>Diagnose</h2>
    <pre id="details">Noch keine Daten.</pre>
  </section>
</main>
<script>
async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.status === 'error') {
    throw new Error(data.message || `HTTP ${response.status}`);
  }
  return data;
}

async function loadAll() {
  await loadConfig();
  await loadStatus();
}

async function loadConfig() {
  const data = await requestJson('/admin/api/config');
  document.getElementById('configPath').textContent = data.config_path || '';
  document.getElementById('configJson').value = JSON.stringify(data.config || {}, null, 2);
}

async function loadStatus() {
  const data = await requestJson('/admin/api/status');
  const sensor = data.status_sensor || {};
  const attrs = sensor.attributes || {};
  const state = sensor.state || 'unbekannt';
  const box = document.getElementById('statusBox');
  box.className = state === 'online' ? 'status' : (state === 'error' ? 'status error' : 'status warn');
  box.textContent = `Status: ${state}`;
  document.getElementById('firebase').textContent = attrs.firebase_connected ? 'verbunden' : 'nicht verbunden';
  document.getElementById('homeAssistant').textContent = attrs.home_assistant_connected ? 'verbunden' : 'nicht verbunden';
  document.getElementById('watchedLists').textContent = (attrs.watched_lists || []).join(', ') || 'keine';
  document.getElementById('todoEntities').textContent = (attrs.synced_todo_entities || []).join(', ') || 'keine';
  document.getElementById('lastSeen').textContent = attrs.last_seen || '-';
  document.getElementById('reconnectCount').textContent = attrs.reconnect_count ?? '-';
  document.getElementById('details').textContent = JSON.stringify(data, null, 2);
}

async function saveConfig() {
  const message = document.getElementById('message');
  try {
    const config = JSON.parse(document.getElementById('configJson').value || '{}');
    const data = await requestJson('/admin/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({config}),
    });
    message.textContent = data.message || 'Gespeichert.';
  } catch (error) {
    message.textContent = error.message;
  }
}

async function restartService() {
  const message = document.getElementById('message');
  if (!confirm('Shopping Sync wirklich neu starten?')) return;
  try {
    const data = await requestJson('/admin/api/restart', {method: 'POST'});
    message.textContent = data.message || 'Neustart ausgeloest.';
  } catch (error) {
    message.textContent = error.message;
  }
}

async function runSync() {
  const message = document.getElementById('message');
  try {
    message.textContent = 'Synchronisation laeuft...';
    const data = await requestJson('/admin/api/sync', {method: 'POST'});
    message.textContent = data.message || 'Synchronisation abgeschlossen.';
    await loadStatus();
  } catch (error) {
    message.textContent = error.message;
  }
}

loadAll();
setInterval(loadStatus, 5000);
</script>
</body>
</html>"""


class ShoppingSyncAdminHandler(BaseHTTPRequestHandler):
    server_version = "ShoppingSyncAdmin/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.debug("Admin UI: " + format, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            self.handle_standard_api("GET", parsed.path)
            return
        if parsed.path in {"/", "/admin"}:
            self.write_html(SHOPPING_SYNC_ADMIN_HTML)
            return
        if parsed.path == "/admin/api/status":
            self.write_json(self.admin_status())
            return
        if parsed.path == "/admin/api/config":
            self.write_json(self.admin_config())
            return
        if parsed.path == "/health":
            self.write_json({"status": "ok", "service": "shopping-sync"})
            return
        self.write_json({"status": "error", "message": "Nicht gefunden."}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            self.handle_standard_api("POST", parsed.path)
            return
        if parsed.path == "/admin/api/config":
            self.save_config()
            return
        if parsed.path == "/admin/api/restart":
            self.restart_service()
            return
        if parsed.path == "/admin/api/sync":
            self.run_sync()
            return
        self.write_json({"status": "error", "message": "Nicht gefunden."}, status=404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/"):
            self.handle_standard_api("PUT", parsed.path)
            return
        self.write_json({"status": "error", "message": "Nicht gefunden."}, status=404)

    @property
    def admin_server(self) -> Any:
        return self.server

    def admin_status(self) -> dict[str, Any]:
        config = self.admin_server.shopping_sync_config
        status_entity_id = self.admin_server.status_entity_id
        status_sensor = None
        if config.home_assistant is not None:
            try:
                status_sensor = get_home_assistant_entity_state(config.home_assistant, status_entity_id)
            except Exception as exc:
                return {
                    "status": "ok",
                    "status_sensor": {"state": "error", "attributes": {"last_error": str(exc)}},
                    "config_path": str(self.admin_server.config_path),
                }
        return {
            "status": "ok",
            "status_sensor": status_sensor or {"state": "unbekannt", "attributes": {}},
            "config_path": str(self.admin_server.config_path),
            "list_name": config.list_name,
            "list_names": config.list_names or [],
            "status_entity_id": status_entity_id,
            "admin_public_url": config.admin.public_url,
            "sync_running": self.admin_server.sync_running,
            "last_sync_result": self.admin_server.last_sync_result,
            "last_sync_error": self.admin_server.last_sync_error,
        }

    def admin_config(self) -> dict[str, Any]:
        config_path = self.admin_server.config_path
        try:
            config = read_config_file(config_path)
        except Exception as exc:
            return {"status": "error", "message": str(exc), "config_path": str(config_path)}
        return {"status": "ok", "config": config, "config_path": str(config_path)}

    def handle_standard_api(self, method: str, path: str) -> None:
        route = path.removeprefix("/api/v1")
        try:
            if method == "GET" and route == "/manifest":
                self.write_json(self.api_manifest())
                return
            if method == "GET" and route == "/health":
                self.write_json(self.api_health())
                return
            if method == "GET" and route == "/status":
                self.write_json(self.api_status())
                return
            if method == "GET" and route == "/config":
                self.require_api_auth()
                self.write_json(self.api_config())
                return
            if method == "PUT" and route == "/config":
                self.require_api_auth()
                self.api_save_config()
                return
            if method == "POST" and route == "/reload":
                self.require_api_auth()
                self.admin_server.shopping_sync_config = load_config(self.admin_server.config_path)
                self.write_json({"ok": True, "message": "Konfiguration neu geladen."})
                return
            if method == "POST" and route.startswith("/actions/"):
                self.require_api_auth()
                self.api_action(route.rsplit("/", 1)[-1])
                return
            if method == "GET" and route == "/logs/recent":
                self.write_json(self.api_recent_logs())
                return
            if method == "POST" and route == "/logs/clear":
                self.require_api_auth()
                self.api_clear_logs()
                return
            self.write_json({"ok": False, "error": "not_found"}, status=404)
        except PermissionError as exc:
            self.write_json({"ok": False, "error": str(exc)}, status=401)
        except Exception as exc:
            LOGGER.exception("Standard-API fehlgeschlagen.")
            self.write_json({"ok": False, "error": str(exc)}, status=500)

    def require_api_auth(self) -> None:
        token = self.admin_server.shopping_sync_config.admin.api_token
        if not token:
            return
        header = self.headers.get("Authorization", "")
        if header != f"Bearer {token}":
            raise PermissionError("ungueltiger API-Token")

    def api_manifest(self) -> dict[str, Any]:
        return {
            "ok": True,
            "tool_id": TOOL_ID,
            "name": TOOL_NAME,
            "version": TOOL_VERSION,
            "tool_version": TOOL_VERSION,
            "api_version": API_VERSION,
            "config_schema_version": CONFIG_SCHEMA_VERSION,
            "capabilities": ["config", "status", "actions", "recent_logs", "home_assistant_todo_sync"],
            "security": {
                "mode": "token" if self.admin_server.shopping_sync_config.admin.api_token else "local_setup_no_token",
                "token_required": bool(self.admin_server.shopping_sync_config.admin.api_token),
            },
            "actions": [
                {"id": "test_connection", "title": "Verbindung testen", "critical": False},
                {"id": "sync_now", "title": "Jetzt synchronisieren", "critical": False},
                {"id": "reload", "title": "Konfiguration neu laden", "critical": False},
                {"id": "restart", "title": "Dienst neu starten", "critical": True},
                {"id": "shutdown", "title": "Dienst beenden", "critical": True},
            ],
            "status_fields": ["state", "last_seen", "last_sync", "watched_lists", "synced_todo_entities", "last_error"],
            "config_schema": {
                "sections": ["firebase", "websocket", "runtime", "admin", "home_assistant"],
                "secret_fields": sorted(SECRET_KEYS),
            },
        }

    def api_health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "tool_id": TOOL_ID,
            "status": "ok",
            "time": datetime.now(timezone.utc).isoformat(),
        }

    def api_status(self) -> dict[str, Any]:
        status = self.admin_status()
        return {
            "ok": True,
            "tool_id": TOOL_ID,
            "sync_running": status.get("sync_running", False),
            "last_sync_result": status.get("last_sync_result"),
            "last_sync_error": status.get("last_sync_error", ""),
            "status_sensor": status.get("status_sensor"),
            "config_path": status.get("config_path"),
            "list_name": status.get("list_name"),
            "list_names": status.get("list_names", []),
            "status_entity_id": status.get("status_entity_id"),
            "admin_public_url": status.get("admin_public_url"),
            "live_monitor": {
                "connected": getattr(self.admin_server, "live_monitor_connected", False),
                "error": getattr(self.admin_server, "live_monitor_error", ""),
            },
        }

    def api_config(self) -> dict[str, Any]:
        config_path = self.admin_server.config_path
        config = read_config_file(config_path)
        return {
            "ok": True,
            "config": redact_config_value(config),
            "config_path": str(config_path),
        }

    def api_recent_logs(self) -> dict[str, Any]:
        live_events: list[dict[str, Any]] = []
        if hasattr(self.admin_server, "live_log_lock"):
            with self.admin_server.live_log_lock:
                live_events = list(self.admin_server.live_log)
        live_lines = [
            f"{event.get('time', '')} {event.get('kind', '-')}: {event.get('summary', '')}"
            for event in live_events
        ]
        return {
            "ok": True,
            "lines": list(RECENT_LOG_LINES) + live_lines,
            "events": live_events,
            "monitor": {
                "connected": getattr(self.admin_server, "live_monitor_connected", False),
                "error": getattr(self.admin_server, "live_monitor_error", ""),
            },
        }

    def api_clear_logs(self) -> None:
        RECENT_LOG_LINES.clear()
        if hasattr(self.admin_server, "live_log_lock"):
            with self.admin_server.live_log_lock:
                self.admin_server.live_log.clear()
        self.write_json({"ok": True, "message": "Logs geloescht."})

    def api_save_config(self) -> None:
        body = self.read_json_body()
        config = body.get("config", body)
        if not isinstance(config, dict):
            raise ConfigError("Konfiguration muss ein Objekt sein.")
        current_config = read_config_file(self.admin_server.config_path)
        config = merge_preserving_masked_secrets(config, current_config)
        write_config_file(self.admin_server.config_path, config)
        self.admin_server.shopping_sync_config = load_config(self.admin_server.config_path)
        self.write_json({"ok": True, "message": "Konfiguration gespeichert."})

    def api_action(self, action_id: str) -> None:
        if action_id in {"test_connection", "health"}:
            self.write_json(self.api_health())
            return
        if action_id in {"sync_now", "sync"}:
            self.run_sync()
            return
        if action_id == "reload":
            self.admin_server.shopping_sync_config = load_config(self.admin_server.config_path)
            self.write_json({"ok": True, "message": "Konfiguration neu geladen."})
            return
        if action_id == "restart":
            self.write_json({"ok": True, "message": "Neustart wird ausgeloest."})
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return
        if action_id == "shutdown":
            self.write_json({"ok": True, "message": "Dienst wird beendet."})
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return
        self.write_json({"ok": False, "error": f"Unbekannte Aktion: {action_id}"}, status=404)

    def save_config(self) -> None:
        config_path = self.admin_server.config_path
        try:
            body = self.read_json_body()
            config = body.get("config", body)
            if not isinstance(config, dict):
                raise ConfigError("Konfiguration muss ein JSON-Objekt sein.")
            write_config_file(config_path, config)
            self.admin_server.shopping_sync_config = load_config(config_path)
        except Exception as exc:
            self.write_json({"status": "error", "message": str(exc)}, status=400)
            return
        self.write_json(
            {
                "status": "ok",
                "message": "Konfiguration gespeichert. Ein Neustart ist sinnvoll, damit alle laufenden Verbindungen sie verwenden.",
            }
        )

    def restart_service(self) -> None:
        self.write_json({"status": "ok", "message": "Neustart wird ausgeloest."})
        threading.Timer(0.5, lambda: os._exit(0)).start()

    def run_sync(self) -> None:
        with self.admin_server.sync_lock:
            if self.admin_server.sync_running:
                self.write_json(
                    {
                        "status": "ok",
                        "message": "Synchronisation laeuft bereits.",
                        "sync_running": True,
                    },
                    status=202,
                )
                return
            self.admin_server.sync_running = True
            self.admin_server.last_sync_result = None
            self.admin_server.last_sync_error = ""

        thread = threading.Thread(
            target=self.run_sync_in_background,
            name="shopping-sync-on-demand",
            daemon=True,
        )
        thread.start()
        self.write_json(
            {
                "status": "ok",
                "message": "Synchronisation wurde gestartet.",
                "sync_running": True,
            },
            status=202,
        )

    def run_sync_in_background(self) -> None:
        try:
            result = perform_on_demand_sync(
                self.admin_server.shopping_sync_config,
                self.admin_server.status_entity_id,
            )
            with self.admin_server.sync_lock:
                self.admin_server.last_sync_result = result
                self.admin_server.last_sync_error = ""
        except Exception as exc:
            LOGGER.exception("On-Demand-Synchronisation fehlgeschlagen.")
            with self.admin_server.sync_lock:
                self.admin_server.last_sync_error = str(exc)
        finally:
            with self.admin_server.sync_lock:
                self.admin_server.sync_running = False

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw_body or "{}")
        if not isinstance(data, dict):
            raise ConfigError("Request muss ein JSON-Objekt sein.")
        return data

    def write_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_admin_server(
    config: AppConfig,
    config_path: Path,
    host: str,
    port: int,
    status_entity_id: str,
) -> ThreadingHTTPServer:
    config_path = resolve_config_path(config_path)
    server = ThreadingHTTPServer((host, port), ShoppingSyncAdminHandler)
    server.shopping_sync_config = config
    server.config_path = config_path
    server.status_entity_id = status_entity_id
    server.sync_lock = threading.Lock()
    server.sync_running = False
    server.last_sync_result = None
    server.last_sync_error = ""
    server.last_trigger_times = {}
    server.trigger_cooldown_seconds = 30
    server.live_log_lock = threading.Lock()
    server.live_log = deque(maxlen=200)
    server.live_monitor_connected = False
    server.live_monitor_error = ""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if config.home_assistant is not None:
        monitor_thread = threading.Thread(
            target=run_home_assistant_event_monitor,
            args=(server,),
            name="shopping-sync-ha-event-monitor",
            daemon=True,
        )
        monitor_thread.start()
    safe_print(f"Admin-Seite laeuft: http://{host}:{port}/admin")
    safe_print(f"Konfigurationsdatei: {config_path}")
    return server


def run_idle_service(
    config: AppConfig,
    status_entity_id: str = DEFAULT_STATUS_SENSOR,
) -> None:
    snapshot: dict[str, str] = {}
    last_periodic_sync = time.monotonic()
    if config.home_assistant is not None:
        write_shopping_sync_status(
            config.home_assistant,
            status_entity_id,
            "idle",
            firebase_connected=False,
            home_assistant_connected=True,
        )
        if config.runtime.ha_watchdog_enabled:
            try:
                states = get_home_assistant_states(config.home_assistant)
                snapshot = build_home_assistant_watchdog_snapshot_from_content(
                    config.home_assistant,
                    states,
                )
            except Exception as exc:
                LOGGER.warning("Home-Assistant-Watchdog konnte Startzustand nicht lesen: %s", exc)
    safe_print("Idle-Modus laeuft. Firebase wird nur bei Bedarf kurz verbunden.")
    while True:
        if config.home_assistant is None or not config.runtime.ha_watchdog_enabled:
            time.sleep(60)
            continue
        try:
            time.sleep(max(1, config.runtime.ha_watchdog_seconds))
            states = get_home_assistant_states(config.home_assistant)
            if not home_assistant_watchdog_enabled(states):
                snapshot = build_home_assistant_watchdog_snapshot(states)
                continue
            next_snapshot = build_home_assistant_watchdog_snapshot_from_content(
                config.home_assistant,
                states,
            )
            periodic_sync_due = (
                config.runtime.ha_periodic_sync_minutes > 0
                and time.monotonic() - last_periodic_sync
                >= config.runtime.ha_periodic_sync_minutes * 60
            )
            if snapshot and next_snapshot != snapshot:
                safe_print("Home-Assistant-Aenderung erkannt. Synchronisation wird ausgeloest.")
                time.sleep(max(0, config.runtime.ha_watchdog_debounce_seconds))
                perform_on_demand_sync(config, status_entity_id=status_entity_id)
                last_periodic_sync = time.monotonic()
                states = get_home_assistant_states(config.home_assistant)
                snapshot = build_home_assistant_watchdog_snapshot_from_content(
                    config.home_assistant,
                    states,
                )
            elif periodic_sync_due:
                safe_print("Sicherheitsabgleich wird nach Zeitintervall ausgeloest.")
                perform_on_demand_sync(config, status_entity_id=status_entity_id)
                last_periodic_sync = time.monotonic()
                states = get_home_assistant_states(config.home_assistant)
                snapshot = build_home_assistant_watchdog_snapshot_from_content(
                    config.home_assistant,
                    states,
                )
            else:
                snapshot = next_snapshot
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            LOGGER.warning("Home-Assistant-Watchdog fehlgeschlagen: %s", exc)
            if config.home_assistant is not None:
                try:
                    write_shopping_sync_status(
                        config.home_assistant,
                        status_entity_id,
                        "error",
                        last_error=str(exc),
                        firebase_connected=False,
                        home_assistant_connected=False,
                    )
                except Exception:
                    LOGGER.debug("Statussensor konnte nicht geschrieben werden.", exc_info=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Liest Shopping-App-Listen aus Firebase."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="Pfad zur config.yaml oder config.json",
    )
    parser.add_argument(
        "--all-lists",
        action="store_true",
        help="Listennamen aus /sync/{uid}/list_names lesen und jede Liste einzeln ausgeben.",
    )
    parser.add_argument(
        "--list",
        dest="list_name",
        help="Nur diese einzelne Liste ausgeben. Ueberschreibt list_name aus der Konfiguration.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Firebase dauerhaft beobachten und Home Assistant bei Aenderungen sofort aktualisieren.",
    )
    parser.add_argument(
        "--sync-ha",
        action="store_true",
        help="Gelesene Liste(n) als Home-Assistant-Sensor(en) schreiben.",
    )
    parser.add_argument(
        "--sync-todo",
        action="store_true",
        help="Gleichnamige vorhandene Home-Assistant-Todo-Listen aus Firebase befuellen.",
    )
    parser.add_argument(
        "--sync-back",
        action="store_true",
        help="Home-Assistant-Aenderungen im Watch-Modus nach Firebase zurueckschreiben.",
    )
    parser.add_argument(
        "--ha-poll-seconds",
        type=int,
        default=2,
        help="Pruefintervall fuer Home-Assistant-Aenderungen im Rueckschreibmodus.",
    )
    parser.add_argument(
        "--reconnect-seconds",
        type=int,
        default=10,
        help="Wartezeit vor neuer Firebase-Verbindung nach einem Verbindungsabbruch.",
    )
    parser.add_argument(
        "--idle-mode",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Dienst ohne dauerhafte Firebase-Verbindung betreiben. Sync nur per Admin-Seite/API.",
    )
    parser.add_argument(
        "--ha-todo-refresh-seconds",
        type=int,
        default=60,
        help="Intervall zum Neueinlesen vorhandener Home-Assistant-Todo-Listen im Watch-Modus.",
    )
    parser.add_argument(
        "--ha-status-sensor",
        default=DEFAULT_STATUS_SENSOR,
        help="Home-Assistant-Entity-ID fuer den Statussensor.",
    )
    parser.add_argument(
        "--ha-reset-button",
        default=DEFAULT_RESET_BUTTON,
        help="Home-Assistant-Entity-ID des Reset-Buttons.",
    )
    parser.add_argument(
        "--admin-server",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Kleine Konfigurations- und Statusseite per HTTP bereitstellen. Standard im Watch-Modus: aktiv.",
    )
    parser.add_argument(
        "--admin-host",
        default=None,
        help="Host/IP fuer die Admin-Seite. Ueberschreibt admin.host aus der Konfiguration.",
    )
    parser.add_argument(
        "--admin-port",
        type=int,
        default=None,
        help="Port fuer die Admin-Seite. Ueberschreibt admin.port aus der Konfiguration.",
    )
    parser.add_argument(
        "--prune-todo",
        action="store_true",
        help="Todo-Eintraege entfernen, die in Firebase nicht mehr vorhanden sind.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mehr technische Diagnose ausgeben, ohne Zugangsdaten zu loggen.",
    )
    return parser.parse_args()


def configure_logging(debug: bool) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    recent_handler = RecentLogHandler()
    recent_handler.setFormatter(formatter)
    logging.getLogger().addHandler(recent_handler)


def main() -> int:
    args = parse_args()
    configure_logging(args.debug)

    try:
        config = load_config(args.config)
        idle_mode = args.idle_mode if args.idle_mode is not None else config.runtime.idle_mode
        admin_server_enabled = args.admin_server
        if admin_server_enabled is None:
            admin_server_enabled = bool(args.watch and config.admin.enabled)
        if admin_server_enabled:
            admin_host = args.admin_host or config.admin.host
            admin_port = args.admin_port or config.admin.port
            admin_server = start_admin_server(
                config,
                args.config,
                admin_host,
                admin_port,
                args.ha_status_sensor,
            )
        if args.watch and idle_mode:
            run_idle_service(config, status_entity_id=args.ha_status_sensor)
            return 0
        session = sign_in(config.firebase)

        if args.sync_back and not args.watch:
            raise ConfigError("--sync-back ist nur im --watch-Modus sinnvoll.")
        if args.watch:
            selected_list_names = [args.list_name] if args.list_name else None
            watch_lists_via_websocket(config, session, selected_list_names, sync_todo=args.sync_todo, prune_todo=args.prune_todo, sync_back=args.sync_back, ha_poll_seconds=args.ha_poll_seconds, reconnect_seconds=args.reconnect_seconds, status_entity_id=args.ha_status_sensor, reset_button_entity_id=args.ha_reset_button, todo_refresh_seconds=args.ha_todo_refresh_seconds)
            return 0

        if args.all_lists:
            raw_lists = fetch_all_raw_lists_via_websocket(config, session)
            lists = {list_name: extract_items(payload) for list_name, payload in raw_lists.items()}
            print_lists(lists)
            if args.sync_ha or args.sync_todo:
                if config.home_assistant is None:
                    raise ConfigError("In der Konfiguration fehlt der Abschnitt home_assistant.")
            if args.sync_ha:
                entity_ids = sync_lists_to_home_assistant(config.home_assistant, lists)
                print()
                print("Home-Assistant-Sensoren geschrieben:")
                for entity_id in entity_ids:
                    print(f"  {entity_id}")
            if args.sync_todo:
                todo_entity_ids = sync_lists_to_home_assistant_todos(config.home_assistant, raw_lists, prune_todo=args.prune_todo)
                print()
                print("Home-Assistant-Todo-Listen aktualisiert:")
                if todo_entity_ids:
                    for entity_id in todo_entity_ids:
                        print(f"  {entity_id}")
                else:
                    print("  Keine gleichnamigen Todo-Listen gefunden.")
            return 0

        selected_list_names = [args.list_name] if args.list_name else config.list_names
        if selected_list_names is None:
            selected_list_names = [config.list_name] if config.list_name else []
        if not selected_list_names:
            raise ConfigError(
                "Bitte list_name oder list_names in der Konfiguration setzen oder --all-lists verwenden."
            )

        raw_lists: dict[str, Any] = {}
        for list_name in selected_list_names:
            raw_lists[list_name] = fetch_list_via_websocket(config, session, list_name)
        lists = {list_name: extract_items(payload) for list_name, payload in raw_lists.items()}

        print_lists(lists)
        if not args.sync_ha and not args.sync_todo:
            print()
            print("Home Assistant wurde nicht aktualisiert. Dafuer mit --sync-ha oder --sync-todo starten.")
        if args.sync_ha or args.sync_todo:
            if config.home_assistant is None:
                raise ConfigError("In der Konfiguration fehlt der Abschnitt home_assistant.")
        if args.sync_ha:
            entity_ids = sync_lists_to_home_assistant(config.home_assistant, lists)
            print()
            print("Home-Assistant-Sensoren geschrieben:")
            for entity_id in entity_ids:
                print(f"  {entity_id}")
        if args.sync_todo:
            todo_entity_ids = sync_lists_to_home_assistant_todos(config.home_assistant, raw_lists, prune_todo=args.prune_todo)
            print()
            print("Home-Assistant-Todo-Listen aktualisiert:")
            if todo_entity_ids:
                for entity_id in todo_entity_ids:
                    print(f"  {entity_id}")
            else:
                print("  Keine gleichnamigen Todo-Listen gefunden.")
        return 0
    except Exception as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())























