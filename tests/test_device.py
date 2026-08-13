"""Unit tests for the dependency-free device detection/routing helpers."""

from __future__ import annotations

from _load import load

device = load("device")


def _device(**overrides):
    base = {
        "deviceInfos": {
            "name": "Portail",
            "model": "HG2-400",
            "deviceCategory": "GateController",
            "deviceSubCategory": "",
            "productName": "",
            "deviceType": "",
            "status": 1,
        },
        "resourceInfos": [{"resourceId": "abc123", "localIndex": "0"}],
    }
    base.update(overrides)
    return base


# --- identification -----------------------------------------------------


def test_is_hg2_true_for_model_field():
    assert device.is_hg2(_device()) is True


def test_is_hg2_false_for_unrelated_device():
    d = _device(deviceInfos={"model": "C6", "name": "Camera"})
    assert device.is_hg2(d) is False


def test_is_ch3_true_for_model_field():
    d = _device(deviceInfos={"model": "CH3", "name": "Carillon"})
    assert device.is_ch3(d) is True
    assert device.is_hg2(d) is False


def test_is_supported_device_matches_either():
    assert device.is_supported_device(_device()) is True
    assert device.is_supported_device({"deviceInfos": {"model": "C6"}}) is False


def test_device_model_prefers_hg2_over_ch3_when_both_present():
    # Defensive: should not happen in practice, but the resolution order
    # must be deterministic.
    d = _device(deviceInfos={"model": "HG2 CH3"})
    assert device.device_model(d) == "HG2"


def test_device_search_text_includes_name_and_category():
    d = _device(
        deviceInfos={
            "name": "Portail HG2",
            "model": "",
            "deviceCategory": "",
            "deviceSubCategory": "",
            "productName": "",
            "deviceType": "",
        }
    )
    assert device.is_hg2(d) is True


def test_get_device_info_missing_returns_empty_dict():
    assert device.get_device_info({}) == {}
    assert device.get_device_info({"deviceInfos": "not-a-dict"}) == {}


def test_is_cloud_offline():
    assert device.is_cloud_offline(_device(deviceInfos={"status": 0})) is True
    assert device.is_cloud_offline(_device(deviceInfos={"status": 1})) is False
    assert device.is_cloud_offline({}) is False


# --- routing --------------------------------------------------------------


def test_resolve_gate_route_found():
    route = device.resolve_gate_route(_device())
    assert route == device.Hg2GateRoute(resource_id="global", local_index="0")


def test_resolve_gate_route_uses_local_index_from_resource():
    d = _device(resourceInfos=[{"resourceId": "abc", "localIndex": "2"}])
    route = device.resolve_gate_route(d)
    assert route is not None
    assert route.local_index == "2"
    # The resource segment used in the URL is always "global"; the device's
    # own resourceId has never been part of that path in this integration.
    assert route.resource_id == "global"


def test_resolve_gate_route_defaults_local_index_when_absent():
    d = _device(resourceInfos=[{"resourceId": "abc"}])
    route = device.resolve_gate_route(d)
    assert route is not None
    assert route.local_index == "0"


def test_resolve_gate_route_none_when_no_resource_infos():
    assert device.resolve_gate_route({}) is None
    assert device.resolve_gate_route({"resourceInfos": "nope"}) is None


def test_resolve_gate_route_none_when_resource_id_falsy():
    d = _device(resourceInfos=[{"resourceId": ""}, {"resourceId": None}])
    assert device.resolve_gate_route(d) is None


def test_resolve_gate_route_skips_entries_without_resource_id():
    d = _device(
        resourceInfos=[
            {"localIndex": "9"},
            {"resourceId": "abc", "localIndex": "1"},
        ]
    )
    route = device.resolve_gate_route(d)
    assert route is not None
    assert route.local_index == "1"


def test_gate_route_default_domains():
    route = device.Hg2GateRoute(resource_id="global", local_index="0")
    assert route.status_domain == "Door"
    assert route.status_feature == "DoorStatus"
    assert route.action_domain == "RemoteControlDoor"
    assert route.action_id == "RemoteControlDoor"


# --- DoorStatus parsing -----------------------------------------------------


def test_get_door_status_closed():
    d = _device()
    device.set_door_status(d, [0])
    assert device.get_door_status(d) == 0


def test_get_door_status_open():
    d = _device()
    device.set_door_status(d, [1])
    assert device.get_door_status(d) == 1


