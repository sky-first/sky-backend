"""Um vocabulário só para os planos (10/10/2026).

Havia dois conjuntos de nomes (registo: starter/foundation/core/advanced/
strategic; limites: starter/foundation/scale/enterprise) e a tradução entre
eles deu um 500 na Consola ao pôr a SkyFirst em Enterprise. Agora os dois
lados usam os nomes da proposta comercial — e estes testes provam que não
há tradução nenhuma a falhar.
"""

from __future__ import annotations

import pytest

from src.models.tenant import TenantTier
from src.services import planos, pricing_tiers
from src.services.vocabulario_dos_planos import COMERCIAL_PARA_REGISTO, nome_de


def test_o_registo_aceita_exactamente_os_planos_da_proposta():
    assert {t.value for t in TenantTier} == set(planos.PLANOS)


@pytest.mark.parametrize("slug", list(planos.PLANOS))
def test_cada_plano_do_catalogo_grava_se_tal_e_qual(slug):
    assert pricing_tiers.get_tier(slug).slug == slug
    assert COMERCIAL_PARA_REGISTO[slug] == slug


@pytest.mark.parametrize("antigo,novo", list(planos.ANTIGOS.items()))
def test_os_nomes_antigos_chegam_ao_plano_de_hoje(antigo, novo):
    assert planos.normalizar(antigo) == novo
    assert COMERCIAL_PARA_REGISTO[antigo] == novo


def test_o_nome_que_se_le_e_o_da_proposta():
    assert nome_de("core") == "Core"
    assert nome_de("strategic") == "Enterprise"
