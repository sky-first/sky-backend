"""Os planos limitam mesmo, e quem se aproxima do tecto e avisado.

**Dois defeitos, e os dois custam dinheiro.**

1. Havia DOIS registos de planos que nao coincidiam. O Console vendia
   `starter/foundation/core/advanced/strategic`; o sistema aplicava
   `starter/foundation/scale/enterprise`. Os que nao existiam no segundo eram
   tratados como ILIMITADOS — um cliente de 120 000 EUR em `core` nao era
   limitado em nada.

2. A logica dos limiares (80/95/100%) existia e escrevia uma linha de
   auditoria «que os ganchos de email da Fase 2 leem». A Fase 2 nunca foi
   feita. O cliente era BLOQUEADO aos 100% e nunca tinha sido AVISADO. Um
   bloqueio sem aviso le-se como avaria.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.services import avisos_de_limite as avisos
from src.services.tectos_do_plano import A_CONFIRMAR, ROTULO_APLICADO, TECTOS, tectos_de


class TestTodosOsPlanosLimitam:
    @pytest.mark.parametrize("plano", ["starter", "foundation", "scale"])
    def test_os_planos_pagos_TEM_tecto_de_agentes(self, plano):
        """**O defeito exacto.**

        `core` e `advanced` caiam em «ilimitado» porque nao existiam na tabela
        de aplicacao. O plano existia na fatura e nao existia no sistema.
        """
        _rotulo, tectos, conhecido = tectos_de(plano)
        assert conhecido
        assert tectos["max_agents"] is not None, f"{plano} sem tecto de agentes"

    def test_so_o_enterprise_e_mesmo_sem_tecto(self):
        # E negociado por contrato, caso a caso. E o unico.
        _r, t, _c = tectos_de("enterprise")
        assert t["max_agents"] is None

    def test_os_tectos_sobem_com_o_preco(self):
        # Um plano mais caro que limitasse mais seria um erro de copiar e
        # colar, e ninguem daria por ele ate um cliente reclamar.
        escada = ["starter", "foundation", "scale"]
        agentes = [TECTOS[p]["max_agents"] for p in escada]
        assert agentes == sorted(agentes)
        assert len(set(agentes)) == len(agentes)

    def test_os_nomes_antigos_continuam_a_limitar(self):
        """`core`, `advanced`, `strategic` e `pilot` estao gravados na base.

        Antes caiam em «ilimitado». Agora herdam os tectos do plano para onde
        apontam — um cliente com um nome antigo continua limitado.
        """
        for antigo, esperado_tem_tecto in (
            ("core", True),
            ("pilot", True),
            ("advanced", False),
            ("strategic", False),
        ):
            _r, t, conhecido = tectos_de(antigo)
            assert conhecido, antigo
            assert (t["max_agents"] is not None) is esperado_tem_tecto, antigo

    def test_o_catalogo_comercial_esta_todo_coberto(self):
        """Uma varredura, em vez de uma lista que envelhece.

        E assim que este defeito nasceu: acrescentaram-se planos ao catalogo
        comercial e ninguem os acrescentou a tabela de aplicacao.
        """
        from src.services.pricing_tiers import TIER_REGISTRY

        em_falta = [p for p in TIER_REGISTRY if p not in TECTOS]
        assert em_falta == [], f"planos que se vendem e nao se limitam: {em_falta}"

    def test_cada_plano_tem_um_rotulo_que_a_base_aceita(self):
        """A coluna `tier` tem uma restricao na base a quatro valores.

        Escrever `core` la rebenta a gravacao — e o cliente ficava sem linha
        de limites nenhuma, ou seja, outra vez sem tecto.
        """
        permitidos = {"starter", "foundation", "scale", "enterprise"}
        for plano in TECTOS:
            assert ROTULO_APLICADO[plano] in permitidos


class TestUmPlanoDesconhecido:
    def test_continua_a_servir(self):
        """Fechar num erro de configuracao NOSSO cortava o servico a quem paga.

        E o primeiro a saber seria o cliente.
        """
        _r, t, conhecido = tectos_de("plano-que-nao-existe")
        assert conhecido is False
        assert t["max_agents"] is None

    def test_mas_ja_nao_em_silencio(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            tectos_de("plano-que-nao-existe")
        assert any("desconhecido" in r.getMessage().lower() for r in caplog.records)


class TestOQueEuNaoDecidi:
    def test_as_duvidas_comerciais_ficam_escritas(self):
        """Onde os dois registos discordavam, nao escolhi por palpite.

        Um teste e nao um comentario: um comentario que ninguem abre e o
        mesmo que nao existir — que e precisamente o que aconteceu com a
        «Fase 2».
        """
        assert "armazenamento" in A_CONFIRMAR
        assert "utilizadores" in A_CONFIRMAR
        # E a maior de todas: o custo por pergunta e uma ESTIMATIVA. A medicao
        # real esta na `tenant_llm_daily_snapshots` e ainda nao foi usada.
        assert "medicao_real_dos_tokens" in A_CONFIRMAR


class TestOAvisoChegaAAlguem:
    @pytest.mark.asyncio
    async def test_os_admins_do_cliente_recebem_no_sino(self):
        db = AsyncMock()
        criadas = []

        class _Servico:
            def __init__(self, _db):
                pass

            async def create_notification(self, n):
                criadas.append(n)
                return n

        # UUIDs a serio: o `NotificationCreate.user_id` e um UUID, e um "u1"
        # rebenta na validacao — dentro do `except` largo, em silencio. Foi
        # assim que este teste falhou a primeira vez, e e a prova de que o
        # registo de aviso naquele `except` faz falta.
        admins = [uuid4(), uuid4()]
        with patch.object(
            avisos, "_admins_do_cliente", AsyncMock(return_value=admins)
        ), patch(
            "src.services.notification_service.NotificationService", _Servico
        ), patch.object(
            avisos, "operadores_da_plataforma", lambda: []
        ):
            await avisos.avisar(
                db,
                tenant_id="t1",
                tenant_slug="gbtsolutions",
                tier="starter",
                recurso="agents",
                limiar=80,
                atual=8,
                limite=10,
            )
        assert len(criadas) == 2
        # Em portugues, e nao «agents»: quem le isto e um cliente, nao quem
        # escreveu a coluna.
        assert "agentes" in criadas[0].title

    @pytest.mark.asyncio
    async def test_a_equipa_recebe_por_email(self):
        db = AsyncMock()
        enviados = []

        class _Email:
            def send_email(self, to_email, subject, html_content, text_content=None):
                enviados.append((to_email, subject))
                return True

        with patch.object(
            avisos, "_admins_do_cliente", AsyncMock(return_value=[])
        ), patch("src.services.email_service.EmailService", _Email), patch.object(
            avisos, "operadores_da_plataforma", lambda: ["ops@skyfirstlabs.com"]
        ):
            await avisos.avisar(
                db,
                tenant_id="t1",
                tenant_slug="gbtsolutions",
                tier="core",
                recurso="agents",
                limiar=95,
                atual=28,
                limite=30,
            )
        assert enviados
        assert "gbtsolutions" in enviados[0][1]
        assert "95" in enviados[0][1]

    @pytest.mark.asyncio
    async def test_sem_destinatarios_configurados_GRITA(self, caplog):
        """Uma definicao em falta nao pode voltar a ser silenciosa.

        E exactamente assim que o defeito original sobreviveu: havia um
        caminho de aviso que nao levava a lado nenhum e nao se queixava.
        """
        import logging

        db = AsyncMock()
        with patch.object(
            avisos, "_admins_do_cliente", AsyncMock(return_value=[])
        ), patch.object(avisos, "operadores_da_plataforma", lambda: []):
            with caplog.at_level(logging.WARNING):
                await avisos.avisar(
                    db,
                    tenant_id="t1",
                    tenant_slug="x",
                    tier="starter",
                    recurso="agents",
                    limiar=100,
                    atual=3,
                    limite=3,
                )
        assert any("PLATFORM_ALERT_EMAILS" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_uma_falha_de_email_nao_trava_nada(self):
        """Isto corre dentro do incremento de um contador.

        Uma falha de SMTP nao pode impedir alguem de fazer uma pergunta.
        """
        db = AsyncMock()

        class _EmailQuebrado:
            def send_email(self, **kw):
                raise RuntimeError("SMTP em baixo")

        with patch.object(
            avisos, "_admins_do_cliente", AsyncMock(return_value=[])
        ), patch("src.services.email_service.EmailService", _EmailQuebrado), patch.object(
            avisos, "operadores_da_plataforma", lambda: ["ops@skyfirstlabs.com"]
        ):
            await avisos.avisar(
                db,
                tenant_id="t1",
                tenant_slug="x",
                tier="starter",
                recurso="agents",
                limiar=100,
                atual=3,
                limite=3,
            )  # nao levanta


class TestAsContasFecham:
    """Os limites nao sao numeros escolhidos a mao.

    Saem do custo real de uma pergunta e da infraestrutura fixa. Se alguem
    mexer num sem mexer no outro, isto acende.
    """

    def test_uma_pergunta_custa_cerca_de_tres_centimos(self):
        from src.services.economia_dos_planos import custo_por_pergunta_eur

        c = custo_por_pergunta_eur()
        # Um intervalo largo de proposito: o que nao pode acontecer e passar a
        # ser dez vezes mais sem ninguem reparar — por exemplo se alguem
        # trocar o formatador de Haiku para Sonnet.
        assert 0.01 < c < 0.08, f"{c:.4f} EUR por pergunta"

    def test_os_limites_do_plano_batem_certo_com_os_tectos(self):
        """Os dois ficheiros tem de contar a mesma historia.

        A `economia_dos_planos` calcula a margem com um numero de perguntas; o
        `tectos_do_plano` aplica outro. Se divergirem, a margem calculada e
        sobre um plano que nao existe.
        """
        from src.services.economia_dos_planos import PLANOS
        from src.services.tectos_do_plano import TECTOS

        for slug, plano in PLANOS.items():
            assert TECTOS[slug]["max_queries_per_month"] == plano.perguntas_por_mes, slug
            assert TECTOS[slug]["max_agents"] == plano.agentes, slug

    @pytest.mark.parametrize("plano", ["starter", "foundation", "scale"])
    def test_cada_plano_chega_aos_80_por_cento_com_clientes_a_serio(self, plano):
        """Um plano que nem com muitos clientes da margem esta mal desenhado.

        `None` quer dizer que so os tokens ja comem a margem toda — ou seja, o
        limite de perguntas esta alto de mais para o preco.
        """
        from src.services.economia_dos_planos import clientes_para_margem

        n = clientes_para_margem(plano, 80.0)
        assert n is not None, f"{plano}: os tokens sozinhos comem a margem"
        assert n <= 40, f"{plano}: precisa de {n} clientes para 80%"

    def test_com_poucos_clientes_a_margem_NAO_esta_la(self):
        """E o facto mais importante desta conta, e o mais facil de esquecer.

        Com 5 clientes o starter da 36%, nao 80%. A infraestrutura fixa e que
        manda enquanto sao poucos — o preco por si nao chega.
        """
        from src.services.economia_dos_planos import margem

        assert margem("starter", 5)["margem_pct"] < 50
        assert margem("starter", 20)["margem_pct"] >= 75
