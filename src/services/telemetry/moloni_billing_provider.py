"""MoloniBillingProvider — real BillingProvider backed by the Moloni REST API.

Implements the ``BillingProvider`` Protocol defined in
``src.services.console_telemetry``. Performs:

1. OAuth token acquisition via ``POST /grant`` (cached with TTL).
2. Customer lookup by tenant slug (``GET /customers/getAll?search=<slug>``).
3. Paid-invoice retrieval (``GET /invoices/getAll?status=1``) to derive
   payment status, last/next invoice dates, and monthly amount.

When Moloni is unreachable or the customer is not found the provider falls
back gracefully to a tier-price estimate without raising an exception.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier price fallback (used when the customer is not found in Moloni)
# ---------------------------------------------------------------------------

_PRICE_BY_TIER: dict[str, float] = {
    "pilot": 1_250.0,
    "foundation": 3_500.0,
    "core": 7_500.0,
    "advanced": 15_000.0,
    "strategic": 35_000.0,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _sub_end(start: datetime) -> datetime:
    """Return subscription end as +1 year from *start*, clamping Feb-29."""
    try:
        return start.replace(year=start.year + 1)
    except ValueError:
        return start.replace(year=start.year + 1, day=28)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class MoloniBillingProvider:
    """Real ``BillingProvider`` backed by the Moloni REST API.

    Required env vars:
        MOLONI_API_KEY     — long-lived API key issued by Moloni.
        MOLONI_COMPANY_ID  — Moloni internal company id for SkyFirst Labs.
        MOLONI_BASE_URL    — defaults to ``https://api.moloni.pt/v1``.

    The provider caches the OAuth access token and renews it automatically
    when it expires. All HTTP requests time out after 10 s. Any Moloni
    error causes a graceful fallback to the tier-price estimate — the
    caller never receives an exception from this class.
    """

    def __init__(self) -> None:
        self._base_url: str = os.getenv("MOLONI_BASE_URL", "https://api.moloni.pt/v1")
        self._token: Optional[str] = None
        self._token_exp: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _ensure_token(self) -> Optional[str]:
        """Return a valid bearer token, renewing if necessary.

        Returns ``None`` (instead of raising) when ``MOLONI_API_KEY`` is
        absent — this is expected in local development.
        """
        if self._token and self._token_exp and self._token_exp > _now():
            return self._token

        api_key = os.getenv("MOLONI_API_KEY")
        if not api_key:
            return None

        try:
            import httpx
        except ImportError:
            logger.warning("moloni_billing_provider: httpx not installed — pip install httpx")
            return None

        try:
            resp = httpx.post(
                f"{self._base_url}/grant",
                json={"grant_type": "api_key", "api_key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data: dict = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "moloni_token_grant_failed",
                extra={"error": str(exc)[:300]},
            )
            return None

        token = data.get("access_token")
        if not token:
            logger.warning("moloni_token_grant_missing_access_token", extra={"response": str(data)[:200]})
            return None

        self._token = token
        self._token_exp = _now() + timedelta(seconds=int(data.get("expires_in", 3600)))
        return self._token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict) -> Optional[list]:
        """Perform an authenticated GET against the Moloni API.

        Returns the parsed JSON list on success, or ``None`` on any error
        (HTTP non-2xx, network timeout, JSON parse failure, missing token).
        """
        token = self._ensure_token()
        if not token:
            return None

        try:
            import httpx
        except ImportError:
            return None

        try:
            resp = httpx.get(
                f"{self._base_url}/{path.lstrip('/')}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "moloni_http_error",
                extra={"path": path, "error": str(exc)[:300]},
            )
            return None

        if resp.status_code != 200:
            logger.warning(
                "moloni_non_200",
                extra={"path": path, "status": resp.status_code, "body": resp.text[:300]},
            )
            return None

        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "moloni_json_decode_error",
                extra={"path": path, "error": str(exc)[:200]},
            )
            return None

        # Moloni wraps results in different shapes depending on the endpoint:
        # plain list OR {"customers": [...]} / {"invoices": [...]} etc.
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in payload:
                if isinstance(payload[key], list):
                    return payload[key]
        return []

    def _lookup_customer(self, slug: str, company_id: str) -> Optional[dict]:
        """Search Moloni customers for the one whose name or notes match *slug*.

        Returns the first matching customer dict, or ``None`` if not found.
        """
        results = self._get(
            "/customers/getAll",
            {"company_id": company_id, "search": slug, "qty": 50, "offset": 0},
        )
        if results is None:
            return None

        # Exact name match first, then notes/custom field fallback.
        for customer in results:
            if customer.get("name") == slug:
                return customer

        for customer in results:
            notes: str = customer.get("notes") or ""
            if slug in notes:
                return customer
            # Some integrations store slug in a custom field keyed "reference"
            if customer.get("reference") == slug:
                return customer

        return None

    def _fetch_paid_invoices(self, customer_id: int | str, company_id: str) -> list[dict]:
        """Return all paid invoices (status=1) for *customer_id*, newest first."""
        results = self._get(
            "/invoices/getAll",
            {
                "company_id": company_id,
                "customer_id": customer_id,
                "status": 1,
                "qty": 50,
                "offset": 0,
            },
        )
        if not results:
            return []

        # Sort by date descending — Moloni may return them in any order.
        def _invoice_date(inv: dict) -> str:
            return inv.get("date") or inv.get("expiration_date") or ""

        return sorted(results, key=_invoice_date, reverse=True)

    def _monthly_amount_from_invoice(self, invoice: dict) -> float:
        """Derive a monthly EUR amount from a single invoice.

        Moloni invoices include ``net_value`` (total) and ``date`` /
        ``expiration_date``. We divide by the number of months the invoice
        covers, defaulting to 1 month when that information is absent.
        """
        total: float = 0.0
        try:
            total = float(invoice.get("net_value") or invoice.get("total") or 0.0)
        except (TypeError, ValueError):
            pass

        # Attempt to determine coverage in months via expiration_date − date.
        months = 1
        date_str = invoice.get("date")
        exp_str = invoice.get("expiration_date")
        if date_str and exp_str:
            try:
                inv_start = datetime.fromisoformat(date_str)
                inv_end = datetime.fromisoformat(exp_str)
                delta_days = (inv_end - inv_start).days
                if delta_days > 0:
                    months = max(1, round(delta_days / 30))
            except (ValueError, TypeError):
                pass

        return round(total / months, 2) if months > 0 else total

    # ------------------------------------------------------------------
    # BillingProvider Protocol implementation
    # ------------------------------------------------------------------

    def tenant_billing(
        self,
        slug: str,
        tier: str,
        created_at: Optional[datetime] = None,
    ):
        """Return a ``TenantBilling`` for the tenant identified by *slug*.

        Performs a two-step Moloni lookup:

        1. ``GET /customers/getAll?search=<slug>`` — find the customer.
        2. ``GET /invoices/getAll?customer_id=<id>&status=1`` — find paid
           invoices.

        Falls back gracefully to a tier-price estimate when Moloni is not
        configured, the customer is not found, or any HTTP error occurs.
        """
        # Import here to avoid a hard dependency at module load time.
        from src.services.console_telemetry import TenantBilling

        fallback_amount = _PRICE_BY_TIER.get(tier, 0.0)
        now = _now()
        subscription_start = created_at or now

        def _fallback(payment_status: str = "unknown") -> TenantBilling:
            return TenantBilling(
                tier=tier,
                subscription_start=_iso(subscription_start),
                subscription_end=_iso(_sub_end(subscription_start)),
                monthly_amount_eur=fallback_amount,
                payment_status=payment_status,
                last_invoice_at=None,
                next_invoice_at=None,
                mrr_contribution_eur=fallback_amount,
            )

        company_id = os.getenv("MOLONI_COMPANY_ID")
        if not company_id:
            # No API key / company configured — expected in dev, no noise.
            return _fallback("unknown")

        # -- Step 1: customer lookup --
        customer = self._lookup_customer(slug, company_id)
        if customer is None:
            # Could not reach Moloni or customer not found.
            logger.warning(
                "moloni_customer_not_found",
                extra={"slug": slug},
            )
            return _fallback("unknown")

        customer_id = customer.get("id")

        # Prefer Moloni's own creation date as subscription start.
        moloni_created_raw: Optional[str] = customer.get("created_at") or customer.get("date")
        if moloni_created_raw:
            try:
                subscription_start = datetime.fromisoformat(moloni_created_raw)
                if subscription_start.tzinfo is None:
                    subscription_start = subscription_start.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass  # keep the arg-provided or _now() value

        # -- Step 2: paid invoices --
        invoices = self._fetch_paid_invoices(customer_id, company_id)

        if not invoices:
            # Customer exists but no paid invoice on record.
            return TenantBilling(
                tier=tier,
                subscription_start=_iso(subscription_start),
                subscription_end=_iso(_sub_end(subscription_start)),
                monthly_amount_eur=fallback_amount,
                payment_status="pending",
                last_invoice_at=None,
                next_invoice_at=None,
                mrr_contribution_eur=fallback_amount,
            )

        # -- Step 3: derive billing fields from the latest paid invoice --
        latest = invoices[0]
        monthly_amount = self._monthly_amount_from_invoice(latest)

        # last_invoice_at — prefer explicit date field, fall back to expiration.
        last_inv_raw: Optional[str] = latest.get("date") or latest.get("expiration_date")
        last_invoice_at: Optional[str] = None
        next_invoice_dt: Optional[datetime] = None
        if last_inv_raw:
            try:
                last_inv_dt = datetime.fromisoformat(last_inv_raw)
                if last_inv_dt.tzinfo is None:
                    last_inv_dt = last_inv_dt.replace(tzinfo=timezone.utc)
                last_invoice_at = _iso(last_inv_dt)
                next_invoice_dt = last_inv_dt + timedelta(days=30)
            except (ValueError, TypeError):
                pass

        return TenantBilling(
            tier=tier,
            subscription_start=_iso(subscription_start),
            subscription_end=_iso(_sub_end(subscription_start)),
            monthly_amount_eur=monthly_amount,
            payment_status="paid",
            last_invoice_at=last_invoice_at,
            next_invoice_at=_iso(next_invoice_dt) if next_invoice_dt else None,
            mrr_contribution_eur=monthly_amount,
        )

    def alerts(self) -> list:
        """Return an empty list.

        Billing alerts come from Sentry / PagerDuty, not from Moloni.
        A dedicated AlertProvider will be wired in a future module.
        """
        return []

    def incidents(self) -> list:
        """Return an empty list.

        Incidents come from Sentry / PagerDuty, not from Moloni.
        A dedicated IncidentProvider will be wired in a future module.
        """
        return []


__all__ = ["MoloniBillingProvider"]
