"""Tests for the tenant tier-change endpoint.

Covers the GBT-pre-deploy invariants (2026-05-30):

* ``pilot`` is gone — ``starter`` is the cheapest tier on the registry.
* Tier change updates the tier label + rate limits.
* Tier change updates ``capacity_limits`` when ``apply_preset=true``,
  preserves them when ``apply_preset=false``.
* Downgrade is refused with HTTP 422 when ``capacity_used`` exceeds
  the new tier's preset caps (per-dimension breakdown returned).
* Downgrade override path: ``apply_preset=false`` bypasses the
  capacity check intentionally (contractual override).
* Audit log records both success and the 422-failure case.
* Idempotency: re-applying the same tier does not write a new
  ``CHANGE_TIER`` audit entry.

A quirk worth knowing: the global ``http_exception_handler`` in
``src.core.errors.handlers`` wraps every HTTPException detail into
``{"code", "correlation_id", "message"}`` and stringifies the original
detail. ``_unwrap_error_message`` below recovers the structured dict
the endpoint actually returned via ``ast.literal_eval``.
"""

from __future__ import annotations

import ast
import uuid
from typing import Any, Dict

import pytest
from sqlalchemy import select

from src.api.console_auth import require_sky_team
from src.api.deps import get_current_user
from src.main import app
from src.models.tenant import Tenant, TenantTier
from src.models.user import User
from src.services import pricing_tiers


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def sky_team_dev_bypass(monkeypatch):
    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "")
    yield


@pytest.fixture
def sky_team_user():
    return User(
        id=uuid.uuid4(),
        email="lucas@skyfirstlabs.com",
        password_hash="",
        name="Lucas",
        role="admin",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=True,
    )


@pytest.fixture
def authed_client(client, sky_team_user):
    app.dependency_overrides[get_current_user] = lambda: sky_team_user
    app.dependency_overrides[require_sky_team] = lambda: sky_team_user
    yield client
    app.dependency_overrides.pop(require_sky_team, None)


def _unwrap_error_message(body: Dict[str, Any]) -> Dict[str, Any]:
    """Recover the structured error dict the endpoint returned.

    The global handler at ``src/core/errors/handlers.py`` packages the
    response as ``{"error": {"code", "message", "correlation_id"}}``
    where ``message`` is ``str(original_detail)``. For a dict detail
    that string is the Python repr — ``ast.literal_eval`` round-trips
    it back to the dict.
    """
    # The handler envelope nests under ``error``.
    if isinstance(body, dict):
        envelope = body.get("error")
        if isinstance(envelope, dict):
            msg = envelope.get("message")
            if isinstance(msg, str) and msg.startswith("{"):
                try:
                    return ast.literal_eval(msg)
                except Exception:  # noqa: BLE001
                    pass
            # Envelope without a parseable message — return it raw.
            return envelope
        # Raw detail dict (no envelope).
        if "error" in body and isinstance(body["error"], str):
            return body
    return body


def _registry_payload(slug: str = "gbt", **overrides) -> Dict:
    base = dict(
        slug=slug,
        display_name=f"{slug.upper()} Co.",
        tier="starter",
        db_host=f"postgres-{slug}.local",
        db_port=5432,
        db_name=f"tenant_{slug}",
        db_credentials_secret_arn=f"arn:secret:{slug}:db",
        redis_host=f"redis-{slug}.local",
        redis_credentials_secret_arn=f"arn:secret:{slug}:redis",
        sso_provider="google",
    )
    base.update(overrides)
    return base


# ── Rename invariants ──────────────────────────────────────────────


def test_starter_is_cheapest_tier():
    """The ``pilot`` slug must no longer be a TIER_REGISTRY key — it
    was renamed to ``starter`` in the 2026-05-30 rename."""
    assert "pilot" not in pricing_tiers.TIER_REGISTRY
    assert "starter" in pricing_tiers.TIER_REGISTRY

    cheapest = pricing_tiers.list_tiers()[0]
    assert cheapest.slug == "starter"
    # O nome da proposta comercial oficial (10/10/2026).
    assert cheapest.display_name == "Starter"


def test_tenant_tier_enum_uses_starter():
    """The ORM enum was updated alongside the registry. ``PILOT`` is
    gone; ``STARTER`` is the canonical lowest tier."""
    assert not hasattr(TenantTier, "PILOT")
    assert TenantTier.STARTER.value == "starter"


# ── Listing tiers ──────────────────────────────────────────────────


def test_list_tiers_returns_starter(authed_client):
    res = authed_client.get("/api/console/v1/tiers")
    assert res.status_code == 200
    slugs = [t["slug"] for t in res.json()]
    assert slugs[0] == "starter"
    assert "pilot" not in slugs


# ── Mudar de plano (10/10/2026: tabela única, uso contado) ─────────
#
# A descida compara os tectos novos com o uso CONTADO na base do cliente
# (`limites_do_plano.uso_do_cliente`). Nos testes não há base de cliente;
# o uso é simulado.


