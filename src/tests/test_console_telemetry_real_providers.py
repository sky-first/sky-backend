"""Unit coverage for the real Console telemetry providers.

Covers the wiring (factory + flags) plus the boundary code in
``PrometheusActivityProvider`` and ``MoloniBillingProvider``. The
HTTP layer is faked with a small ``DummyResp`` so we don't depend on
``requests-mock`` or live infrastructure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.services.console_telemetry import (
    MockActivityProvider,
    MockBillingProvider,
    activity_provider,
    billing_provider,
)


class DummyResp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise RuntimeError(f"http {self._status}")

    def json(self) -> Any:
        return self._payload


def test_factory_returns_mock_when_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSOLE_MOCK_INFRA", "true")
    monkeypatch.delenv("PROMETHEUS_ACTIVITY_ENABLED", raising=False)
    monkeypatch.delenv("MOLONI_BILLING_ENABLED", raising=False)
    assert isinstance(activity_provider(), MockActivityProvider)
    assert isinstance(billing_provider(), MockBillingProvider)


def test_factory_switches_to_real_when_flags_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONSOLE_MOCK_INFRA", "false")
    monkeypatch.setenv("PROMETHEUS_ACTIVITY_ENABLED", "true")
    monkeypatch.setenv("MOLONI_BILLING_ENABLED", "true")
    from src.services.console_telemetry_real import (
        MoloniBillingProvider,
        PrometheusActivityProvider,
    )

    assert isinstance(activity_provider(), PrometheusActivityProvider)
    assert isinstance(billing_provider(), MoloniBillingProvider)


def test_prometheus_platform_activity_parses_range_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMETHEUS_URL", "http://prom.example:9090")
    from src.services.console_telemetry_real import PrometheusActivityProvider

    p = PrometheusActivityProvider()

    response = {
        "status": "success",
        "data": {
            "result": [
                {
                    "metric": {"tenant": "gbt"},
                    "values": [[1717200000.0, "1.5"], [1717203600.0, "2.2"]],
                },
                {
                    "metric": {"tenant": "other"},
                    "values": [[1717200000.0, "0.5"]],
                },
            ]
        },
    }
    with patch(
        "requests.get",
        return_value=DummyResp(response),
    ):
        points = p.platform_activity_24h(["gbt"])

    assert all(pt.label == "gbt" for pt in points)
    assert [pt.value for pt in points] == [1.5, 2.2]


def test_prometheus_raises_unavailable_when_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    from src.services.console_telemetry import TelemetryUnavailable
    from src.services.console_telemetry_real import PrometheusActivityProvider

    p = PrometheusActivityProvider()
    with pytest.raises(TelemetryUnavailable):
        p.platform_activity_24h(["gbt"])


def test_moloni_tenant_billing_resolves_customer_and_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOLONI_API_KEY", "test-key")
    monkeypatch.setenv("MOLONI_COMPANY_ID", "42")
    from src.services.console_telemetry_real import MoloniBillingProvider

    grant_resp = DummyResp({"access_token": "tok", "expires_in": 3600})
    customers_resp = DummyResp(
        [
            {"customer_id": 1, "reference": "other", "name": "Other Co"},
            {"customer_id": 7, "reference": "gbt", "name": "GBT Solutions"},
        ]
    )
    invoices_resp = DummyResp(
        [
            {"date": "2026-05-20", "status": 2},
            {"date": "2026-04-20", "status": 2},
        ]
    )

    def fake_get(url: str, params: Any = None, timeout: Any = None) -> DummyResp:
        if "customers" in url:
            return customers_resp
        if "invoices" in url:
            return invoices_resp
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url: str, json: Any = None, timeout: Any = None) -> DummyResp:
        if "grant" in url:
            return grant_resp
        raise AssertionError(f"unexpected POST {url}")

    with patch("requests.get", side_effect=fake_get), patch(
        "requests.post", side_effect=fake_post
    ):
        billing = MoloniBillingProvider().tenant_billing("gbt", tier="core")

    assert billing.tier == "core"
    assert billing.monthly_amount_eur == 7500.0
    assert billing.payment_status == "paid"
    assert billing.last_invoice_at == "2026-05-20"
    assert billing.next_invoice_at == "2026-06-20"


def test_moloni_tenant_billing_unknown_customer_surfaces_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOLONI_API_KEY", "test-key")
    from src.services.console_telemetry import TelemetryUnavailable
    from src.services.console_telemetry_real import MoloniBillingProvider

    with patch(
        "requests.post",
        return_value=DummyResp({"access_token": "tok", "expires_in": 60}),
    ), patch("requests.get", return_value=DummyResp([])):
        with pytest.raises(TelemetryUnavailable):
            MoloniBillingProvider().tenant_billing("missing", tier="starter")


def test_moloni_alerts_and_incidents_are_empty_until_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOLONI_API_KEY", "test-key")
    from src.services.console_telemetry_real import MoloniBillingProvider

    provider = MoloniBillingProvider()
    assert provider.alerts() == []
    assert provider.incidents() == []
