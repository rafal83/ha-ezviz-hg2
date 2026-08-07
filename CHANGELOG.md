# Changelog

All notable changes to this project are documented in this file.

## 0.2.3

- Mark the gate cover as an assumed-state entity so the open and close buttons stay available regardless of the last known door status, since the EZVIZ API only reports closed versus not-closed and cannot confirm a full open position.

## 0.2.2

- Add a per-device raw data diagnostic sensor (disabled by default, localized name) exposing the complete raw API payload as an attribute, for debugging without downloading diagnostics.

## 0.2.1

- Remove the gate direction lock after a pause: it was masking a motor issue, not a real device constraint, so open/close now work freely regardless of the last paused direction.

## 0.2.0

- Raise the default gate status polling interval from 5 to 15 seconds and make it configurable through the integration's options flow, to ease load on the EZVIZ cloud API.

## 0.1.0

- Initial HACS release.
- Add EZVIZ HG2 gate control and five-second status polling.
- Add HG2 motor, warning light, fill light, automatic closing, and notification settings.
- Add EZVIZ CH3 mute, microphone, night light, detection, and network settings when reported by the device.
- Add config flow, reauthentication, diagnostics, services, translations, and local brand icon.
