"""Todo o modelo que uma rota lê tem de ter migração que crie a tabela.

Encontrado a varrer as leituras em produção com as três contas de teste:

    GET /api/v1/settings/api-keys      -> 500  (owner, admin e member)
    GET /api/v1/settings/integrations  -> 500  (owner, admin e member)

Modelo, rota e serviço existiam. A migração é que nunca foi escrita. Dois
ecrãs das Definições em erro para toda a gente, desde sempre, escondidos
atrás do mesmo 500 genérico que escondia o `embeddings` na semana passada.

Este teste compara os `__tablename__` dos modelos com os `create_table` das
migrações. É grosseiro de propósito — lê texto, não corre alembic — porque o
que interessa é falhar no CI quando alguém acrescenta um modelo e se esquece
da migração, que foi exactamente o que aconteceu aqui.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MODELOS = RAIZ / "src" / "models"
MIGRACOES = RAIZ / "migrations" / "versions"

#: Tabelas que o varrimento acusa mas que existem de facto — criadas por
#: migrações que não usam `create_table` com o nome literal (renomeações,
#: SQL cru). Cada entrada tem de dizer PORQUÊ, senão esta lista transforma-se
#: no sítio onde os defeitos se escondem.
CONHECIDAS_E_EXISTENTES = {
    # `a3f2c1d0e9b8_rename_planets_to_pages.py` renomeia `planets` -> `pages`;
    # nunca há um `create_table("pages")`. Confirmado vivo: GET /pages -> 200.
    "pages",
    "page_members",
    "page_build_jobs",
}


def _tabelas_dos_modelos() -> set[str]:
    nomes: set[str] = set()
    for f in MODELOS.rglob("*.py"):
        nomes |= set(
            re.findall(
                r'__tablename__\s*=\s*["\']([a-z0-9_]+)["\']',
                f.read_text(encoding="utf-8"),
            )
        )
    return nomes


def _tabelas_criadas() -> set[str]:
    nomes: set[str] = set()
    for f in MIGRACOES.glob("*.py"):
        fonte = f.read_text(encoding="utf-8")
        nomes |= set(re.findall(r'create_table\(\s*["\']([a-z0-9_]+)["\']', fonte))
        nomes |= set(
            re.findall(
                r'CREATE TABLE (?:IF NOT EXISTS )?["\']?([a-z0-9_]+)', fonte, re.I
            )
        )
    return nomes


def test_nenhum_modelo_fica_sem_tabela():
    faltam = _tabelas_dos_modelos() - _tabelas_criadas() - CONHECIDAS_E_EXISTENTES
    assert faltam == set(), (
        "estes modelos não têm migração que crie a tabela — qualquer rota que "
        f"os leia devolve 500: {sorted(faltam)}"
    )


def test_api_keys_e_integrations_passaram_a_ter_migracao():
    """As duas concretas, nomeadas.

    Sem isto, alguém que alargasse `CONHECIDAS_E_EXISTENTES` fazia o teste
    acima passar sem resolver nada.
    """
    criadas = _tabelas_criadas()
    assert "api_keys" in criadas
    assert "integrations" in criadas


def test_a_lista_de_excepcoes_nao_cresce_a_esmo():
    """Uma excepção sem razão escrita é um defeito por descobrir."""
    fonte = Path(__file__).read_text(encoding="utf-8")
    bloco = fonte[fonte.index("CONHECIDAS_E_EXISTENTES = {") :]
    bloco = bloco[: bloco.index("}")]
    assert "#" in bloco, "cada excepção tem de trazer a razão por que existe"
    assert len(CONHECIDAS_E_EXISTENTES) <= 5, (
        "a lista de excepções está a crescer — provavelmente estão a esconder-se "
        "defeitos reais lá dentro"
    )
