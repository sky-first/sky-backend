"""O Console oferecia um tier que a base recusava.

⚠️ **O Lucas apanhou-o a tentar pôr a própria SkyFirst em Enterprise.**
O que viu foi um 500 genérico; o que estava por baixo era isto:

    POST /api/console/v1/tenants/skyfirstlabs/tier  ->  500
    CheckViolationError: new row for relation "tenant_registry"
    violates check constraint "tenant_registry_tier_check"

── Dois vocabulários, e o endpoint usava um de cada lado ────────────

Há dois conjuntos de nomes de tier, e isso é deliberado — está escrito
em `_REGISTRY_TO_COMMERCIAL_TIER`:

    registo   (tenant_registry.tier) : starter foundation core advanced strategic
    comercial (tenant_plan_limits)   : starter foundation scale enterprise

O endpoint procurava o preset no catálogo COMERCIAL e depois gravava
esse mesmo nome na coluna do REGISTO.

`starter` e `foundation` passavam **por coincidência**: são os dois
únicos nomes que existem nos dois lados. `scale` e `enterprise`
rebentavam — e `enterprise` é justamente o que se quer dar a um cliente
estratégico.

── Porque é que o teste é sobre os QUATRO ───────────────────────────

Testar só o `enterprise` fixava o sintoma. O defeito é a tradução entre
vocabulários: qualquer nome comercial tem de ter correspondência no
registo, senão volta o 500 no tier seguinte que alguém acrescentar.
"""

from __future__ import annotations

import pytest

from src.api.v1.console import (
    _COMMERCIAL_TO_REGISTRY_TIER,
    _REGISTRY_TO_COMMERCIAL_TIER,
)
from src.models.tenant import TenantTier
from src.services import pricing_tiers


def _tiers_aceites_pela_base() -> set[str]:
    """Os nomes que a restricao `tenant_registry_tier_check` deixa passar."""
    return {t.value for t in TenantTier}


def test_todo_o_tier_comercial_cabe_no_registo():
    """O defeito, em forma de regra.

    Se um tier do catálogo nao tiver traducao para o registo, gravá-lo
    dá `CheckViolationError` — um 500 sem explicacao nenhuma para quem
    carregou no botao.
    """
    comerciais = {t.slug for t in pricing_tiers.list_tiers()}
    sem_traducao = sorted(comerciais - set(_COMMERCIAL_TO_REGISTRY_TIER))
    assert not sem_traducao, (
        f"tiers do catalogo que nao sabem ir para o registo: {sem_traducao} — "
        "grava-los da 500"
    )


def test_a_traducao_aterra_sempre_num_valor_que_a_base_aceita():
    aceites = _tiers_aceites_pela_base()
    maus = {k: v for k, v in _COMMERCIAL_TO_REGISTRY_TIER.items() if v not in aceites}
    assert not maus, f"traducoes para valores que a base recusa: {maus}"


@pytest.mark.parametrize("comercial", ["starter", "foundation", "scale", "enterprise"])
def test_os_quatro_tiers_do_console_tem_destino(comercial):
    """Nao so o que falhou — os quatro.

    `starter` e `foundation` passavam por coincidencia. Se alguem mudar
    um nome de um dos lados, e aqui que se ve.
    """
    assert comercial in _COMMERCIAL_TO_REGISTRY_TIER
    assert _COMMERCIAL_TO_REGISTRY_TIER[comercial] in _tiers_aceites_pela_base()


def test_a_ida_e_a_volta_sao_coerentes():
    """Traduzir para o registo e voltar tem de dar o mesmo tier comercial.

    `scale` tem duas origens possiveis (`core` e `advanced`), por isso a
    volta nao e simetrica nos nomes — mas o tier comercial tem de ser o
    mesmo, senao os limites que o cliente paga mudam sozinhos.
    """
    for comercial, registo in _COMMERCIAL_TO_REGISTRY_TIER.items():
        de_volta = _REGISTRY_TO_COMMERCIAL_TIER.get(registo)
        assert de_volta == comercial, (
            f"{comercial} -> {registo} -> {de_volta}: a volta muda os limites"
        )


def test_enterprise_vai_para_strategic():
    """O caso exacto que deu 500 a 02/10."""
    assert _COMMERCIAL_TO_REGISTRY_TIER["enterprise"] == "strategic"
    assert "strategic" in _tiers_aceites_pela_base()
    assert "enterprise" not in _tiers_aceites_pela_base()
