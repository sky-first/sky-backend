# -*- coding: utf-8 -*-
"""Duas línguas, não uma — regra do Lucas, 12/10/2026.

1. A língua da APP («Idioma») manda em todo o texto de interface — incluindo
   as frases de estado enquanto a Sky trabalha, os avisos e os erros.
2. «Sky responde en» manda na língua da RESPOSTA. «Sigue su pregunta» vai
   como `auto` e chega ao motor como `locale=None` (o motor detecta).

── Os defeitos (Android, app em castelhano, perfil em português) ──

A. «Analisando pergunta…» em português: o motor cravava a frase, e o
   «A pensar…» do backend usava o `locale` da RESPOSTA — que, com
   «Sigue su pregunta», é `None` e caía no português por omissão.
B. Ver o `sky-ai` (`deteccao_confiante`): a língua da conversa ganhava à
   da pergunta.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.core.locale import lingua_da_interface, lingua_da_resposta
from src.schemas.ai import AIQueryRequest, ChatMessageRequest
from src.schemas.chat_stream import normalize_event, parse_sse_data_line, progress_event


class TestALinguaDaInterface:
    def test_o_que_a_app_diz_ganha(self):
        assert lingua_da_interface("es", {"language": "pt"}, locale_do_pedido="pt") == "es"

    def test_auto_nao_e_uma_lingua(self):
        assert lingua_da_interface(None, {"language": "es"}, locale_do_pedido="auto") == "es"

    def test_cliente_antigo_que_manda_a_lingua_no_locale(self):
        assert lingua_da_interface(None, {"language": "pt"}, locale_do_pedido="en") == "en"

    def test_sem_nada_vale_a_conta(self):
        assert lingua_da_interface(None, {"language": "es"}) == "es"
        assert lingua_da_interface(None, None) == "pt"

    def test_os_pedidos_aceitam_ui_locale(self):
        m = ChatMessageRequest(message="x", widget_id=uuid4(), ui_locale="es-ES", locale="auto")
        assert m.ui_locale == "es" and m.locale == "auto"
        assert ChatMessageRequest(message="x", widget_id=uuid4()).ui_locale is None
        assert AIQueryRequest(question="x", ui_locale="pt-PT").ui_locale == "pt"


class TestALinguaDaRespostaGuardada:
    def test_auto_guardado_na_conta_pede_deteccao(self):
        prefs = {"language": "pt", "answer_language": "auto"}
        assert lingua_da_resposta(prefs, permitir_auto=True) == "auto"

    def test_quem_nao_sabe_de_auto_recebe_a_interface(self):
        prefs = {"language": "pt", "answer_language": "auto"}
        assert lingua_da_resposta(prefs) == "pt"

    def test_escolha_explicita_continua_a_valer(self):
        assert (
            lingua_da_resposta({"language": "es", "answer_language": "pt"}, permitir_auto=True)
            == "pt"
        )


class TestAsEtapasNaLinguaDaApp:
    @pytest.mark.parametrize(
        "etapa,chave,esperado",
        [
            ("starting", "thinking", "Pensando…"),
            ("orchestrator", "analyzing_question", "Analizando la pregunta…"),
            ("specialist", "running_query", "Consultando los datos…"),
            ("formatter", "generating_answer", "Redactando la respuesta…"),
        ],
    )
    def test_app_em_castelhano(self, etapa, chave, esperado):
        ev = progress_event(etapa, ui_locale="es")
        assert ev["key"] == chave
        assert ev["message"] == esperado

    def test_o_motor_antigo_em_pt_br_e_traduzido(self):
        """Um sky-ai ainda por publicar manda «Analisando pergunta...»."""
        linha = 'data: {"type": "progress", "stage": "orchestrator", "message": "Analisando pergunta..."}'
        ev = normalize_event(parse_sse_data_line(linha), ui_locale="es")
        assert ev == {
            "type": "progress",
            "stage": "orchestrator",
            "key": "analyzing_question",
            "message": "Analizando la pregunta…",
        }

    def test_a_chave_do_motor_novo_e_respeitada(self):
        raw = {
            "type": "progress",
            "stage": "x",
            "key": "running_query",
            "message": "Querying the data…",
        }
        assert normalize_event(raw, ui_locale="pt")["message"] == "A consultar os dados…"

    def test_etapa_desconhecida_passa_como_veio(self):
        ev = normalize_event({"type": "progress", "stage": "nova", "message": "m"}, ui_locale="es")
        assert ev == {"type": "progress", "stage": "nova", "message": "m"}


async def _aiter(items):
    for x in items:
        yield x


@pytest.mark.asyncio
async def test_app_em_castelhano_perfil_pt_segue_a_pergunta(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session
):
    """O caso de produção, ponta a ponta no backend.

    App em castelhano, perfil em português, «Sigue su pregunta», pergunta
    «cuál ha sido mi facturación». As etapas saem em castelhano, e o motor
    recebe `locale=None` (detecta a pergunta) e `ui_locale="es"`.
    """
    user = test_user_with_tokens["user"]
    user.preferences = {"language": "pt"}
    await db_session.commit()

    capturado: dict = {}

    def _motor(*args, **kwargs):
        capturado.update(kwargs)
        return _aiter(
            [
                'data: {"type": "progress", "stage": "orchestrator", "message": "Analisando pergunta..."}',
                'data: {"type": "chunk", "content": "Su facturación fue de 10.000 €."}',
            ]
        )

    with (
        patch(
            "src.services.ai_service.AIService._get_first_active_connection",
            new=AsyncMock(return_value=str(uuid4())),
        ),
        patch(
            "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
            side_effect=_motor,
        ),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={
                "message": "cuál ha sido mi facturación",
                "widget_id": str(uuid4()),
                "locale": "auto",
                "ui_locale": "es",
            },
            headers={"Authorization": f"Bearer {test_user_with_tokens['access_token']}"},
        ) as resp:
            assert resp.status_code == 200
            corpo = b""
            async for pedaco in resp.aiter_bytes():
                corpo += pedaco

    eventos = [
        json.loads(l[len("data: ") :])
        for l in corpo.decode("utf-8").split("\n\n")
        if l.startswith("data: ")
    ]
    progresso = [e for e in eventos if e["type"] == "progress"]
    assert [e["message"] for e in progresso] == ["Pensando…", "Analizando la pregunta…"]
    assert [e["key"] for e in progresso] == ["thinking", "analyzing_question"]
    texto = corpo.decode("utf-8")
    assert "Analisando" not in texto and "A pensar" not in texto

    assert capturado["locale"] is None, "«Sigue su pregunta» tem de deixar o motor detectar"
    assert capturado["ui_locale"] == "es"


@pytest.mark.asyncio
async def test_portugues_explicito_forca_a_resposta_mas_nao_a_interface(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    capturado: dict = {}

    def _motor(*args, **kwargs):
        capturado.update(kwargs)
        return _aiter(['data: {"type": "chunk", "content": "ok"}'])

    with (
        patch(
            "src.services.ai_service.AIService._get_first_active_connection",
            new=AsyncMock(return_value=str(uuid4())),
        ),
        patch(
            "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
            side_effect=_motor,
        ),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={
                "message": "cuál ha sido mi facturación",
                "widget_id": str(uuid4()),
                "locale": "pt",
                "ui_locale": "es",
            },
            headers={"Authorization": f"Bearer {test_user_with_tokens['access_token']}"},
        ) as resp:
            corpo = b""
            async for pedaco in resp.aiter_bytes():
                corpo += pedaco

    assert capturado["locale"] == "pt"
    assert capturado["ui_locale"] == "es"
    primeiro = next(
        json.loads(l[len("data: ") :])
        for l in corpo.decode("utf-8").split("\n\n")
        if l.startswith("data: ")
    )
    assert primeiro["type"] == "progress" and primeiro["message"] == "Pensando…"
