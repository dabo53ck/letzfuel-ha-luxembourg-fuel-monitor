"""Shared test helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from custom_components.letzfuel_ha.models import FuelType

_COLUMNS = (FuelType.SP98, FuelType.SP95, FuelType.DIESEL)

PriceMap = dict[FuelType, tuple[Decimal | None, Decimal | None]]


def _fmt(value: Decimal | None) -> str:
    return "-" if value is None else f"{value}"


def build_petrol_lu_html(entries: list[tuple[date, PriceMap]]) -> str:
    """Render a petrol.lu-shaped price table.

    ``entries`` is ``[(effective_date, {fuel: (incl_vat, excl_vat)}), ...]``.
    """
    header = (
        "<tr><th>Date</th><th>Super 98 oct.</th><th>Super 95 oct.</th>"
        "<th>Diesel</th><th>Gasoil chauffage</th><th>Gasoil chauff. BTS</th>"
        "<th>TVA</th></tr>"
    )
    rows = [header]
    for day, prices in entries:
        d = day.strftime("%d/%m/%Y")
        incl = "".join(
            f"<td>{_fmt(prices.get(f, (None, None))[0])}</td>" for f in _COLUMNS
        )
        excl = "".join(
            f"<td>{_fmt(prices.get(f, (None, None))[1])}</td>" for f in _COLUMNS
        )
        rows.append(f"<tr><td>{d}</td>{incl}<td>-</td><td>1.355</td><td>TVAC</td></tr>")
        rows.append(f"<tr><td>{d}</td>{excl}<td>-</td><td>1.100</td><td>HTVA</td></tr>")
    return f"<html><body><h1>Official prices</h1><table>{''.join(rows)}</table></body></html>"


def sheet_json(rows: list[tuple[date, dict[FuelType, str]]]) -> dict:
    """Render a live-sheet-shaped payload.

    ``rows`` is ``[(effective_date, {fuel: "2.095"}), ...]``; missing fuels are
    blank cells, like in the real sheet.
    """
    header = ["Date", "Essence 95", "Essence 98", "Diesel", "46289"]
    order = (FuelType.SP95, FuelType.SP98, FuelType.DIESEL)
    table = [header, ["", "", "", "", ""]]
    for day, prices in rows:
        cells = [f"{prices[f]} €" if f in prices else "" for f in order]
        table.append([day.strftime("%d.%m.%Y"), *cells, ""])
    return {"data": [table], "sheetNames": ["Sheet1"], "refreshed": "2026-09-25"}
