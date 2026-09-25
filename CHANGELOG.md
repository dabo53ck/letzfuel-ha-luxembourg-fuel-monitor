# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). SemVer,
pre-release identifiers included (`0.0.1-beta`, …).

## [0.1.1] - 2026-09-25

### Fixed

- **Evening price announcement no longer missed when a source skips it.**
  On 2026-09-24 a Diesel increase for the next day was announced around
  17:40, but the only announcement source never published it, so the change
  only showed up at midnight as "New price in effect". Tomorrow's price now
  comes from a more reliable announcement feed, which is only trusted while it
  agrees with petrol.lu on today's price. If it is unreachable, unreadable or
  disagrees, a backup feed stands in. petrol.lu's own next-day row always
  wins. Closes #17.
- **Earlier and longer evening checks.** The evening check now starts at
  **17:30** (was 18:01) and retries every 2 minutes until 18:30, then every
  20–30 minutes (randomised) until midnight, as long as tomorrow's price is
  still unknown. The checks stop as soon as tomorrow's price is known,
  changed or not. A restart during the evening now resumes them instead of
  waiting for the next day. Installs still on the old 18:01 default are
  moved to 17:30; a custom time is kept.
- A half-filled row in the announcement feed (prices still being entered)
  is ignored until every fuel is filled in, so a partial update can't
  trigger a premature or split announcement.
- Announced dates are read as Luxembourg calendar days, whatever time zone
  Home Assistant runs in.

### Added

- **Corrections.** Once a price has been announced for a day, it stays until
  petrol.lu publishes the official price for that day. If the two differ, the
  new `letzfuel_ha_price_change_corrected` event fires, the same evening or
  after midnight. The notifications blueprint sends it as a correction that
  replaces the earlier notification on the phone, e.g.
  `DIESEL: 2.095 €/L (no change) instead of 2.055 €/L`.
- **Plausibility check** for announced prices: values more than 15 % away
  from today's price, or dated more than a week ahead, are ignored.
- **Repair issue** when the announcement feed has been unusable for 3 days in
  a row, so a silent loss of the evening announcement gets noticed.
- **Load spread across installs.** Each install shifts its evening and
  midnight refreshes by a fixed offset of up to one minute, so installs
  don't all query the sources at the same second.
- **Diagnostics** show, per announcement source, when it was last checked,
  the newest date it listed and the outcome (`announced`, `nothing_future`,
  `implausible`, `inconsistent`, `error`, or `standby` for the backup while
  it isn't needed), plus since when the feed has been unusable.

## [0.1.0] - 2026-09-24

### Added

- **Portuguese and Italian support**, both for the integration's own UI
  (config flow, options) and for the notifications blueprint (notification
  titles/messages, comma decimal separator). Pick them like any other
  language — Notification language on the blueprint side, Home Assistant's
  own language setting on the integration side.

### Changed

- **Live countdown to midnight is no longer marked experimental** — confirmed
  working on both iOS (Live Activity) and Android (Live Update).

## [0.0.3-beta] - 2026-09-20

### Added

- **Tapping a notification now opens something useful.** By default it opens
  the details of the relevant entity (the fuel's price and history, or the
  refuel recommendation). A new optional input, *Dashboard opened when you tap
  a notification*, lets you send every notification to your own dashboard
  instead. Applies to all notification types and the Live countdown. Closes #11.

### Changed

- **Shorter notification titles** so they no longer get cut off on the
  device: the "price change announced" and "price below your target" titles
  are shorter in all four languages.
- README: added a release-version badge, first in the badge row at the top.

## [0.0.2-beta] - 2026-09-16

### Added

- **Local brand icon for notifications** (integration + blueprint). The
  integration now serves `brand/icon.png` locally
  (`hass.http.async_register_static_paths`, at `/letzfuel_ha/icon.png`) and
  the notifications blueprint points the announced/effective/recommendation/
  threshold notifications' `icon_url` at it, so those pushes show the
  LëtzFuel droplet instead of the generic Home Assistant icon. Nothing to
  configure. Closes #7. Doesn't apply to the *Live countdown* — iOS Live
  Activities only support a Material Design Icon, not a custom image.

### Changed

- **Blueprint title no longer carries a version number.** The version marker
  now lives only in the blueprint's `description` (which is where you'd
  check anyway); the title (`LëtzFuel HA – Notifications`) stays stable
  across versions.
- README: the RTL.lu data-source row no longer calls the announced-price
  lookup "optional" — the wording didn't match how central it is to the
  next-day awareness features.

### Fixed

