"""As mensagens que chegam ao utilizador tratam-no por você.

O frontend e a app já tinham guarda para isto; o backend não, e por isso
escapou-lhe *"Não podes decidir pedidos de acesso."* — que eu próprio escrevi
há dois dias. Só apareceu ao ler os registos de produção, três chamadas
depois de alguém ter batido nessa recusa.

A lista de palavras é fechada de propósito. Apanhar toda a 2.ª pessoa por
morfologia dava falsos positivos a rodos: `precisas` é adjectivo em "consultas
precisas contra os seus dados".
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

INFORMAL = re.compile(
    r"\b(podes|queres|tens|fazes|vais|estás|contigo|teu|tua|teus|tuas)\b",
    re.IGNORECASE,
)

#: Onde o tratamento informal é legítimo. Cada entrada com a sua razão — uma
#: isenção sem razão escrita é um defeito à espera de se esconder.
FICHEIROS_ISENTOS = {
    # Lista de palavras portuguesas comuns, usada para adivinhar a língua de
    # um texto. Não é copy que chegue a ninguém.
    "services/demo_domain_gate.py",
}


def _mensagens_de(caminho: Path) -> list[str]:
    """As strings do ficheiro que parecem mensagens para pessoas.

    Comentários ficam de fora: um comentário que **cita** a frase errada para
    explicar porque é errada não é uma mensagem para ninguém. Sem isto o teste
    acusava as próprias explicações que documentam a correcção — e passava a
    exigir que se apagasse a explicação, que é o oposto do que se quer.
    """
    linhas = [
        linha
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if not linha.lstrip().startswith("#")
    ]
    fonte = "\n".join(linhas)
    # Só strings com espaços e acentuação portuguesa — o resto são chaves,
    # nomes de campos e SQL.
    return [
        m
        for m in re.findall(r'"([^"\n]{12,})"', fonte)
        if " " in m and re.search(r"[áàâãéêíóôõúç]", m, re.IGNORECASE)
    ]


def test_nenhuma_mensagem_trata_o_utilizador_por_tu():
    encontradas: list[str] = []
    for f in RAIZ.rglob("*.py"):
        rel = str(f.relative_to(RAIZ)).replace("\\", "/")
        if "tests" in f.parts or rel in FICHEIROS_ISENTOS:
            continue
        for m in _mensagens_de(f):
            if INFORMAL.search(m):
                encontradas.append(f"{rel}: {m}")
    assert encontradas == [], (
        "estas mensagens tratam a pessoa por tu, ao contrário do resto do "
        f"produto: {encontradas}"
    )


def test_um_comentario_que_cita_a_frase_errada_nao_conta():
    """A afinação que foi precisa, guardada."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write('# dizia "Nao podes decidir pedidos" e estava errado\n')
        f.write('MENSAGEM = "Não pode decidir pedidos de acesso."\n')
        caminho = Path(f.name)
    try:
        assert [m for m in _mensagens_de(caminho) if INFORMAL.search(m)] == []
    finally:
        caminho.unlink()


def test_o_detector_apanha_de_facto():
    """Sem esta guarda, um regex partido fazia o teste acima passar sempre."""
    assert INFORMAL.search("Não podes decidir pedidos de acesso.")
    assert INFORMAL.search("O teu pedido foi enviado.")
    assert not INFORMAL.search("Não pode decidir pedidos de acesso.")
    assert not INFORMAL.search("O seu pedido foi enviado.")
    # E o falso positivo conhecido continua a passar.
    assert not INFORMAL.search("Consultas precisas contra os seus dados.")
