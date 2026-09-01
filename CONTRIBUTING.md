# Contributing

Thanks for helping improve Luxembourg Fuel Monitor.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-test.txt
```

## Checks

```bash
ruff check .          # CI gate
pytest                # CI gate
ruff format .         # keep formatting consistent
mypy custom_components/lux_fuel_monitor   # advisory
```

`ruff check` and `pytest` run in CI (`.github/workflows/`), alongside Home Assistant's
`hassfest` and the HACS validation action. `mypy` is advisory — run it locally.

## Architecture notes

- **Providers** (`providers/`) are the only place that talks to a data source. A provider
  implements `async_get_history()`; the shared `build_price_set()` turns points into the
  resolved current / previous / upcoming structure the rest of the integration uses.
  To add a Luxembourg source, add a `FuelProvider` subclass and register it in
  `providers/__init__.py`.
- **`analytics.py`** holds pure functions (trend, recommendation) and has no Home
  Assistant dependencies beyond `dt_util`. Prefer adding logic here so it stays testable.
- **`coordinator.py`** owns polling, the evening (~18:00) schedule, change detection and
  the `price_change_announced` / `price_changed` events.
- **`sensor.py`** is description-driven: add an entry to `PER_FUEL_SENSORS`,
  `GLOBAL_SENSORS` or `VEHICLE_SENSORS` with `value_fn` / `attributes_fn`.

## Conventions

- `async` only, full typing, `ruff` + `mypy` clean.
- New user-visible strings go in `strings.json` **and** every file in `translations/`.
- New entities need a `unique_id`, a `translation_key`, and an entry in the translation
  files.
