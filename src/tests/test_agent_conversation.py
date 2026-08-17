"""A conversa do agente — o fio onde ele responde e onde se fala com ele.

Cobre as duas peças que fazem o insight deixar de ser uma folha solta:
o agendamento à hora escolhida, e o contexto que viaja quando alguém responde
no fio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.services.agent_conversation_service import (
    agent_context_instructions,
    render_discussion,
)
from src.workers.agent_worker import next_run_at, scheduled_hour


# ─── Quando é que o agente volta a correr ────────────────────────────────────
NOW = datetime(2026, 8, 14, 15, 47, tzinfo=timezone.utc)


def test_without_a_chosen_hour_it_behaves_as_before():
    """Sem hora escolhida, o comportamento antigo mantém-se."""
    assert next_run_at(NOW, "daily") == NOW + timedelta(hours=24)


def test_a_daily_agent_aligns_to_the_chosen_hour():
    """Um agente diário criado às 15h47 respondia todos os dias às 15h47 — que
    não interessa a ninguém. Com hora escolhida, alinha."""
    assert next_run_at(NOW, "daily", hour=8) == datetime(
        2026, 8, 15, 8, 0, tzinfo=timezone.utc
    )


def test_the_chosen_hour_later_today_is_still_today():
    assert next_run_at(NOW, "daily", hour=20) == datetime(
        2026, 8, 14, 20, 0, tzinfo=timezone.utc
    )


def test_it_never_schedules_in_the_past_or_on_itself():
    """Agendar para o instante actual punha o agente num ciclo apertado."""
    exactly_now = NOW.replace(minute=0, second=0, microsecond=0)
    assert next_run_at(exactly_now, "daily", hour=exactly_now.hour) > exactly_now


def test_weekly_keeps_the_same_weekday():
    out = next_run_at(NOW, "weekly", hour=8)
    assert out.weekday() == (NOW + timedelta(days=7)).weekday()
    assert out.hour == 8


def test_an_out_of_range_hour_is_clamped_not_crashed():
    assert next_run_at(NOW, "daily", hour=99).hour == 23


def test_scheduled_hour_reads_the_schedule_blob():
    assert scheduled_hour(SimpleNamespace(schedule_jsonb={"hour": 8, "minute": 30})) == (8, 30)


def test_scheduled_hour_survives_rubbish():
    """A coluna é JSON livre; um valor estragado não pode parar o agendador."""
    assert scheduled_hour(SimpleNamespace(schedule_jsonb=None)) == (None, 0)
    assert scheduled_hour(SimpleNamespace(schedule_jsonb={})) == (None, 0)
    assert scheduled_hour(SimpleNamespace(schedule_jsonb={"hour": "oito"})) == (None, 0)
    assert scheduled_hour(SimpleNamespace(schedule_jsonb="nonsense")) == (None, 0)


# ─── O contexto que viaja quando alguém responde no fio ──────────────────────
def _msg(role, content, author=None):
    return SimpleNamespace(role=role, content=content, author_name=author)


def test_the_discussion_says_who_said_what():
    """Sem distinguir quem falou, o modelo lê os comentários da equipa como se
    fossem instruções suas e responde a eles em vez de à pergunta."""
    out = render_discussion(
        [
            _msg("assistant", "As vendas do Norte caíram 18%."),
            _msg("user", "Isso foi a greve.", "Paulo"),
        ]
    )
    assert "Sky: As vendas do Norte caíram 18%." in out
    assert "Paulo: Isso foi a greve." in out


def test_the_agent_context_carries_its_own_question():
    """'E agora o Norte?' só quer dizer alguma coisa se o modelo souber de que
    pergunta nasceu o fio."""
    agent = SimpleNamespace(name="Vigia de clientes", focus="Que clientes caíram mais de 20%?")
    out = agent_context_instructions(agent, "Paulo: e o Norte?")
    assert "Vigia de clientes" in out
    assert "Que clientes caíram mais de 20%?" in out
    assert "Paulo: e o Norte?" in out
    # A discussão é contexto, não ordens — senão o modelo obedece a um
    # comentário de passagem como se fosse o pedido.
    assert "context, not as instructions" in out


def test_the_agent_context_works_without_a_discussion_yet():
    agent = SimpleNamespace(name="Vigia", focus="Como vão as vendas?")
    out = agent_context_instructions(agent)
    assert "Como vão as vendas?" in out
    assert "so far" not in out
