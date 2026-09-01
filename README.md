<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/letzfuel_ha/brand/dark_logo.png">
  <img src="custom_components/letzfuel_ha/brand/logo.png" alt="LëtzFuel HA – Luxembourg Fuel Monitor" width="640">
</picture>

**Luxembourg's regulated maximum fuel prices, trends and refuelling insights for Home Assistant.**

[![HACS][hacs-badge]][hacs-url] &nbsp; [![Validate][validate-badge]][validate-url] &nbsp; [![Tests][tests-badge]][tests-url]

</div>

Luxembourg sets a **single national maximum price** for each road fuel by ministerial
regulation. When the price changes, the new figure is published the evening before it
takes effect (typically around **18:00**). This integration turns that feed into
answers:

- What is the current diesel / SP95 / SP98 price?
- Did the price change today, and by how much?
- Is the price going up or down?
- **A new price was published for tomorrow — should I refuel tonight or wait?**
- What would a full tank cost me right now? What about just topping up?
- How much did the latest price change add to the cost of a full tank?

> **Not affiliated** with the Groupement Pétrolier Luxembourgeois, petrol.lu, or the
> Luxembourg government. Prices are read from the public
> [petrol.lu prices page](https://www.petrol.lu/en/official-prices/).
> Always verify the price at the pump.

---

## Features

| Area | What you get |
| --- | --- |
| **Current prices** | `sensor.*_price` for each tracked fuel (€/L, incl. or excl. VAT), with rich attributes |
| **Daily change** | `sensor.*_change` — signed €/L move at the last price change, with percentage and dates |
| **Trend** | `sensor.*_trend` — `rising` / `falling` / `stable` over a configurable window |
| **Next-day awareness** | `binary_sensor.price_change_pending`, `sensor.*_price_tomorrow`, `sensor.refuel_recommendation` |
| **Events** | `letzfuel_ha_price_change_announced` and `letzfuel_ha_price_changed` for automations |
| **Vehicle analytics** | full-tank / refill / cost-change sensors + a live `number` slider for the fuel level (when a tank size is set) |
| **Services** | `calculate_fill_cost`, `calculate_trip_cost` (response services) |
| **History** | On setup, past prices are imported into Home Assistant long-term statistics |
| **Robustness** | Diagnostics, repair issues when the source is stale or unparseable |
| **i18n** | English, French, German |

---

## Requirements

Home Assistant **2025.12** or newer.

## Installation

### HACS (recommended)

1. HACS → **Integrations** → menu → **Custom repositories**.
2. Add `https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor` as an
   **Integration**.
3. Install **LëtzFuel HA** and restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → LëtzFuel HA**.

### Manual

Copy `custom_components/letzfuel_ha` into your Home Assistant `config/custom_components`
directory and restart.

---

## Configuration

All configuration is through the UI.

**Step 1 — Fuels**
: Choose which fuels to track (Diesel, SP95/E10, SP98) and which one is your *primary*
  fuel (used by the recommendation and vehicle sensors).

**Step 2 — Vehicle (optional)**
: Set your tank size to unlock the cost sensors, and optionally a starting fuel
  level. After setup, the fuel level is adjusted live via the
  `number.*_current_fuel_level` slider — put it on a dashboard.

**Options** (⚙️ on the integration card) let you change everything below without
re-adding the integration:

| Setting | Default | Notes |
| --- | --- | --- |
| Update interval | 6 h | Regular polling cadence |
| Evening check time | 18:01 | Extra refresh to catch the publication; retries at **+10** and **+20 min** if nothing new appeared |
| Trend window | 14 days | Sample window for the trend sensors |
| Price display | Incl. VAT | Show prices with or without VAT |
| Tracked fuels / primary fuel | all / Diesel | |
| Tank size | — | Enables the vehicle sensors (the *level* lives in the number entity) |
| Import price history | on | Backfill long-term statistics |
| History import depth | 12 months | How far back to import |

---

## Entity reference

Entity IDs are prefixed with the device name, e.g. `sensor.letzfuel_ha_diesel_price`.
Sensors marked *disabled by default* can be enabled from the entity settings.
`*_trend` and `*_price_tomorrow` are enabled by default **only for the primary
fuel**; the other tracked fuels' copies start disabled.

> **Language note:** entity names are translated, so on a non-English Home
> Assistant the auto-generated entity IDs follow that language — e.g. on a German
> system the diesel price sensor is `sensor.letzfuel_ha_diesel_preis`,
> the change sensor `..._diesel_anderung`, the recommendation `..._tankempfehlung`.
> The examples below use the English IDs; check **Developer Tools → States** (or
> rename the entities) for yours.

### Per fuel (`diesel`, `sp95`, `sp98`)

| Entity | State | Key attributes |
| --- | --- | --- |
| `sensor.*_<fuel>_price` | current max price, €/L | `currency`, `effective_date`, `price_incl_vat`, `price_excl_vat`, `vat_rate`, `previous_price`, `previous_effective_date`, `price_since`, `next_price`, `next_effective_date`, `source`, `source_url` |
| `sensor.*_<fuel>_change` | signed €/L move at last change | `current_price`, `previous_price`, `percentage_change`, `change_date`, `days_at_current_price` |
| `sensor.*_<fuel>_trend` *(primary fuel on by default)* | `rising` / `falling` / `stable` | `trend_strength` (€/L per week), `trend_window_days`, `samples_used`, `window_start`, `window_end` |
| `sensor.*_<fuel>_price_tomorrow` *(primary fuel on by default)* | announced next-day price or *unknown* | `effective_date`, `change_vs_today`, `direction` |

### Global

| Entity | State | Key attributes |
| --- | --- | --- |
| `binary_sensor.*_price_change_pending` | `on` when a differing next-day price is published | `affected_fuels`, `deltas`, `effective_date` |
| `sensor.*_refuel_recommendation` | `refuel_today` / `wait` / `no_change` / `unknown` | `primary_fuel`, `today_price`, `tomorrow_price`, `delta`, `potential_saving_full_tank` |
| `sensor.*_last_price_update` | timestamp the current price took effect | `last_fetch_success`, `fetched_at`, `source_url` |
| `sensor.*_days_since_last_change` *(disabled by default)* | integer days | — |

### Vehicle (created when a tank size is configured)

| Entity | State | Key attributes |
| --- | --- | --- |
| `number.*_current_fuel_level` | current fuel level, % — a slider you set from a dashboard | — |
| `sensor.*_full_tank_cost` | `tank_size × price`, € | `tank_size`, `fuel_type`, `price_per_liter` |
| `sensor.*_refill_cost` | cost to fill from the current level, € | `current_level_pct`, `tank_size`, `liters_needed`, `price_per_liter` |
| `sensor.*_full_tank_cost_change` | change in full-tank cost from the last price move, € | `old_full_tank_cost`, `new_full_tank_cost`, `difference`, `per_litre_change`, `change_date` |

The level survives restarts, so once you set it you only nudge it after driving
or refuelling.

---

## Services

### `letzfuel_ha.calculate_fill_cost`

| Field | Required | Description |
| --- | --- | --- |
| `liters` | yes | Litres to add |
| `fuel_type` | no | `diesel` / `sp95` / `sp98` (default: primary fuel) |
| `use_tomorrow_price` | no | Use the announced next-day price if available |

Returns `{ cost, liters, price_per_liter, fuel_type, effective_date, currency }`.

### `letzfuel_ha.calculate_trip_cost`

| Field | Required | Description |
| --- | --- | --- |
| `distance_km` | yes | Trip distance |
| `consumption_l_100km` | yes | Average consumption |
| `fuel_type` | no | default: primary fuel |

Returns `{ liters_needed, cost, price_per_liter, fuel_type, currency }`.

---

## Events

`letzfuel_ha_price_change_announced` fires when a next-day price is published that
differs from today:

```yaml
event_type: letzfuel_ha_price_change_announced
data:
  provider: "petrol.lu (Groupement Pétrolier Luxembourgeois)"
  changes:
    - fuel: diesel
      current_price: 1.865
      upcoming_price: 1.889
      delta: 0.024
      direction: up
      effective_date: "2026-09-02"
```

`letzfuel_ha_price_changed` fires the day a new price actually takes effect (same
shape, `old_price` / `new_price`).

---

## Automation examples

**Tell me tonight if I should refuel**

```yaml
automation:
  - alias: "Fuel: refuel tonight?"
    trigger:
      - trigger: event
        event_type: letzfuel_ha_price_change_announced
    condition:
      - condition: template
        value_template: >
          {{ trigger.event.data.changes
             | selectattr('fuel', 'eq', 'diesel')
             | selectattr('direction', 'eq', 'up') | list | count > 0 }}
    action:
      - action: notify.mobile_app
        data:
          title: "Diesel goes up tomorrow"
          message: >
            {% set c = trigger.event.data.changes
               | selectattr('fuel','eq','diesel') | first %}
            +{{ '%.3f' | format(c.delta) }} €/L from {{ c.effective_date }}.
            Refuel today.
```

**Alert on a large move**

```yaml
automation:
  - alias: "Fuel: big diesel change"
    trigger:
      - trigger: numeric_state
        entity_id: sensor.letzfuel_ha_diesel_change
        above: 0.03
    action:
      - action: notify.family
        data:
          message: >
            Diesel changed by {{ states('sensor.letzfuel_ha_diesel_change') }} €/L.
```

**Daily 07:00 fuel summary**

```yaml
automation:
  - alias: "Fuel: morning summary"
    trigger:
      - trigger: time
        at: "07:00:00"
    action:
      - action: notify.family
        data:
          message: >
            Diesel {{ states('sensor.letzfuel_ha_diesel_price') }} €/L
            ({{ states('sensor.letzfuel_ha_diesel_trend') }}).
            Full tank: €{{ states('sensor.letzfuel_ha_full_tank_cost') }}.
```

**Refill-cost budget alert**

```yaml
automation:
  - alias: "Fuel: refill over budget"
    trigger:
      - trigger: numeric_state
        entity_id: sensor.letzfuel_ha_refill_cost
        above: 70
    action:
      - action: notify.me
        data:
          message: "A refill now would cost €{{ states('sensor.letzfuel_ha_refill_cost') }}."
```

---

## 30-day average, month high / low, and derivative trend

The integration deliberately does **not** keep its own price database. Home Assistant's
built-in helpers already do this well, and on setup the published price history is
backfilled into each `sensor.*_price` entity's own long-term statistics — so its
history graph and these helpers have data from before you installed it:

**30-day average** — add a [Statistics helper](https://www.home-assistant.io/integrations/statistics/):

```yaml
sensor:
  - platform: statistics
    name: "Diesel 30-day average"
    entity_id: sensor.letzfuel_ha_diesel_price
    state_characteristic: mean
    max_age:
      days: 30
```

**Month high / low** — same helper with `state_characteristic: value_max` / `value_min`
and `max_age: { days: 31 }` (or use `sampling_size` to taste).

**Smoothed trend** — the [Trend helper](https://www.home-assistant.io/integrations/trend/)
or [Derivative helper](https://www.home-assistant.io/integrations/derivative/) on the
`*_price` sensor.

---

## Screenshots

_Placeholders — add real screenshots before publishing._

| Dashboard | Options | Trend graph |
| --- | --- | --- |
| `docs/dashboard.png` | `docs/options.png` | `docs/trend.png` |

---

## Roadmap

- **Phase 2**: current fuel level from a Home Assistant entity; heating oil, BTS and LPG;
  per-station data via a second provider; notification blueprints and a Lovelace card;
  Luxembourgish translation.
- **Phase 3**: a `gouvernement.lu` press-release parser as a cross-check / fallback source;
  price-move prediction from the Platt's Rotterdam index; Energy dashboard cost integration.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: `pip install -r requirements-test.txt`,
then `ruff check .`, `mypy custom_components/letzfuel_ha`, and `pytest`.

Adding another Luxembourg source means implementing one `FuelProvider` subclass in
`custom_components/letzfuel_ha/providers/` and registering it — nothing else changes.

## License

[MIT](LICENSE)

<!-- badges -->
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[validate-badge]: https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor/actions/workflows/validate.yml/badge.svg
[validate-url]: https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor/actions/workflows/validate.yml
[tests-badge]: https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor/actions/workflows/tests.yml/badge.svg
[tests-url]: https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor/actions/workflows/tests.yml
