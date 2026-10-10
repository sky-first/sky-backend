"""O Console prometia dez vezes mais espaço do que a plataforma dá.

⚠️ **Dois sítios guardavam os limites de cada plano, e divergiram.**

    `pricing_tiers`      — o que o Console MOSTRA a quem compra
    `tenant_plan_limits` — o que a plataforma IMPÕE a quem usa

Em 02/10/2026 estavam assim:

    Sky Start   mostrava  50 GB   impunha   5 GB
    Sky Core    mostrava 200 GB   impunha  50 GB
    Sky Plus    mostrava 500 GB   impunha 200 GB
    Sky Plus    mostrava  30 agentes      impunha 50

O armazenamento estava **10× errado em todos os planos**. Mostrar aquele
ecrã a um cliente era prometer dez vezes mais espaço do que o sistema o
deixa usar — e isso descobre-se no dia em que ele enche.

O Lucas escolheu os números que a plataforma impõe: 3/5, 10/50, 50/200.

── Porque é que isto nao se resolve escolhendo um sitio ─────────────

Os dois precisam de existir: o catalogo tem preco, publico-alvo e o que
esta incluido (coisas comerciais); os limites tem contadores e sao lidos
no caminho quente de cada pedido. Juntá-los punha texto de marketing
dentro de uma verificacao que corre mil vezes por minuto.

O que nao pode e divergirem em silêncio. É isso que este teste impede.
"""

from __future__ import annotations

import pytest

from src.models.tenant_plan_limits import TIER_LIMITS
from src.services import pricing_tiers


TIERS = [t.slug for t in pricing_tiers.list_tiers()]


def test_os_dois_sitios_conhecem_os_mesmos_planos():
    # TIER_LIMITS também responde aos nomes antigos (foundation, scale…),
    # que mapeiam; o que se vende tem de estar todo lá.
    from src.services import planos

    assert set(TIERS) == set(planos.PLANOS)
    assert set(TIERS) <= set(TIER_LIMITS), (
        "um plano existe num sitio e nao no outro — o Console vende o que "
        "a plataforma nao sabe impor, ou ao contrario"
    )


@pytest.mark.parametrize("slug", TIERS)
def test_os_agentes_prometidos_sao_os_impostos(slug):
    mostra = pricing_tiers.get_tier(slug).capacity_limits["agents"]
    impoe = TIER_LIMITS[slug]["max_agents"]
    if impoe is None:
        return  # ilimitado: o catalogo usa um numero grande de propósito
    assert (
        mostra == impoe
    ), f"{slug}: o Console mostra {mostra} agentes e a plataforma deixa {impoe}"


@pytest.mark.parametrize("slug", TIERS)
def test_o_espaco_prometido_e_o_imposto(slug):
    """O que estava 10x errado."""
    mostra = pricing_tiers.get_tier(slug).capacity_limits["indexed_gb"]
    impoe = TIER_LIMITS[slug]["max_storage_gb"]
    if impoe is None:
        return
    assert mostra == impoe, f"{slug}: o Console promete {mostra} GB e a plataforma deixa {impoe} GB"


def test_os_numeros_sao_os_que_o_lucas_decidiu():
    """Áreas vigiadas e GB da proposta oficial (10/10/2026).

    Fixado por extenso porque sao numeros comerciais: se alguem os mudar,
    foi uma decisao de preco e nao um acaso de codigo.
    """
    esperado = {
        "starter": (10, 10),
        "core": (30, 50),
        "plus": (100, 200),
    }
    for slug, (agentes, gb) in esperado.items():
        c = pricing_tiers.get_tier(slug).capacity_limits
        assert (c["agents"], c["indexed_gb"]) == (agentes, gb), f"{slug} mudou"


def test_os_nomes_sao_os_da_proposta_oficial():
    """Starter · Core · Plus · Enterprise — como na proposta enviada aos
    clientes (10/10/2026). A 02/10 tinha-se decidido «Sky Start/Core/Plus/
    Max»; o documento oficial ganhou («segue os dados do documento»)."""
    nomes = [
        pricing_tiers.get_tier(s).display_name for s in ("starter", "core", "plus", "enterprise")
    ]
    assert nomes == ["Starter", "Core", "Plus", "Enterprise"]


def test_os_nomes_nao_se_traduzem():
    """Sao marca, nao vocabulario.

    Um cliente espanhol e um portugues tem de poder dizer «estou no Sky
    Core» e ser o mesmo plano. O que se traduz e a descricao do que ele
    inclui, nao o nome.
    """
    for slug in TIERS:
        nome = pricing_tiers.get_tier(slug).display_name
        assert nome.isascii(), f"{slug}: {nome!r} tem acentos — nao e marca"


# ── A receita ───────────────────────────────────────────────────────
#
# ⚠️ **O painel de CEO reportava um doze avos da receita real.**
#
# O comentario em `TierPreset.headline_price_eur` dizia "annual list
# price". Nao era verdade: 490, 900 e 1.800 sao as MENSALIDADES do
# documento comercial.
#
# Tres sitios acreditaram no comentario e dividiram por 12:
#
#     ceo_dashboard.py  — o MRR e o ARR contratados
#     console.py        — a coluna `monthly_eur` do comparador
#     csm_service.py    — o valor em risco nas renovacoes
#
# O Sky Start aparecia a **40,83 EUR/mes**. Ninguem reparou porque o
# numero aparece sozinho, longe do preco de tabela.


def test_os_precos_sao_mensais():
    """O documento comercial: 490 / 900 / 1.800 por MES."""
    esperado = {"starter": 490, "core": 900, "plus": 1_800}
    for slug, preco in esperado.items():
        t = pricing_tiers.get_tier(slug)
        assert t.headline_price_eur == preco, slug
        assert t.pricing_unit == "month", f"{slug}: {t.pricing_unit!r}"


def test_o_plano_sob_consulta_nao_tem_preco():
    t = pricing_tiers.get_tier("enterprise")
    assert t.headline_price_eur is None
    assert t.pricing_unit == "custom"


@pytest.mark.parametrize(
    "ficheiro",
    [
        "src/services/ceo_dashboard.py",
        "src/api/v1/console.py",
        "src/services/csm_service.py",
    ],
)
def test_ninguem_volta_a_dividir_o_preco_por_doze(ficheiro):
    """A regra, nao o caso.

    Os tres sitios que calculavam receita dividiam por 12 porque o
    comentario os enganou. Se alguem voltar a faze-lo, e aqui que se ve —
    e o custo de nao ver e reportar 1/12 da receita ao proprio CEO.
    """
    from pathlib import Path

    fonte = Path(ficheiro).read_text(encoding="utf-8")
    linhas = [
        (n, l.strip())
        for n, l in enumerate(fonte.splitlines(), 1)
        if "headline_price_eur" in l and ("/ 12" in l or "/12" in l)
    ]
    assert not linhas, f"{ficheiro}: o preco mensal esta a ser dividido por 12: {linhas}"
