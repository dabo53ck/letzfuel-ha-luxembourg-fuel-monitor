"""Shared test helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from custom_components.lux_fuel_monitor.models import FuelType

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
