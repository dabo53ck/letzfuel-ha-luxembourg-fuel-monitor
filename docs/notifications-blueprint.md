# Notification blueprint

`blueprints/automation/letzfuel_ha/notifications.yaml` is one automation that
turns LëtzFuel HA's events and sensors into phone notifications. Every
notification type is **opt-in** and lives in its own collapsible section — you
pick your device(s) once, enable the types you want, and you're done. Message
text is fixed (in English); there's nothing to write.

- [Requirements](#requirements)
- [Install](#install)
- [Notification delivery](#notification-delivery)
- [Grouping](#grouping)
- [Priority and Do Not Disturb](#priority-and-do-not-disturb)
- [The notification types](#the-notification-types)
  - [Evening: next-day price announced](#evening-next-day-price-announced)
  - [New price in effect](#new-price-in-effect)
  - [Refuel recommendation](#refuel-recommendation)
  - [Price threshold](#price-threshold)
- [Quiet hours](#quiet-hours)
- [Only when home / away](#only-when-home--away)
- [Worked configurations](#worked-configurations)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- Home Assistant **2025.12** or newer.
- The [Home Assistant Companion app](https://companion.home-assistant.io/) on
  every phone/tablet you want to notify — the blueprint only targets paired
  companion-app devices.
- For **critical** notifications:
  - **iOS** – allow *Critical Alerts* for the Home Assistant app
    (iOS Settings → Notifications → Home Assistant → Critical Alerts). Without
    this, iOS silently downgrades a critical alert to time-sensitive.
  - **Android** – nothing to enable; critical uses the companion app's built-in
    *Alarm stream* channel, which plays at alarm volume and ignores Do Not
    Disturb.

## Install

1. In Home Assistant: **Settings → Automations & Scenes → Blueprints →
   Import Blueprint**.
2. Paste:
   ```
   https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor/blob/main/blueprints/automation/letzfuel_ha/notifications.yaml
   ```
3. **Create Automation** from the blueprint.
4. Open **Notification delivery**, pick your device(s), then open the
   sections for the notifications you want and switch **Enable** on.

To pick up a later fix: **Blueprints → ⋮ on the blueprint → Re-import**.

### Versioning

Home Assistant has no built-in blueprint version tracking or update check —
re-importing always silently overwrites whatever you had. The blueprint's
`description` (visible on the Blueprints page and while editing an automation
built from it) carries a version marker (`Blueprint version N`) and a one-line
summary of what changed, so you can tell at a glance whether you're on the
latest. Check [`CHANGELOG.md`](../CHANGELOG.md) for the full history.

Re-importing a new version does **not** touch inputs you already set on
automations built from it (device picks, enabled types, …) — except where a
version note says otherwise (e.g. v2 renamed the delivery input, so it comes
back empty and needs to be re-picked once).

## Notification delivery

One input, **Devices**, decides where everything goes: a device picker
pre-filtered to your paired Home Assistant Companion app devices. Pick one or
several — there's no notify service name to look up. Every enabled type is
sent to every selected device.

**Notification tag prefix** (default `letzfuel`) controls the tag used for
[grouping](#grouping) below.

## Grouping

Every notification carries `group: letzfuel_ha` (Android) and
`push.thread-id: letzfuel_ha` (iOS), so they collapse into one stack on the
phone instead of scattering. This is fixed and has no setting.

Within that, each **type** uses its own tag (`<prefix>_announced`,
`<prefix>_effective`, `<prefix>_recommendation`, `<prefix>_threshold`), so a
newer message of the same type **replaces** the previous one rather than
stacking.

## Priority and Do Not Disturb

Each notification type has a **Priority** dropdown:

| Priority | Android | iOS |
| --- | --- | --- |
| **Normal** | default channel | default |
| **Elevated** | `importance: high`, `priority: high` | `interruption-level: time-sensitive` |
| **Critical** | `channel: alarm_stream` – alarm volume, **bypasses Do Not Disturb** | `interruption-level: critical` + critical sound – **bypasses the silent switch and Focus** |

Notes:

- iOS critical needs the one-time permission in [Requirements](#requirements).
- Android `alarm_stream` is loud. Use it only where you mean it — e.g. the
  *announced* type with **Direction: Increases only** and a real
  **Minimum change**.
- A **critical** notification also ignores [quiet hours](#quiet-hours) and the
  [presence gate](#only-when-home--away) by default (each has its own
  "Critical notifications ignore …" toggle).

## The notification types

Titles and messages are fixed for every type (see the source blueprint if you
want to fork it and change the wording); the inputs below only control
*whether* and *when* each type fires.

### Evening: next-day price announced

Fires on the `letzfuel_ha_price_change_announced` event — a new price has been
published for tomorrow (Luxembourg publishes around 18:00 the day before).

| Input | Meaning |
| --- | --- |
| **Fuels** | Which fuels to notify about. *Primary fuel* follows the integration's configured primary fuel. |
| **Direction** | Up and down / increases only / decreases only. |
| **Minimum change** | Ignore moves smaller than this (€/L). `0` = any change. |
| **Priority** | See [above](#priority-and-do-not-disturb). |
| **Ignore quiet hours** | Send even inside the quiet window. |

### New price in effect

Same inputs as *announced*, but fires on `letzfuel_ha_price_changed` — the day a
new price **actually applies** (usually just after midnight).

### Refuel recommendation

Fires when `sensor.letzfuel_ha_refuel_recommendation` changes. Nothing to
configure beyond enabling it — the blueprint always watches that one, stable
entity.

| Input | Meaning |
| --- | --- |
| **Notify when it becomes** | Any of `refuel_today`, `wait`, `no_change`. Default: `refuel_today` only. |

> If you renamed that entity in your own install, this section won't fire —
> fork the blueprint and change the hardcoded entity id (search for
> `sensor.letzfuel_ha_refuel_recommendation` in the YAML).

### Price threshold

Fires when a watched price sensor drops **below** a value you set — "tell me
when diesel is under 1.60".

| Input | Meaning |
| --- | --- |
| **Fuels** | Which fuels to watch. Same picker as *announced*/*effective*: *Primary fuel* follows the integration's configured primary fuel. |
| **Notify when the price is below** | Your target €/L, applied to every selected fuel. Leave at `0` until you enable this section (a `0` threshold never fires). |

## Quiet hours

When enabled, notifications inside the window are **suppressed — not delayed**.
You will not receive them afterwards. Getting through anyway:

- a type with **Ignore quiet hours** on, or
- a **critical** notification while **Critical notifications ignore quiet hours**
  is on (default).

The window may cross midnight (e.g. 22:00 → 07:00).

## Only when home / away

Optional presence gate.

| Input | Meaning |
| --- | --- |
| **Person or group** | A `person` or a `group` of persons. Leave empty to disable the gate even if the section toggle is on. |
| **Send only when** | `Home` or `Away`. |
| **Critical notifications ignore the presence gate** | Default on. |

## Worked configurations

**"Just tell me when to refuel."**
Delivery: your phone. Enable *Evening: next-day price announced* → Fuels
*Primary fuel*, Direction *Up and down*, Priority *Normal*. Nothing else.

**Power user.**
Also enable *New price in effect* (Priority *Elevated*) and *Refuel
recommendation* → `refuel_today`. Set *Quiet hours* 22:00 → 07:00.

**Critical only for a real hike.**
Enable *Evening: next-day price announced* → Direction *Increases only*,
Minimum change `0.03`, Priority *Critical*. Leave every other type off.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| No notification at all | Confirm the device is picked in **Devices** and still paired (Settings → Companion App). Check the automation trace (Automations → ⋮ → Traces). |
| Notifications don't group | Shouldn't happen — grouping is fixed and not user-configurable. Check the trace for the `notification_data` variable. |
| *Critical* doesn't pierce Do Not Disturb | iOS: *Critical Alerts* not allowed for the HA app. Android: another app owns a Do-Not-Disturb override, or the phone blocks the alarm channel. |
| Nothing during a certain time of day | Quiet hours. Set **Ignore quiet hours** on that type, or use *Critical*. |
| Announced/effective/threshold never fires | No price change has been published yet, or your **Fuels / Direction / Minimum change** filtered it out. Confirm the `letzfuel_ha_price_change_announced` event in Developer Tools → Events. |
| Refuel recommendation never fires | You renamed `sensor.letzfuel_ha_refuel_recommendation` — see the note in [Refuel recommendation](#refuel-recommendation). |
