# Upstream contribution plan

The long-term target is the official Home Assistant `ezviz` integration. The
custom `ezviz_hg2` domain remains the proving ground for device and firmware
compatibility; it should not be copied into Home Assistant Core as a second
EZVIZ integration.

## Phase 1: pyezvizapi

Submit a focused library pull request that adds a stable public contract for
RemoteControlDoor-compatible gates:

- `get_gate_status(serial, local_index="0")`
- `set_gate_command(serial, command, local_index="0")`
- accepted commands: `open`, `close`, and `pause`
- status endpoint: `global/{index}/Door/DoorStatus`
- action endpoint: `global/{index}/RemoteControlDoor/RemoteControlDoor`
- action body: `{"value":{"controlDoorCmd":"..."}}`

The pull request must include exact request-path and JSON-body tests, invalid
command coverage, a changelog entry, and an update to the Home Assistant public
API contract. It must not contain device serials, account data, tokens, or raw
diagnostics.

The generic IoT v3 primitives already exist in `pyezvizapi` 1.0.5.0. The new
helpers keep endpoint details and payload envelopes out of Home Assistant and
replace all private `_request_json`, `_session`, and `_token` access used by the
custom integration.

## Phase 2: Home Assistant Core

After the library change is released on PyPI:

1. Update `homeassistant/components/ezviz/manifest.json` to the released
   `pyezvizapi` version.
2. Add `Platform.COVER` to the official EZVIZ cloud platforms.
3. Add a gate `cover` with open, close, and stop support. Stop maps to the
   library's `pause` command.
4. Keep position support disabled because HG2 reports only closed versus open
   or partially open.
5. Keep the existing 30-second camera coordinator contract unchanged.
6. Discover HG2 devices through an additive inventory path so raw gate records
   are never inserted into the normalized camera mapping.
7. Add tests for discovery, malformed or missing state, commands, command
   failures, device registry association, and regression coverage for existing
   camera platforms.
8. Add or update the official Home Assistant documentation in the matching
   documentation pull request.

The polling interval needs maintainer agreement. A gate-only 5-second poll has
been validated in the custom integration, but the official integration's global
camera coordinator must remain at 30 seconds. The Core implementation should
either use a dedicated gate poll or retain 30 seconds with an immediate refresh
after commands; it must not increase polling for every EZVIZ camera.

## Phase 3: HG2 and CH3 settings

Configuration entities should follow in separate pull requests after the cover
is accepted. Start with settings that return stable values across tested
firmware. Do not expose generic raw-write services, product metadata dumps, or
features that return `data: null`.

## Out of scope for the first Core pull request

- The custom integration's raw IoT and metadata services.
- Account inventory sensors and raw feature attributes.
- Gate position or percentage control.
- Calibration and experimental commands.
- CH3 settings.
- A second config flow or a second EZVIZ account session.

## Upstream references

- Home Assistant EZVIZ integration:
  <https://github.com/home-assistant/core/tree/dev/homeassistant/components/ezviz>
- pyezvizapi: <https://github.com/RenierM26/pyEzvizApi>
- Related non-camera discovery request:
  <https://github.com/home-assistant/core/issues/166295>
- Related pyezvizapi detector draft:
  <https://github.com/RenierM26/pyEzvizApi/pull/99>
