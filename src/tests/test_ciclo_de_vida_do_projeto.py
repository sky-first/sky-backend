"""Arquivar, sair, duplicar, apagar — os gestos que faltavam.

Casos 10 a 13 de ``docs/pessoas-equipas-e-projetos.md`` §6.

Um projeto de teste que não se pode tirar da frente polui a lista para sempre.
Não havia arquivar, não havia sair, não havia duplicar, e apagar não tinha
travão nenhum — ao lado de arquivar, num telemóvel.
"""

import uuid

import pytest

from src.core.exceptions import BadRequestError


class _Espaco:
    def __init__(self, nome, criador):
        self.id = uuid.uuid4()
        self.name = nome
        self.description = None
        self.created_by = criador
        self.archived_at = None
        self.deleted_at = None
        self.is_demo = False


@pytest.mark.asyncio
async def test_11_apagar_exige_o_nome_escrito():
    """**O travão que impede apagar por engano.**

    «Apagar» fica ao lado de «Arquivar». Um toque a mais leva um projeto
    inteiro com os seus dados e conversas. Escrever o nome obriga a ler o que
    se está a apagar — é o mesmo travão do GitHub, e funciona.
    """
    from src.services.space_service import SpaceService

    dono = uuid.uuid4()
    espaco = _Espaco("Finanças", dono)

    s = SpaceService.__new__(SpaceService)

    async def _get(_id):
        return espaco

    s.space_repo = type("R", (), {"get_by_id": staticmethod(_get)})()

    async def _sem_travao(*a, **k):
        return None

    s._require_space_role = _sem_travao

    utilizador = type("U", (), {"id": dono, "role": "admin"})()

    with pytest.raises(BadRequestError) as erro:
        await s.delete_space(espaco.id, utilizador, confirmacao="Financas")
    assert "exactly" in str(erro.value)

    # O nome certo passa do travão — o resto do apagar não é o objecto deste
    # teste, e falha a seguir por falta de base. O que importa é que **chegou
    # lá**: o travão deixou passar.
    with pytest.raises(Exception) as outro:
        await s.delete_space(espaco.id, utilizador, confirmacao="  Finanças  ")
    assert not isinstance(outro.value, BadRequestError)


@pytest.mark.asyncio
async def test_apagar_sem_confirmacao_mantem_o_comportamento_antigo():
    """Os chamadores internos — limpeza de demo, testes — não sabem do travão.

    `confirmacao=None` não valida nada. Se validasse, a limpeza automática
    passaria a falhar em silêncio e ninguém daria por isso durante semanas.
    """
    from src.services.space_service import SpaceService

    dono = uuid.uuid4()
    espaco = _Espaco("Qualquer", dono)
    s = SpaceService.__new__(SpaceService)

    async def _get(_id):
        return espaco

    s.space_repo = type("R", (), {"get_by_id": staticmethod(_get)})()

    async def _sem_travao(*a, **k):
        return None

    s._require_space_role = _sem_travao
    utilizador = type("U", (), {"id": dono, "role": "admin"})()

    with pytest.raises(Exception) as erro:
        await s.delete_space(espaco.id, utilizador)
    assert not isinstance(erro.value, BadRequestError)


def test_o_documento_e_o_codigo_dizem_o_mesmo():
    """As regras do §4.3 têm de existir em código, e não só no documento.

    Um documento que descreve gestos que ninguém implementou é pior do que
    nenhum: dá a sensação de que está feito.
    """
    import inspect

    from src.services.space_service import SpaceService

    for gesto in ("arquivar", "sair", "duplicar"):
        assert hasattr(SpaceService, gesto), f"falta o gesto: {gesto}"

    # Arquivar pausa os agentes — é a parte que se esquece, e é a que custa
    # dinheiro: um projeto arquivado a correr agentes é uma fatura que
    # ninguém percebe.
    assert "paused" in inspect.getsource(SpaceService.arquivar)

    # O último dono não sai.
    assert "only owner" in inspect.getsource(SpaceService.sair)

    # Duplicar não leva conversas, e respeita a permissão de ligar dados.
    fonte = inspect.getsource(SpaceService.duplicar)
    assert "connections.edit" in fonte
    assert "conversation" not in fonte.lower()
