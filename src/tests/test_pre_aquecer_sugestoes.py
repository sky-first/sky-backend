# -*- coding: utf-8 -*-
"""Ligar uma fonte pré-aquece as perguntas sugeridas do projeto.

> *"na conexao que fazemos, já gerarmos ali algumas perguntas e respostas"*
> — Lucas, 31/08/2026

As perguntas são geradas pelo Sherlock a olhar para as tabelas que acabaram
de ser descobertas, e o resultado fica em cache. Sem este passo, quem abre o
projeto a seguir é a **primeira pessoa a pagar a espera** — e, pior, apanha a
lista genérica de reserva se o pedido demorar de mais, porque um ecrã vazio
não espera por ninguém.

---

**São perguntas, não respostas — e isso foi uma decisão.**

Pré-correr as respostas seria N consultas ao modelo por cada ligação, a
envelhecer sozinhas. Uma resposta velha é pior do que nenhuma, porque parece
fresca: quem a lê não tem como saber que os dados mudaram desde então.

As perguntas não envelhecem da mesma maneira — quem manda nelas é o esquema,
e o esquema só muda quando se volta a descobrir, que é exactamente quando
isto volta a correr.
"""
from __future__ import annotations

import inspect

from src.services.space_service import SpaceService


def _fonte() -> str:
    return inspect.getsource(SpaceService._trigger_ai_discovery)


class TestPreAquecimento:
    def test_a_descoberta_e_seguida_das_sugestoes(self):
        fonte = _fonte()
        assert "discover_connection" in fonte
        assert "chat_bootstrap" in fonte

    def test_pela_ordem_certa(self):
        """Pedir sugestões antes de haver metadados devolve a lista genérica
        — e guarda-a em cache, que é o pior dos dois mundos."""
        fonte = _fonte()
        assert fonte.index("discover_connection") < fonte.index("chat_bootstrap")

    def test_se_a_descoberta_falhar_nao_se_pede_nada(self):
        """Sem metadados não há o que sugerir. Parar poupa uma chamada ao
        modelo que só podia devolver a lista de reserva."""
        fonte = _fonte()
        i = fonte.index("Auto-discovery for space")
        j = fonte.index("chat_bootstrap")
        assert "return" in fonte[i:j]

    def test_falhar_a_pre_aquecer_nao_estraga_a_ligacao(self):
        """A fonte já está ligada quando isto corre. Deixar a excepção subir
        marcaria como falhada uma ligação que ficou boa."""
        fonte = _fonte()
        i = fonte.index("chat_bootstrap")
        assert "except Exception" in fonte[i:]

    def test_e_corre_em_segundo_plano(self):
        """Quem liga uma fonte não pode ficar à espera do modelo."""
        fonte = inspect.getsource(SpaceService.add_space_connection)
        assert "background_tasks.add_task" in fonte
        assert "_trigger_ai_discovery" in fonte

    def test_com_o_utilizador_que_ligou(self):
        """O bootstrap resolve as equipas a partir de quem pergunta; sem
        utilizador, as sugestões saem do âmbito errado."""
        assert "user_id=str(user.id)" in inspect.getsource(
            SpaceService.add_space_connection
        )
