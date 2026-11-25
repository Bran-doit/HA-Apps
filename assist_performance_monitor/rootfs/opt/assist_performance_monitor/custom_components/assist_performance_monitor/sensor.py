"""Sensors for Assist Performance Monitor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.loader import async_get_integration

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AssistPerformanceCoordinator


@dataclass(frozen=True, kw_only=True)
class AssistSensorDescription(SensorEntityDescription):
    """Describe an Assist metric sensor."""

    value_fn: Callable[[AssistPerformanceCoordinator], Any]


SENSORS = (
    AssistSensorDescription(
        key="total_duration",
        name="Assist total duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:timer-outline",
        value_fn=lambda c: c.last_run.pipeline_duration_ms if c.last_run else None,
    ),
    AssistSensorDescription(
        key="stt_duration",
        name="Assist STT duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:microphone-message",
        value_fn=lambda c: c.last_run.stt_duration_ms if c.last_run else None,
    ),
    AssistSensorDescription(
        key="agent_duration",
        name="Assist agent duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:message-processing-outline",
        value_fn=lambda c: c.last_run.intent_duration_ms if c.last_run else None,
    ),
    AssistSensorDescription(
        key="reaction_time",
        name="Assist reaction time",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:timer-sand",
        value_fn=lambda c: c.last_run.reaction_time_ms if c.last_run else None,
    ),
    AssistSensorDescription(
        key="tts_duration",
        name="Assist TTS orchestration duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:account-voice",
        value_fn=lambda c: c.last_run.tts_orchestration_duration_ms if c.last_run else None,
    ),
    AssistSensorDescription(
        key="average_duration",
        name="Assist average duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:chart-line",
        value_fn=lambda c: c.average_duration,
    ),
    AssistSensorDescription(
        key="p90_duration",
        name="Assist P90 duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:chart-bell-curve-cumulative",
        value_fn=lambda c: c.p90_duration,
    ),
    AssistSensorDescription(
        key="trend_current_average",
        name="Assist trend current average",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:speedometer",
        value_fn=lambda c: c.trend_summary["current_average_ms"],
    ),
    AssistSensorDescription(
        key="trend_baseline_average",
        name="Assist trend reference average",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:history",
        value_fn=lambda c: c.trend_summary["baseline_average_ms"],
    ),
    AssistSensorDescription(
        key="performance_trend",
        name="Assist performance trend",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:chart-timeline-variant-shimmer",
        value_fn=lambda c: c.trend_summary["trend_percent"],
    ),
    AssistSensorDescription(
        key="local_average_duration",
        name="Assist local average duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:home-clock-outline",
        value_fn=lambda c: c.local_average_duration,
    ),
    AssistSensorDescription(
        key="local_p90_duration",
        name="Assist local P90 duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:home-analytics",
        value_fn=lambda c: c.local_p90_duration,
    ),
    AssistSensorDescription(
        key="external_average_duration",
        name="Assist external average duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:cloud-clock-outline",
        value_fn=lambda c: c.external_average_duration,
    ),
    AssistSensorDescription(
        key="external_p90_duration",
        name="Assist external P90 duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:cloud-percent-outline",
        value_fn=lambda c: c.external_p90_duration,
    ),
    AssistSensorDescription(
        key="local_average_reaction_time",
        name="Assist local average reaction time",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:home-clock-outline",
        value_fn=lambda c: c.local_average_reaction_time,
    ),
    AssistSensorDescription(
        key="local_p90_reaction_time",
        name="Assist local P90 reaction time",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:home-analytics",
        value_fn=lambda c: c.local_p90_reaction_time,
    ),
    AssistSensorDescription(
        key="external_average_reaction_time",
        name="Assist external average reaction time",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:cloud-clock-outline",
        value_fn=lambda c: c.external_average_reaction_time,
    ),
    AssistSensorDescription(
        key="external_p90_reaction_time",
        name="Assist external P90 reaction time",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        icon="mdi:cloud-percent-outline",
        value_fn=lambda c: c.external_p90_reaction_time,
    ),
    AssistSensorDescription(
        key="error_rate",
        name="Assist error rate",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:alert-circle-outline",
        value_fn=lambda c: c.error_rate,
    ),
    AssistSensorDescription(
        key="local_percentage",
        name="Assist local intent percentage",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:home-lightning-bolt-outline",
        value_fn=lambda c: c.local_percentage,
    ),
    AssistSensorDescription(
        key="total_runs",
        name="Assist monitored runs",
        icon="mdi:counter",
        value_fn=lambda c: c.total_runs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Assist metric sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)
    async_add_entities(
        [
            *(
                AssistMetricSensor(coordinator, entry, description, version)
                for description in SENSORS
            ),
            AssistVersionSensor(entry, version),
        ]
    )


class AssistMetricSensor(SensorEntity):
    """Expose a metric calculated by the coordinator."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: AssistPerformanceCoordinator,
        entry: ConfigEntry,
        description: AssistSensorDescription,
        version: str,
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"
        self._attr_state_class = (
            SensorStateClass.TOTAL_INCREASING
            if description.key == "total_runs"
            else SensorStateClass.MEASUREMENT
        )
        # Recorder must retain every completed run, even if two adjacent runs
        # happen to have exactly the same duration.
        self._attr_force_update = description.key == "total_duration"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Assist Performance Monitor",
            "manufacturer": "Local custom integration",
            "model": "Diagnostic collector",
            "sw_version": version,
        }
        self._remove_listener = None

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "performance_trend":
            summary = self.coordinator.trend_summary
            return {
                "status": summary["status"],
                "coverage": summary.get("coverage", "none"),
                "method": "equal-weighted active-day medians",
                "current_window": "latest 2-3 eligible active days",
                "reference_window": "up to 7 preceding eligible active days",
                "minimum_samples_per_day_and_class": 3,
                "neutral_range_percent": 5,
                "workflow_classes": summary["classes"],
            }
        if self.entity_description.key != "total_duration" or not self.coordinator.last_run:
            return None
        run = self.coordinator.last_run
        attrs = {
            "run_id": run.run_id,
            "pipeline_id": run.pipeline_id,
            "started_at": run.started_at,
            "satellite_id": run.satellite_id,
            "device_id": run.device_id,
            "stt_engine": run.stt_engine,
            "conversation_engine": run.conversation_engine,
            "tts_engine": run.tts_engine,
            "reaction_time_ms": run.reaction_time_ms,
            "processed_locally": run.processed_locally,
            "workflow_class": run.workflow_class,
            "success": run.success,
            "error_code": run.error_code,
            "error_message": run.error_message,
        }
        if self.coordinator.include_text:
            attrs["transcript"] = run.transcript
            attrs["response_text"] = run.response_text
        return attrs

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self.coordinator.async_add_listener(
            self._handle_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class AssistVersionSensor(SensorEntity):
    """Expose the installed integration version in the device overview."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:tag-outline"
    _attr_name = "Assist Performance Monitor Version"

    def __init__(self, entry: ConfigEntry, version: str) -> None:
        self._attr_native_value = version
        self._attr_unique_id = f"{DOMAIN}_version"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Assist Performance Monitor",
            "manufacturer": "Local custom integration",
            "model": "Diagnostic collector",
            "sw_version": version,
        }
