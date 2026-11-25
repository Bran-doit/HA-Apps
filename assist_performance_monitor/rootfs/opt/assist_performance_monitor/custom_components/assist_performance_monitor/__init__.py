"""Assist Performance Monitor integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_HISTORY_SIZE,
    CONF_INCLUDE_TEXT,
    CONF_SCAN_INTERVAL,
    DATA_COORDINATOR,
    DEFAULT_HISTORY_SIZE,
    DEFAULT_INCLUDE_TEXT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import AssistPerformanceCoordinator

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(
                    CONF_INCLUDE_TEXT, default=DEFAULT_INCLUDE_TEXT
                ): cv.boolean,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
                vol.Optional(
                    CONF_HISTORY_SIZE, default=DEFAULT_HISTORY_SIZE
                ): vol.All(vol.Coerce(int), vol.Range(min=20, max=5000)),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Import YAML configuration into a config entry."""
    if domain_config := config.get(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=dict(domain_config),
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the monitor from a config entry."""
    coordinator = AssistPerformanceCoordinator(hass, entry)
    await coordinator.async_initialize()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the monitor."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    data = hass.data[DOMAIN].pop(entry.entry_id)
    data[DATA_COORDINATOR].async_stop()
    return True

