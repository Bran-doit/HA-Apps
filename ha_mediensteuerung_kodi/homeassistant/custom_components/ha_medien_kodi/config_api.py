"""Private player store and authenticated, admin-only configuration WebSocket API."""
import asyncio
import copy
import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

import aiohttp
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from urllib.parse import urlencode
from .session_policy import session_summary, select_session, SessionError
from .emby_config import public_emby, validate_emby, emby_get, inspect_emby

SECRET_KEYS = {"password", "pin"}


def host(value):
    value = str(value).strip()
    if not value or len(value) > 253 or not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
        raise ValueError("Bitte eine gültige IPv4-Adresse oder einen Hostnamen ohne http:// und Port eingeben.")
    return value


def public_player(player):
    p = copy.deepcopy(player)
    p["connection"]["has_password"] = bool(p["connection"].pop("password", ""))
    sony = p["startup"].get("sony", {})
    sony["has_pin"] = bool(sony.pop("pin", ""))
    return p


def validate_player(raw, previous=None):
    previous = previous or {}
    name = str(raw.get("name", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("Bitte einen Gerätenamen mit höchstens 80 Zeichen eingeben.")
    aliases = raw.get("room_aliases", [])
    if not isinstance(aliases, list) or not aliases or any(not isinstance(v, str) or not v.strip() or len(v)>60 for v in aliases):
        raise ValueError("Bitte mindestens einen Raum-/Gerätenamen für Sprachbefehle angeben.")
    c = raw.get("connection", {})
    port = int(c.get("port", 8080))
    if not 1 <= port <= 65535:
        raise ValueError("Der Port muss zwischen 1 und 65535 liegen.")
    password = c.get("password") or previous.get("connection", {}).get("password", "")
    if c.get("clear_password") is True:
        password = ""
    startup = raw.get("startup", {})
    method = startup.get("method", "none")
    if method not in ("none", "remote", "sony"):
        raise ValueError("Unbekannte Einschaltmethode.")
    remote = str(startup.get("remote_entity", "")).strip()
    if remote and not re.fullmatch(r"remote\.[a-z0-9_]+", remote):
        raise ValueError("Bitte eine remote.-Entität auswählen.")
    if method == "remote" and not remote:
        raise ValueError("Für Android/Google TV ist eine Remote-Entität nötig.")
    s = {"enabled": startup.get("enabled") is True and method != "none", "method": method,
         "remote_entity": remote, "activity": str(startup.get("activity", "org.xbmc.kodi")).strip(),
         "bring_to_front": bool(remote), "timeout_seconds": 20}
    if not s["activity"] or len(s["activity"]) > 250:
        raise ValueError("Bitte eine gültige Kodi-App-ID eingeben.")
    if method == "sony":
        sony = startup.get("sony", {})
        pin = sony.get("pin") or previous.get("startup", {}).get("sony", {}).get("pin", "")
        if sony.get("clear_pin") is True:
            pin = ""
        s["sony"] = {"host": host(sony.get("host") or c.get("host")), "pin": str(pin), "use_ssl": sony.get("use_ssl") is True}
        s["launch_uri"] = str(startup.get("launch_uri") or "com.sony.dtv.org.xbmc.kodi.org.xbmc.kodi.Splash")
    return {"id": previous.get("id") or "kodi_" + uuid4().hex[:12], "name": name,
            "enabled": raw.get("enabled") is True,
            "room_aliases": list(dict.fromkeys(v.strip().casefold() for v in aliases)),
            "connection": {"host": host(c.get("host", "")), "port": port, "ssl": c.get("ssl") is True,
                           "username": str(c.get("username", ""))[:200], "password": str(password)}, "startup": s}


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".kodi-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def request_json(hass, url, payload, headers=None, auth=None):
    async with async_get_clientsession(hass).post(url, json=payload, headers=headers, auth=auth,
                timeout=aiohttp.ClientTimeout(total=5), allow_redirects=False) as response:
        response.raise_for_status()
        return await response.json(content_type=None)


async def ping(hass, player):
    c = player["connection"]
    result = await request_json(hass, ("https" if c.get("ssl") else "http")+"://"+c["host"]+":"+str(c["port"])+"/jsonrpc",
        {"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}, auth=aiohttp.BasicAuth(c.get("username", ""), c.get("password", "")))
    if result.get("result") != "pong" or result.get("id") != 1:
        raise ValueError("Kodi hat keine gültige Antwort geliefert.")


async def power(hass, player, on):
    s = player["startup"]
    if s["method"] == "sony":
        c = s["sony"]
        origin = ("https" if c.get("use_ssl") else "http")+"://"+c["host"]+"/sony/"
        async def sony(endpoint, method, params):
            result = await request_json(hass, origin+endpoint, {"method":method,"params":params,"id":1,"version":"1.0"}, {"X-Auth-PSK":c["pin"]})
            if "error" in result:
                raise ValueError("Der Sony-Fernseher hat den Steuerbefehl abgewiesen.")
        await sony("system", "setPowerStatus", [{"status":on}])
        if on:
            await sony("appControl", "setActiveApp", [{"uri":s["launch_uri"]}])
    elif s["method"] == "remote":
        data = {"entity_id":s["remote_entity"]}
        if on:
            data["activity"] = s["activity"]
        await hass.services.async_call("remote", "turn_on" if on else "turn_off", data, blocking=True)
    else:
        raise ValueError("Für dieses Gerät ist noch keine Einschaltmethode eingerichtet.")
    if on:
        for attempt in range(10):
            try:
                await ping(hass, player)
                return "Kodi ist erreichbar."
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                if attempt == 9:
                    raise ValueError("Einschaltbefehl gesendet, Kodi antwortet aber noch nicht.") from None
                await asyncio.sleep(1)
    return "Ausschaltbefehl für dieses Gerät gesendet."


def setup_config_api(hass):
    path = Path(hass.config.path("ha_medien_kodi_private", "players.json"))
    lock = asyncio.Lock()

    @websocket_api.websocket_command({vol.Required("type"): "ha_medien_kodi/config", vol.Required("action"):str,
        vol.Optional("player_id"):str, vol.Optional("player"):dict, vol.Optional("revision"):int, vol.Optional("emby"):dict, vol.Optional("backend"):str, vol.Optional("device_id"):str, vol.Optional("client"):str, vol.Optional("aliases"):[str]})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def config_command(hass, connection, msg):
        try:
            async with lock:
                store = await hass.async_add_executor_job(lambda: json.loads(path.read_text(encoding="utf-8")))
                action = msg["action"]
                players = store["players"]
                previous = next((p for p in players if p["id"] == msg.get("player_id")), None)
                if action in ("emby_save", "emby_test", "emby_users"):
                    candidate = validate_emby(msg.get("emby", {}), store.get("emby", {}))
                    if action == "emby_users":
                        users = await emby_get(hass, candidate, "Users")
                        connection.send_result(msg["id"], {"users":[{"id":str(u["Id"]),"name":u.get("Name",str(u["Id"]))} for u in users if not u.get("Policy",{}).get("IsDisabled")]})
                        return
                    if candidate["enabled"] or action == "emby_test" or store.get("backend")=="emby":
                        candidate = await inspect_emby(hass, candidate)
                    if action == "emby_test":
                        connection.send_result(msg["id"], {"message":"Emby und Benutzerprofil erfolgreich geprüft.","emby":public_emby(candidate)})
                        return
                    if msg.get("revision") != store["revision"]:
                        raise ValueError("Die Konfiguration wurde inzwischen geändert. Bitte neu laden.")
                    store["emby"] = candidate
                    store["revision"] += 1
                    await hass.async_add_executor_job(atomic_write,path,store)
                    hass.bus.async_fire("ha_medien_kodi_config_changed", {"revision":store["revision"]})
                    action = "get"
                if action in ("emby_sessions", "backend_save"):
                    emby = store.get("emby", {})
                    backend = msg.get("backend",store.get("backend","kodi"))
                    if backend not in ("kodi","emby"):
                        raise ValueError("Bitte Kodi oder Emby als Backend wählen.")
                    if action == "backend_save" and msg.get("revision") != store["revision"]:
                        raise ValueError("Die Konfiguration wurde inzwischen geändert. Bitte neu laden.")
                    if action == "emby_sessions" or backend == "emby":
                        emby = await inspect_emby(hass,dict(emby))
                        sessions = await emby_get(hass,emby,"Sessions?"+urlencode({"ControllableByUserId":emby["user_id"]}))
                        if action == "emby_sessions":
                            summaries=[session_summary(v) for v in sessions]
                            summaries.sort(key=lambda v:(not v["remote_control"],v["device_name"],v["client"]))
                            selected=None;error=""
                            try:selected=session_summary(select_session(sessions,emby.get("target_device_id",""),emby["user_id"],emby.get("target_client","")))
                            except SessionError as exc:error=str(exc)
                            connection.send_result(msg["id"],{"sessions":summaries,"selected":selected,"error":error,"user_id":emby["user_id"]})
                            return
                        device=msg.get("device_id",emby.get("target_device_id",""))
                        client=msg.get("client",emby.get("target_client",""))
                        if not device and backend=="emby":raise ValueError("TARGET_DEVICE_NOT_CONFIGURED: Bitte ausdrücklich ein Emby-Gerät auswählen.")
                        try:
                            target=select_session(sessions,device,emby["user_id"],client)
                            emby.update(target_device_id=target["DeviceId"],target_device_name=target.get("DeviceName",""),target_client=target.get("Client",""))
                        except SessionError as exc:
                            if exc.code!="TARGET_SESSION_OFFLINE" or device!=emby.get("target_device_id") or client!=emby.get("target_client"):raise
                        aliases=msg.get("aliases") or emby.get("target_aliases") or ["familienzimmer","wohnzimmer","fernseher","kodi","google tv"]
                        if any(not a.strip() or len(a)>60 for a in aliases):raise ValueError("Ungültiger Raumname.")
                        emby["target_aliases"]=[a.strip().casefold() for a in aliases]
                        store["emby"]=emby
                    store["backend"]=backend
                    store["revision"]+=1
                    await hass.async_add_executor_job(atomic_write,path,store)
                    hass.bus.async_fire("ha_medien_kodi_config_changed",{"revision":store["revision"]})
                    action="get"
                if action == "discover":
                    from homeassistant.helpers import entity_registry as er
                    registry = er.async_get(hass)
                    devices = []
                    for entry in hass.config_entries.async_entries():
                        if entry.domain != "kodi":
                            continue
                        data = dict(entry.data) | dict(entry.options)
                        if data.get("host"):
                            devices.append({"name":entry.title,"host":data["host"],"port":data.get("port",8080),"ssl":data.get("ssl",False),"username":data.get("username","")})
                    remotes = [{"id":s.entity_id,"name":s.attributes.get("friendly_name",s.entity_id)} for s in hass.states.async_all("remote")]
                    connection.send_result(msg["id"], {"devices":devices,"remotes":remotes})
                    return
                if action in ("save", "delete", "default"):
                    if msg.get("revision") != store["revision"]:
                        raise ValueError("Die Konfiguration wurde inzwischen geändert. Bitte neu laden.")
                    if action == "save":
                        if msg.get("player_id") and previous is None:
                            raise ValueError("Dieses Gerät existiert nicht mehr.")
                        candidate = validate_player(msg.get("player", {}), previous)
                        for other in players:
                            if other["id"] == candidate["id"]:
                                continue
                            a, b = other["connection"], candidate["connection"]
                            if (a["host"].casefold(), a["port"]) == (b["host"].casefold(), b["port"]):
                                raise ValueError("Diese Kodi-Adresse ist bereits eingerichtet.")
                            if set(other["room_aliases"]) & set(candidate["room_aliases"]):
                                raise ValueError("Raum-/Gerätenamen müssen pro Kodi eindeutig sein.")
                        players[:] = [candidate if p["id"] == candidate["id"] else p for p in players]
                        if previous is None:
                            if len(players) >= 12:
                                raise ValueError("Es sind höchstens zwölf Geräte vorgesehen.")
                            players.append(candidate)
                    else:
                        if previous is None:
                            raise ValueError("Gerät nicht gefunden.")
                        if action == "delete":
                            players.remove(previous)
                        else:
                            if not previous["enabled"]:
                                raise ValueError("Bitte das Gerät zuerst aktivieren.")
                            store["default_player"] = previous["id"]
                    enabled = [p["id"] for p in players if p["enabled"]]
                    if store.get("default_player") not in enabled:
                        store["default_player"] = next(iter(enabled), "")
                    store["revision"] += 1
                    await hass.async_add_executor_job(atomic_write, path, store)
                    hass.bus.async_fire("ha_medien_kodi_config_changed", {"revision":store["revision"]})
                elif action == "test":
                    candidate = validate_player(msg.get("player", previous or {}), previous)
                    await ping(hass, candidate)
                    connection.send_result(msg["id"], {"message":"Kodi antwortet: Verbindung und Zugangsdaten sind gültig."})
                    return
                elif action in ("on", "off"):
                    if previous is None:
                        raise ValueError("Gerät nicht gefunden.")
                    message = await power(hass, previous, action == "on")
                    connection.send_result(msg["id"], {"message":message})
                    return
                elif action != "get":
                    raise ValueError("Unbekannte Konfigurationsaktion.")
                connection.send_result(msg["id"], {"revision":store["revision"], "default_player":store.get("default_player", ""), "players":[public_player(p) for p in players], "emby":public_emby(store.get("emby",{})), "backend":store.get("backend","kodi")})
        except ValueError as exc:
            connection.send_error(msg["id"], "invalid_config", str(exc))
        except (aiohttp.ClientError, asyncio.TimeoutError):
            connection.send_error(msg["id"], "connection_failed", "Gerät nicht erreichbar oder Anmeldung abgewiesen. Adresse, Port und Zugangsdaten prüfen.")
        except Exception:
            connection.send_error(msg["id"], "config_failed", "Konfiguration konnte nicht verarbeitet werden. Bitte das Home-Assistant-Protokoll prüfen.")
    websocket_api.async_register_command(hass, config_command)
