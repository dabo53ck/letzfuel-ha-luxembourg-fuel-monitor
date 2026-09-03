# LëtzFuel HA

Luxembourg's regulated maximum fuel prices, trends and refuelling insights for Home Assistant.

- Current Diesel / SP95 / SP98 prices with rich attributes
- Daily change, trend, and **next-day price awareness** ("refuel tonight or wait?")
- `price_change_announced` / `price_changed` events for automations
- Import-and-go notification blueprint (`docs/notifications-blueprint.md`)
- Optional vehicle sensors: full-tank cost, refill cost, cost impact of a price change
- `calculate_fill_cost` and `calculate_trip_cost` services
- Price history imported into Home Assistant long-term statistics on setup
- English / French / German / Luxembourgish

Data from the public [petrol.lu prices page](https://www.petrol.lu/en/official-prices/);
the announced next-day price comes from [RTL.lu](https://www.rtl.lu/mobiliteit/petrolspraisser),
which publishes it the evening before (petrol.lu does not).
Not affiliated with GPL, petrol.lu, RTL or the Luxembourg government. Verify at the pump.
