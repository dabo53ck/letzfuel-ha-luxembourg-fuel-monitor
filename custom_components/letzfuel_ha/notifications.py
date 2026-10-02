"""Built-in phone notifications, one set of settings per notification target.

Each target is a config subentry (see config_flow.py). The coordinator hands
over the price events it fires and every successful update; this module turns
them into Companion app notifications, with the same texts, tags and payload
the notifications blueprint uses.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .analytics import refuel_recommendation
from .const import (
    BRAND_ICON_URL,
    DOMAIN,
    FUEL_CHOICE_PRIMARY,
    NOTIFY_ANNOUNCED,
    NOTIFY_COUNTDOWN,
    NOTIFY_DEVICES,
    NOTIFY_EFFECTIVE,
    NOTIFY_GROUP,
    NOTIFY_LANGUAGE,
    NOTIFY_PRESENCE,
    NOTIFY_RECOMMENDATION,
    NOTIFY_TAP_PATH,
    NOTIFY_THRESHOLD,
    PRIORITY_CRITICAL,
    PRIORITY_ELEVATED,
    RECOMMENDATION_NO_CHANGE,
    RECOMMENDATION_REFUEL_TODAY,
    SUBENTRY_NOTIFICATION,
)
from .models import FUEL_LABELS, FuelType, PriceSet
from .notification_texts import SUPPORTED_LANGUAGES, TEXTS

if TYPE_CHECKING:
    from .coordinator import LuxFuelCoordinator

_LOGGER = logging.getLogger(__name__)
_STORE_VERSION = 1

TAG_ANNOUNCED = "letzfuel_announced"
TAG_EFFECTIVE = "letzfuel_effective"
TAG_RECOMMENDATION = "letzfuel_recommendation"
TAG_THRESHOLD = "letzfuel_threshold"
TAG_COUNTDOWN = "letzfuel_countdown"


def default_language(hass: HomeAssistant) -> str:
    """Home Assistant's language if there are texts for it, else English."""
    code = (hass.config.language or "en").split("-")[0].lower()
    return code if code in SUPPORTED_LANGUAGES else "en"


def texts(language: str) -> Mapping[str, Any]:
    return TEXTS.get(language, TEXTS["en"])


# -- formatting (pure) --------------------------------------------------------


def _price(value: float, decimal: str) -> str:
    return f"{value:.3f}".replace(".", decimal)


def _cents(delta: float, decimal: str) -> str:
    return str(round(abs(delta) * 100, 1)).replace(".", decimal)


def _sign(delta: float) -> str:
    return "+" if delta > 0 else "-"


def _date(iso: str) -> str:
    """YYYY-MM-DD to Luxembourg's DD/MM/YYYY."""
    year, month, day = iso.split("-")
    return f"{day}/{month}/{year}"


def _fuel_name(fuel: str) -> str:
    return fuel.upper()


def _wanted(choice: list[str], primary: FuelType) -> set[str]:
    return {primary.value if f == FUEL_CHOICE_PRIMARY else f for f in choice}


def _passes(section: Mapping[str, Any], delta: float) -> bool:
    direction = section.get("direction", "both")
    if direction == "up" and delta <= 0:
        return False
    if direction == "down" and delta >= 0:
        return False
    return abs(delta) >= float(section.get("min_delta", 0) or 0)


def announced_lines(
    changes: list[Mapping[str, Any]],
    section: Mapping[str, Any],
    primary: FuelType,
    language: str,
) -> list[str]:
    """One line per announced change the target wants to hear about."""
    t = texts(language)
    want = _wanted(section.get("fuels", [FUEL_CHOICE_PRIMARY]), primary)
    lines = []
    for c in changes:
        delta = float(c["delta"])
        if c["fuel"] in want and _passes(section, delta):
            lines.append(
                f"{_fuel_name(c['fuel'])}: {_sign(delta)}{_cents(delta, t['decimal'])}"
                f" ct/L → {_price(float(c['upcoming_price']), t['decimal'])} €/L"
                f" ({_date(c['effective_date'])})"
            )
    return lines


