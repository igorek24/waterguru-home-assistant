# WaterGuru for Home Assistant

Home Assistant integration for **WaterGuru** pool and spa monitors (SENSE
pods). It signs in to the WaterGuru cloud exactly like the mobile app does
and exposes every reading as native entities — no Docker sidecar, no REST
sensors, no YAML.

## Features

- **Water chemistry sensors** — free chlorine, pH, skimmer flow, water
  temperature, plus any other measurement your pods report (alkalinity,
  calcium hardness, CYA, salt)
- **Pod sensors** — cassette level (% and measurements remaining), battery,
  Wi-Fi signal, last connection, firmware version
- **Problem binary sensors** — water problem (WaterGuru's own red/yellow
  status), cassette low, battery low
- **Alerts and advice as attributes** — e.g. "pH high" with
  "Add 2 cups of 93.2% concentration dry acid"
- **Multiple pools and multiple pods** — each water body becomes a device,
  each pod a sub-device
- Proper **token refresh** (the reference projects re-authenticate on every
  poll), configurable polling, re-auth flow, and diagnostics

## Installation

### HACS

HACS → ⋮ → **Custom repositories** → `https://github.com/igorek24/waterguru-home-assistant`,
type **Integration** → Download → restart Home Assistant.

### Manual

Copy `custom_components/waterguru` into `config/custom_components/` and
restart.

## Configuration

Settings → Devices & Services → **Add Integration** → **WaterGuru** →
sign in with the same email and password you use in the WaterGuru app.

### Options

| Option | Default | Meaning |
|---|---|---|
| Polling interval (hours) | `6` | WaterGuru pods measure roughly once a day, so polling faster gains nothing and hammers their API. 1–24 h allowed. |
| Temperature unit | `auto` | Which unit your account **reports** (the source unit), not the display unit. Auto assumes Fahrenheit for readings ≥ 45 (no pool is 45 °C). |

`waterguru.refresh` forces an immediate poll.

## Entities

Per water body (device named after your pool):

| Entity | Notes |
|---|---|
| `sensor.<pool>_free_chlorine` | ppm, with `target`, `good_min`/`good_max`, `alert`, `advice` attributes |
| `sensor.<pool>_ph` | same attributes |
| `sensor.<pool>_skimmer_flow` | gal/min |
| `sensor.<pool>_water_temperature` | follows your Home Assistant unit setting; `fahrenheit` / `celsius` attributes carry both values |
| `sensor.<pool>_water_temperature_degf` | always Fahrenheit, regardless of HA's unit system |
| `sensor.<pool>_water_temperature_degc` | always Celsius, regardless of HA's unit system |
| `sensor.<pool>_status` | `GREEN` / `YELLOW` / `ORANGE` / `RED`, with all alerts + advice |
| `sensor.<pool>_last_measurement` | timestamp of the pod's last reading |
| `binary_sensor.<pool>_water_problem` | on when the status is not green |

Per pod (sub-device):

| Entity | Notes |
|---|---|
| `sensor.<pod>_cassette` | % left, plus measurements remaining and "time left" text |
| `sensor.<pod>_battery` | % left, plus voltage |
| `binary_sensor.<pod>_cassette_low` / `_battery_low` | on when WaterGuru flags it |
| `sensor.<pod>_wifi_signal`, `sensor.<pod>_last_connection` | disabled by default |

## Example automations

```yaml
automation:
  - alias: "Pool needs attention"
    trigger:
      - platform: state
        entity_id: binary_sensor.mosquero_water_problem
        to: "on"
    action:
      - action: notify.mobile_app
        data:
          title: "Pool: {{ state_attr('binary_sensor.mosquero_water_problem','status') }}"
          message: >
            {{ state_attr('binary_sensor.mosquero_water_problem','alerts') | join(', ') }} —
            {{ state_attr('binary_sensor.mosquero_water_problem','advice') | join(' ') }}

  - alias: "Order a new WaterGuru cassette"
    trigger:
      - platform: numeric_state
        entity_id: sensor.mosquero_sense_cassette
        below: 15
    action:
      - action: persistent_notification.create
        data:
          title: "WaterGuru cassette low"
          message: "{{ state_attr('sensor.mosquero_sense_cassette','time_left') }} remaining."

  - alias: "Pod went offline"
    trigger:
      - platform: template
        value_template: >
          {{ (now() - states('sensor.mosquero_last_measurement') | as_datetime).days > 3 }}
    action:
      - action: persistent_notification.create
        data:
          message: "No WaterGuru measurement in over 3 days — check battery and Wi-Fi."
```

## How it works

WaterGuru has no public API. The app authenticates against AWS Cognito
using SRP and then invokes a Lambda function directly with SigV4-signed
requests:

1. Cognito user pool SRP login → id / access / refresh tokens
2. Cognito identity pool → temporary AWS credentials
3. SigV4 `POST` to `prod-getDashboardView` → the dashboard payload

This integration reproduces that flow with `aiohttp` (all I/O async, no
blocking calls in the event loop); only the SRP maths comes from
`pycognito`, which already ships with Home Assistant. Tokens are cached and
refreshed with the refresh token instead of logging in on every poll.

## Troubleshooting

- **"Invalid email or password"** — the same credentials must work in the
  WaterGuru app. Note the login is whatever email the account was created
  with, which may not be your everyday address.
- **Readings look stale** — that's the data WaterGuru has; check
  `sensor.<pool>_last_measurement`. A pod that lost Wi-Fi or ran out of
  cassette stops measuring, and the cloud keeps serving the last values.
- **Temperature shows the wrong unit** — the main temperature sensor follows
  Home Assistant's unit system. To change just this entity: entity settings
  (gear icon) → **Unit of Measurement** → °F/°C. Or use the dedicated
  `..._water_temperature_degf` / `..._degc` sensors, which never convert.
  (The "Temperature unit" option describes what WaterGuru *sends*, so
  changing it does not change the display unit.)
- **Debug logging**: `logger: logs: custom_components.waterguru: debug`
- **Diagnostics**: integration entry → ⋮ → Download diagnostics (credentials
  and identifiers redacted).

## Credits

Protocol details owe a lot to
[bdwilson/waterguru-api](https://github.com/bdwilson/waterguru-api) (the
Cognito/Lambda flow) and
[jkoehl/homebridge-waterguru](https://github.com/jkoehl/homebridge-waterguru)
(the payload shape), plus the
[Home Assistant community thread](https://community.home-assistant.io/t/water-guru-integration/291917).

## Trademarks and disclaimer

This is an **unofficial, independent** project. It is not affiliated with,
endorsed by, or supported by WaterGuru, Inc.

"WaterGuru" and "SENSE" are trademarks of their respective owner and are
used here only to identify the hardware this integration works with
(nominative use). No WaterGuru logo, brand artwork, or other proprietary
asset is included in this repository — the integration's icon is original
artwork created for this project.

The integration talks to WaterGuru's cloud service using your own account
credentials, the same way their app does. Use at your own risk, respect
WaterGuru's terms of service, and do not poll their API aggressively (the
default six-hour interval is deliberate — the pods only measure about once
a day).
