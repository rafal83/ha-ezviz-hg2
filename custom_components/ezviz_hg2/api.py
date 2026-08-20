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
        client = self._client
        path = (
            f"/v3/iot-feature/action/{serial.upper()}/{resource_id}/"
            f"{local_index}/{domain_id}/{action_id}"
        )
        body = {"value": dict(payload or {})}

        # pyezvizapi 1.0.0.7 has no public generic action helper. Keep the
        # private API use isolated here so it is easy to replace later.
        if hasattr(client, "_request_json"):
            result = client._request_json(  # noqa: SLF001
                "PUT", path, json_body=body
            )
        else:
            token = client._token  # noqa: SLF001
            response = client._session.put(  # noqa: SLF001
                f"https://{token['api_url']}{path}",
                json=body,
                timeout=client._timeout,  # noqa: SLF001
            )
            response.raise_for_status()
            result = response.json()

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
        client = self._client
        path = (
            f"/v3/iot-feature/feature/{serial.upper()}/{resource_id}/"
            f"{local_index}/{domain_id}/{feature_id}"
        )
        if hasattr(client, "_request_json"):
            result = client._request_json("GET", path)  # noqa: SLF001
        else:
            token = client._token  # noqa: SLF001
            response = client._session.get(  # noqa: SLF001
                f"https://{token['api_url']}{path}",
                timeout=client._timeout,  # noqa: SLF001
            )
            response.raise_for_status()
            result = response.json()
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
        client = self._client
        path = (
            f"/v3/iot-feature/feature/{serial.upper()}/{resource_id}/"
            f"{local_index}/{domain_id}/{feature_id}"
        )
        body = {"value": value}
        if hasattr(client, "_request_json"):
            result = client._request_json(  # noqa: SLF001
                "PUT", path, json_body=body
            )
        else:
            token = client._token  # noqa: SLF001
            response = client._session.put(  # noqa: SLF001
                f"https://{token['api_url']}{path}",
                json=body,
                timeout=client._timeout,  # noqa: SLF001
            )
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise PyEzvizError("Unexpected EZVIZ feature write response")
        meta = result.get("meta")
        if isinstance(meta, dict) and meta.get("code") != 200:
            raise PyEzvizError(f"EZVIZ feature write rejected: {json.dumps(meta)}")
        return result

    def upgrade_device(self, serial: str) -> bool:
        """Trigger the firmware upgrade EZVIZ already has queued for a device."""
        return self._client.upgrade_device(serial)

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
            if hasattr(client, "_request_json"):
                result = client._request_json(  # noqa: SLF001
                    "GET", path, params=params
                )
            else:
                token = client._token  # noqa: SLF001
                response = client._session.get(  # noqa: SLF001
                    f"https://{token['api_url']}{path}",
                    params=params,
                    timeout=client._timeout,  # noqa: SLF001
                )
                response.raise_for_status()
                result = response.json()
            if not isinstance(result, dict):
                raise PyEzvizError("Unexpected EZVIZ product config response")
            return result
        if page_filter:
            result = client._api_get_pagelist(page_filter)  # noqa: SLF001
            if not isinstance(result, dict):
                raise PyEzvizError("Unexpected EZVIZ pagelist response")
            return result

        service_urls = client._token.get("service_urls", {})  # noqa: SLF001
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
        if hasattr(client, "_request_json"):
            result = client._request_json(  # noqa: SLF001
                "GET", path, params=params
            )
        else:
            token = client._token  # noqa: SLF001
            response = client._session.get(  # noqa: SLF001
                f"https://{token['api_url']}{path}",
                params=params,
                timeout=client._timeout,  # noqa: SLF001
            )
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise PyEzvizError("Unexpected EZVIZ manual scene response")
        return result
