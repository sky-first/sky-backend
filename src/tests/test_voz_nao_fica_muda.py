"""Uma falha a meio de um turno de voz não pode deixar a sessão muda.

**O que aconteceu.** A 26/08 o `_voice_answer` ganhou um parâmetro
(`space_id`) e passou a ser chamado com seis argumentos posicionais. O duplo
do `test_be07_voice_ws` tinha cinco. `TypeError`.

O que se seguiu é que interessa: **não houve erro nenhum**. O `do_turn` tinha
`try/finally` sem `except`, a excepção subia, e a sessão ficava calada — do
lado de lá, um telemóvel com o microfone aberto e nada a acontecer, sem aviso
e sem fim. O teste não falhou: ficou à espera de tramas que nunca chegavam, e
a suíte inteira encravou nele durante um dia.

A causa imediata era a assinatura. **A causa que importa é o silêncio**: o
mesmo aconteceria com o motor em baixo, com uma resposta vazia, ou com
qualquer erro dentro de um turno. É isso que estes testes fixam.
"""

import inspect

from src.api.v1 import voice


def test_o_turno_apanha_as_falhas():
    """Sem `except`, um erro no meio do turno cala a sessão para sempre."""
    fonte = inspect.getsource(voice.voice_session_ws)
    i = fonte.index("async def do_turn")
    corpo = fonte[i : fonte.index("async def consume_transcripts", i)]
    assert "except Exception:" in corpo, (
        "o `do_turn` voltou a não apanhar falhas — qualquer erro deixa o "
        "telemóvel com o microfone aberto e nada a acontecer"
    )


def test_e_avisa_quem_esta_do_outro_lado():
    """Falhar em silêncio e falhar a dizer que falhou não são a mesma coisa."""
    fonte = inspect.getsource(voice.voice_session_ws)
    i = fonte.index("async def do_turn")
    corpo = fonte[i : fonte.index("async def consume_transcripts", i)]
    assert '"turn_failed"' in corpo


def test_e_devolve_a_palavra_ao_utilizador():
    """**A parte que se esquece.**

    Dizer que correu mal e ficar à espera é quase tão mau como não dizer: a
    sessão está viva e inútil. Tem de voltar a ouvir.
    """
    fonte = inspect.getsource(voice.voice_session_ws)
    i = fonte.index("async def do_turn")
    corpo = fonte[i : fonte.index("async def consume_transcripts", i)]
    depois_do_except = corpo[corpo.index("except Exception:") :]
    assert 'state("user_speaking")' in depois_do_except
    assert "restart_stt" in depois_do_except


def test_o_space_id_vai_por_nome_e_nao_por_posicao():
    """Um argumento novo passado por posição parte todos os duplos antigos.

    E parte-os de uma maneira que não se vê: `TypeError` dentro de um turno
    era silêncio, não erro.
    """
    fonte = inspect.getsource(voice.voice_session_ws)
    assert "space_id=space_id" in fonte
    assert "ctx, locale, space_id)" not in fonte


def test_todos_os_duplos_do_voice_answer_seguem_a_assinatura():
    """**O guarda que faltava.**

    O `space_id` partiu **dois** duplos, em ficheiros diferentes, e os dois da
    mesma maneira: `TypeError` dentro de um turno, que é silêncio e não erro.
    O segundo só apareceu horas depois do primeiro, porque a suíte encravava
    antes de lá chegar.

    Um duplo de uma função tem de aceitar o que ela aceita — senão não
    protege nada, esconde.
    """
    import re
    from pathlib import Path

    reais = set(inspect.signature(voice._voice_answer).parameters)
    pasta = Path(__file__).parent
    maus: list[str] = []

    for ficheiro in pasta.glob("test_*.py"):
        fonte = ficheiro.read_text(encoding="utf-8")
        if "_voice_answer" not in fonte:
            continue
        # `async def <nome>(...)` imediatamente antes de o remendo o usar.
        for m in re.finditer(r"async def (\w+)\(([^)]*)\)", fonte):
            nome, params = m.group(1), m.group(2)
            if f'"src.api.v1.voice._voice_answer", {nome}' not in fonte:
                continue
            declarados = {p.split(":")[0].split("=")[0].strip() for p in params.split(",") if p.strip()}
            faltam = reais - declarados
            if faltam:
                maus.append(f"{ficheiro.name}:{nome} não aceita {sorted(faltam)}")

    assert maus == [], (
        "estes duplos não seguem a assinatura do `_voice_answer` — um turno "
        f"com eles rebenta em silêncio: {maus}"
    )


def test_a_assinatura_tem_mesmo_o_space_id():
    """Se o parâmetro desaparecer, os testes acima passam a guardar nada."""
    params = inspect.signature(voice._voice_answer).parameters
    assert "space_id" in params
    assert params["space_id"].default is None