@pytest.fixture
def uso(monkeypatch):
    from src.services import limites_do_plano

    atual = {"ligacoes": 0, "agentes": 0, "armazenamento_bytes": 0, "perguntas_mes": 0}

    async def _uso(slug, tenant_id):
        return dict(atual)

    monkeypatch.setattr(limites_do_plano, "uso_do_cliente", _uso)
    from src.tests.conftest import TestSessionLocal

    monkeypatch.setattr(limites_do_plano, "_sessao_da_plataforma", lambda: TestSessionLocal())
    return atual


def test_subir_de_starter_para_core_aplica_os_tectos(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("up", tier="starter"))
    res = authed_client.post(
        "/api/console/v1/tenants/up/tier", json={"tier": "core", "apply_preset": True}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tier"] == "core"
    core = pricing_tiers.get_tier("core")
    assert body["capacity_limits"] == core.capacity_limits
    assert body["rate_limit_rpm"] == core.rate_limit_rpm


def test_o_nome_antigo_foundation_chega_ao_core(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("old", tier="starter"))
    res = authed_client.post(
        "/api/console/v1/tenants/old/tier", json={"tier": "foundation", "apply_preset": True}
    )
    assert res.status_code == 200, res.text
    assert res.json()["tier"] == "core"


def test_mudar_de_plano_fica_no_registo_de_auditoria(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("aud", tier="starter"))
    authed_client.post(
        "/api/console/v1/tenants/aud/tier", json={"tier": "core", "apply_preset": True}
    )
    audit = authed_client.get("/api/console/v1/audit?tenant_slug=aud").json()
    change = [e for e in audit if e["action"] == "change_tier"]
    assert len(change) == 1
    assert change[0]["request_payload"]["from"] == "starter"
    assert change[0]["request_payload"]["to"] == "core"


@pytest.mark.asyncio
async def test_descer_abaixo_do_uso_e_recusado_com_o_que_excede(authed_client, uso, db_session):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("over", tier="core"))
    uso.update(ligacoes=2, agentes=15)
    res = authed_client.post(
        "/api/console/v1/tenants/over/tier", json={"tier": "starter", "apply_preset": True}
    )
    assert res.status_code == 422, res.text
    err = _unwrap_error_message(res.json())
    assert err.get("error") == "tier_change_breach"
    fora = {b["recurso"]: b for b in err["breaches"]}
    assert fora["max_connections"] == {"recurso": "max_connections", "usado": 2, "limite": 1}
    assert fora["max_agents"]["limite"] == 10
    # Nada mudou.
    t = (await db_session.execute(select(Tenant).where(Tenant.slug == "over"))).scalar_one()
    await db_session.refresh(t)
    assert t.tier == "core"


def test_descida_recusada_fica_auditada(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("audf", tier="core"))
    uso.update(agentes=15)
    authed_client.post(
        "/api/console/v1/tenants/audf/tier", json={"tier": "starter", "apply_preset": True}
    )
    audit = authed_client.get("/api/console/v1/audit?tenant_slug=audf").json()
    falhou = [e for e in audit if e["action"] == "change_tier" and e["result"] == "failure"]
    assert len(falhou) == 1
    assert any(b["recurso"] == "max_agents" for b in falhou[0]["request_payload"]["excessos"])


def test_apply_preset_false_muda_o_nome_e_mantem_os_tectos(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("keep", tier="plus"))
    res = authed_client.post(
        "/api/console/v1/tenants/keep/tier", json={"tier": "starter", "apply_preset": False}
    )
    assert res.status_code == 200, res.text
    plano = authed_client.get("/api/console/v1/tenants/keep/plano").json()
    assert plano["plano"] == "starter"
    assert plano["tectos"]["max_connections"] == 5  # os do Plus ficaram
    assert plano["personalizado"] is True


def test_plano_especial_na_consola(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("esp", tier="starter"))
    res = authed_client.put(
        "/api/console/v1/tenants/esp/plano",
        json={"plano": "starter", "tectos": {"max_connections": 2}},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tectos"]["max_connections"] == 2
    assert body["tectos_do_plano"]["max_connections"] == 1
    assert body["personalizado"] is True


def test_a_consola_lista_a_tabela_oficial(authed_client):
    planos = authed_client.get("/api/console/v1/planos").json()["planos"]
    assert [(p["slug"], p["preco_mensal_eur"]) for p in planos][:3] == [
        ("starter", 490),
        ("core", 900),
        ("plus", 1800),
    ]


# ── Unknown tier / tenant ──────────────────────────────────────────


def test_unknown_tier_400(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("u", tier="starter"))
    res = authed_client.post(
        "/api/console/v1/tenants/u/tier", json={"tier": "not-a-real-tier", "apply_preset": True}
    )
    assert res.status_code == 400


def test_unknown_tenant_404(authed_client, uso):
    res = authed_client.post(
        "/api/console/v1/tenants/ghost/tier", json={"tier": "starter", "apply_preset": True}
    )
    assert res.status_code == 404


def test_o_mesmo_plano_nao_escreve_mudanca(authed_client, uso):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("idem", tier="core"))
    res = authed_client.post(
        "/api/console/v1/tenants/idem/tier", json={"tier": "core", "apply_preset": True}
    )
    assert res.status_code == 200
    audit = authed_client.get("/api/console/v1/audit?tenant_slug=idem").json()
    assert [e for e in audit if e["action"] == "change_tier"] == []
