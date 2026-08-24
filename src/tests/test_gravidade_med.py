"""Um achado gravado com `med` nao pode partir o ecra do agente.

**O defeito, e foi meu.** O classificador do `sky-ai` gravou `severity="med"`
durante dois dias. O enum do backend chama-lhe `medium`. Resultado: o
`GET /agents/{id}` rebentava inteiro::

    ResponseValidationError: 5 validation errors
    Input should be 'low', 'medium', 'high' or 'critical' [input: 'med']

Ficou em producao sem ninguem dar por isso porque a LISTA de agentes funciona
— nao devolve achados — e so o DETALHE e que parte.

**Tolerante a leitura, estrito a escrita.** Rejeitar na leitura castiga quem
le por um erro de quem escreveu: o achado esta la, correcto, so com a palavra
errada.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.models.agent import FindingSeverity
from src.schemas.agent import AgentFindingResponse


def _achado(gravidade):
    return {
        "id": uuid4(),
        "agent_id": uuid4(),
        "type": "insight",
        "severity": gravidade,
        "title": "Receita faturada",
        "description": "Ha 17 faturas em atraso.",
        "created_at": datetime.now(timezone.utc),
    }


class TestOQueJaEstaGravado:
    def test_med_le_se_como_medium(self):
        """**O defeito exacto.** Cinco destes davam um 500."""
        r = AgentFindingResponse(**_achado("med"))
        assert r.severity == FindingSeverity.MEDIUM

    @pytest.mark.parametrize("antigo", ["med", "MED", " med ", "mid", "moderate"])
    def test_as_variantes_todas(self, antigo):
        assert AgentFindingResponse(**_achado(antigo)).severity == FindingSeverity.MEDIUM

    @pytest.mark.parametrize("bom", ["low", "medium", "high", "critical"])
    def test_os_validos_passam_na_mesma(self, bom):
        assert AgentFindingResponse(**_achado(bom)).severity.value == bom

    def test_lixo_continua_a_ser_recusado(self):
        """A tolerancia e para o `med`, nao para tudo.

        Aceitar qualquer coisa esconderia o proximo erro de escrita em vez de
        o mostrar — que e como este chegou a producao.
        """
        with pytest.raises(Exception):
            AgentFindingResponse(**_achado("catastrofico"))


class TestAEscritaEstrita:
    def test_o_worker_nunca_grava_um_valor_invalido(self):
        from src.workers.agent_worker import GRAVIDADES_VALIDAS, _gravidade_valida

        for entrada in ["med", "mid", "", None, "catastrofico", "HIGH"]:
            assert _gravidade_valida(entrada) in GRAVIDADES_VALIDAS

    def test_o_med_do_classificador_vira_medium(self):
        from src.workers.agent_worker import _gravidade_valida

        assert _gravidade_valida("med") == "medium"

    def test_o_de_omissao_do_cliente_de_ia_e_valido(self):
        """Ate a saida de emergencia tem de ser gravavel."""
        import inspect

        from src.ai import http_client

        fonte = inspect.getsource(http_client)
        assert '"severity": "med"' not in fonte
