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
    assert set(TIERS) == set(TIER_LIMITS), (
        "um plano existe num sitio e nao no outro — o Console vende o que "
        "a plataforma nao sabe impor, ou ao contrario"
    )


@pytest.mark.parametrize("slug", TIERS)
def test_os_agentes_prometidos_sao_os_impostos(slug):
    mostra = pricing_tiers.get_tier(slug).capacity_limits["agents"]
    impoe = TIER_LIMITS[slug]["max_agents"]
    if impoe is None:
        return  # ilimitado: o catalogo usa um numero grande de propósito
    assert mostra == impoe, (
        f"{slug}: o Console mostra {mostra} agentes e a plataforma deixa {impoe}"
    )


@pytest.mark.parametrize("slug", TIERS)
def test_o_espaco_prometido_e_o_imposto(slug):
    """O que estava 10x errado."""
    mostra = pricing_tiers.get_tier(slug).capacity_limits["indexed_gb"]
    impoe = TIER_LIMITS[slug]["max_storage_gb"]
    if impoe is None:
        return
    assert mostra == impoe, (
        f"{slug}: o Console promete {mostra} GB e a plataforma deixa {impoe} GB"
    )


def test_os_numeros_sao_os_que_o_lucas_decidiu():
    """3/5 · 10/50 · 50/200, decidido a 02/10/2026.

    Fixado por extenso porque sao numeros comerciais: se alguem os mudar,
    foi uma decisao de preco e nao um acaso de codigo.
    """
    esperado = {
        "starter": (3, 5),
        "foundation": (10, 50),
        "scale": (50, 200),
    }
    for slug, (agentes, gb) in esperado.items():
        c = pricing_tiers.get_tier(slug).capacity_limits
        assert (c["agents"], c["indexed_gb"]) == (agentes, gb), f"{slug} mudou"


def test_o_quarto_plano_nao_se_chama_enterprise():
    """«Enterprise» e ingles num produto que vende em PT e ES — e todas as
    clientes sao empresas, por isso o nome nao distingue nada.

    «Max» le-se igual nas tres linguas e fecha a escada:
    Start -> Core -> Plus -> Max.
    """
    nome = pricing_tiers.get_tier("enterprise").display_name
    assert nome == "Sky Max", nome
    assert "Enterprise" not in nome


def test_os_nomes_nao_se_traduzem():
    """Sao marca, nao vocabulario.

    Um cliente espanhol e um portugues tem de poder dizer «estou no Sky
    Core» e ser o mesmo plano. O que se traduz e a descricao do que ele
    inclui, nao o nome.
    """
    for slug in TIERS:
        nome = pricing_tiers.get_tier(slug).display_name
        assert nome.startswith("Sky "), f"{slug}: {nome!r} foge ao padrao"
        assert nome.isascii(), f"{slug}: {nome!r} tem acentos — nao e marca"
