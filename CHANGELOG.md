# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); until the
first tagged release, everything lives under *Unreleased*.

## Unreleased

### Added

- **Notification blueprint**
  (`blueprints/automation/letzfuel_ha/notifications.yaml`) — one import covering
  next-day price alerts, "new price in effect", refuel recommendation, a
  stale-feed alarm and a price-threshold watch. Every type is opt-in with its
  own priority (normal / elevated / critical), plus quiet hours and a presence
  gate. All notifications are forced into one `letzfuel_ha` phone group. See
  [`docs/notifications-blueprint.md`](docs/notifications-blueprint.md).
- `scripts/validate_blueprints.py` and a CI job that structurally checks the
  shipped blueprints.

### Changed

- Entity IDs are now pinned to a stable, language-independent form
  (`sensor.letzfuel_ha_diesel_price`,
  `sensor.letzfuel_ha_refuel_recommendation`, …) on first creation, instead of
  being derived from the translated entity name. This lets the blueprint and
  the docs reference entities by a fixed id in any language. Existing
  installations keep the entity IDs already stored in their registry.
