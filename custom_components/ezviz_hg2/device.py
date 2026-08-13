"""Centralized EZVIZ HG2/CH3 device detection, routing, and capabilities.

This module is intentionally free of Home Assistant imports: it only parses
the raw ``pyezvizapi`` device mapping. Keeping it dependency-free makes it
easy to unit test and is a step toward a future generic ``pyezvizapi``
contract (see ``UPSTREAM.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

# --- Device identification -------------------------------------------------


def get_device_info(device: dict[str, Any]) -> dict[str, Any]:
    """Return the ``deviceInfos`` mapping for a raw EZVIZ device."""
    info = device.get("deviceInfos")
    return info if isinstance(info, dict) else {}


def device_search_text(device: dict[str, Any]) -> str:
    """Return an uppercased blob of the fields used to recognize a model."""
    info = get_device_info(device)
    fields = (
        info.get("name"),
        info.get("model"),
        info.get("deviceCategory"),
        info.get("deviceSubCategory"),
        info.get("productName"),
        info.get("deviceType"),
    )
    return " ".join(str(value) for value in fields if value).upper()


def is_hg2(device: dict[str, Any]) -> bool:
    """Return whether a raw EZVIZ device looks like an HG2 gate controller."""
    return "HG2" in device_search_text(device)


def is_ch3(device: dict[str, Any]) -> bool:
    """Return whether a raw EZVIZ device looks like a CH3 chime."""
    return "CH3" in device_search_text(device)


def is_supported_device(device: dict[str, Any]) -> bool:
    """Return whether a raw EZVIZ device is relevant to this integration."""
    return is_hg2(device) or is_ch3(device)


def device_model(device: dict[str, Any]) -> str:
    """Return the normalized model family: ``"HG2"``, ``"CH3"``, or ``""``."""
    text = device_search_text(device)
    if "HG2" in text:
        return "HG2"
    if "CH3" in text:
        return "CH3"
    return ""


def is_cloud_offline(device: dict[str, Any]) -> bool:
    """Return whether EZVIZ explicitly reports this device offline."""
    return get_device_info(device).get("status") == 0


# --- Gate routing ------------------------------------------------------------


@dataclass(frozen=True)
class Hg2GateRoute:
    """Where and how to read/write the gate state of one HG2.

    ``resource_id`` is the fixed ``"global"`` IoT-feature path segment that
    every tested HG2 firmware uses; it is not the device's own
    ``resourceId`` field (that value has never been part of the URL path in
    this integration, only ``localIndex`` is). Keeping this dataclass frozen
    documents the contract instead of leaving it implicit in three files.
    """

    resource_id: str
    local_index: str
    status_domain: str = "Door"
    status_feature: str = "DoorStatus"
    action_domain: str = "RemoteControlDoor"
    action_id: str = "RemoteControlDoor"


class CommandRoute(Enum):
    """Where a gate command should be attempted before it is sent."""

    CLOUD = auto()
    """A resolvable cloud route exists; try it first."""

    BLE_CLOUD_OFFLINE = auto()
    """The cloud is already known unavailable; go straight to BLE."""

    BLE_NO_CLOUD_ROUTE = auto()
    """No cloud route exists, but BLE is configured as the only option."""

    NO_ROUTE = auto()
    """Neither a cloud route nor BLE is available; the command cannot be sent."""


def decide_command_route(
    *,
    ble_configured: bool,
    cloud_offline: bool,
    last_update_success: bool,
    has_route: bool,
) -> CommandRoute:
    """Return where an outgoing gate command should be attempted.

    This only covers the decision made *before* attempting the command.
    Whether a failed cloud attempt is safe to retry over BLE afterward is a
    separate, narrower question answered by
    :func:`api.should_fallback_to_ble` (only an explicit clean rejection is
    eligible; ambiguous network failures are not retried).
    """
    if ble_configured and (cloud_offline or not last_update_success):
        return CommandRoute.BLE_CLOUD_OFFLINE
    if not has_route:
        return (
            CommandRoute.BLE_NO_CLOUD_ROUTE if ble_configured else CommandRoute.NO_ROUTE
        )
    return CommandRoute.CLOUD


def resolve_gate_route(device: dict[str, Any]) -> Hg2GateRoute | None:
    """Return the gate route for a device, or ``None`` if not resolvable.

    Mirrors the historical behavior: a route exists once ``resourceInfos``
    has at least one entry with a truthy ``resourceId``, and the resource's
    ``localIndex`` (default ``"0"``) is used to read and write the door
    feature. The IoT-feature resource segment itself is always ``"global"``.
    """
    resources = device.get("resourceInfos")
    if not isinstance(resources, list):
        return None
    for resource in resources:
        if not isinstance(resource, dict) or not resource.get("resourceId"):
            continue
        local_index = str(resource.get("localIndex", "0"))
        return Hg2GateRoute(resource_id="global", local_index=local_index)
    return None


# --- Door status parsing -----------------------------------------------------


def get_door_status(
    device: dict[str, Any], route: Hg2GateRoute | None = None
) -> int | None:
    """Return the raw ``DoorStatus`` value cached for a device, if any.

    ``0`` means closed, ``1`` means not fully closed (open or partially
    open). EZVIZ does not report a percentage. When ``route`` is omitted the
    historical fixed lookup path (``local index "0"`` / resource
    ``"global"``) is used, matching every previously cached snapshot.
    """
    local_index = route.local_index if route is not None else "0"
    resource_id = route.resource_id if route is not None else "global"
    status_domain = route.status_domain if route is not None else "Door"
    status_feature = route.status_feature if route is not None else "DoorStatus"

    feature_info = device.get("FEATURE_INFO")
    if not isinstance(feature_info, dict):
        return None
    index = feature_info.get(local_index, feature_info.get(0))
    if not isinstance(index, dict):
        return None
    resource = index.get(resource_id)
    if not isinstance(resource, dict):
        return None
    domain = resource.get(status_domain)
    if not isinstance(domain, dict):
        return None
    feature = domain.get(status_feature)
    if not isinstance(feature, dict):
        return None
    values = feature.get("doorStatus")
    if not isinstance(values, list) or not values:
        return None
    value = values[0]
    return value if isinstance(value, int) else None


def set_door_status(
    device: dict[str, Any], values: Any, route: Hg2GateRoute | None = None
) -> None:
    """Cache a direct ``DoorStatus`` feature read onto a device mapping."""
    if not isinstance(values, list):
        return
    local_index = route.local_index if route is not None else "0"
    resource_id = route.resource_id if route is not None else "global"
    status_domain = route.status_domain if route is not None else "Door"
    status_feature = route.status_feature if route is not None else "DoorStatus"

    feature_info = device.setdefault("FEATURE_INFO", {})
    index = feature_info.setdefault(local_index, {})
    resource = index.setdefault(resource_id, {})
    domain = resource.setdefault(status_domain, {})
    feature = domain.setdefault(status_feature, {})
    feature["doorStatus"] = values


# --- Feature-based capability detection --------------------------------------


def _feature_present(
    device: dict[str, Any], local_index: str, resource: str, domain: str, feature: str
) -> bool:
    value: Any = device.get("FEATURE_INFO", {})
    for key in (local_index, resource, domain, feature):
        if not isinstance(value, dict):
            return False
        value = value.get(key)
    return value is not None


@dataclass(frozen=True)
class Hg2Capabilities:
    """What one HG2 device is known to support.

    Detection prefers concrete signals from the cloud payload (a resolvable
    gate route, a present feature branch) and falls back to the commercial
    name/model match used historically. This keeps today's HG2 400 behavior
    unchanged while leaving room for HG2 variants that expose a different
    feature subset.
    """

    gate_control: bool = False
    gate_status: bool = False
    custom_opening: bool = False
    ble_control: bool = False
    motor_speed: bool = False
    auto_close: bool = False
    warning_light: bool = False


def get_hg2_capabilities(device: dict[str, Any]) -> Hg2Capabilities:
    """Return the best-effort capability set for a raw EZVIZ device."""
    if not is_hg2(device):
        return Hg2Capabilities()

    route = resolve_gate_route(device)
    has_route = route is not None

    return Hg2Capabilities(
        gate_control=has_route,
        gate_status=has_route,
        custom_opening=_feature_present(
            device, "0", "global", "ChannelControllerMgr", "MotorParamCfg"
        ),
        # No cloud metadata currently distinguishes BLE-capable HG2 hardware;
        # fall back to the model match like the rest of this integration.
        ble_control=True,
        motor_speed=_feature_present(
            device, "0", "global", "ChannelControllerMgr", "MotorParamCfg"
        ),
        auto_close=_feature_present(device, "0", "global", "Door", "DoorParamCfg"),
        warning_light=_feature_present(
            device, "0", "global", "WarningLightMgr", "WarningLightCfg"
        ),
    )
