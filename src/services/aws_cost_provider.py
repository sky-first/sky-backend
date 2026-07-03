"""Real AWS Cost Explorer-backed CostProvider for the Internal Console.

This provider ships behind ``AWS_COSTS_TELEMETRY_ENABLED`` (and is only
wired in when ``CONSOLE_MOCK_INFRA=false``). It calls the AWS Cost
Explorer ``GetCostAndUsage`` API directly via boto3 and projects the
``SERVICE`` dimension into the four buckets the CEO Master Dashboard
expects: ``compute_usd``, ``storage_usd``, ``network_usd``, and
``bedrock_usd``.

Why a dedicated module (not just ``console_telemetry_real.AwsCostProvider``)?

* The CEO Master Dashboard (PR #477) calls
  ``cost_provider().platform_cost_breakdown(days=30)`` — a new method
  shape that takes an explicit window. The legacy stub in
  ``console_telemetry_real`` is hard-coded to 30 days and only exposes
  ``platform_cost()`` / ``tenant_cost()``. Rather than retrofit the
  legacy stub (which would risk breaking the existing /tenants/{slug}/cost
  route), we ship a clean new provider that satisfies *both* shapes and
  let the factory wire it in behind the feature flag.
* The Cost Explorer API is **paid** ($0.01 per request) and rate-limited.
  This provider memoises results in a process-local TTL cache (default
  30 min) so the Console UI polling every ~30s does not bankrupt the
  AWS bill.
* Per-tenant cost uses AWS Cost Allocation Tags. The tag key is
  ``tenant`` (lowercase) and the value is the tenant slug — this matches
  the infra repo's Terraform tagging convention. Tenants whose infra
  predates tag onboarding return zero, NOT an error.

Failure modes are converted to ``TelemetryUnavailable`` so the Console
routes surface a clean 503 instead of leaking boto3 stack traces.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.services.console_telemetry import (
    CostBreakdown,
    TelemetryUnavailable,
    TimeseriesPoint,
)

logger = logging.getLogger(__name__)


# ── Tunables ───────────────────────────────────────────────────────

# 30-minute cache TTL. Cost Explorer is paid and rate-limited, and the
# underlying data has 24h latency anyway — refreshing every 30 min is
# the right balance between freshness and cost.
DEFAULT_CACHE_TTL_SECONDS = 1800

# Tag key used in cost-allocation tagging on the infra side. Must match
# the Terraform module that stamps ``tenant=<slug>`` on every tenant-owned
# resource (sky-poc-infra: modules/tenant_cluster/main.tf).
TENANT_TAG_KEY = "tenant"

# Cost Explorer is a *global* service. Its only regional endpoint lives in
# ``us-east-1`` for the standard AWS partition — passing any other region
# (e.g. the platform's home ``eu-west-1``) risks an EndpointConnectionError
# on some botocore versions. Home the CE client here regardless of the
# platform region so the query never fails just because of endpoint
# resolution.
COST_EXPLORER_ENDPOINT_REGION = "us-east-1"

# RECORD_TYPE values that represent credits/refunds rather than real
# resource usage. We exclude them from the cost query so the Console shows
# what we actually *consumed* (which reconciles with the AWS Billing
# console's charge view) instead of the credit-masked net. Excluding them
# also removes the nonsensical negative slice we were seeing when a single
# credit landed on one service (e.g. a data-transfer credit rendering
# Network < 0).
CREDIT_RECORD_TYPES = ["Credit", "Refund"]


# ── Service → bucket mapping ──────────────────────────────────────


def _bucket_for_service(service_name: str) -> str:
    """Project a CE ``SERVICE`` string onto one of the four exposed buckets.

    The matching is substring-based against the canonical AWS service
    names. Order matters for the network/storage overlap on EFS — EFS is
    counted as storage even though it shows up as "Amazon Elastic File
    System" (no "S3"/"EBS" substring).

    Services that don't match any bucket are folded into ``compute`` so
    the total still adds up — this matches the brief's "outras → agrega
    em compute" rule. Caller never sees an "other" bucket.
    """
    s = (service_name or "").lower()
    # Bedrock first (it's an LLM service, not "compute" in the EC2 sense).
    if "bedrock" in s:
        return "bedrock_usd"
    # Network: CloudFront + the DataTransfer pseudo-service, plus the
    # networking services that carry the bulk of real egress/ingress cost
    # — NAT gateways, VPC endpoints, load balancers and Route 53. Without
    # these, NAT/VPC/ELB spend (often the biggest network line) silently
    # fell into ``compute`` and the Network slice looked artificially tiny.
    if (
        "cloudfront" in s
        or "data transfer" in s
        or "datatransfer" in s
        or "virtual private cloud" in s
        or "nat gateway" in s
        or "elastic load balancing" in s
        or "route 53" in s
        or "route53" in s
        or "global accelerator" in s
    ):
        return "network_usd"
    # Storage: S3, EBS, EFS. EBS shows up as part of "Amazon Elastic
    # Compute Cloud - Compute" usage types in some accounts, but the
    # SERVICE dimension reports it separately as "Amazon Elastic Block
    # Store" when cost-allocation tags are active.
    if (
        "simple storage service" in s
        or "elastic block store" in s
        or "elastic file system" in s
        or "amazon s3" in s
        or "glacier" in s
        or "backup" in s
        or " ebs" in s
        or " efs" in s
    ):
        return "storage_usd"
    # Compute: EC2, EKS, Fargate, Lambda — anything that runs code.
    if (
        "elastic compute cloud" in s
        or "elastic kubernetes" in s
        or "fargate" in s
        or "lambda" in s
        or " eks" in s
        or " ec2" in s
    ):
        return "compute_usd"
    # Fold everything else into compute. This keeps the four-bucket
    # contract intact and prevents a surprise zero on the Console UI
    # just because a new service (e.g. AppRunner) hasn't been mapped
    # yet. Logged at debug so we notice if a meaningful bucket grows.
    logger.debug("aws_cost_provider_unmapped_service", extra={"service": service_name})
    return "compute_usd"


# ── TTL cache ──────────────────────────────────────────────────────


class _TTLCache:
    """Thread-safe single-process TTL cache.

    Same shape as the one in ``k8s_telemetry`` — duplicated rather than
    extracted because the two providers have independent TTLs and
    invalidation contracts and we don't want to couple them.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(1, int(ttl_seconds))
        self._lock = threading.Lock()
        self._store: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def get(self, key: Tuple[Any, ...]) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Tuple[Any, ...], value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ── Provider ───────────────────────────────────────────────────────


