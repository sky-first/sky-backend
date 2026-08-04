"""Unit tests for ``src/services/k8s_telemetry.py``.

These tests inject a fake CoreV1Api directly into
``KubernetesTelemetryProvider`` so they never touch a real cluster and
never need the ``kubernetes`` package to be installed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List, Optional

import pytest

from src.services import console_telemetry, k8s_telemetry
from src.services.console_telemetry import TelemetryUnavailable
from src.services.k8s_telemetry import (
    KubernetesTelemetryProvider,
    PlatformHealthSnapshot,
    TenantHealthSnapshot,
    reset_provider,
)


# ── helpers ────────────────────────────────────────────────────────


def _pod(
    *,
    name: str = "sky-be-abc",
    namespace: str = "alpha-stg-aws",
    phase: str = "Running",
    crash_loop: bool = False,
    restarts: int = 0,
    component: str = "sky-be",
    image: str = "ecr/sky-be@sha256:abcdef1234567890",
    created_hours_ago: int = 4,
):
    waiting = (
        SimpleNamespace(reason="CrashLoopBackOff", message="back-off")
        if crash_loop
        else None
    )
    state = SimpleNamespace(waiting=waiting, running=None, terminated=None)
    cs = SimpleNamespace(state=state, restart_count=restarts)
    status = SimpleNamespace(phase=phase, container_statuses=[cs])
    spec = SimpleNamespace(containers=[SimpleNamespace(image=image)])
    metadata = SimpleNamespace(
        name=name,
        namespace=namespace,
        labels={"app.kubernetes.io/component": component},
        creation_timestamp=datetime.now(timezone.utc)
        - timedelta(hours=created_hours_ago),
    )
    return SimpleNamespace(metadata=metadata, spec=spec, status=status)


def _event(
    *,
    pod_name: str,
    namespace: str,
    reason: str = "BackOff",
    event_type: str = "Warning",
    age_hours: int = 2,
    kind: str = "Pod",
):
    return SimpleNamespace(
        type=event_type,
        reason=reason,
        involved_object=SimpleNamespace(kind=kind, name=pod_name, namespace=namespace),
        last_timestamp=datetime.now(timezone.utc) - timedelta(hours=age_hours),
        event_time=None,
        first_timestamp=None,
    )


class FakeCoreV1Api:
    """Stand-in for ``kubernetes.client.CoreV1Api``."""

    def __init__(
        self,
        *,
        pods_by_namespace: Optional[dict] = None,
        all_pods: Optional[List] = None,
        events_by_namespace: Optional[dict] = None,
        list_ns_raises: Optional[Exception] = None,
        list_all_raises: Optional[Exception] = None,
        list_events_raises: Optional[Exception] = None,
    ) -> None:
        self.pods_by_namespace = pods_by_namespace or {}
        self.all_pods = all_pods if all_pods is not None else []
        self.events_by_namespace = events_by_namespace or {}
        self.list_ns_raises = list_ns_raises
        self.list_all_raises = list_all_raises
        self.list_events_raises = list_events_raises
        self.call_log: List[str] = []

    def list_namespaced_pod(self, namespace: str):
        self.call_log.append(f"list_namespaced_pod:{namespace}")
        if self.list_ns_raises:
            raise self.list_ns_raises
        return SimpleNamespace(items=list(self.pods_by_namespace.get(namespace, [])))

    def list_pod_for_all_namespaces(self):
        self.call_log.append("list_pod_for_all_namespaces")
        if self.list_all_raises:
            raise self.list_all_raises
        return SimpleNamespace(items=list(self.all_pods))

    def list_namespaced_event(self, namespace: str):
        self.call_log.append(f"list_namespaced_event:{namespace}")
        if self.list_events_raises:
            raise self.list_events_raises
        return SimpleNamespace(items=list(self.events_by_namespace.get(namespace, [])))


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_provider()
    yield
    reset_provider()


# ── tests ──────────────────────────────────────────────────────────


def test_platform_health_aggregates_phases_and_crashloop():
    """Pods are bucketed correctly: phase=Running counts as running
    unless a container is in CrashLoopBackOff, in which case it
    counts as crashlooping (and NOT also as running)."""
    pods = [
        _pod(name="sky-be-1", phase="Running"),
        _pod(name="sky-be-2", phase="Running"),
        _pod(name="sky-ai-1", phase="Pending"),
        # Kubernetes reports CrashLoopBackOff as phase=Running with a
        # waiting container — the provider must catch this case.
        _pod(name="sky-ai-2", phase="Running", crash_loop=True),
        _pod(name="postgres-0", phase="Running"),
    ]
    fake = FakeCoreV1Api(all_pods=pods)
    provider = KubernetesTelemetryProvider(
        cache_ttl_seconds=1, platform_namespaces=[], core_v1_api=fake
    )

    snap = provider.get_platform_health_sync()

    assert isinstance(snap, PlatformHealthSnapshot)
    assert snap.pods_total == 5
    assert snap.pods_running == 3  # the crashloop pod is NOT also counted as running
    assert snap.pods_pending == 1
    assert snap.pods_crashlooping == 1


def test_platform_health_respects_namespace_allowlist():
    """When platform namespaces are provided, the provider issues
    per-namespace list calls and does NOT call list-all."""
    fake = FakeCoreV1Api(
        pods_by_namespace={
            "staging": [_pod(name="be-stg", namespace="staging")],
            "production": [
                _pod(name="be-prd-1", namespace="production"),
                _pod(name="be-prd-2", namespace="production", phase="Pending"),
            ],
        },
    )
    provider = KubernetesTelemetryProvider(
        cache_ttl_seconds=60,
        platform_namespaces=["staging", "production"],
        core_v1_api=fake,
    )

    snap = provider.get_platform_health_sync()

    assert snap.pods_total == 3
    assert snap.pods_running == 2
    assert snap.pods_pending == 1
    assert set(snap.namespaces_scanned) == {"staging", "production"}
    # Must not have used the cluster-wide call when allowlisted.
    assert "list_pod_for_all_namespaces" not in fake.call_log


def test_tenant_health_filters_by_namespace_template():
    """Tenant health derives namespaces from the template and only
    returns pods inside those namespaces."""
    fake = FakeCoreV1Api(
        pods_by_namespace={
            "gbt-stg-aws": [_pod(name="be-stg-1", namespace="gbt-stg-aws")],
            "gbt-prd-aws": [
                _pod(name="be-prd-1", namespace="gbt-prd-aws"),
                _pod(
                    name="ai-prd-1",
                    namespace="gbt-prd-aws",
                    crash_loop=True,
                    component="sky-ai",
                ),
            ],
            # Should never be touched — different tenant.
            "alpha-prd-aws": [_pod(name="alpha", namespace="alpha-prd-aws")],
        },
    )
    provider = KubernetesTelemetryProvider(
        cache_ttl_seconds=60,
        namespace_template="{slug}-{env}-aws",
        platform_namespaces=[],
        core_v1_api=fake,
    )

    snap = provider.get_tenant_health_sync("GBT")  # slug normalisation

    assert isinstance(snap, TenantHealthSnapshot)
    assert snap.slug == "gbt"
    assert snap.namespaces == ["gbt-stg-aws", "gbt-prd-aws"]
    assert snap.pods_total == 3
    assert snap.pods_crashlooping == 1
    assert {p.namespace for p in snap.pods} == {"gbt-stg-aws", "gbt-prd-aws"}
    assert "list_namespaced_pod:alpha-prd-aws" not in fake.call_log


def test_unhealthy_events_last_24h_counts_unique_pods():
    """Two warning events for the same pod count once; old events
    (>24h) and Normal events are excluded."""
    pods = [
        _pod(name="ai-1", namespace="alpha-prd-aws"),
        _pod(name="ai-2", namespace="alpha-prd-aws"),
    ]
    events = {
        "alpha-prd-aws": [
            _event(pod_name="ai-1", namespace="alpha-prd-aws", reason="BackOff", age_hours=2),
            # Same pod, second warning — must not double-count.
            _event(
                pod_name="ai-1", namespace="alpha-prd-aws", reason="Unhealthy", age_hours=1
            ),
            _event(
                pod_name="ai-2",
                namespace="alpha-prd-aws",
                reason="OOMKilled",
                age_hours=6,
            ),
            # Too old — outside the 24h window.
            _event(
                pod_name="ai-3", namespace="alpha-prd-aws", reason="BackOff", age_hours=48
            ),
            # Normal event — should be ignored even if reason is "BackOff".
            _event(
                pod_name="ai-4",
                namespace="alpha-prd-aws",
                reason="BackOff",
                event_type="Normal",
                age_hours=1,
            ),
        ]
    }
    fake = FakeCoreV1Api(all_pods=pods, events_by_namespace=events)
    provider = KubernetesTelemetryProvider(
        cache_ttl_seconds=60, platform_namespaces=[], core_v1_api=fake
    )

    snap = provider.get_platform_health_sync()

    # ai-1 (deduped) + ai-2 = 2 distinct unhealthy pods.
    assert snap.pods_unhealthy_last_24h == 2


def test_ttl_cache_avoids_repeated_api_calls():
    """The second call inside the TTL window must not hit the kube API
    again; a third call AFTER ``invalidate_cache`` must."""
    fake = FakeCoreV1Api(all_pods=[_pod(name="x")])
    provider = KubernetesTelemetryProvider(
        cache_ttl_seconds=60,
        platform_namespaces=[],
        core_v1_api=fake,
    )

    provider.get_platform_health_sync()
    provider.get_platform_health_sync()
    # Only the first call talks to the API. Events queries are issued
    # per namespace, but with only one pod and one namespace there's at
    # most one list_namespaced_event call cached too.
    assert fake.call_log.count("list_pod_for_all_namespaces") == 1

    provider.invalidate_cache()
    provider.get_platform_health_sync()
    assert fake.call_log.count("list_pod_for_all_namespaces") == 2


def test_kube_api_errors_become_telemetry_unavailable():
    """Errors from the kubernetes client must be converted to
    ``TelemetryUnavailable`` so the Console route returns 503 rather
    than leaking the original exception."""
    fake = FakeCoreV1Api(list_all_raises=RuntimeError("kube-apiserver unreachable"))
    provider = KubernetesTelemetryProvider(
        cache_ttl_seconds=60, platform_namespaces=[], core_v1_api=fake
    )

    with pytest.raises(TelemetryUnavailable) as exc:
        provider.get_platform_health_sync()
    assert "list_pod_for_all_namespaces" in str(exc.value)


def test_infra_provider_factory_returns_k8s_when_gated_on(monkeypatch):
    """When CONSOLE_MOCK_INFRA=false and K8S_TELEMETRY_ENABLED=true,
    ``infra_provider()`` returns a KubernetesTelemetryProvider — not
    the legacy KubernetesInfraProvider or the mock."""
    monkeypatch.setenv("CONSOLE_MOCK_INFRA", "false")
    monkeypatch.setenv("K8S_TELEMETRY_ENABLED", "true")

    provider = console_telemetry.infra_provider()

    assert isinstance(provider, KubernetesTelemetryProvider)