- **Blueprint: Price threshold no longer errors when a fuel isn't tracked.**
  The three price-threshold triggers (diesel/SP95/SP98) are now `template`
  triggers (`has_value(...) and states(...) < below`) instead of
  `numeric_state`, which used to error at load time ("unknown entity
  sensor.letzfuel_ha_sp95_e10_price") when that fuel's sensor doesn't
  exist. Starts working on its own once that fuel is tracked, no re-import
  needed. Closes #9.
- **No more false "price changed" notifications at the midnight rollover.**
  A tracked fuel's price record gets a fresh entry dated "today" every day
  regardless of whether its price actually moved — the coordinator now only
  fires `letzfuel_ha_price_changed` (and the "New price in effect" push)
  when the price itself differs from the previous value, not just because
  the effective date advanced. Confirmed via a real trace where Diesel sent
  a "−0.0 ct/L" notification on a day only SP95/SP98 actually changed.
  Closes #10.

## [0.0.1-beta] - 2026-09-12

### Added

- **Fuel level from another entity.** Step 2 / Options now has a *Fuel level
  source* choice: **Manual** (the `number.*_current_fuel_level` slider, as
  before) or **From another entity** — pick a `sensor`, `number` or
  `input_number` whose state is the tank fill level in percent (0–100) and
  `sensor.*_refill_cost` tracks it live. In entity mode the slider entity is
  not created; an unusable value (missing, `unknown`/`unavailable`,
  non-numeric, outside 0–100) leaves the refill sensor at *unknown*.
  `sensor.*_refill_cost` gains `level_source` (+ `level_entity_id`) attributes.
- **Live countdown to midnight** (blueprint v7, experimental, off by
  default). New *Live countdown to midnight* section starts an iOS Live
  Activity / Android Live Update the moment `sensor.*_refuel_recommendation`
  becomes `refuel_today`, counting down to the midnight price rise; ends
  automatically once the recommendation moves on (normally via the
  just-after-midnight refresh). Purely additive to the existing *Refuel
  recommendation* push, not a replacement. Needs a Companion App with Live
  Activity / Live Update support (iOS 17.2+, Android 16+); fallback
  behaviour on older app versions hasn't been broadly verified yet.
- **Notification blueprint** (`blueprint version 0.0.1-beta`,
  `blueprints/automation/letzfuel_ha/notifications.yaml`) — one import covering
  next-day price alerts, "new price in effect", refuel recommendation and a
  price-threshold watch. Every type is opt-in with its own priority (normal /
  elevated / critical) and a presence gate. Delivery is a device picker
  (paired Companion App devices) — no notify service to configure, and no
  message text to write; every type's title/message is fixed, in one of four
  languages (English, German, French, Lëtzebuergesch) picked via a
  **Language** input — Home Assistant has no mechanism to translate a
  blueprint's own input UI, so the text sets are hardcoded per language
  instead. Refuel recommendation always watches
  `sensor.letzfuel_ha_refuel_recommendation` (no entity to pick); Price
  threshold uses the same Fuels picker as the other types instead of a raw
  sensor picker. All notifications are forced into one `letzfuel_ha` phone
  group. See [`docs/notifications-blueprint.md`](docs/notifications-blueprint.md).
- **Just-after-midnight refresh** (coordinator) so a next-day price becomes
  "in effect" (and the `letzfuel_ha_price_changed` event/notification fires)
  promptly, instead of waiting for the next periodic poll — which isn't
  anchored to wall-clock time and can land hours into the new day depending
  on when the previous poll happened to run.
- `scripts/validate_blueprints.py` and a CI job that structurally checks the
  shipped blueprints.
- Option **"Fetch tomorrow's announced price"** (default on) to disable the
  RTL.lu lookup and rely on petrol.lu alone. A failure of the RTL.lu endpoint is
  logged once and otherwise ignored — it never breaks the petrol.lu update.

### Removed

- **Quiet hours** (blueprint v4) — the whole section and every type's "Ignore
  quiet hours" toggle. Re-importing over an earlier version just drops
  whatever you had set there; use Home Assistant's own automation
  conditions if you need time-window suppression.

### Changed

- **Blueprint versioning now follows the integration's release number**
  instead of its own v1/v2/.../v7 counter, so both stay in sync going
  forward. Purely a naming change — v0.0.1-beta is the same content as v7.
- **Evening check retries more often.** After the configured
  `evening_check_time` (default 18:01), the coordinator now rechecks every
  2 minutes for 14 minutes, then every 5 minutes up to 29 minutes after
  that (10 retries total instead of 2 at +10/+20 min) — a real-world price
  change had appeared later than the old +20 min cutoff caught. Stops
  doing any real work as soon as the price is found; the extra checks are
  once-a-day and lightweight.
- **Blueprint v5 → v6: Luxembourg date format.** The date shown in the
  "Evening: next-day price announced" message (e.g. `SP95 −2,8 ct/L →
  1,84 €/L (10/09/2026)`) is now `DD/MM/YYYY` instead of the raw
  `YYYY-MM-DD` the integration emits internally. No inputs changed — a
  re-import is enough, nothing to re-pick.
- **Blueprint v4 → v5: refuel-recommendation notifications.** The *Notify
  when it becomes* multi-select no longer offers `no_change`; a separate
  *Also notify when there is no recommendation* toggle (default **off**)
  covers that state instead, so the default is "only notify when there is
  an actual recommendation". Re-import the blueprint; if you had *No change*
  ticked under v4, open the automation and re-save it once so the stale
  value is dropped. `awaiting_price` remains a non-notifying state.
- **Blueprint: the *Notification tag prefix* input is removed** (v5). The
  per-type notification tags are now hardcoded (`letzfuel_announced`,
  `letzfuel_effective`, `letzfuel_recommendation`, `letzfuel_threshold`) —
  same values as the old `letzfuel` default, so a re-import changes nothing
  unless you had customised the prefix.
- Entity IDs are now pinned to a stable, language-independent form
  (`sensor.letzfuel_ha_diesel_price`,
  `sensor.letzfuel_ha_refuel_recommendation`, …) on first creation, instead of
  being derived from the translated entity name. This lets the blueprint and
  the docs reference entities by a fixed id in any language. Existing
  installations keep the entity IDs already stored in their registry.

### Fixed

- **`sensor.*_refuel_recommendation`'s "no data yet" state is no longer stuck
  showing "Unknown".** It used the literal string `"unknown"` as one of its
  enum options — but Home Assistant's frontend hard-codes that exact string
  (and `"unavailable"`) to always render the generic core "Unknown"/"Unbekannt"
  label, short-circuiting before any entity-specific translation is even
  considered, no matter what the integration's own translation files say.
  Renamed the state to `awaiting_price` (translated properly in all four
  languages) so it actually reaches the custom label. **Breaking**: any
  existing automation/dashboard matching the literal state `unknown` on this
  sensor needs updating to `awaiting_price`.
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
