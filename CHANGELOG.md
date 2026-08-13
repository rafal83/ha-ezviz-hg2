# Changelog

All notable changes to this project are documented in this file.

## 0.4.1

- Fix: the gate `cover` entity could fail to be created at all for an HG2 whose resource route was not yet resolvable when entities were set up, instead of appearing and simply reporting unavailable as before 0.4.0. A cover is now created for every discovered HG2 again, regardless of route state.

## 0.4.0

- **Breaking:** each HG2 gate's travel duration and BLE fallback settings now live on that gate's own config subentry ("Add a gate" / "Reconfigure" from the integration's page) instead of being shared across the whole EZVIZ account. Accounts with more than one HG2 no longer have their calibration or BLE settings overwrite each other; the integration's own **Configure** dialog now only holds the cloud polling interval. Existing BLE and travel-duration settings are not migrated automatically — re-add them per gate.
- Fix: a failed open, close, or pause command no longer leaves the cover reporting a fake in-progress movement; the position estimate now only starts (or stops) once the command's outcome is known.
- Fix: a gate found already open when Home Assistant starts is no longer assumed to be at 100% — EZVIZ only reports closed versus not-closed, so the position stays unknown until a command starts a fresh estimate.
- Fix: a failed `DoorStatus` poll no longer keeps showing the last cached closed/open value as if it were current; the cover reports unknown until a fresh poll succeeds. One gate's poll failure no longer affects the others on the same account.
- The cover's `available` state now reflects actual cloud or BLE reachability (including current BLE presence) instead of becoming available just because BLE fallback is configured.
- Centralize HG2/CH3 device detection, gate routing, `DoorStatus` parsing, and cloud/BLE fallback error classification into two dependency-free modules (`device.py`, `travel.py`), replacing several duplicated implementations.
- Add a pytest suite covering device detection and routing, position/movement estimation, cloud/BLE command dispatch and fallback classification, coordinator polling and per-gate freshness, and the new per-gate config subentry flow.

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
