"""Unit tests for the cloud error classification used before a BLE retry."""

from __future__ import annotations

from pyezvizapi.exceptions import HTTPError, InvalidURL, PyEzvizError

from _load import load

api = load("api")


def test_explicit_action_rejection_is_eligible_for_ble_fallback():
    err = api.EzvizActionRejected("meta code 4001")
    assert api.should_fallback_to_ble(err) is True


def test_generic_pyezviz_error_is_not_eligible():
    # A clean rejection is distinguishable from an ambiguous failure; only
    # the former is safe to retry without risking a duplicated command.
    assert api.should_fallback_to_ble(PyEzvizError("boom")) is False


def test_http_error_is_not_eligible():
    assert api.should_fallback_to_ble(HTTPError("timeout")) is False


def test_invalid_url_is_not_eligible():
    assert api.should_fallback_to_ble(InvalidURL("bad url")) is False


def test_arbitrary_exception_is_not_eligible():
    assert api.should_fallback_to_ble(ValueError("unexpected")) is False


def test_action_rejected_is_a_pyezviz_error_subclass():
    assert issubclass(api.EzvizActionRejected, PyEzvizError)
