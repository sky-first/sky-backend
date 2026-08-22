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


# ─── Uma pergunta, uma resposta ──────────────────────────────────────────────
#
# O worker gravava um `AgentFinding` POR LIGAÇÃO de dados. Um agente é uma
# pergunta só: varrer três ligações para lhe responder é o caminho até à
# resposta, não três descobertas. No feed saíam três cartões para uma pergunta.
#
# Pior: a mensagem escrita no fio era UMA — a da última ligação, porque tanto o
# texto como o id do achado eram reatribuídos a cada volta do ciclo. As outras
# ficavam gravadas e sem conversa nenhuma, impossíveis de abrir num produto
# onde uma descoberta É uma conversa.

from src.workers.agent_worker import _juntar_respostas


def _r(**kw):
    base = {
        "conn_id": "c1",
        "answer": "As vendas subiram 12%.",
        "title": "Vendas",
        "viz_kind": "line",
        "rows": None,
        "table_ids": None,
    }
    base.update(kw)
    return base


def test_uma_ligacao_passa_intacta():
    """O caso normal — e é por isto que a mudança não mexe na maioria dos
    agentes: com uma ligação, sai exactamente o que ela disse."""
    out = _juntar_respostas([_r(rows={"columns": ["a"], "data": [[1]]})])
    assert out["answer"] == "As vendas subiram 12%."
    assert out["title"] == "Vendas"
    assert out["rows"] == {"columns": ["a"], "data": [[1]]}


def test_varias_ligacoes_dao_UMA_resposta():
    out = _juntar_respostas(
        [
            _r(conn_id="c1", title="Norte", answer="Subiu 12%."),
            _r(conn_id="c2", title="Sul", answer="Desceu 3%."),
        ]
    )
    assert "Subiu 12%." in out["answer"]
    assert "Desceu 3%." in out["answer"]


def test_cada_parte_diz_de_onde_veio():
    """Sem isto, as duas metades lêem-se como um parágrafo só que se
    contradiz a meio — «subiu 12%» seguido de «desceu 3%»."""
    out = _juntar_respostas(
        [
            _r(conn_id="c1", title="Norte", answer="Subiu 12%."),
            _r(conn_id="c2", title="Sul", answer="Desceu 3%."),
        ]
    )
    assert "**Norte**" in out["answer"]
    assert "**Sul**" in out["answer"]


def test_o_grafico_vem_de_UMA_ligacao_e_nao_de_todas():
    """Um gráfico feito de linhas de três bases diferentes não quer dizer
    nada. Vem da primeira que traga linhas."""
    linhas = {"columns": ["mes"], "data": [["jan"]]}
    out = _juntar_respostas(
        [
            _r(conn_id="c1", title="Sem dados", rows=None, viz_kind="text"),
            _r(conn_id="c2", title="Com dados", rows=linhas, viz_kind="bar"),
        ]
    )
    assert out["rows"] == linhas
    assert out["viz_kind"] == "bar"
    assert out["conn_id"] == "c2"


def test_ligacoes_caladas_nao_contam():
    """Uma ligação que não respondeu não pode ocupar espaço na resposta com
    um cabeçalho vazio por baixo."""
    out = _juntar_respostas([_r(answer=""), _r(conn_id="c2", answer="   ")])
    assert out is None


def test_uma_calada_no_meio_nao_estraga_as_outras():
    out = _juntar_respostas(
        [_r(conn_id="c1", answer=""), _r(conn_id="c2", title="Sul", answer="Desceu 3%.")]
    )
    # Sobrou uma só — portanto passa intacta, sem cabeçalho a mais.
    assert out["answer"] == "Desceu 3%."


def test_a_mesma_tabela_por_duas_ligacoes_conta_uma_vez():
    """Listá-la duas vezes só faz a origem parecer maior do que é."""
    out = _juntar_respostas(
        [
            _r(conn_id="c1", table_ids=["vendas", "clientes"]),
            _r(conn_id="c2", table_ids=["clientes", "stock"]),
        ]
    )
    assert out["data_sources"] == ["vendas", "clientes", "stock"]


def test_sem_ligacao_nenhuma_nao_ha_achado():
    assert _juntar_respostas([]) is None


def _linhas_do_worker() -> str:
    """A fonte do worker sem comentários.

    Sem eles porque os comentários que explicam estas avarias citam os nomes
    das variáveis e as condições — e o guarda apanhava-se a si próprio.
    """
    import inspect

    from src.workers import agent_worker

    return "\n".join(
        l
        for l in inspect.getsource(agent_worker).splitlines()
        if not l.lstrip().startswith("#")
    )


# ─── Uma corrida sem nenhuma resposta não é uma corrida bem sucedida ─────────
#
# Visto em produção a 22/08/2026: o serviço de IA devolvia 404 a todas as
# ligações do agente — não tinha metadados — e a execução ficava `completed`,
# sem `error_message` e com zero achados. Do lado da app isso lê-se como
# «correu e não encontrou nada», que é uma frase tranquilizadora para dizer
# que nem uma consulta chegou a ser feita.
#
# É o mesmo silêncio que fez ninguém reparar, durante meses, que nenhum agente
# corria: o `/run` respondia 200 e a app dizia que aquilo corria em segundo
# plano.


def test_todas_as_ligacoes_falhadas_marcam_a_corrida_como_falhada():
    fonte = _linhas_do_worker()
    assert 'if ligacoes_falhadas and not respostas_por_ligacao:' in fonte
    assert 'execution.status = "failed"' in fonte


def test_uma_ligacao_que_respondeu_salva_a_corrida():
    """Só quando falham TODAS.

    Se uma respondeu, houve resposta — marcar a corrida como falhada por causa
    de outra seria enganar ao contrário, e um agente com uma fonte partida de
    três passaria a parecer avariado.
    """
    fonte = _linhas_do_worker()
    i = fonte.index("if ligacoes_falhadas and not respostas_por_ligacao:")
    # A condição exige as duas coisas na mesma linha: falhas E nenhuma
    # resposta. Um `if ligacoes_falhadas:` sozinho seria o outro extremo.
    assert "and not respostas_por_ligacao" in fonte[i : i + 120]


def test_a_razao_da_falha_fica_gravada():
    """Sem a razão, o ecrã diz «falhou» e mais nada — que é melhor do que
    mentir, mas não chega para alguém agir."""
    fonte = _linhas_do_worker()
    assert "execution.error_message" in fonte
    assert "ligacoes_falhadas.append((conn_id" in fonte
