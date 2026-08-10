# Changelog

All notable changes to this project are documented in this file.

## 0.3.3

- Add optional authenticated BLE configuration for one HG2, disabled by default, with serial discovery through Home Assistant's shared Bluetooth stack and an optional explicit BLE address.
- Route gate commands through BLE when EZVIZ reports the HG2 offline, the last cloud refresh failed, or the cloud explicitly rejects the command; ambiguous failures after transmission are not automatically retried.
- Add `ezviz_hg2.send_ble_command` to test open, close, and pause directly over BLE.
- Add a cloud custom-opening button that uses the configured HG2 custom distance.

## 0.2.6

- Support dragging the gate cover to a target position: it is timed via the same travel model as a full open/close, then automatically paused near the target. Only available once travel durations are calibrated.
- Stop assuming a 20-second default travel duration: the position estimate and set-position support now stay off until the open and close durations are actually known (via calibration or manual entry), instead of silently guessing.
- Add a "Reset travel calibration" button (disabled by default) to clear the measured or entered travel durations and go back to no position estimate.
- Ship the official EZVIZ icon and logo assets (including hDPI variants) in the integration's local `brand` folder.

## 0.2.5

- Add a "Calibrate travel duration" button (disabled by default) that automatically measures the gate's full close duration and applies it to both the open and close travel-time options, instead of requiring a manual guess.

## 0.2.4

- Estimate the gate's travel position from configurable open/close durations (new options flow fields), eased to match the motor slowing down near the end of its travel, since the EZVIZ cloud only reports closed versus not-closed.

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