def effective_lines(
    changes: list[Mapping[str, Any]],
    section: Mapping[str, Any],
    primary: FuelType,
    language: str,
) -> list[str]:
    t = texts(language)
    want = _wanted(section.get("fuels", [FUEL_CHOICE_PRIMARY]), primary)
    lines = []
    for c in changes:
        delta = float(c["new_price"]) - float(c["old_price"])
        if c["fuel"] in want and _passes(section, delta):
            lines.append(
                f"{_fuel_name(c['fuel'])}: {_price(float(c['new_price']), t['decimal'])}"
                f" €/L ({_sign(delta)}{_cents(delta, t['decimal'])} ct/L)"
            )
    return lines


def corrected_lines(
    changes: list[Mapping[str, Any]],
    section: Mapping[str, Any],
    primary: FuelType,
    language: str,
) -> list[str]:
    """Corrections only for announcements this target was actually sent."""
    t = texts(language)
    want = _wanted(section.get("fuels", [FUEL_CHOICE_PRIMARY]), primary)
    lines = []
    for c in changes:
        base = float(c["current_price"])
        announced = float(c["announced_price"])
        corrected = float(c["corrected_price"])
        if c["fuel"] not in want or not _passes(section, announced - base):
            continue
        delta = corrected - base
        change = (
            t["no_change"]
            if abs(delta) < 0.0005
            else f"{_sign(delta)}{_cents(delta, t['decimal'])} ct/L"
        )
        lines.append(
            f"{_fuel_name(c['fuel'])}: {_price(corrected, t['decimal'])} €/L ({change})"
            f" {t['instead_of']} {_price(announced, t['decimal'])} €/L"
            f" ({_date(c['effective_date'])})"
        )
    return lines


def payload(tag: str, priority: str, tap: Mapping[str, Any]) -> dict[str, Any]:
    """Companion app `data` for a notification, like the blueprint's."""
    data: dict[str, Any] = {
        "tag": tag,
        "group": NOTIFY_GROUP,
        "icon_url": BRAND_ICON_URL,
        "push": {"thread-id": NOTIFY_GROUP},
        **tap,
    }
    if priority == PRIORITY_ELEVATED:
        data.update(importance="high", priority="high", ttl=0)
        data["push"]["interruption-level"] = "time-sensitive"
    elif priority == PRIORITY_CRITICAL:
        data.update(channel="alarm_stream", importance="high", priority="high", ttl=0)
        data["push"]["interruption-level"] = "critical"
        data["push"]["sound"] = {"name": "default", "critical": 1, "volume": 1.0}
    return data


# -- the notifier ----------------------------------------------------------------


