# -*- coding: utf-8 -*-
"""Os dois motores de voz discordam sobre o `awscrt`.

── O conflito, e porque não é cosmético ────────────────────────────

    amazon-transcribe 0.6.3/0.6.4  ->  awscrt~=0.26.1
    smithy-http[awscrt]            ->  awscrt~=0.32.0

Do lado do Sonic é real: o `smithy_http.aio.crt` importa
`awscrt.aio.http`, um módulo que **não existe** no 0.26.1. Com o CRT
antigo o cliente morre a ser construído, e com uma mensagem enganadora —
«awscrt is not installed», quando está.

Do lado do Transcribe é conservadorismo do empacotador. **Medido:** com
`awscrt==0.37.0` ele faz uma transcrição em streaming de verdade contra
eu-west-1, em espanhol, e devolve o texto certo. Os dois convivem — só o
resolvedor do pip é que não deixa, porque lê o que está declarado e não
o que funciona.

Daí a separação: o `amazon-transcribe` sai do `requirements.txt` e passa
a instalar-se com `--no-deps` a partir do `requirements-voz.txt`.

── Porque isto é um teste e não só um comentário ───────────────────

Porque a tentação de arrumar é enorme. Uma linha solta num ficheiro à
parte parece desarrumação, e juntá-la de volta ao `requirements.txt`
parece limpeza — mas **a imagem deixa de construir**, ou pior,
reinstala-se o CRT antigo e a voz nova parte em produção com uma
mensagem que diz que falta uma coisa que lá está.

É também o contrapeso ao aviso que já existe no `ci-pr-gate.yml`: um
`pip install` sem versão depois do `requirements.txt` actualizou o
pytest e rebentou a recolha dos testes. Aqui o `--no-deps` torna esse
acidente impossível por construção, e o pino é exacto — mas só enquanto
os dois estiverem lá.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PEDIDOS = RAIZ / "requirements.txt"
PEDIDOS_VOZ = RAIZ / "requirements-voz.txt"
DOCKERFILE = RAIZ / "Dockerfile"
FLUXOS = RAIZ / ".github" / "workflows"


def _sem_comentarios(texto: str) -> str:
    return "\n".join(
        l for l in texto.splitlines() if not l.lstrip().startswith("#")
    )


class TestOndeCadaUmVive:
    def test_o_transcribe_esta_no_ficheiro_a_parte(self):
        assert PEDIDOS_VOZ.exists(), (
            "o requirements-voz.txt desapareceu — sem ele o pip não "
            "consegue resolver os dois motores de voz"
        )
        assert "amazon-transcribe" in _sem_comentarios(
            PEDIDOS_VOZ.read_text(encoding="utf-8")
        )

    def test_e_NAO_esta_no_requirements_normal(self):
        """O que parte a imagem se alguém "arrumar"."""
        assert "amazon-transcribe" not in _sem_comentarios(
            PEDIDOS.read_text(encoding="utf-8")
        ), (
            "o amazon-transcribe voltou ao requirements.txt — o pip vai "
            "dar ResolutionImpossible contra o awscrt do Nova Sonic. "
            "Ler o cabeçalho do requirements-voz.txt antes de mexer"
        )

    def test_e_esta_pinado_exactamente(self):
        """Sem versão, um dia instala-se outra coisa e ninguém sabe quando."""
        linhas = [
            l.strip()
            for l in _sem_comentarios(
                PEDIDOS_VOZ.read_text(encoding="utf-8")
            ).splitlines()
            if l.strip()
        ]
        soltas = [l for l in linhas if not re.match(r"^[\w.-]+==[\w.]+$", l)]
        assert not soltas, f"sem pino exacto: {soltas}"


class TestOCrtTemDeSerONovo:
    def test_o_awscrt_esta_pinado_acima_do_032(self):
        """O 0.26.1 não tem `awscrt.aio.http` e o Sonic não arranca."""
        texto = _sem_comentarios(PEDIDOS.read_text(encoding="utf-8"))
        m = re.search(r"^awscrt==(\d+)\.(\d+)\.", texto, re.M)
        assert m, "o awscrt saiu do requirements.txt"
        maior, menor = int(m.group(1)), int(m.group(2))
        assert (maior, menor) >= (0, 32), (
            f"awscrt {m.group(0)} é anterior ao 0.32 — o "
            "`smithy_http.aio.crt` importa `awscrt.aio.http`, que não "
            "existe nessas versões, e falha com a mensagem enganadora "
            "«awscrt is not installed»"
        )

    def test_e_o_sdk_do_sonic_esta_la(self):
        texto = _sem_comentarios(PEDIDOS.read_text(encoding="utf-8"))
        assert "aws-sdk-bedrock-runtime==" in texto, (
            "é o único SDK com InvokeModelWithBidirectionalStream; o "
            "boto3 não a tem"
        )


class TestQuemInstalaUsaNoDeps:
    """Três sítios instalam, e os três têm de passar `--no-deps`.

    Esquecer num deles dá uma avaria que só aparece nesse caminho — e o
    pior é o Dockerfile, porque só se nota em produção.
    """

    @pytest.mark.parametrize(
        "ficheiro",
        [
            DOCKERFILE,
            FLUXOS / "ci-pr-gate.yml",
            FLUXOS / "red-team-ai-regression.yml",
        ],
    )
    def test_instala_a_voz_sem_dependencias(self, ficheiro: Path):
        texto = ficheiro.read_text(encoding="utf-8")
        linhas = [
            l for l in texto.splitlines() if "requirements-voz.txt" in l
            and not l.lstrip().startswith("#")
        ]
        assert linhas, f"{ficheiro.name} não instala o requirements-voz.txt"
        sem_flag = [l for l in linhas if "pip install" in l and "--no-deps" not in l]
        assert not sem_flag, (
            f"{ficheiro.name} instala a voz SEM --no-deps: {sem_flag}. "
            "O pip vai tentar resolver o awscrt e recusa"
        )

    def test_o_dockerfile_copia_o_ficheiro(self):
        """Um `COPY` esquecido é um build que falha no último passo."""
        assert "requirements-voz.txt" in DOCKERFILE.read_text(
            encoding="utf-8"
        ).split("RUN pip install")[0], (
            "o requirements-voz.txt não é copiado antes de ser instalado"
        )
