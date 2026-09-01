"""Provider for petrol.lu -- the GPL official maximum price table.

Source: https://www.petrol.lu/en/official-prices/

The page renders a single HTML table with two rows per effective date (``TVAC`` =
incl. VAT, ``HTVA`` = excl. VAT) and one column per petroleum product. Rows can be
future-dated once the Ministry of the Economy publishes the next day's prices.

There is no public API, so this scrapes the page politely: a descriptive
User-Agent, a short in-memory cache, and a low refresh cadence set by the
coordinator.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from aiohttp import ClientError, ClientSession

from ..const import VAT_RATE_LU
from ..models import FuelType, PricePoint
from .base import FuelProvider, ProviderConnectionError, ProviderParseError

_LOGGER = logging.getLogger(__name__)

SOURCE_URL = "https://www.petrol.lu/en/official-prices/"
_USER_AGENT = (
    "HomeAssistant-LuxFuelMonitor/0.1 "
    "(+https://github.com/dabo53ck/home-assistant-luxembourg-fuel-monitor)"
)
_REQUEST_TIMEOUT = 30
_CACHE_TTL = 300  # seconds

_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_VAT_DECIMAL = Decimal("1") + Decimal(str(VAT_RATE_LU))

# Header substrings -> fuel. Order matters: check "98"/"95" before generic terms.
_HEADER_MATCHERS: tuple[tuple[str, FuelType], ...] = (
    ("98", FuelType.SP98),
    ("95", FuelType.SP95),
    ("diesel", FuelType.DIESEL),
    ("gazole", FuelType.DIESEL),
)
# Fallback column order if the header cannot be read (date is column 0).
_DEFAULT_COLUMNS: dict[FuelType, int] = {
    FuelType.SP98: 1,
    FuelType.SP95: 2,
    FuelType.DIESEL: 3,
}


class PetrolLuProvider(FuelProvider):
    """Scraper for the petrol.lu official maximum price table."""

    key = "petrol_lu"
    name = "petrol.lu (Groupement Pétrolier Luxembourgeois)"
    source_url = SOURCE_URL
    attribution = "Official maximum prices published by petrol.lu (GPL)"

    def __init__(self, session: ClientSession) -> None:
        """Store the shared aiohttp session."""
        self._session = session
        self._cache: list[PricePoint] | None = None
        self._cache_at: float = 0.0
        self._lock = asyncio.Lock()

    async def async_get_history(self, since: date | None = None) -> list[PricePoint]:
        """Fetch and parse the full price history (cached for a few minutes)."""
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._cache is None or now - self._cache_at > _CACHE_TTL:
                html = await self._async_fetch()
                self._cache = _parse_history(html)
                self._cache_at = now
            history = self._cache

        if since is not None:
            return [p for p in history if p.effective_date >= since]
        return list(history)

    async def _async_fetch(self) -> str:
        """GET the price page."""
        try:
            async with self._session.get(
                SOURCE_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    raise ProviderConnectionError(
                        f"petrol.lu returned HTTP {response.status}"
                    )
                return await response.text()
        except (ClientError, asyncio.TimeoutError) as err:
            raise ProviderConnectionError(f"Could not reach petrol.lu: {err}") from err


def _parse_history(html: str) -> list[PricePoint]:
    """Parse the official price table out of the page HTML."""
    # Imported lazily so the module imports without the requirement installed
    # (e.g. during tooling that only reads manifests).
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(html, "html.parser")
    table = _find_price_table(soup)
    if table is None:
        raise ProviderParseError("Could not locate the price table on petrol.lu")

    rows = table.find_all("tr")
    columns = _resolve_columns(rows)

    # date -> vat kind -> fuel -> Decimal
    grouped: dict[date, dict[str, dict[FuelType, Decimal]]] = {}
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            continue
        day = _parse_date(cells[0])
        if day is None:
            continue
        vat_kind = _row_vat_kind(cells)
        bucket = grouped.setdefault(day, {}).setdefault(vat_kind, {})
        for fuel, index in columns.items():
            if index >= len(cells):
                continue
            value = _parse_decimal(cells[index])
            if value is not None:
                bucket[fuel] = value

    points = _build_points(grouped)
    if not points:
        raise ProviderParseError("Price table on petrol.lu contained no usable rows")
    return sorted(points, key=lambda p: (p.effective_date, p.fuel.value))


def _find_price_table(soup):  # type: ignore[no-untyped-def]
    """Return the <table> that holds the fuel prices, or None."""
    best = None
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True).lower()
        if "diesel" in text and ("95" in text or "super" in text):
            # Prefer the table with the most date-looking rows.
            score = len(_DATE_RE.findall(text))
            if best is None or score > best[0]:
                best = (score, table)
    return best[1] if best else None


def _resolve_columns(rows) -> dict[FuelType, int]:  # type: ignore[no-untyped-def]
    """Map each fuel to its column index, from the header if possible."""
    for row in rows:
        header_cells = [c.get_text(" ", strip=True).lower() for c in row.find_all(["th", "td"])]
        if not header_cells or _parse_date(header_cells[0] if header_cells else ""):
            continue
        resolved: dict[FuelType, int] = {}
        for idx, text in enumerate(header_cells):
            for needle, fuel in _HEADER_MATCHERS:
                if needle in text and fuel not in resolved:
                    resolved[fuel] = idx
        if FuelType.DIESEL in resolved and FuelType.SP95 in resolved:
            return resolved
    _LOGGER.debug("petrol.lu: header not recognised, using default column order")
    return dict(_DEFAULT_COLUMNS)


def _row_vat_kind(cells: list[str]) -> str:
    """Classify a row as incl. ('incl') or excl. ('excl') VAT."""
    joined = " ".join(cells).lower()
    if "htva" in joined or "hors tva" in joined or "excl" in joined:
        return "excl"
    if "tvac" in joined or "ttc" in joined or "incl" in joined:
        return "incl"
    return "incl"


def _parse_date(text: str) -> date | None:
    """Parse a ``DD/MM/YYYY`` date, or return None."""
    match = _DATE_RE.search(text)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_decimal(text: str) -> Decimal | None:
    """Parse a European-formatted price cell, or return None for blanks/dashes."""
    cleaned = text.replace("\xa0", "").replace(" ", "").replace("€", "").strip()
    if not cleaned or cleaned in {"-", "--", "n/a", "N/A"}:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _build_points(
    grouped: dict[date, dict[str, dict[FuelType, Decimal]]],
) -> list[PricePoint]:
    """Combine the incl./excl. VAT rows for each date into PricePoints."""
    points: list[PricePoint] = []
    for day, kinds in grouped.items():
        incl = kinds.get("incl", {})
        excl = kinds.get("excl", {})
        for fuel in set(incl) | set(excl):
            price_incl = incl.get(fuel)
            price_excl = excl.get(fuel)
            if price_incl is None and price_excl is not None:
                price_incl = (price_excl * _VAT_DECIMAL).quantize(Decimal("0.0001"))
            if price_excl is None and price_incl is not None:
                price_excl = (price_incl / _VAT_DECIMAL).quantize(Decimal("0.0001"))
            if price_incl is None or price_excl is None:
                continue
            points.append(
                PricePoint(
                    effective_date=day,
                    fuel=fuel,
                    price_incl_vat=price_incl,
                    price_excl_vat=price_excl,
                )
            )
    return points