def test_get_door_status_missing_is_unknown():
    assert device.get_door_status(_device()) is None


def test_get_door_status_invalid_shape_is_unknown():
    d = _device()
    d["FEATURE_INFO"] = {"0": {"global": {"Door": {"DoorStatus": {"doorStatus": "nope"}}}}}
    assert device.get_door_status(d) is None

    d2 = _device()
    d2["FEATURE_INFO"] = {"0": {"global": {"Door": {"DoorStatus": {"doorStatus": []}}}}}
    assert device.get_door_status(d2) is None

    d3 = _device()
    d3["FEATURE_INFO"] = {"0": {"global": {"Door": {"DoorStatus": {"doorStatus": ["not-an-int"]}}}}}
    assert device.get_door_status(d3) is None


def test_set_door_status_ignores_non_list_values():
    d = _device()
    device.set_door_status(d, "not-a-list")
    assert device.get_door_status(d) is None


def test_get_door_status_respects_explicit_route():
    d = _device()
    route = device.Hg2GateRoute(resource_id="global", local_index="3")
    device.set_door_status(d, [0], route)
    # Not visible at the default "0" lookup path.
    assert device.get_door_status(d) is None
    assert device.get_door_status(d, route) == 0


# --- capabilities -----------------------------------------------------------


def test_capabilities_empty_for_non_hg2():
    assert device.get_hg2_capabilities({"deviceInfos": {"model": "C6"}}) == device.Hg2Capabilities()


def test_capabilities_gate_control_requires_route():
    with_route = device.get_hg2_capabilities(_device())
    assert with_route.gate_control is True
    assert with_route.gate_status is True

    without_route = device.get_hg2_capabilities(_device(resourceInfos=[]))
    assert without_route.gate_control is False
    assert without_route.gate_status is False


def test_capabilities_feature_detection_from_feature_info():
    d = _device()
    d["FEATURE_INFO"] = {
        "0": {
            "global": {
                "ChannelControllerMgr": {"MotorParamCfg": {"motorSpeed": "high"}},
                "WarningLightMgr": {"WarningLightCfg": {"lightEnabled": True}},
            }
        }
    }
    caps = device.get_hg2_capabilities(d)
    assert caps.motor_speed is True
    assert caps.custom_opening is True
    assert caps.warning_light is True
    assert caps.auto_close is False


def test_capabilities_ble_control_is_a_model_fallback():
    # No cloud signal distinguishes BLE-capable hardware today; documented
    # as a deliberate model-based fallback rather than a real capability read.
    assert device.get_hg2_capabilities(_device()).ble_control is True


# --- command routing decision -----------------------------------------------


def test_decide_command_route_prefers_cloud_when_healthy():
    route = device.decide_command_route(
        ble_configured=True,
        cloud_offline=False,
        last_update_success=True,
        has_route=True,
    )
    assert route is device.CommandRoute.CLOUD


def test_decide_command_route_cloud_when_ble_not_configured_even_if_offline():
    # Without BLE configured there is nothing to fall back to before even
    # trying, so the (doomed) cloud attempt is still made; the caller
    # surfaces the resulting cloud error.
    route = device.decide_command_route(
        ble_configured=False,
        cloud_offline=True,
        last_update_success=False,
        has_route=True,
    )
    assert route is device.CommandRoute.CLOUD


def test_decide_command_route_ble_when_cloud_reports_device_offline():
    route = device.decide_command_route(
        ble_configured=True,
        cloud_offline=True,
        last_update_success=True,
        has_route=True,
    )
    assert route is device.CommandRoute.BLE_CLOUD_OFFLINE


def test_decide_command_route_ble_when_last_poll_failed():
    route = device.decide_command_route(
        ble_configured=True,
        cloud_offline=False,
        last_update_success=False,
        has_route=True,
    )
    assert route is device.CommandRoute.BLE_CLOUD_OFFLINE


def test_decide_command_route_ble_when_no_cloud_route_at_all():
    route = device.decide_command_route(
        ble_configured=True,
        cloud_offline=False,
        last_update_success=True,
        has_route=False,
    )
    assert route is device.CommandRoute.BLE_NO_CLOUD_ROUTE


def test_decide_command_route_no_route_when_neither_available():
    route = device.decide_command_route(
        ble_configured=False,
        cloud_offline=False,
        last_update_success=True,
        has_route=False,
    )
    assert route is device.CommandRoute.NO_ROUTE
