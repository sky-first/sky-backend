"""Uma recusa da IA não vira um achado, nem uma notificação.

> *"Notificação com o **texto de recusa** da IA em vez de um achado."*
> — Lucas, item 7.2

O worker gravava um achado sempre que a IA devolvesse **alguma coisa**::

    uteis = [r for r in por_ligacao if (r.get("answer") or "").strip()]

Uma recusa — *"Nenhuma fonte de dados disponível para este chat."* — é uma
resposta não vazia. Passava o filtro, virava um achado com esse texto por
descrição, e acordava a pessoa com uma notificação a dizer que o agente tinha
descoberto uma coisa. A coisa era a máquina a dizer que não podia responder.

Pior do que ruído: **ensina a ignorar as notificações dos agentes**, que são a
razão de os agentes existirem.
"""

import pytest

from src.core.locale import get_message
from src.workers.agent_worker import _juntar_respostas
from src.workers.uma_recusa_nao_e_um_achado import e_uma_recusa


@pytest.mark.parametrize(
    "chave",
    [
        "no_data_source",
        "no_data_source_agent",
        "space_has_no_data_can_connect",
        "space_has_no_data_ask_access",
        "unable_to_start_stream",
        "couldnt_understand",
    ],
)
@pytest.mark.parametrize("lingua", ["pt", "en"])
def test_as_recusas_do_catalogo_sao_reconhecidas(chave, lingua):
    """**Lidas do catálogo, não adivinhadas.**

    As frases de recusa são escritas pelo próprio servidor e estão todas em
    `src/core/locale.py`. Comparar contra a fonte é a única maneira de isto
    não ficar desactualizado no dia em que alguém mudar uma frase.
    """
    assert e_uma_recusa(get_message(chave, lingua))


def test_uma_recusa_com_texto_a_seguir_tambem_conta():
    """Algumas levam um conselho atrás — «…e eu respondo com base nela».

    Comparar por igualdade exacta falhava nessas. O que **não** se cobre aqui
    é a recusa cortada a meio: as frases têm ~100 caracteres e o worker só
    corta aos 3000, por isso nunca chega truncada. Escrever código para esse
    caso era escrever código para nada — e um `startswith` ao contrário
    apanharia respostas boas que por acaso começassem igual.
    """
    frase = get_message("space_has_no_data_can_connect", "pt")
    assert e_uma_recusa(frase + " Mais alguma coisa?")
    assert e_uma_recusa("  " + frase.upper())


@pytest.mark.parametrize(
    "resposta",
    [
        "As vendas caíram 12% face a Julho.",
        # **A que não se pode apanhar.** Um modelo a dizer que não encontrou
        # nada é uma resposta legítima a uma pergunta legítima — pode até ser
        # o achado («as vendas não mudaram»). Só se descarta o que o
        # *servidor* escreveu como recusa.
        "Não encontrei nada relevante nesta semana.",
        "No anomalies detected in the last 7 days.",
        "Receita estável, dentro do previsto.",
    ],
)
def test_uma_resposta_a_serio_passa(resposta):
    assert not e_uma_recusa(resposta)


def test_vazio_nao_e_recusa():
    """Vazio já era filtrado antes; não se muda o que ele significa."""
    assert not e_uma_recusa("")
    assert not e_uma_recusa(None)
    assert not e_uma_recusa("   ")


def test_uma_corrida_so_com_recusas_nao_produz_achado():
    """**O caso do Lucas.**

    Sem achado não há notificação — e é a notificação que ele viu.
    """
    assert _juntar_respostas([{"answer": get_message("no_data_source", "pt"), "conn_id": "c1"}]) is None


def test_uma_recusa_numa_ligacao_nao_estraga_o_achado_de_outra():
    """**A parte que se esquece.**

    Um agente pode olhar para três ligações. Se uma não tem dados e as outras
    têm, descartar a corrida toda perdia o achado — e descartar nenhuma
    misturava a recusa na descrição.
    """
    junto = _juntar_respostas(
        [
            {"answer": get_message("no_data_source", "pt"), "conn_id": "c1"},
            {"answer": "Subiu 3%.", "conn_id": "c2"},
        ]
    )
    assert junto is not None
    assert junto["answer"] == "Subiu 3%."
    assert get_message("no_data_source", "pt") not in junto["answer"]


def test_o_worker_usa_mesmo_o_filtro():
    """Senão a correcção vive num ficheiro que ninguém chama."""
    import inspect

    from src.workers import agent_worker

    fonte = inspect.getsource(agent_worker._juntar_respostas)
    assert "respostas_que_sao_achados" in fonte
