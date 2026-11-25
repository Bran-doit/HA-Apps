"""Authenticated Home Assistant service -> AppDaemon event with correlated reply."""
import asyncio
import json
import time
from uuid import uuid4
import voluptuous as vol
from homeassistant.core import SupportsResponse, callback
from homeassistant.helpers import config_validation as cv

DOMAIN="ha_medien_kodi"
CONFIG_SCHEMA=vol.Schema({DOMAIN:vol.Any(None,vol.Schema({}))},extra=vol.ALLOW_EXTRA)

async def async_setup(hass, config):
    from .config_api import setup_config_api
    setup_config_api(hass)
    async def process(call):
        request_id=uuid4().hex
        future=hass.loop.create_future()
        @callback
        def completed(event):
            if event.data.get("request_id")==request_id and not future.done():
                try:
                    future.set_result(json.loads(event.data["payload"]))
                except (KeyError,TypeError,ValueError):
                    future.set_result({"handled":True,"status":"error","speech":"Die Mediensteuerung hat eine ungültige Antwort geliefert."})
        remove=hass.bus.async_listen("ha_mediensteuerung_kodi_voice_result",completed)
        try:
            hass.bus.async_fire("ha_mediensteuerung_kodi",{
                "action":"voice", "request_id":request_id,
                "text":call.data["text"], "session":call.data.get("session", "") + "|" + (call.context.user_id or "local"),
                "dry_run":call.data.get("dry_run",False), "expires_at":time.time()+65,
            },context=call.context)
            return await asyncio.wait_for(future,75)
        except TimeoutError:
            return {"handled":True,"status":"error","speech":"Die Mediensteuerung antwortet nicht rechtzeitig. Bitte prüfe das Dashboard, bevor du den Start wiederholst."}
        finally:
            remove()
    hass.services.async_register(DOMAIN,"process",process,
        schema=vol.Schema({vol.Required("text"):vol.All(cv.string,vol.Length(min=1,max=300)),vol.Optional("session",default=""):vol.All(cv.string,vol.Length(max=200)),vol.Optional("dry_run",default=False):cv.boolean}),
        supports_response=SupportsResponse.ONLY)
    return True
