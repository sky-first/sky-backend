"""Alert and incident providers for the Internal Console.

Two real integrations are supported:

* **Sentry** — surfaces open issues (high-severity) as ``Alert`` objects and
  open incidents as ``IncidentEntry`` objects. Activated by setting
  ``SENTRY_AUTH_TOKEN``.
* **PagerDuty** — surfaces triggered/acknowledged alerts and incidents.
  Activated by setting ``PD_API_KEY``.

Factory function ``get_alerts_provider()`` inspects env vars and returns the
first available provider (Sentry > PagerDuty). When neither is configured a
silent empty fallback is returned so the Console renders gracefully without
log noise in dev mode.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

import httpx

from src.services.console_telemetry import Alert, IncidentEntry

logger = logging.getLogger(__name__)

_TIMEOUT = 8.0  # seconds


# ---------------------------------------------------------------------------
# Sentry provider
# ---------------------------------------------------------------------------


class SentryAlertsProvider:
    """Fetch open high-severity issues and incidents from the Sentry API.

    Required env vars:
        SENTRY_AUTH_TOKEN   — personal or internal-integration token
        SENTRY_ORG          — organization slug (e.g. ``skyfirstlabs``)
        SENTRY_PROJECT      — project slug (e.g. ``sky-api``)

    Optional:
        SENTRY_BASE_URL     — defaults to ``https://sentry.io``
    """

    def __init__(self) -> None:
        self._token: str = os.environ["SENTRY_AUTH_TOKEN"]
        self._org: str = os.getenv("SENTRY_ORG", "skyfirstlabs")
        self._project: str = os.getenv("SENTRY_PROJECT", "sky-api")
        self._base: str = os.getenv("SENTRY_BASE_URL", "https://sentry.io").rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_severity(level: str, priority: Optional[str]) -> str:
        if level == "fatal" or priority == "high":
            return "critical"
        if level == "warning":
            return "warning"
        return "info"

    @staticmethod
    def _extract_tenant_slug(tags: list) -> Optional[str]:
        for tag in tags:
            if isinstance(tag, dict) and tag.get("key") == "tenant_slug":
                return tag.get("value")
        return None

    def _issue_detail(self, issue: dict) -> str:
        culprit = issue.get("culprit", "")
        if culprit:
            return culprit[:200]
        return str(issue.get("metadata", {}).get("value", ""))[:200]

    def _issue_permalink(self, issue: dict) -> str:
        permalink = issue.get("permalink")
        if permalink:
            return permalink
        return f"{self._base}/organizations/{self._org}/issues/{issue['id']}/"

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------

    def alerts(self) -> List[Alert]:
        url = (
            f"{self._base}/api/0/projects/{self._org}/{self._project}/issues/"
            "?query=is:unresolved&level=error&limit=20"
        )
        try:
            resp = httpx.get(url, headers=self._headers(), timeout=_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sentry alerts request failed: %s", exc)
            return []

        if resp.status_code != 200:
            logger.warning(
                "Sentry alerts returned HTTP %s for project %s/%s",
                resp.status_code, self._org, self._project,
            )
            return []

        results: List[Alert] = []
        for issue in resp.json():
            results.append(
                Alert(
                    severity=self._map_severity(
                        issue.get("level", ""),
                        issue.get("priority"),
                    ),
                    title=issue.get("title", ""),
                    detail=self._issue_detail(issue),
                    tenant_slug=self._extract_tenant_slug(issue.get("tags", [])),
                    fired_at=issue.get("firstSeen", ""),
                    suggested_action=f"View in Sentry: {self._issue_permalink(issue)}",
                )
            )
        return results

    def incidents(self) -> List[IncidentEntry]:
        url = (
            f"{self._base}/api/0/organizations/{self._org}/incidents/"
            "?status=open&limit=10"
        )
        try:
            resp = httpx.get(url, headers=self._headers(), timeout=_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sentry incidents request failed: %s", exc)
            return []

        if resp.status_code != 200:
            logger.warning(
                "Sentry incidents returned HTTP %s for org %s",
                resp.status_code, self._org,
            )
            return []

        results: List[IncidentEntry] = []
        for incident in resp.json():
            critical_threshold = incident.get("alertRule", {}).get("criticalThreshold")
            severity = "critical" if critical_threshold is not None else "warning"
            affected: List[str] = [
                p if isinstance(p, str) else p.get("slug", str(p))
                for p in incident.get("projects", [])
            ]
            results.append(
                IncidentEntry(
                    id=str(incident["id"]),
                    severity=severity,
                    title=incident.get("title", ""),
                    started_at=incident.get("dateStarted", ""),
                    resolved_at=incident.get("dateResolved"),
                    affected_tenants=affected,
                )
            )
        return results


# ---------------------------------------------------------------------------
# PagerDuty provider
# ---------------------------------------------------------------------------

_PD_SEVERITY_MAP: dict[str, str] = {
    "critical": "critical",
    "high": "critical",
    "warning": "warning",
    "low": "info",
    "info": "info",
}


class PagerDutyIncidentsProvider:
    """Fetch triggered/acknowledged alerts and incidents from PagerDuty.

    Required env vars:
        PD_API_KEY      — REST API key (user or service)

    Optional:
        PD_SERVICE_IDS  — comma-separated service IDs to filter on
    """

    _BASE = "https://api.pagerduty.com"

    def __init__(self) -> None:
        self._api_key: str = os.environ["PD_API_KEY"]
        raw_ids = os.getenv("PD_SERVICE_IDS", "")
        self._service_ids: List[str] = [s.strip() for s in raw_ids.split(",") if s.strip()]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token token={self._api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_severity(raw: str) -> str:
        return _PD_SEVERITY_MAP.get(raw.lower(), "info")

    @staticmethod
    def _tenant_slug_from_alert(alert: dict) -> Optional[str]:
        contexts = alert.get("body", {}).get("contexts", [])
        if contexts and isinstance(contexts, list):
            return contexts[0].get("tenant_slug")
        return None

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------

    def alerts(self) -> List[Alert]:
        params: dict = {
            "statuses[]": ["triggered", "acknowledged"],
            "limit": 20,
        }
        if self._service_ids:
            params["service_ids[]"] = self._service_ids

        try:
            resp = httpx.get(
                f"{self._BASE}/alerts",
                headers=self._headers(),
                params=params,
                timeout=_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("PagerDuty alerts request failed: %s", exc)
            return []

        if resp.status_code != 200:
            logger.warning("PagerDuty alerts returned HTTP %s", resp.status_code)
            return []

        results: List[Alert] = []
        for alert in resp.json().get("alerts", []):
            detail = str(alert.get("body", {}).get("details", ""))[:200]
            results.append(
                Alert(
                    severity=self._normalize_severity(alert.get("severity", "")),
                    title=alert.get("summary", ""),
                    detail=detail,
                    tenant_slug=self._tenant_slug_from_alert(alert),
                    fired_at=alert.get("created_at", ""),
                    suggested_action=f"View in PagerDuty: {alert.get('html_url', '')}",
                )
            )
        return results

    def incidents(self) -> List[IncidentEntry]:
        params: dict = {
            "statuses[]": ["triggered", "acknowledged"],
            "limit": 10,
        }
        if self._service_ids:
            params["service_ids[]"] = self._service_ids

        try:
            resp = httpx.get(
                f"{self._BASE}/incidents",
                headers=self._headers(),
                params=params,
                timeout=_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("PagerDuty incidents request failed: %s", exc)
            return []

        if resp.status_code != 200:
            logger.warning("PagerDuty incidents returned HTTP %s", resp.status_code)
            return []

        results: List[IncidentEntry] = []
        for incident in resp.json().get("incidents", []):
            raw_sev = incident.get("urgency", "")
            severity = "critical" if raw_sev == "high" else "warning"
            affected: List[str] = [
                s.get("summary", s.get("id", ""))
                for s in incident.get("services", [])
            ]
            results.append(
                IncidentEntry(
                    id=str(incident.get("id", "")),
                    severity=severity,
                    title=incident.get("title", incident.get("summary", "")),
                    started_at=incident.get("created_at", ""),
                    resolved_at=incident.get("resolved_at"),
                    affected_tenants=affected,
                )
            )
        return results


# ---------------------------------------------------------------------------
# Empty fallback
# ---------------------------------------------------------------------------


class _EmptyAlertsProvider:
    """Silent fallback when no integration is configured (dev mode)."""

    def alerts(self) -> List[Alert]:
        return []

    def incidents(self) -> List[IncidentEntry]:
        return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_alerts_provider() -> "_EmptyAlertsProvider | SentryAlertsProvider | PagerDutyIncidentsProvider":
    """Return the first available alerts provider based on configured env vars.

    Priority order:
        1. Sentry  — when ``SENTRY_AUTH_TOKEN`` is set
        2. PagerDuty — when ``PD_API_KEY`` is set
        3. ``_EmptyAlertsProvider`` — silent no-op for dev/unconfigured environments
    """
    if os.getenv("SENTRY_AUTH_TOKEN"):
        return SentryAlertsProvider()
    if os.getenv("PD_API_KEY"):
        return PagerDutyIncidentsProvider()
    return _EmptyAlertsProvider()
