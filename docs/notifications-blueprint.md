# Notification blueprint

`blueprints/automation/letzfuel_ha/notifications.yaml` is one automation that
turns LëtzFuel HA's events and sensors into phone notifications. Every
notification type is **opt-in** and lives in its own collapsible section — you
enable the ones you want, pick a notify action once, and you're done.

- [Requirements](#requirements)
- [Install](#install)
- [Notification delivery](#notification-delivery)
- [Grouping](#grouping)
- [Priority and Do Not Disturb](#priority-and-do-not-disturb)
- [The notification types](#the-notification-types)
  - [Evening: next-day price announced](#evening-next-day-price-announced)
  - [New price in effect](#new-price-in-effect)
  - [Refuel recommendation](#refuel-recommendation)
  - [Data problems](#data-problems)
  - [Price threshold](#price-threshold)
- [Quiet hours](#quiet-hours)
- [Only when home / away](#only-when-home--away)
- [Advanced](#advanced)
- [Message templates and placeholders](#message-templates-and-placeholders)
- [Localised message snippets](#localised-message-snippets)
- [Worked configurations](#worked-configurations)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- Home Assistant **2025.12** or newer.
- The [Home Assistant Companion app](https://companion.home-assistant.io/) on the
  phone(s) you want to notify, **or** any other `notify.*` service / group.
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
4. Open **Notification delivery**, set the notify action (see below), then open
   the sections for the notifications you want and switch **Enable** on.

To pick up a later fix: **Blueprints → ⋮ on the blueprint → Re-import**.

## Notification delivery

One input, **Notify action**, decides where everything goes. It is a normal
action editor. The default is:

```yaml
- action: notify.notify
  data:
    title: "{{ title }}"
    message: "{{ message }}"
    data: "{{ notification_data }}"
```

Change `notify.notify` to your phone (`notify.mobile_app_<your_device>`), a
[notify group](https://www.home-assistant.io/integrations/group/#notify-groups),
or add more `- action:` lines for several targets. You can add anything a normal
action can do.

> **Keep the `data: "{{ notification_data }}"` line.** It carries the
> `letzfuel_ha` [notification group](#grouping) and the per-type
> [priority](#priority-and-do-not-disturb). If you remove it, notifications
> still send but they won't group and *critical* won't bypass Do Not Disturb.

**Also create a persistent notification** (on by default) mirrors every *sent*
notification to **Settings → Notifications**. Messages suppressed by
[quiet hours](#quiet-hours) are **not** mirrored.

## Grouping

Every notification carries `group: letzfuel_ha` (Android) and
`push.thread-id: letzfuel_ha` (iOS), so they collapse into one stack on the
phone instead of scattering. This is fixed and has no setting.

Within that, each **type** uses its own tag (`<prefix>_announced`,
`<prefix>_effective`, `<prefix>_recommendation`, `<prefix>_problem`,
`<prefix>_threshold`), so a newer message of the same type **replaces** the
previous one rather than stacking. The prefix is **Notification tag prefix**
in *Notification delivery* (default `letzfuel`).

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
- To go further on Android (force max volume) set
  **Advanced → Extra notification data** to `{ "channel": "alarm_stream_max" }`.

## The notification types

### Evening: next-day price announced

Fires on the `letzfuel_ha_price_change_announced` event — a new price has been
published for tomorrow (Luxembourg publishes around 18:00 the day before).

| Input | Meaning |
| --- | --- |
| **Fuels** | Which fuels to notify about. *Primary fuel* follows the integration's configured primary fuel. |
| **Direction** | Up and down / increases only / decreases only. |
| **Minimum change** | Ignore moves smaller than this (€/L). `0` = any change. |
| **Priority** | See [above](#priority-and-do-not-disturb). |
| **Title / Message** | See [templates](#message-templates-and-placeholders). |
| **Ignore quiet hours** | Send even inside the quiet window. |

### New price in effect

Same inputs as *announced*, but fires on `letzfuel_ha_price_changed` — the day a
new price **actually applies** (usually just after midnight).

### Refuel recommendation

Fires when `sensor.*_refuel_recommendation` changes.

| Input | Meaning |
| --- | --- |
| **Recommendation sensor** | Pre-filled with `sensor.letzfuel_ha_refuel_recommendation`. Change it only if you renamed the entity. |
| **Notify when it becomes** | Any of `refuel_today`, `wait`, `no_change`. Default: `refuel_today` only. |

### Data problems

Fires when the price feed stops refreshing — derived from
`sensor.letzfuel_ha_last_price_update`.

That sensor's **state** is the effective date of the current price, which is
legitimately days old when Luxembourg holds a price steady. The blueprint
instead reads its **attributes**: `fetched_at` (time of the last *successful*
fetch) and `last_fetch_success`. A template trigger re-checks every minute (it
uses `now()`), so about **Alert after** hours with no successful fetch it fires
once. It does not repeat while the problem persists.

| Input | Meaning |
| --- | --- |
| **Last-price-update sensor** | Pre-filled with `sensor.letzfuel_ha_last_price_update`. |
| **Alert after** | Hours without a successful fetch before alerting (default 30). |
| **Also notify when data recovers** | Send a follow-up when fetches succeed again. May emit one "restored" message shortly after a Home Assistant restart. |

Data-problem notifications **ignore quiet hours and presence** — they're about
the integration being broken.

### Price threshold

Fires when the watched price sensor drops **below** a value you set — "tell me
when diesel is under 1.60".

| Input | Meaning |
| --- | --- |
| **Price sensor to watch** | Pre-filled with `sensor.letzfuel_ha_diesel_price`. |
| **Notify when the price is below** | Your target €/L. Leave at `0` until you enable this section (a `0` threshold never fires). |

## Quiet hours

When enabled, notifications inside the window are **suppressed — not delayed**.
You will not receive them afterwards, and they are not mirrored to persistent
notifications. Getting through anyway:

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

## Advanced

| Input | Meaning |
| --- | --- |
| **Minimum minutes between notifications** | Global throttle across *all* types. `0` = off. |
| **Extra notification data** | Deep-merged into every notification's `data`. E.g. `{ "channel": "alarm_stream_max" }`, `{ "push": { "sound": "..." } }`, `{ "notification_icon": "mdi:gas-station" }`. |
| **Actionable-notification buttons** | A list passed as `data.actions`, e.g. `[{ "action": "URI", "title": "Open petrol.lu", "uri": "https://www.petrol.lu/en/official-prices/" }]`. |
| **Always mirror to a persistent notification** | Debug aid — mirror even when *persistent fallback* is off. |

## Message templates and placeholders

**Title** and **Message** are Jinja templates. In scope:

| Name | Available in | What it is |
| --- | --- | --- |
| `matched_changes` | announced, effective | list of `{ fuel, delta, direction, price, old_price, effective_date }` after your Fuels / Direction / Minimum-change filter. `delta` is signed €/L; `price` is the new/upcoming price. |
| `trigger` | all | the raw trigger. `trigger.to_state` / `trigger.from_state` for *recommendation*. |
| `stale_entity`, `stale_after_hours` | data problems | the configured sensor and threshold. |
| `threshold_entity`, `threshold_below` | price threshold | the configured sensor and target. |

Anything else Home Assistant templates can do (`states()`, `state_attr()`, `now()`)
works too.

Default *announced* message:

```jinja
{% set lines = namespace(v=[]) %}
{%- for c in matched_changes %}
{%- set lines.v = lines.v + [(c.fuel | upper) ~ ' ' ~ ('+' if c.direction == 'up' else '−') ~ (((c.delta | abs) * 100) | round(1)) ~ ' ct/L → ' ~ c.price ~ ' €/L (' ~ c.effective_date ~ ')'] %}
{%- endfor %}
{{ lines.v | join('\n') }}
```

## Localised message snippets

Paste into the **Message** field of the matching type.

**Announced — French**

```jinja
{% set l = namespace(v=[]) %}
{%- for c in matched_changes %}
{%- set l.v = l.v + [(c.fuel | upper) ~ ' ' ~ ('en hausse de' if c.direction == 'up' else 'en baisse de') ~ ' ' ~ (((c.delta | abs) * 100) | round(1)) ~ ' ct/L → ' ~ c.price ~ ' €/L le ' ~ c.effective_date] %}
{%- endfor %}
{{ l.v | join('\n') }}
```

**Announced — German**

```jinja
{% set l = namespace(v=[]) %}
{%- for c in matched_changes %}
{%- set l.v = l.v + [(c.fuel | upper) ~ ': ' ~ ('+' if c.direction == 'up' else '−') ~ (((c.delta | abs) * 100) | round(1)) ~ ' ct/L → ' ~ c.price ~ ' €/L ab ' ~ c.effective_date] %}
{%- endfor %}
{{ l.v | join('\n') }}
```

**Announced — Luxembourgish**

```jinja
{% set l = namespace(v=[]) %}
{%- for c in matched_changes %}
{%- set l.v = l.v + [(c.fuel | upper) ~ ': ' ~ ('+' if c.direction == 'up' else '−') ~ (((c.delta | abs) * 100) | round(1)) ~ ' ct/L → ' ~ c.price ~ ' €/L vum ' ~ c.effective_date] %}
{%- endfor %}
{{ l.v | join('\n') }}
```

**Recommendation — French / German / Luxembourgish**

```jinja
{% set m = {'refuel_today': 'Tanken haut', 'wait': 'Waarden', 'no_change': 'Keng Ännerung'} %}
{{ m.get(trigger.to_state.state, trigger.to_state.state) }}
```

## Worked configurations

**"Just tell me when to refuel."**
Delivery: your phone. Enable *Evening: next-day price announced* → Fuels
*Primary fuel*, Direction *Up and down*, Priority *Normal*. Nothing else.

**Power user.**
Also enable *New price in effect* (Priority *Elevated*), *Data problems*
(Priority *Elevated*), and *Refuel recommendation* → `refuel_today`. Set
*Quiet hours* 22:00 → 07:00 and *Advanced → Minimum minutes between
notifications* 30.

**Critical only for a real hike.**
Enable *Evening: next-day price announced* → Direction *Increases only*,
Minimum change `0.03`, Priority *Critical*. Leave every other type off.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| No notification at all | Test the **Notify action** on its own (Developer Tools → Actions). Check the automation trace (Automations → ⋮ → Traces). |
| Notifications don't group | The `data: "{{ notification_data }}"` line was removed from the Notify action. |
| *Critical* doesn't pierce Do Not Disturb | iOS: *Critical Alerts* not allowed for the HA app. Android: another app owns a Do-Not-Disturb override, or the phone blocks the alarm channel. |
| Nothing during a certain time of day | Quiet hours. Set **Ignore quiet hours** on that type, or use *Critical*. |
| "Data problem" fires on a healthy system | You pointed **Last-price-update sensor** at the wrong entity, or **Alert after** is shorter than your update interval. |
| Announced/effective never fires | No price change has been published yet, or your **Fuels / Direction / Minimum change** filtered it out. Confirm the `letzfuel_ha_price_change_announced` event in Developer Tools → Events. |
| Wrong entity pre-fills | You renamed the entity. Pick the current one in the section's entity field. |
