"""Config flow for Assist Performance Monitor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HISTORY_SIZE,
    CONF_INCLUDE_TEXT,
    CONF_SCAN_INTERVAL,
    DEFAULT_HISTORY_SIZE,
    DEFAULT_INCLUDE_TEXT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


class AssistPerformanceMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Assist Performance Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle UI setup."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title="Assist Performance Monitor", data=user_input
            )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_INCLUDE_TEXT, default=DEFAULT_INCLUDE_TEXT
                ): bool,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
                vol.Optional(
                    CONF_HISTORY_SIZE, default=DEFAULT_HISTORY_SIZE
                ): vol.All(vol.Coerce(int), vol.Range(min=20, max=5000)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Import YAML configuration."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Assist Performance Monitor", data=import_data
        )