class Notifier:
    """Sends the notifications of every notification target of an entry."""

    def __init__(self, hass: HomeAssistant, coordinator: LuxFuelCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        entry_id = coordinator.config_entry.entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORE_VERSION, f"{DOMAIN}.{entry_id}.notifications"
        )
        #: Per target: last recommendation seen, countdown running, and per
        #: fuel whether the price was below the threshold.
        self._state: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        self._state = await self._store.async_load() or {}

    @property
    def targets(self) -> list[ConfigSubentry]:
        return [
            sub
            for sub in self.coordinator.config_entry.subentries.values()
            if sub.subentry_type == SUBENTRY_NOTIFICATION
        ]

    # -- entry points --------------------------------------------------------

    async def async_handle_events(
        self,
        announced: list[dict[str, Any]],
        changed: list[dict[str, Any]],
        corrected: list[dict[str, Any]],
    ) -> None:
        """Notify about the price events the coordinator just fired."""
        primary = self.coordinator.primary_fuel
        for target in self.targets:
            data = target.data
            lang = data.get(NOTIFY_LANGUAGE, "en")
            t = texts(lang)
            ann = data.get(NOTIFY_ANNOUNCED, {})
            eff = data.get(NOTIFY_EFFECTIVE, {})
            if ann.get("enabled") and announced:
                lines = announced_lines(announced, ann, primary, lang)
                if lines:
                    await self._send(
                        target,
                        t["announced_title"],
                        lines,
                        TAG_ANNOUNCED,
                        ann,
                        self._fuel_tap(target, lines_fuel(announced, ann, primary)),
                    )
            if ann.get("enabled") and corrected:
                lines = corrected_lines(corrected, ann, primary, lang)
                if lines:
                    await self._send(
                        target,
                        t["corrected_title"],
                        lines,
                        TAG_ANNOUNCED,
                        ann,
                        self._fuel_tap(target, lines_fuel(corrected, ann, primary)),
                    )
            if eff.get("enabled") and changed:
                lines = effective_lines(changed, eff, primary, lang)
                if lines:
                    await self._send(
                        target,
                        t["effective_title"],
                        lines,
                        TAG_EFFECTIVE,
                        eff,
                        self._fuel_tap(target, lines_fuel(changed, eff, primary)),
                    )

    async def async_handle_update(self, price_set: PriceSet) -> None:
        """Recommendation, live countdown and threshold after each update."""
        coordinator = self.coordinator
        primary = coordinator.primary_fuel
        recommendation = refuel_recommendation(price_set.prices.get(primary))
        known = {target.subentry_id for target in self.targets}
        changed = False
        for stale in set(self._state) - known:
            del self._state[stale]
            changed = True

        for target in self.targets:
            state = self._state.setdefault(target.subentry_id, {})
            previous = state.get("recommendation")
            if previous is None:
                state["recommendation"] = recommendation  # first sight: no alert
                changed = True
            elif previous != recommendation:
                await self._recommendation(target, previous, recommendation)
                state["recommendation"] = recommendation
                changed = True
            changed |= await self._threshold(target, state, price_set, primary)

        if changed:
            await self._store.async_save(self._state)

    # -- types -----------------------------------------------------------------

    async def _recommendation(
        self, target: ConfigSubentry, previous: str, current: str
    ) -> None:
        data = target.data
        t = texts(data.get(NOTIFY_LANGUAGE, "en"))
        rec = data.get(NOTIFY_RECOMMENDATION, {})
        wanted = current in rec.get("states", [RECOMMENDATION_REFUEL_TODAY]) or (
            rec.get("no_change") and current == RECOMMENDATION_NO_CHANGE
        )
        if rec.get("enabled") and wanted:
            await self._send(
                target,
                t["rec_title"],
                [t["rec_states"].get(current, current)],
                TAG_RECOMMENDATION,
                rec,
                self._entity_tap(target, self._rec_entity()),
            )
        if not data.get(NOTIFY_COUNTDOWN, {}).get("enabled"):
            return
        if current == RECOMMENDATION_REFUEL_TODAY:
            now = dt_util.now()
            midnight = dt_util.start_of_local_day(now + timedelta(days=1))
            await self._deliver(
                target,
                {
                    "title": t["rec_title"],
                    "message": t["rec_states"][RECOMMENDATION_REFUEL_TODAY],
                    "data": {
                        "tag": TAG_COUNTDOWN,
                        "live_update": True,
                        "chronometer": True,
                        "when_relative": True,
                        "when": int((midnight - now).total_seconds()),
                        "notification_icon": "mdi:gas-station",
                        **self._entity_tap(target, self._rec_entity()),
                    },
                },
            )
        elif previous == RECOMMENDATION_REFUEL_TODAY:
            await self._deliver(
                target,
                {"message": "clear_notification", "data": {"tag": TAG_COUNTDOWN}},
            )

    async def _threshold(
        self,
        target: ConfigSubentry,
        state: dict[str, Any],
        price_set: PriceSet,
        primary: FuelType,
    ) -> bool:
        """Notify once when a price drops below the target; True if state changed."""
        section = target.data.get(NOTIFY_THRESHOLD, {})
        limit = float(section.get("below", 0) or 0)
        if not section.get("enabled") or limit <= 0:
            if "below" in state:
                state.pop("below")
                state.pop("limit", None)
                return True
            return False
        if state.get("limit") != limit:
            state["limit"], state["below"] = limit, {}
        below_state: dict[str, bool] = state.setdefault("below", {})
        t = texts(target.data.get(NOTIFY_LANGUAGE, "en"))
        changed = False
        for fuel in sorted(
            _wanted(section.get("fuels", [FUEL_CHOICE_PRIMARY]), primary)
        ):
            fp = price_set.prices.get(FuelType(fuel))
            price = self.coordinator.display_price(fp.current) if fp else None
            if price is None:
                continue
            below = price < limit
            was = below_state.get(fuel)
            if was is None or was != below:
                below_state[fuel] = below
                changed = True
            if below and was is False:
                message = t["threshold_message"].format(
                    name=FUEL_LABELS[FuelType(fuel)],
                    price=_price(price, t["decimal"]),
                    target=_price(limit, t["decimal"]),
                )
                await self._send(
                    target,
                    t["threshold_title"],
                    [message],
                    TAG_THRESHOLD,
                    section,
                    self._fuel_tap(target, fuel),
                )
        return changed

    # -- delivery --------------------------------------------------------------

    async def _send(
        self,
        target: ConfigSubentry,
        title: str,
        lines: list[str],
        tag: str,
        section: Mapping[str, Any],
        tap: Mapping[str, Any],
    ) -> None:
        priority = section.get("priority", "normal")
        if not self._presence_ok(target, priority):
            return
        await self._deliver(
            target,
            {
                "title": title,
                "message": "\n".join(lines),
                "data": payload(tag, priority, tap),
            },
        )

    async def _deliver(
        self, target: ConfigSubentry, service_data: dict[str, Any]
    ) -> None:
        for service in self._services(target):
            try:
                await self.hass.services.async_call(
                    "notify", service, service_data, blocking=True
                )
            except Exception:  # one phone must not stop the others
                _LOGGER.warning(
                    "Could not send a notification via notify.%s",
                    service,
                    exc_info=True,
                )

    def _presence_ok(self, target: ConfigSubentry, priority: str) -> bool:
        presence = target.data.get(NOTIFY_PRESENCE, {})
        entity_id = presence.get("entity")
        if not entity_id:
            return True
        if priority == PRIORITY_CRITICAL and presence.get("critical_overrides", True):
            return True
        home = self.hass.states.is_state(entity_id, "home")
        return home if presence.get("mode", "home") == "home" else not home

    def _services(self, target: ConfigSubentry) -> list[str]:
        """notify.mobile_app_<slug> for each picked Companion app device."""
        registry = er.async_get(self.hass)
        services: list[str] = []
        for device_id in target.data.get(NOTIFY_DEVICES, []):
            for entry in er.async_entries_for_device(registry, device_id):
                if entry.domain != "notify" or entry.platform != "mobile_app":
                    continue
                service = f"mobile_app_{entry.entity_id.split('.', 1)[1]}"
                if self.hass.services.has_service("notify", service):
                    services.append(service)
                else:
                    _LOGGER.warning("notify.%s does not exist", service)
        return list(dict.fromkeys(services))

    # -- tap targets -------------------------------------------------------------

    def _entity_id(self, suffix: str) -> str | None:
        unique_id = f"{self.coordinator.config_entry.entry_id}_{suffix}"
        return er.async_get(self.hass).async_get_entity_id("sensor", DOMAIN, unique_id)

    def _rec_entity(self) -> str | None:
        return self._entity_id("refuel_recommendation")

    def _entity_tap(
        self, target: ConfigSubentry, entity_id: str | None
    ) -> dict[str, str]:
        path = (target.data.get(NOTIFY_TAP_PATH) or "").strip()
        if path:
            return {"url": path, "clickAction": path}
        if entity_id is None:
            return {}
        return {"entity_id": entity_id, "clickAction": f"entityId:{entity_id}"}

    def _fuel_tap(self, target: ConfigSubentry, fuel: str | None) -> dict[str, str]:
        entity_id = self._entity_id(f"{fuel}_price") if fuel else None
        return self._entity_tap(target, entity_id or self._rec_entity())


def lines_fuel(
    changes: list[Mapping[str, Any]], section: Mapping[str, Any], primary: FuelType
) -> str | None:
    """The first fuel of ``changes`` the section selects (for the tap target)."""
    want = _wanted(section.get("fuels", [FUEL_CHOICE_PRIMARY]), primary)
    return next((c["fuel"] for c in changes if c["fuel"] in want), None)
