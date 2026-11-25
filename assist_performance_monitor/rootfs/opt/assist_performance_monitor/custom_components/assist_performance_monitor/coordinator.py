"""Collect and normalize Assist pipeline debug runs."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from functools import partial
import logging
import math
from statistics import fmean, median
from typing import Any

from homeassistant.components.recorder.history import get_significant_states
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.recorder import get_instance
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from homeassistant.components.assist_pipeline.pipeline import KEY_ASSIST_PIPELINE

from .const import (
    CONF_HISTORY_SIZE,
    CONF_INCLUDE_TEXT,
    CONF_SCAN_INTERVAL,
    DEFAULT_HISTORY_SIZE,
    DEFAULT_INCLUDE_TEXT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}.statistics"
SEEN_ID_LIMIT = 5000
RECENT_RUN_LIMIT = 20
TREND_SAMPLE_LIMIT = 10000
TREND_RETENTION_DAYS = 60
TREND_CURRENT_ACTIVE_DAYS = 3
TREND_MIN_CURRENT_DAYS = 2
TREND_BASELINE_ACTIVE_DAYS = 7
TREND_MIN_BASELINE_DAYS = 2
TREND_MIN_SAMPLES_PER_DAY_AND_CLASS = 3
TREND_NEUTRAL_PERCENT = 5.0
TREND_SOURCE_ENTITY_ID = "sensor.assist_performance_monitor_assist_total_duration"


@dataclass
class AssistRun:
    """Normalized completed pipeline run."""

    run_id: str
    pipeline_id: str
    started_at: str | None
    satellite_id: str | None
    device_id: str | None
    stt_engine: str | None
    conversation_engine: str | None
    tts_engine: str | None
    pipeline_duration_ms: float | None
    stt_duration_ms: float | None
    intent_duration_ms: float | None
    tts_orchestration_duration_ms: float | None
    processed_locally: bool | None
    workflow_class: str
    success: bool
    error_code: str | None
    error_message: str | None
    transcript: str | None = None
    response_text: str | None = None
    reaction_time_ms: float | None = None


@dataclass
class TrendSample:
    """One timestamped run used for usage-normalized trend calculation."""

    run_id: str
    timestamp: str
    pipeline_duration_ms: float
    reaction_time_ms: float | None
    processed_locally: bool | None
    success: bool


class AssistPerformanceCoordinator:
    """Poll Home Assistant's in-memory Assist debug data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.include_text = entry.data.get(CONF_INCLUDE_TEXT, DEFAULT_INCLUDE_TEXT)
        self.scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.history_size = entry.data.get(CONF_HISTORY_SIZE, DEFAULT_HISTORY_SIZE)
        self.last_run: AssistRun | None = None
        self.total_runs = 0
        self.error_runs = 0
        self.local_runs = 0
        self.classified_intent_runs = 0
        self.durations: deque[float] = deque(maxlen=self.history_size)
        self.local_durations: deque[float] = deque(maxlen=self.history_size)
        self.external_durations: deque[float] = deque(maxlen=self.history_size)
        self.local_reaction_durations: deque[float] = deque(maxlen=self.history_size)
        self.external_reaction_durations: deque[float] = deque(maxlen=self.history_size)
        self.seen_ids: deque[str] = deque(maxlen=SEEN_ID_LIMIT)
        self._seen_lookup: set[str] = set()
        self.recent_runs: deque[AssistRun] = deque(maxlen=RECENT_RUN_LIMIT)
        self._recent_lookup: set[str] = set()
        self.trend_samples: deque[TrendSample] = deque(maxlen=TREND_SAMPLE_LIMIT)
        self._trend_lookup: set[str] = set()
        self._listeners: set[Callable[[], None]] = set()
        self._unsub_interval: Callable[[], None] | None = None
        self._store = Store(hass, STORE_VERSION, STORE_KEY)

    async def async_initialize(self) -> None:
        """Restore aggregate state."""
        data = await self._store.async_load() or {}
        self.total_runs = int(data.get("total_runs", 0))
        self.error_runs = int(data.get("error_runs", 0))
        self.local_runs = int(data.get("local_runs", 0))
        self.classified_intent_runs = int(data.get("classified_intent_runs", 0))
        self.durations.extend(float(value) for value in data.get("durations", []))
        self.local_durations.extend(
            float(value) for value in data.get("local_durations", [])
        )
        self.external_durations.extend(
            float(value) for value in data.get("external_durations", [])
        )
        self.local_reaction_durations.extend(
            float(value) for value in data.get("local_reaction_durations", [])
        )
        self.external_reaction_durations.extend(
            float(value) for value in data.get("external_reaction_durations", [])
        )
        self.seen_ids.extend(str(value) for value in data.get("seen_ids", []))
        self._seen_lookup = set(self.seen_ids)
        for raw_run in data.get("recent_runs", []):
            run = self._run_from_data(raw_run)
            self.recent_runs.append(run)
            self._recent_lookup.add(run.run_id)
        if raw_last_run := data.get("last_run"):
            self.last_run = self._run_from_data(raw_last_run)
            # Upgrade stores written before recent_runs was introduced.
            if self.last_run.run_id not in self._recent_lookup:
                self._remember_recent(self.last_run)

        for raw_sample in data.get("trend_samples", []):
            try:
                sample = TrendSample(**raw_sample)
            except (TypeError, ValueError):
                continue
            self.trend_samples.append(sample)
            self._trend_lookup.add(sample.run_id)

        # Migrate stores written before split duration statistics existed.
        if "local_durations" not in data and "external_durations" not in data:
            migrated_runs = list(self.recent_runs)
            if not migrated_runs and self.last_run is not None:
                migrated_runs = [self.last_run]
            for run in migrated_runs:
                self._record_split_duration(run)

        if "local_reaction_durations" not in data and "external_reaction_durations" not in data:
            for run in self.recent_runs:
                self._record_split_reaction_duration(run)

        # Reuse recorder history so the trend is available immediately after
        # upgrading instead of starting with an empty second history.
        if await self._async_backfill_trend_samples():
            await self._store.async_save(self._serialize())

    @callback
    def async_start(self) -> None:
        """Start periodic collection."""
        self._unsub_interval = async_track_time_interval(
            self.hass, self._async_poll, timedelta(seconds=self.scan_interval)
        )
        self.hass.async_create_task(self._async_poll())

    @callback
    def async_stop(self) -> None:
        """Stop periodic collection."""
        if self._unsub_interval:
            self._unsub_interval()
            self._unsub_interval = None

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to data updates."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    async def _async_poll(self, _now: datetime | None = None) -> None:
        """Read newly completed runs from the internal debug buffer."""
        pipeline_data = self.hass.data.get(KEY_ASSIST_PIPELINE)
        if pipeline_data is None:
            return

        changed = False
        for pipeline_id, pipeline_runs in list(pipeline_data.pipeline_debug.items()):
            for run_id, debug_run in list(pipeline_runs.items()):
                run_id = str(run_id)
                if run_id in self._seen_lookup:
                    # Backfill normalized details added in v0.1.1 from the
                    # still-available Core debug buffer without recounting.
                    if run_id not in self._recent_lookup:
                        events = list(debug_run.events)
                        if any(
                            self._event_type(event) == "run-end"
                            for event in events
                        ):
                            self._remember_recent(
                                self._normalize_run(
                                    str(pipeline_id), run_id, events
                                )
                            )
                            changed = True
                    continue
                events = list(debug_run.events)
                if not any(self._event_type(event) == "run-end" for event in events):
                    continue
                run = self._normalize_run(str(pipeline_id), run_id, events)
                self._remember_seen(run_id)
                self._record(run)
                changed = True

        if not changed:
            return
        await self._store.async_save(self._serialize())
        for listener in tuple(self._listeners):
            listener()

    def _record(self, run: AssistRun) -> None:
        self.last_run = run
        self._remember_recent(run)
        self.total_runs += 1
        if not run.success:
            self.error_runs += 1
        if run.processed_locally is not None:
            self.classified_intent_runs += 1
            if run.processed_locally:
                self.local_runs += 1
        if run.pipeline_duration_ms is not None:
            self.durations.append(run.pipeline_duration_ms)
        self._record_split_duration(run)
        self._record_split_reaction_duration(run)
        self._remember_trend_run(run)
        log_data = asdict(run)
        if not self.include_text:
            log_data.pop("transcript", None)
            log_data.pop("response_text", None)
        _LOGGER.info("Assist pipeline run: %s", log_data)

    def _record_split_duration(self, run: AssistRun) -> None:
        """Record duration by actual intent processing location."""
        if run.pipeline_duration_ms is None:
            return
        if run.processed_locally is True:
            self.local_durations.append(run.pipeline_duration_ms)
        elif run.processed_locally is False:
            self.external_durations.append(run.pipeline_duration_ms)

    def _record_split_reaction_duration(self, run: AssistRun) -> None:
        """Record user-facing reaction time by actual intent processing location."""
        if run.reaction_time_ms is None:
            return
        if run.processed_locally is True:
            self.local_reaction_durations.append(run.reaction_time_ms)
        elif run.processed_locally is False:
            self.external_reaction_durations.append(run.reaction_time_ms)

    def _remember_recent(self, run: AssistRun) -> None:
        """Retain normalized diagnostic details for recent runs."""
        if run.run_id in self._recent_lookup:
            return
        if len(self.recent_runs) == self.recent_runs.maxlen:
            self._recent_lookup.discard(self.recent_runs[0].run_id)
        self.recent_runs.append(run)
        self._recent_lookup.add(run.run_id)

    def _remember_seen(self, run_id: str) -> None:
        if len(self.seen_ids) == self.seen_ids.maxlen:
            old_id = self.seen_ids[0]
            self._seen_lookup.discard(old_id)
        self.seen_ids.append(run_id)
        self._seen_lookup.add(run_id)

    def _remember_trend_run(self, run: AssistRun) -> None:
        """Retain timestamped run data for the usage-normalized trend."""
        if (
            run.run_id in self._trend_lookup
            or run.started_at is None
            or run.pipeline_duration_ms is None
        ):
            return
        self._append_trend_sample(
            TrendSample(
                run_id=run.run_id,
                timestamp=run.started_at,
                pipeline_duration_ms=run.pipeline_duration_ms,
                reaction_time_ms=run.reaction_time_ms,
                processed_locally=run.processed_locally,
                success=run.success,
            )
        )

    def _append_trend_sample(self, sample: TrendSample) -> None:
        """Append a trend sample while keeping the lookup in sync."""
        if sample.run_id in self._trend_lookup:
            return
        if len(self.trend_samples) == self.trend_samples.maxlen:
            self._trend_lookup.discard(self.trend_samples[0].run_id)
        self.trend_samples.append(sample)
        self._trend_lookup.add(sample.run_id)

    async def _async_backfill_trend_samples(self) -> bool:
        """Backfill timestamped samples from existing Recorder state history.

        Recorder history is an internal Core Python API. This isolated adapter
        is the only compatibility boundary needed to reuse pre-upgrade values.
        """
        start_time = dt_util.utcnow() - timedelta(days=TREND_RETENTION_DAYS)
        source_entity_id = (
            er.async_get(self.hass).async_get_entity_id(
                "sensor", DOMAIN, f"{DOMAIN}_total_duration"
            )
            or TREND_SOURCE_ENTITY_ID
        )
        query = partial(
            get_significant_states,
            self.hass,
            start_time,
            entity_ids=[source_entity_id],
            include_start_time_state=False,
            significant_changes_only=False,
            minimal_response=False,
            no_attributes=False,
        )
        try:
            history = await get_instance(self.hass).async_add_executor_job(query)
        except Exception:  # noqa: BLE001 - compatibility boundary must not break setup
            _LOGGER.exception("Unable to backfill Assist trend data from Recorder")
            return False

        changed = False
        for state in history.get(source_entity_id, []):
            try:
                pipeline_duration = float(state.state)
            except (TypeError, ValueError):
                continue
            attributes = state.attributes
            run_id = str(attributes.get("run_id") or state.last_updated.isoformat())
            if run_id in self._trend_lookup:
                continue
            reaction_value = attributes.get("reaction_time_ms")
            try:
                reaction_time = (
                    float(reaction_value) if reaction_value is not None else None
                )
            except (TypeError, ValueError):
                reaction_time = None
            processed_locally = attributes.get("processed_locally")
            if not isinstance(processed_locally, bool):
                processed_locally = None
            self._append_trend_sample(
                TrendSample(
                    run_id=run_id,
                    timestamp=state.last_updated.isoformat(),
                    pipeline_duration_ms=pipeline_duration,
                    reaction_time_ms=reaction_time,
                    processed_locally=processed_locally,
                    success=attributes.get("success") is not False,
                )
            )
            changed = True
        self._prune_trend_samples()
        return changed

    def _prune_trend_samples(self) -> None:
        """Discard timestamped samples older than the trend retention period."""
        cutoff = dt_util.utcnow() - timedelta(days=TREND_RETENTION_DAYS)
        retained: list[TrendSample] = []
        for sample in self.trend_samples:
            parsed = dt_util.parse_datetime(sample.timestamp)
            if parsed is not None and parsed >= cutoff:
                retained.append(sample)
        self.trend_samples.clear()
        self._trend_lookup.clear()
        for sample in retained:
            self._append_trend_sample(sample)

    def _normalize_run(
        self, pipeline_id: str, run_id: str, events: list[Any]
    ) -> AssistRun:
        by_type: dict[str, Any] = {}
        error_event = None
        for event in events:
            event_type = self._event_type(event)
            by_type[event_type] = event
            if event_type == "error" and error_event is None:
                error_event = event

        run_start = by_type.get("run-start")
        run_end = by_type.get("run-end")
        stt_start = by_type.get("stt-start")
        stt_end = by_type.get("stt-end")
        intent_start = by_type.get("intent-start")
        intent_end = by_type.get("intent-end")
        tts_start = by_type.get("tts-start")
        tts_end = by_type.get("tts-end")
        first_intent_progress = self._first_event(events, "intent-progress")
        first_reaction = first_intent_progress or intent_end

        run_data = self._event_data(run_start)
        intent_start_data = self._event_data(intent_start)
        intent_end_data = self._event_data(intent_end)
        error_data = self._event_data(error_event)

        processed_locally = intent_end_data.get("processed_locally")
        if not isinstance(processed_locally, bool):
            processed_locally = None

        transcript = None
        response_text = None
        if self.include_text:
            transcript = (
                self._event_data(stt_end).get("stt_output") or {}
            ).get("text")
            response_text = self._event_data(tts_start).get("tts_input")

        return AssistRun(
            run_id=run_id,
            pipeline_id=run_data.get("pipeline", pipeline_id),
            started_at=self._event_timestamp(run_start),
            satellite_id=run_data.get("satellite_id")
            or intent_start_data.get("satellite_id"),
            device_id=intent_start_data.get("device_id"),
            stt_engine=self._event_data(stt_start).get("engine"),
            conversation_engine=intent_start_data.get("engine"),
            tts_engine=self._event_data(tts_start).get("engine"),
            pipeline_duration_ms=self._duration_ms(run_start, run_end),
            stt_duration_ms=self._duration_ms(stt_start, stt_end),
            intent_duration_ms=self._duration_ms(intent_start, intent_end),
            tts_orchestration_duration_ms=self._duration_ms(tts_start, tts_end),
            reaction_time_ms=self._duration_ms(stt_end, first_reaction),
            processed_locally=processed_locally,
            workflow_class=self._workflow_class(
                processed_locally,
                self._event_data(stt_start).get("engine"),
                self._event_data(tts_start).get("engine"),
            ),
            success=error_event is None,
            error_code=error_data.get("code"),
            error_message=error_data.get("message"),
            transcript=transcript,
            response_text=response_text,
        )

    @staticmethod
    def _event_type(event: Any) -> str:
        value = getattr(event, "type", "")
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def _event_data(event: Any | None) -> dict[str, Any]:
        if event is None:
            return {}
        data = getattr(event, "data", None)
        return data if isinstance(data, dict) else {}

    @classmethod
    def _first_event(cls, events: list[Any], event_type: str) -> Any | None:
        for event in events:
            if cls._event_type(event) == event_type:
                return event
        return None

    @staticmethod
    def _event_timestamp(event: Any | None) -> str | None:
        return getattr(event, "timestamp", None) if event is not None else None

    @staticmethod
    def _run_from_data(data: dict[str, Any]) -> AssistRun:
        valid_fields = {field.name for field in fields(AssistRun)}
        return AssistRun(**{key: value for key, value in data.items() if key in valid_fields})

    @classmethod
    def _duration_ms(cls, start: Any | None, end: Any | None) -> float | None:
        try:
            start_dt = dt_util.parse_datetime(cls._event_timestamp(start))
            end_dt = dt_util.parse_datetime(cls._event_timestamp(end))
            if start_dt is None or end_dt is None:
                return None
            return round((end_dt - start_dt).total_seconds() * 1000, 1)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _workflow_class(
        processed_locally: bool | None,
        stt_engine: str | None,
        tts_engine: str | None,
    ) -> str:
        # The installed OpenAI providers are known cloud stages. Unknown engines
        # stay unknown instead of being guessed from arbitrary names.
        stt_cloud = bool(stt_engine and "openai" in stt_engine.lower())
        tts_cloud = bool(tts_engine and "openai" in tts_engine.lower())
        if processed_locally is True and (stt_cloud or tts_cloud):
            return "hybrid"
        if processed_locally is False or stt_cloud or tts_cloud:
            return "cloud"
        if processed_locally is True and stt_engine is None and tts_engine is None:
            return "local_intent_only"
        return "unknown"

    @property
    def average_duration(self) -> float | None:
        return round(sum(self.durations) / len(self.durations), 1) if self.durations else None

    @property
    def p90_duration(self) -> float | None:
        return self._p90(self.durations)

    @staticmethod
    def _average(values: deque[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    @staticmethod
    def _p90(values: deque[float]) -> float | None:
        if not values:
            return None
        sorted_values = sorted(values)
        index = max(0, math.ceil(0.9 * len(sorted_values)) - 1)
        return round(sorted_values[index], 1)

    @property
    def local_average_duration(self) -> float | None:
        return self._average(self.local_durations)

    @property
    def local_p90_duration(self) -> float | None:
        return self._p90(self.local_durations)

    @property
    def external_average_duration(self) -> float | None:
        return self._average(self.external_durations)

    @property
    def external_p90_duration(self) -> float | None:
        return self._p90(self.external_durations)

    @property
    def local_average_reaction_time(self) -> float | None:
        return self._average(self.local_reaction_durations)

    @property
    def local_p90_reaction_time(self) -> float | None:
        return self._p90(self.local_reaction_durations)

    @property
    def external_average_reaction_time(self) -> float | None:
        return self._average(self.external_reaction_durations)

    @property
    def external_p90_reaction_time(self) -> float | None:
        return self._p90(self.external_reaction_durations)

    @property
    def error_rate(self) -> float:
        return round(self.error_runs / self.total_runs * 100, 1) if self.total_runs else 0.0

    @property
    def local_percentage(self) -> float:
        if not self.classified_intent_runs:
            return 0.0
        return round(self.local_runs / self.classified_intent_runs * 100, 1)

    @staticmethod
    def _daily_median(values: list[float]) -> float:
        """Return a robust daily center that is insensitive to burst size."""
        return round(float(median(values)), 1)

    def _trend_for_class(self, processed_locally: bool) -> dict[str, Any] | None:
        """Calculate equal-day-weighted trend for local or external runs."""
        daily_values: dict[str, list[float]] = {}
        sample_count = 0
        for sample in self.trend_samples:
            if (
                not sample.success
                or sample.processed_locally is not processed_locally
                or sample.reaction_time_ms is None
            ):
                continue
            parsed = dt_util.parse_datetime(sample.timestamp)
            if parsed is None:
                continue
            day = dt_util.as_local(parsed).date().isoformat()
            daily_values.setdefault(day, []).append(sample.reaction_time_ms)
            sample_count += 1

        eligible_days = [
            (day, self._daily_median(values), len(values))
            for day, values in sorted(daily_values.items())
            if len(values) >= TREND_MIN_SAMPLES_PER_DAY_AND_CLASS
        ]
        if len(eligible_days) < (TREND_MIN_CURRENT_DAYS + TREND_MIN_BASELINE_DAYS):
            return None

        current_day_count = min(
            TREND_CURRENT_ACTIVE_DAYS,
            len(eligible_days) - TREND_MIN_BASELINE_DAYS,
        )
        current_days = eligible_days[-current_day_count:]
        baseline_days = eligible_days[
            -(current_day_count + TREND_BASELINE_ACTIVE_DAYS) : -current_day_count
        ]
        if len(baseline_days) < TREND_MIN_BASELINE_DAYS:
            return None

        current_average = fmean(item[1] for item in current_days)
        baseline_average = fmean(item[1] for item in baseline_days)
        if baseline_average <= 0:
            return None
        return {
            "current_average_ms": round(current_average, 1),
            "baseline_average_ms": round(baseline_average, 1),
            "trend_percent": round(
                (current_average - baseline_average) / baseline_average * 100, 1
            ),
            "current_active_days": len(current_days),
            "baseline_active_days": len(baseline_days),
            "current_samples": sum(item[2] for item in current_days),
            "baseline_samples": sum(item[2] for item in baseline_days),
            "available_samples": sample_count,
        }

    @property
    def trend_summary(self) -> dict[str, Any]:
        """Return a usage-normalized trend with fixed workflow weighting."""
        class_results = {
            "local": self._trend_for_class(True),
            "external": self._trend_for_class(False),
        }
        usable = {key: value for key, value in class_results.items() if value}
        if not usable:
            return {
                "status": "insufficient_data",
                "trend_percent": None,
                "current_average_ms": None,
                "baseline_average_ms": None,
                "classes": class_results,
            }

        current_average = fmean(
            result["current_average_ms"] for result in usable.values()
        )
        baseline_average = fmean(
            result["baseline_average_ms"] for result in usable.values()
        )
        trend_percent = fmean(
            result["trend_percent"] for result in usable.values()
        )
        if trend_percent < -TREND_NEUTRAL_PERCENT:
            status = "faster"
        elif trend_percent > TREND_NEUTRAL_PERCENT:
            status = "slower"
        else:
            status = "stable"
        return {
            "status": status,
            "trend_percent": round(trend_percent, 1),
            "current_average_ms": round(current_average, 1),
            "baseline_average_ms": round(baseline_average, 1),
            "coverage": "full" if len(usable) == 2 else "partial",
            "classes": class_results,
        }

    def _serialize(self) -> dict[str, Any]:
        self._prune_trend_samples()
        return {
            "total_runs": self.total_runs,
            "error_runs": self.error_runs,
            "local_runs": self.local_runs,
            "classified_intent_runs": self.classified_intent_runs,
            "durations": list(self.durations),
            "local_durations": list(self.local_durations),
            "external_durations": list(self.external_durations),
            "local_reaction_durations": list(self.local_reaction_durations),
            "external_reaction_durations": list(self.external_reaction_durations),
            "seen_ids": list(self.seen_ids),
            "recent_runs": [asdict(run) for run in self.recent_runs],
            "last_run": asdict(self.last_run) if self.last_run else None,
            "trend_samples": [asdict(sample) for sample in self.trend_samples],
        }
