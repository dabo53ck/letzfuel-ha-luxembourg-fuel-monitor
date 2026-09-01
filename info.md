# LëtzFuel HA

Luxembourg's official maximum fuel prices, trends and refuelling insights for Home Assistant.

- Current Diesel / SP95 / SP98 prices with rich attributes
- Daily change, trend, and **next-day price awareness** ("refuel tonight or wait?")
- `price_change_announced` / `price_changed` events for automations
- Optional vehicle sensors: full-tank cost, refill cost, cost impact of a price change
- `calculate_fill_cost` and `calculate_trip_cost` services
- Price history imported into Home Assistant long-term statistics on setup
- English / French / German

Data from the public [petrol.lu official prices page](https://www.petrol.lu/en/official-prices/).
Not affiliated with GPL, petrol.lu or the Luxembourg government. Verify at the pump.
