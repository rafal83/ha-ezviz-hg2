# EZVIZ HG2 & CH3 for Home Assistant

[![HACS validation](https://github.com/rafal83/ha-ezviz-hg2/actions/workflows/validate.yml/badge.svg)](https://github.com/rafal83/ha-ezviz-hg2/actions/workflows/validate.yml)
[![GitHub release](https://img.shields.io/github/v/release/rafal83/ha-ezviz-hg2)](https://github.com/rafal83/ha-ezviz-hg2/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=rafal83&repository=ha-ezviz-hg2&category=integration)

Unofficial Home Assistant integration for the EZVIZ HG2 gate controller and its associated CH3 chime.

## Features

- Native gate `cover` with open, close, and pause commands, plus an estimated travel position based on configurable open/close durations.
- Direct gate status polling with a configurable interval (15 seconds by default, adjustable from the integration's **Configure** options).
- HG2 motor speed, direction, anti-bounce sensitivity, automatic closing, STOP input, warning light, warning sound, fill light, and notification settings.
- CH3 mute mode, mute plan, microphone volume, night light, loitering detection, and network port protection.
- Config flow, reauthentication, diagnostics, and service actions.
- English defaults and French translations.

## Requirements

- Home Assistant 2026.3.0 or newer.
- An EZVIZ account containing an HG2 or CH3 device.
- EZVIZ two-factor authentication must currently be disabled because the upstream API library cannot complete that flow.
- Internet access to the EZVIZ cloud.

## Installation with HACS

Until the repository is included in the HACS default list:

1. Open HACS.
2. Open the three-dot menu and select **Custom repositories**.
3. Add `https://github.com/rafal83/ha-ezviz-hg2` as an **Integration** repository.
4. Install **EZVIZ HG2 & CH3**.
5. Restart Home Assistant.
6. Open **Settings > Devices & services > Add integration**.
7. Search for **EZVIZ HG2 & CH3** and enter your EZVIZ account details.

## Gate behavior

The HG2 reports a binary door status:

- `0`: closed
- `1`: open or partially open

The cloud does not report a reliable movement percentage, so the `cover` entity estimates its position from the configured full open/close travel times (adjustable from the integration's **Configure** options) instead of a real reading. The estimate is eased to account for the gate slowing down near the end of its travel, and it resyncs to 0% whenever the cloud confirms the gate is fully closed. It is informational only: the entity does not support setting an exact position.

A **Calibrate travel duration** button (disabled by default, since it fully cycles the gate) measures these durations automatically: it opens the gate, waits for it to settle fully open, then times a full close down to a confirmed closed status. Both directions are set to that measurement, assuming a roughly symmetrical travel. This is unrelated to the HG2's own native **Calibrer la course** button, which calibrates the motor's internal travel limits and does not affect what the cloud reports.

The HG2 hardware has a separate custom opening preset, exposed as a `select` entity.

## CH3 limitations

The CH3 product profile advertises more sound and ringtone functions than some firmware versions actually report. Entities are created only for settings with a usable value. Functions returning `data: null` are not exposed as controls.

## Service actions

Advanced read-only metadata and generic IoT actions are available under the `ezviz_hg2` domain. Generic writes should only be used with identifiers confirmed by the device product profile.

## Diagnostics and bug reports

Before opening an issue:

1. Download diagnostics from the integration page.
2. Enable debug logging for `custom_components.ezviz_hg2` and reproduce the issue.
3. Attach redacted diagnostics and relevant logs to the issue.

Never publish passwords, session tokens, verification codes, or unredacted diagnostics.

## Official integration

The proposed path to the official Home Assistant EZVIZ integration is documented
in [UPSTREAM.md](UPSTREAM.md). It starts with public gate helpers in
`pyezvizapi`, followed by a focused cover-only Home Assistant Core pull request.

## Disclaimer

This project is unofficial and is not affiliated with, endorsed by, or supported by EZVIZ. It relies on private cloud APIs that may change without notice. Gate movement can cause injury or damage; keep the area clear and retain a working physical control and safety system.

## License

[MIT](LICENSE)
