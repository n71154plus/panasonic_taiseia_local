"""Left-Riemann energy integration from operating power (W → kWh)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ENERGY_CYCLE,
    CONF_ENERGY_CYCLE_DAYS,
    CONF_ENERGY_RESET_DAY,
    CONF_ENERGY_RESET_WEEKDAY,
    DEFAULT_ENERGY_CYCLE,
    DEFAULT_ENERGY_CYCLE_DAYS,
    DEFAULT_ENERGY_RESET_DAY,
    DEFAULT_ENERGY_RESET_WEEKDAY,
    DOMAIN,
    ENERGY_CYCLE_DAILY,
    ENERGY_CYCLE_DAYS,
    ENERGY_CYCLE_MONTHLY,
    ENERGY_CYCLE_NONE,
    ENERGY_CYCLE_WEEKLY,
    ENERGY_CYCLE_YEARLY,
)

_LOGGER = logging.getLogger(__package__)

STORAGE_VERSION = 1
SETTINGS_VERSION = 1
_MAX_DT_HOURS = 2.0
# Fixed epoch for N-day rolling periods (local calendar dates)
_DAYS_EPOCH = date(2020, 1, 1)

CYCLE_LABELS = {
    ENERGY_CYCLE_MONTHLY: "本月耗電",
    ENERGY_CYCLE_DAILY: "本日耗電",
    ENERGY_CYCLE_WEEKLY: "本週耗電",
    ENERGY_CYCLE_YEARLY: "本年耗電",
    ENERGY_CYCLE_DAYS: "週期耗電",
    ENERGY_CYCLE_NONE: "本期耗電",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local(when: datetime) -> datetime:
    return when.astimezone()


def period_key(
    when: datetime,
    *,
    cycle: str,
    reset_day: int = 1,
    reset_weekday: int = 0,
    cycle_days: int = DEFAULT_ENERGY_CYCLE_DAYS,
) -> str:
    """Return opaque key for the billing period containing ``when`` (local TZ)."""
    local = _local(when)
    cycle = cycle or DEFAULT_ENERGY_CYCLE
    reset_day = max(1, min(28, int(reset_day or 1)))
    reset_weekday = int(reset_weekday) % 7  # 0=Mon … 6=Sun
    cycle_days = max(1, min(365, int(cycle_days or DEFAULT_ENERGY_CYCLE_DAYS)))

    if cycle == ENERGY_CYCLE_NONE:
        return "all"

    if cycle == ENERGY_CYCLE_DAILY:
        return local.strftime("%Y-%m-%d")

    if cycle == ENERGY_CYCLE_YEARLY:
        return f"{local.year:04d}"

    if cycle == ENERGY_CYCLE_WEEKLY:
        offset = (local.weekday() - reset_weekday) % 7
        start = (local - timedelta(days=offset)).date()
        return start.isoformat()

    if cycle == ENERGY_CYCLE_DAYS:
        day_num = (local.date() - _DAYS_EPOCH).days
        idx = day_num // cycle_days
        start = _DAYS_EPOCH + timedelta(days=idx * cycle_days)
        return f"{start.isoformat()}+{cycle_days}d"

    # monthly — billing month starts on reset_day
    if local.day >= reset_day:
        start = local.replace(day=reset_day, hour=0, minute=0, second=0, microsecond=0)
    else:
        first = local.replace(day=1)
        prev_last = first - timedelta(days=1)
        start = prev_last.replace(
            day=min(reset_day, prev_last.day),
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    return start.strftime("%Y-%m-%d")


def period_label(cycle: str, cycle_days: int | None = None) -> str:
    if cycle == ENERGY_CYCLE_DAYS:
        n = max(1, int(cycle_days or DEFAULT_ENERGY_CYCLE_DAYS))
        return f"{n}天週期耗電"
    return CYCLE_LABELS.get(cycle or DEFAULT_ENERGY_CYCLE, "本期耗電")


@dataclass
class EnergySettings:
    cycle: str = DEFAULT_ENERGY_CYCLE
    reset_day: int = DEFAULT_ENERGY_RESET_DAY
    reset_weekday: int = DEFAULT_ENERGY_RESET_WEEKDAY
    cycle_days: int = DEFAULT_ENERGY_CYCLE_DAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            CONF_ENERGY_CYCLE: self.cycle,
            CONF_ENERGY_RESET_DAY: self.reset_day,
            CONF_ENERGY_RESET_WEEKDAY: self.reset_weekday,
            CONF_ENERGY_CYCLE_DAYS: self.cycle_days,
        }


async def async_get_energy_settings(hass: HomeAssistant) -> EnergySettings:
    store = Store(hass, SETTINGS_VERSION, f"{DOMAIN}_energy_settings")
    raw = await store.async_load()
    if not isinstance(raw, dict):
        return EnergySettings()
    cycle = str(raw.get(CONF_ENERGY_CYCLE) or DEFAULT_ENERGY_CYCLE)
    if cycle not in CYCLE_LABELS:
        cycle = DEFAULT_ENERGY_CYCLE
    try:
        reset_day = int(raw.get(CONF_ENERGY_RESET_DAY) or DEFAULT_ENERGY_RESET_DAY)
    except (TypeError, ValueError):
        reset_day = DEFAULT_ENERGY_RESET_DAY
    try:
        reset_weekday = int(
            raw.get(CONF_ENERGY_RESET_WEEKDAY) or DEFAULT_ENERGY_RESET_WEEKDAY
        )
    except (TypeError, ValueError):
        reset_weekday = DEFAULT_ENERGY_RESET_WEEKDAY
    try:
        cycle_days = int(
            raw.get(CONF_ENERGY_CYCLE_DAYS) or DEFAULT_ENERGY_CYCLE_DAYS
        )
    except (TypeError, ValueError):
        cycle_days = DEFAULT_ENERGY_CYCLE_DAYS
    return EnergySettings(
        cycle=cycle,
        reset_day=max(1, min(28, reset_day)),
        reset_weekday=reset_weekday % 7,
        cycle_days=max(1, min(365, cycle_days)),
    )


async def async_save_energy_settings(
    hass: HomeAssistant, settings: EnergySettings
) -> None:
    store = Store(hass, SETTINGS_VERSION, f"{DOMAIN}_energy_settings")
    await store.async_save(settings.as_dict())


@dataclass
class EnergyTracker:
    """Accumulate energy from successive power samples (left Riemann)."""

    total_kwh: float = 0.0
    period_kwh: float = 0.0
    period_key: str = ""
    last_power_w: float | None = None
    last_ts: datetime | None = None
    settings: EnergySettings = field(default_factory=EnergySettings)
    _dirty: bool = False

    @property
    def month_kwh(self) -> float:
        return self.period_kwh

    @property
    def month_key(self) -> str:
        return self.period_key

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_kwh": self.total_kwh,
            "period_kwh": self.period_kwh,
            "period_key": self.period_key,
            "month_kwh": self.period_kwh,
            "month_key": self.period_key,
            "last_power_w": self.last_power_w,
            "last_ts": self.last_ts.isoformat() if self.last_ts else None,
        }

    def load_dict(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        try:
            self.total_kwh = float(data.get("total_kwh") or 0.0)
            self.period_kwh = float(
                data.get("period_kwh", data.get("month_kwh")) or 0.0
            )
            self.period_key = str(
                data.get("period_key") or data.get("month_key") or ""
            )
            lp = data.get("last_power_w")
            self.last_power_w = float(lp) if lp is not None else None
            ts = data.get("last_ts")
            if ts:
                self.last_ts = datetime.fromisoformat(ts)
                if self.last_ts.tzinfo is None:
                    self.last_ts = self.last_ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as err:
            _LOGGER.warning("Bad energy store data, starting fresh: %s", err)

    def apply_settings(self, settings: EnergySettings) -> None:
        self.settings = settings

    def _period_key_now(self, now: datetime) -> str:
        return period_key(
            now,
            cycle=self.settings.cycle,
            reset_day=self.settings.reset_day,
            reset_weekday=self.settings.reset_weekday,
            cycle_days=self.settings.cycle_days,
        )

    def ensure_period(self, now: datetime | None = None) -> None:
        now = now or _utcnow()
        key = self._period_key_now(now)
        if not self.period_key:
            self.period_key = key
            self._dirty = True
            return
        if key == self.period_key:
            return
        _LOGGER.info(
            "Energy period roll-over %s → %s (was %.3f kWh, cycle=%s)",
            self.period_key,
            key,
            self.period_kwh,
            self.settings.cycle,
        )
        self.period_key = key
        self.period_kwh = 0.0
        self._dirty = True

    def reset_period(self) -> None:
        self.period_kwh = 0.0
        self.period_key = self._period_key_now(_utcnow())
        self._dirty = True

    def reset_total(self) -> None:
        self.total_kwh = 0.0
        self._dirty = True

    def update(self, power_w: float | None, now: datetime | None = None) -> float:
        """Integrate previous power over elapsed time; return period_kwh."""
        now = now or _utcnow()
        self.ensure_period(now)

        if (
            self.last_ts is not None
            and self.last_power_w is not None
            and power_w is not None
        ):
            dt_h = (now - self.last_ts).total_seconds() / 3600.0
            if 0 < dt_h <= _MAX_DT_HOURS:
                delta = self.last_power_w * dt_h / 1000.0
                if delta > 0:
                    self.total_kwh += delta
                    self.period_kwh += delta
                    self._dirty = True

        if power_w is not None:
            self.last_power_w = float(power_w)
            self.last_ts = now
            self._dirty = True

        return self.period_kwh


def _store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}_energy_{entry_id}")


async def async_load_tracker(
    hass: HomeAssistant, entry_id: str, settings: EnergySettings | None = None
) -> EnergyTracker:
    tracker = EnergyTracker()
    tracker.apply_settings(settings or await async_get_energy_settings(hass))
    data = await _store(hass, entry_id).async_load()
    if isinstance(data, dict):
        tracker.load_dict(data)
    tracker.ensure_period(_utcnow())
    return tracker


async def async_save_tracker(
    hass: HomeAssistant, entry_id: str, tracker: EnergyTracker
) -> None:
    if not tracker._dirty:  # noqa: SLF001
        return
    await _store(hass, entry_id).async_save(tracker.as_dict())
    tracker._dirty = False  # noqa: SLF001
