# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); until the
first tagged release, everything lives under *Unreleased*.

## Unreleased

### Added

- **Notification blueprint**
  (`blueprints/automation/letzfuel_ha/notifications.yaml`) — one import covering
  next-day price alerts, "new price in effect", refuel recommendation and a
  price-threshold watch. Every type is opt-in with its own priority (normal /
  elevated / critical), plus quiet hours and a presence gate. Delivery is a
  device picker (paired Companion App devices) — no notify service to
  configure, and no message text to write; every type's title/message is
  fixed. All notifications are forced into one `letzfuel_ha` phone group. See
  [`docs/notifications-blueprint.md`](docs/notifications-blueprint.md).
- `scripts/validate_blueprints.py` and a CI job that structurally checks the
  shipped blueprints.
- Option **"Fetch tomorrow's announced price"** (default on) to disable the
  RTL.lu lookup and rely on petrol.lu alone. A failure of the RTL.lu endpoint is
  logged once and otherwise ignored — it never breaks the petrol.lu update.

### Changed

- Entity IDs are now pinned to a stable, language-independent form
  (`sensor.letzfuel_ha_diesel_price`,
  `sensor.letzfuel_ha_refuel_recommendation`, …) on first creation, instead of
  being derived from the translated entity name. This lets the blueprint and
  the docs reference entities by a fixed id in any language. Existing
  installations keep the entity IDs already stored in their registry.

### Fixed

- **The announced next-day price is picked up again.** petrol.lu only shows a
  price once it is in effect, so the pre-announcement (`price_change_pending`,
  `price_tomorrow`, the refuel recommendation, `letzfuel_ha_price_change_announced`)
  never fired. The integration now also reads RTL.lu's published price set
  (`https://api-gate.rtl.lu/fuel-prices/current`), which carries the next-day
  price from ~18:00 the evening before, and folds it into petrol.lu's history.

### Notes

- petrol.lu remains the source of truth for the current price, the full history
  and the statistics backfill. RTL.lu is used only for the announced next-day
  price, which it publishes incl. VAT only (the excl.-VAT figure for that one
  point is derived at the 17 % LU rate).
