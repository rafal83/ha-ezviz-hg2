"""EZVIZ cloud API adapter for HG2 discovery and experiments."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from pyezvizapi.client import EzvizClient
from pyezvizapi.exceptions import PyEzvizError


class EzvizActionRejected(PyEzvizError):
    """The cloud explicitly rejected an action without executing it."""


def should_fallback_to_ble(exc: Exception) -> bool:
    """Return whether a cloud command failure is safe to retry over BLE.

    Only an explicit, clean rejection (:class:`EzvizActionRejected`, a
    well-formed cloud response stating the action was not executed) is
    eligible. Network-level failures such as timeouts, connection errors, or
    malformed responses are ambiguous: the gate may already have received
    the command, so this integration does not duplicate it over BLE.
    """
    return isinstance(exc, EzvizActionRejected)


class EzvizHg2Api:
    """Small adapter around pyezvizapi without modifying the EZVIZ integration."""

    def __init__(self, token: Mapping[str, Any], timeout: int) -> None:
        self._client = EzvizClient(token=dict(token), timeout=timeout)

    def refresh(self) -> dict[str, Any]:
        """Refresh authentication and return all raw device mappings."""
        self._client.login()
        devices = self._client.get_device_infos()
        if not isinstance(devices, dict):
            raise PyEzvizError("Unexpected EZVIZ device response")
        return devices

    def send_iot_action(
        self,
        serial: str,
        resource_id: str,
        local_index: str,
        domain_id: str,
        action_id: str,
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Send an explicitly requested generic EZVIZ IoT action."""
        path = (
            f"/v3/iot-feature/action/{serial.upper()}/{resource_id}/"
            f"{local_index}/{domain_id}/{action_id}"
        )
        body = {"value": dict(payload or {})}

        # pyezvizapi's public set_iot_action raises a generic PyEzvizError on a
        # rejected action, which is indistinguishable from an ambiguous failure.
        # The private request helper keeps the meta check here so a clean
        # rejection can still be classified as EzvizActionRejected.
        result = self._client._request_json(  # noqa: SLF001
            "PUT", path, json_body=body
        )

        if not isinstance(result, dict):
            raise PyEzvizError("Unexpected EZVIZ action response")

        meta = result.get("meta")
        if isinstance(meta, dict) and meta.get("code") != 200:
            raise EzvizActionRejected(
                f"EZVIZ action rejected: {json.dumps(meta)}"
            )
        return result

    def get_iot_feature(
        self,
        serial: str,
        resource_id: str,
        local_index: str,
        domain_id: str,
        feature_id: str,
    ) -> dict[str, Any]:
        """Read one explicitly requested EZVIZ IoT feature."""
        result = self._client.get_device_feature_value(
            serial, resource_id, domain_id, feature_id, local_index=local_index
        )
        if not isinstance(result, dict):
            raise PyEzvizError("Unexpected EZVIZ feature response")
        return result

    def set_iot_feature(
        self,
        serial: str,
        resource_id: str,
        local_index: str,
        domain_id: str,
        feature_id: str,
        value: Any,
    ) -> dict[str, Any]:
        """Write one EZVIZ IoT feature using the app's value envelope."""
        # The library raises PyEzvizError itself when meta.code is not 200.
        result = self._client.set_iot_feature(
            serial, resource_id, local_index, domain_id, feature_id, {"value": value}
        )
        if not isinstance(result, dict):
            raise PyEzvizError("Unexpected EZVIZ feature write response")
        return result

    def upgrade_device(self, serial: str) -> bool:
        """Trigger the firmware upgrade EZVIZ already has queued for a device."""
        return self._client.upgrade_device(serial)

    def set_switch(self, serial: str, switch_type: int, enable: bool) -> bool:
        """Toggle one EZVIZ "camera-style" switch (see pyezvizapi ``DeviceSwitchType``)."""
        return self._client.switch_status(serial, switch_type, int(enable))

    def get_cloud_metadata(self, page_filter: str | None) -> dict[str, Any]:
        """Return read-only cloud metadata or one pagelist filter."""
        client = self._client
        client.login()
        if page_filter and page_filter.startswith("DEVICE:"):
            serial = page_filter.removeprefix("DEVICE:").strip()
            products_page = client._api_get_pagelist("PRODUCTS_INFO")  # noqa: SLF001
            products = (
                products_page.get("PRODUCTS_INFO", {})
                if isinstance(products_page, dict)
                else {}
            )

            def find_device(value: Any) -> dict[str, Any] | None:
                if isinstance(value, dict):
                    if value.get("deviceSerial") == serial or value.get("serial") == serial:
                        return value
                    for nested in value.values():
                        if match := find_device(nested):
                            return match
                elif isinstance(value, list):
                    for nested in value:
                        if match := find_device(nested):
                            return match
                return None

            return find_device(products) or {}
        if page_filter and page_filter.startswith("PROFILE:"):
            product_id = page_filter.removeprefix("PROFILE:").strip()
            products_page = client._api_get_pagelist("PRODUCTS_INFO")  # noqa: SLF001
            products = (
                products_page.get("PRODUCTS_INFO", {})
                if isinstance(products_page, dict)
                else {}
            )
            return next(
                (
                    item
                    for item in products.values()
                    if isinstance(item, dict)
                    and item.get("productId") == product_id
                ),
                {},
            )
        if page_filter and page_filter.startswith("DOMAIN:"):
            _, product_id, domain_id = page_filter.split(":", 2)
            products_page = client._api_get_pagelist("PRODUCTS_INFO")  # noqa: SLF001
            products = (
                products_page.get("PRODUCTS_INFO", {})
                if isinstance(products_page, dict)
                else {}
            )
            product = next(
                (
                    item
                    for item in products.values()
                    if isinstance(item, dict)
                    and item.get("productId") == product_id
                ),
                {},
            )
            resources = product.get("profile", {}).get("resources", [])
            return next(
                (
                    domain
                    for resource in resources
                    for domain in resource.get("domains", [])
                    if domain.get("identifier") == domain_id
                ),
                {},
            )
        if page_filter and page_filter.startswith("PRODUCT:"):
            product_id = page_filter.removeprefix("PRODUCT:").strip()
            products_page = client._api_get_pagelist("PRODUCTS_INFO")  # noqa: SLF001
            products = (
                products_page.get("PRODUCTS_INFO", {})
                if isinstance(products_page, dict)
                else {}
            )
            product = next(
                (
                    item
                    for item in products.values()
                    if isinstance(item, dict)
                    and item.get("productId") == product_id
                ),
                {},
            )
            path = "/v3/iot-feature/product/config"
            params = {
                "ver": 3,
                "productId": product_id,
                "version": product.get("version", ""),
                "type": "EIB",
            }
            result = client._request_json(  # noqa: SLF001
                "GET", path, params=params
            )
            if not isinstance(result, dict):
                raise PyEzvizError("Unexpected EZVIZ product config response")
            return result
        if page_filter:
            result = client._api_get_pagelist(page_filter)  # noqa: SLF001
            if not isinstance(result, dict):
                raise PyEzvizError("Unexpected EZVIZ pagelist response")
            return result

        service_urls = client.export_token().get("service_urls", {})
        if not isinstance(service_urls, dict):
            raise PyEzvizError("Unexpected EZVIZ service metadata")
        return service_urls

    def get_manual_scenes(self) -> dict[str, Any]:
        """Return EZVIZ manual scenes without executing them."""
        client = self._client
        path = "/v3/inter/connection/v1/rule/manager/manual/list"
        page = client._api_get_pagelist("CONNECTION")  # noqa: SLF001
        resources = page.get("resourceInfos", []) if isinstance(page, dict) else []
        group_ids = sorted(
            {
                str(resource["groupId"])
                for resource in resources
                if isinstance(resource, dict) and resource.get("groupId") is not None
            }
        )
        group_ids_value = ",".join(group_ids)
        params = {
            "page": 0,
            "pageSize": 100,
            "groupId": group_ids_value if len(group_ids) == 1 else "",
            "groupIds": group_ids_value,
        }
        result = client._request_json(  # noqa: SLF001
            "GET", path, params=params
        )
        if not isinstance(result, dict):
            raise PyEzvizError("Unexpected EZVIZ manual scene response")
        return result