class AwsCostProvider:
    """Live AWS Cost Explorer-backed ``CostProvider``.

    Satisfies the legacy ``CostProvider`` Protocol shape (``platform_cost``
    / ``tenant_cost`` / ``revenue_summary``) **and** the new
    ``platform_cost_breakdown(days)`` / ``tenant_cost_breakdown(slug,
    days)`` shape consumed by the CEO Master Dashboard (PR #477).

    Construction is cheap (no API calls); the boto3 client is lazily
    initialised on first use via ``_ensure_client()`` so that importing
    this module from a unit test environment never touches AWS.

    The provider is intended to be a singleton per process — see
    ``get_provider()`` below.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: Optional[int] = None,
        linked_account_id: Optional[str] = None,
        region: Optional[str] = None,
        ce_client: Any = None,
    ) -> None:
        # Lazy import to avoid hard-coupling settings during test import.
        ttl = cache_ttl_seconds
        linked = linked_account_id
        reg = region
        if ttl is None or linked is None or reg is None:
            try:
                from src.config.settings import settings as _settings

                if ttl is None:
                    ttl = getattr(
                        _settings,
                        "AWS_COSTS_CACHE_TTL_SECONDS",
                        DEFAULT_CACHE_TTL_SECONDS,
                    )
                if linked is None:
                    linked = getattr(_settings, "AWS_COSTS_LINKED_ACCOUNT_ID", None)
                if reg is None:
                    reg = getattr(_settings, "AWS_COSTS_REGION", "eu-west-1")
            except Exception:  # noqa: BLE001
                # In environments without pydantic settings loaded
                # (very early unit tests, alembic migration shells),
                # fall back to safe defaults.
                ttl = ttl if ttl is not None else DEFAULT_CACHE_TTL_SECONDS
                reg = reg if reg is not None else "eu-west-1"

        self._cache = _TTLCache(ttl)
        self._linked_account_id = (linked or "").strip() or None
        self._region = reg or "eu-west-1"
        self._ce_client = ce_client
        self._init_tried = ce_client is not None
        self._init_error: Optional[str] = None

    # ── lifecycle ────────────────────────────────────────────────

    def _ensure_client(self) -> Any:
        if self._ce_client is not None:
            return self._ce_client
        if self._init_tried and self._init_error:
            raise TelemetryUnavailable(self._init_error)
        self._init_tried = True
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:
            self._init_error = (
                "boto3 not installed — add `boto3==1.34.28` to requirements.txt"
            )
            raise TelemetryUnavailable(self._init_error) from exc
        try:
            # CE is global — always target its us-east-1 endpoint (see
            # COST_EXPLORER_ENDPOINT_REGION) regardless of self._region.
            self._ce_client = boto3.client(
                "ce", region_name=COST_EXPLORER_ENDPOINT_REGION
            )
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"AWS Cost Explorer client init failed: {exc}"
            raise TelemetryUnavailable(self._init_error) from exc
        return self._ce_client

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _iso_date(d: datetime) -> str:
        return d.strftime("%Y-%m-%d")

    def _build_filter(
        self,
        *,
        tenant_slug: Optional[str] = None,
        exclude_credits: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Build the ``Filter`` clause for ``get_cost_and_usage``.

        Combines (when they apply):
        * Credit/refund exclusion (``exclude_credits``, default on) so the
          numbers reflect real resource usage — see ``CREDIT_RECORD_TYPES``.
        * Linked-account filter from settings (master payer use case)
        * Tenant tag filter ``tenant=<slug>``

        Returns ``None`` only when *no* clause applies (i.e. credits are
        explicitly kept and neither a linked account nor a tenant is set).
        """
        clauses: List[Dict[str, Any]] = []
        if exclude_credits:
            clauses.append(
                {
                    "Not": {
                        "Dimensions": {
                            "Key": "RECORD_TYPE",
                            "Values": CREDIT_RECORD_TYPES,
                        }
                    }
                }
            )
        if self._linked_account_id:
            clauses.append(
                {
                    "Dimensions": {
                        "Key": "LINKED_ACCOUNT",
                        "Values": [self._linked_account_id],
                    }
                }
            )
        if tenant_slug:
            clauses.append(
                {
                    "Tags": {
                        "Key": TENANT_TAG_KEY,
                        "Values": [tenant_slug],
                    }
                }
            )
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"And": clauses}

    def _query_cost_and_usage(
        self,
        *,
        days: int,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Issue a single ``GetCostAndUsage`` call, with TTL caching.

        Cache key includes the window size and the tenant slug so two
        concurrent calls for different windows do not stomp each other.
        Boto3 errors (``ClientError``, network, IAM permission denied)
        are converted to ``TelemetryUnavailable``.
        """
        days = max(1, int(days))
        cache_key = ("get_cost_and_usage", days, tenant_slug or "")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        client = self._ensure_client()
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        params: Dict[str, Any] = {
            "TimePeriod": {
                "Start": self._iso_date(datetime.combine(start, datetime.min.time())),
                "End": self._iso_date(datetime.combine(end, datetime.min.time())),
            },
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        ce_filter = self._build_filter(tenant_slug=tenant_slug)
        if ce_filter is not None:
            params["Filter"] = ce_filter

        try:
            resp = client.get_cost_and_usage(**params)
        except Exception as exc:  # noqa: BLE001
            # Common cases: AccessDeniedException (IAM), DataUnavailableException,
            # LimitExceededException (rate limit), botocore.exceptions.EndpointConnectionError.
            raise TelemetryUnavailable(
                f"AWS Cost Explorer query failed: {exc}"
            ) from exc

        self._cache.set(cache_key, resp)
        return resp

    @staticmethod
    def _aggregate_response(
        resp: Dict[str, Any],
    ) -> Tuple[Dict[str, float], List[TimeseriesPoint]]:
        """Convert a ``GetCostAndUsage`` response into bucket totals + daily series.

        Returns a tuple of:
        * ``buckets`` — dict with keys compute_usd / storage_usd /
          network_usd / bedrock_usd. Always present, defaulting to 0.0
          so the CostBreakdown shape is stable even on an empty result.
        * ``daily`` — one ``TimeseriesPoint`` per day in the response,
          carrying that day's total spend across all services.
        """
        buckets: Dict[str, float] = {
            "compute_usd": 0.0,
            "storage_usd": 0.0,
            "network_usd": 0.0,
            "bedrock_usd": 0.0,
        }
        daily: List[TimeseriesPoint] = []

        for period in resp.get("ResultsByTime") or []:
            day_total = 0.0
            for group in period.get("Groups") or []:
                keys = group.get("Keys") or ["unknown"]
                service = keys[0] if keys else "unknown"
                metric = (group.get("Metrics") or {}).get("UnblendedCost") or {}
                try:
                    amt = float(metric.get("Amount") or 0.0)
                except (TypeError, ValueError):
                    amt = 0.0
                bucket = _bucket_for_service(service)
                buckets[bucket] = buckets.get(bucket, 0.0) + amt
                # Only count positive charges toward the daily bar so
                # data-transfer credits don't cancel out compute spend.
                if amt > 0:
                    day_total += amt

            # ResultsByTime entries also carry a Total when no GroupBy
            # produced rows (e.g. tenant has no tagged resources). Use
            # it as a fallback so the daily series isn't all zeros.
            if not period.get("Groups"):
                total_metric = (period.get("Total") or {}).get("UnblendedCost") or {}
                try:
                    fallback = float(total_metric.get("Amount") or 0.0)
                except (TypeError, ValueError):
                    fallback = 0.0
                day_total += fallback

            period_start = (period.get("TimePeriod") or {}).get("Start") or ""
            t_iso = (
                f"{period_start}T00:00:00+00:00" if period_start else ""
            )
            daily.append(TimeseriesPoint(t=t_iso, value=round(day_total, 2)))

        return buckets, daily

    # ── public API: new shape (days-aware) ───────────────────────

    def platform_cost_breakdown(self, days: int = 30) -> CostBreakdown:
        """Platform-wide cost over the last ``days`` days.

        Consumed by the CEO Master Dashboard (PR #477). The total is the
        sum of every service across every linked account (or one linked
        account when ``AWS_COSTS_LINKED_ACCOUNT_ID`` is set).
        """
        resp = self._query_cost_and_usage(days=days)
        buckets, daily = self._aggregate_response(resp)
        # Gross positive spend — excludes data-transfer credits (negative rows)
        # that would otherwise net the total to zero.
        total = sum(v for v in buckets.values() if v > 0)
        end = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start = end - timedelta(days=max(1, int(days)))
        return CostBreakdown(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            compute_usd=round(buckets["compute_usd"], 2),
            storage_usd=round(buckets["storage_usd"], 2),
            network_usd=round(buckets["network_usd"], 2),
            bedrock_usd=round(buckets["bedrock_usd"], 2),
            total_usd=round(total, 2),
            daily=daily,
        )

    def tenant_cost_breakdown(self, slug: str, days: int = 30) -> CostBreakdown:
        """Per-tenant cost via the ``tenant=<slug>`` allocation tag.

        Tenants whose infra is not yet tagged return a zero-filled
        ``CostBreakdown`` rather than raising — this is by design so the
        Console UI can distinguish "tag onboarding pending" from "AWS
        outage" (the latter raises ``TelemetryUnavailable``).
        """
        slug_clean = (slug or "").strip().lower()
        if not slug_clean:
            raise TelemetryUnavailable("tenant slug is required")
        resp = self._query_cost_and_usage(days=days, tenant_slug=slug_clean)
        buckets, daily = self._aggregate_response(resp)
        total = sum(v for v in buckets.values() if v > 0)
        end = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start = end - timedelta(days=max(1, int(days)))
        return CostBreakdown(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            compute_usd=round(buckets["compute_usd"], 2),
            storage_usd=round(buckets["storage_usd"], 2),
            network_usd=round(buckets["network_usd"], 2),
            bedrock_usd=round(buckets["bedrock_usd"], 2),
            total_usd=round(total, 2),
            daily=daily,
        )

    # ── legacy ``CostProvider`` Protocol adapters ────────────────

    def platform_cost(self) -> CostBreakdown:
        return self.platform_cost_breakdown(days=30)

    def tenant_cost(self, slug: str) -> CostBreakdown:
        return self.tenant_cost_breakdown(slug, days=30)

    def revenue_summary(self) -> Dict[str, float]:
        # Revenue lives in Moloni / billing, not AWS. Surface a 503 so
        # the route hints at the right integration to wire next.
        raise TelemetryUnavailable(
            "revenue_summary is not sourced from AWS Cost Explorer — wire "
            "MoloniBillingProvider for MRR / margin numbers."
        )

    # ── test/operator helpers ────────────────────────────────────

    def invalidate_cache(self) -> None:
        """Drop all cached CE responses. Useful from a manual `/console/
        refresh` endpoint or from tests asserting distinct API calls."""
        self._cache.clear()


# ── singleton accessor ─────────────────────────────────────────────


_provider_singleton: Optional[AwsCostProvider] = None
_provider_lock = threading.Lock()


def get_provider() -> AwsCostProvider:
    """Return the process-wide ``AwsCostProvider`` instance.

    Constructed lazily on first call so that importing this module from
    a unit test environment never touches AWS.
    """
    global _provider_singleton
    with _provider_lock:
        if _provider_singleton is None:
            _provider_singleton = AwsCostProvider()
        return _provider_singleton


def reset_provider() -> None:
    """Reset the singleton — only for tests."""
    global _provider_singleton
    with _provider_lock:
        _provider_singleton = None


__all__ = [
    "AwsCostProvider",
    "DEFAULT_CACHE_TTL_SECONDS",
    "TENANT_TAG_KEY",
    "get_provider",
    "reset_provider",
]
