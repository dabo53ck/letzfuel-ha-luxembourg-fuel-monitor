# Roadmap / planned ideas

Not implemented yet — design notes kept here so they aren't lost between
sessions. No code exists for any of this.

## Navigate-to-nearest-station notification button

**Idea:** while away from home, the *Refuel recommendation* notification
(`refuel_today`) gets a tappable button that opens turn-by-turn navigation to
the nearest fuel station — no typing an address, one tap from the push.

### Why this is feasible without a click-time server round trip

The Home Assistant Companion app supports a `uri` field on a notification
action: tapping the button opens that URL directly on the device (native
maps app if installed, browser otherwise). So the navigation link only needs
to be fully built at **send time**, in the automation — no webhook or
click-handling automation needed.

### Design

1. **Station data — fetch once, compute locally.**
   Luxembourg has ~234 fuel stations total, so instead of querying a live
   API per notification (rate limits, network dependency, and it would leak
   the user's live GPS to a third party), fetch the *complete* national
   station list once from OpenStreetMap's Overpass API and cache it (e.g. in
   the integration's `Store`, refreshed roughly monthly or via a manual
   reload). "Nearest station" is then a local haversine-distance calculation
   over the cached list — the user's coordinates never leave Home Assistant.

   Overpass query sketch:

   ```
   [out:json][timeout:25];
   area["ISO3166-1"="LU"][admin_level=2]->.lu;
   (
     node["amenity"="fuel"](area.lu);
     way["amenity"="fuel"](area.lu);
   );
   out center tags;
   ```

   New module, e.g. `custom_components/letzfuel_ha/stations.py`: Overpass
   client + cache (with a fallback to stale cached data if a refresh fails)
   + a `FuelStation(name, brand, latitude, longitude, address)` model +
   nearest-neighbour lookup.

2. **New response service** `letzfuel_ha.find_nearest_station` (same shape
   as the existing `calculate_fill_cost` / `calculate_trip_cost`):

   | Field | Required | Description |
   | --- | --- | --- |
   | `person` | yes | A `person` entity to read live `latitude`/`longitude` from |
   | `brand` | no | Filter to one brand |
   | `max_results` | no | Default 1 |

   Response: nearest station(s) with `name`, `brand`, `latitude`,
   `longitude`, `distance_km`, and a ready-to-use `navigation_url` — a
   cross-platform Google Maps deep link
   (`https://www.google.com/maps/dir/?api=1&destination=<lat>,<lon>&travelmode=driving`),
   which opens the installed Maps app on both iOS and Android, or falls back
   to the browser.

3. **Blueprint change** (`blueprints/automation/letzfuel_ha/notifications.yaml`,
   *Refuel recommendation* section): new optional toggle ("Add a Navigate
   button") + a `person` picker (could default to whichever person the
   *presence gate* already uses, if set). When enabled, the automation calls
   the new service with `response_variable` before building the
   notification, then adds:

   ```yaml
   actions:
     - action: "navigate_nearest_station"
       title: "Navigate"  # per-language, like everything else in the blueprint
       uri: "{{ nav_url }}"
   ```

   Only makes sense for `refuel_today` (not `wait`), so gate accordingly.

### Open questions to resolve when this is actually built

- Cache refresh cadence and whether a manual "reload stations" service/button
  is worth adding for immediately after Overpass data corrections.
- Whether to expose a preferred-brand config option (Step 2 / Options) or
  leave brand filtering to the service call only.
- Graceful behaviour when the station cache is empty (first run, Overpass
  unreachable) or the `person` entity has no GPS fix — likely: service
  raises/returns an error the blueprint can skip the button on.
- Whether `google.com/maps/dir` is the best universal choice, or whether to
  branch by platform (`apple_maps` vs `google_maps` companion app data key)
  for a more native feel.
- Test coverage: mocked Overpass client, haversine correctness, the new
  service, and a blueprint trace check.
- Docs: README data-sources table, `docs/notifications-blueprint.md`, and a
  CHANGELOG entry once shipped.

## Portuguese and Italian translations

**Idea:** add `pt` and `it` alongside the existing English/German/French/
Lëtzebuergesch support — both communities are sizeable in Luxembourg, and
neither is covered today.

### Where this touches

1. **Integration** (`custom_components/letzfuel_ha/translations/`): new
   `pt.json` and `it.json`, translated from `strings.json` (the reference
   copy) the same way `de.json`/`fr.json`/`lb.json` already are — config
   flow and options-step labels/descriptions.
2. **Blueprint** (`blueprints/automation/letzfuel_ha/notifications.yaml`):
   - The `notify_language` input's selector options list gets two more
     entries (`{ label: Português, value: pt }`, `{ label: Italiano, value:
     it }`).
   - The `d = {...}` language dict (title/message strings for announced/
     effective/rec/threshold, plus `decimal`) needs a full `'pt'` and `'it'`
     entry — real translations, not machine-generated, same bar as the
     existing four. Portuguese and Italian both use `,` as the decimal
     separator like German/French/Lëtzebuergesch already do.
   - Blueprint's own input *labels* (section names, field descriptions)
     stay English regardless, per the existing "Home Assistant can't
     translate a blueprint's own UI" constraint noted in
     [`docs/notifications-blueprint.md`](notifications-blueprint.md) — only
     the *notification text* is affected.

### Open questions to resolve when this is actually built

- Source the translations properly (native speaker review, not just a
  first machine-translated draft) — wrong wording in a push notification is
  more visible/embarrassing than in a settings screen.
- Whether this bumps the blueprint's version marker on its own or waits to
  ride along with some other change (no code/behaviour changes, pure
  content addition).
- CHANGELOG entry once shipped.
