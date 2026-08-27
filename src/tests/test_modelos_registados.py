"""Cada modelo está registado em ``src/models/__init__.py``.

**O defeito, e porque é silencioso.** `SpaceCrew` foi escrito a 26/08 e nunca
passou pelo `__init__`. Em produção não se nota: a tabela existe porque a
migração a cria. Nos testes nota-se, mas tarde e mal — o esquema é construído
a partir do `Base.metadata`, que só conhece os modelos **importados**, e a
tabela simplesmente não nascia:

    sqlite3.OperationalError: no such table: space_crews

Apareceu em dois testes de autorização que não têm nada a ver com o assunto —
`test_criar_projeto_nao_abre_os_dados` e `test_space_crew_default` — porque
foram os primeiros a ler os acessos. A mensagem culpa a base; a causa está a
três ficheiros de distância.

Este teste fecha a porta: qualquer modelo novo tem de ser importado no
`__init__`, ou isto falha a dizer o nome dele.
"""

import importlib
import pkgutil

import src.models


def _classes_de_modelo(modulo):
    """As classes de tabela declaradas num módulo (e não as importadas)."""
    from src.config.database import Base

    return {
        nome: obj
        for nome, obj in vars(modulo).items()
        if isinstance(obj, type)
        and issubclass(obj, Base)
        and obj is not Base
        and getattr(obj, "__tablename__", None)
        and obj.__module__ == modulo.__name__
    }


def test_o_varrimento_encontra_modelos():
    """Sem esta âncora, um erro na análise aprovava tudo em silêncio."""
    encontrados = 0
    for info in pkgutil.iter_modules(src.models.__path__):
        modulo = importlib.import_module(f"src.models.{info.name}")
        encontrados += len(_classes_de_modelo(modulo))
    assert encontrados > 20


#: Modelos que **já estavam** por registar quando este teste nasceu (26/08).
#:
#: Não se registaram todos de uma vez de propósito: acrescentá-los muda o
#: `Base.metadata` de **toda** a suíte — passam a nascer catorze tabelas que
#: hoje não nascem — e a suíte completa não corre nesta máquina (encrava no
#: Windows, ver a nota em `docs/`). Mexer num esquema que não se consegue
#: verificar inteiro é trocar um defeito conhecido por um desconhecido.
#:
#: A lista fica aqui, à vista, para se fechar com calma. O que importa é que
#: **não cresce**: um modelo novo que não passe pelo `__init__` faz este teste
#: falhar com o nome dele.
#: **Sete destes foram pagos a 27/08** — e não por arrumação. O
#: `tenant_membership` não estava registado, logo a tabela não nascia do
#: `create_all`; o login com cliente resolvido rebentava com
#: `relation "tenant_membership" does not exist`. Ao registá-lo,
#: registaram-se os outros seis que estavam no mesmo caso.
#:
#: Os que ficam são de módulos que ninguém importa hoje. Continuam aqui
#: nomeados para que a lista diga a verdade — e o teste abaixo garante que
#: diz: se alguém registar um deles e se esquecer de o tirar, falha.
DIVIDA = {
    "demo_content": ["DemoEvent"],
    "file": ["SyncLog"],
    "internal_console": [
        "ProvisioningJobEvent",
        "ConsoleSupportTicket",
        "ConsoleImpersonationSession",
    ],
    "permission": ["TableMemberPermission", "RolePermission"],
}


def test_nenhum_modelo_NOVO_fica_por_registar():
    """**O que falta aqui não existe para os testes.**

    E não existir para os testes quer dizer: a suíte constrói um esquema
    incompleto, e o erro aparece longe, noutro ficheiro, a culpar a base —
    `no such table: space_crews` num teste de autorização.
    """
    registados = set(vars(src.models))
    em_falta: dict[str, list[str]] = {}

    for info in pkgutil.iter_modules(src.models.__path__):
        modulo = importlib.import_module(f"src.models.{info.name}")
        conhecidos = set(DIVIDA.get(info.name, ()))
        faltam = [
            n for n in _classes_de_modelo(modulo) if n not in registados and n not in conhecidos
        ]
        if faltam:
            em_falta[info.name] = faltam

    assert em_falta == {}, (
        "estes modelos não estão importados em src/models/__init__.py — a "
        f"tabela deles não nasce nos testes: {em_falta}"
    )


def test_a_divida_nao_cresce_e_e_verdadeira():
    """A lista de dispensas tem de dizer a verdade.

    Se alguém registar um deles e esquecer de o tirar daqui, a lista deixa de
    descrever o que se passa — e uma lista que mente é pior do que não haver
    lista nenhuma.
    """
    registados = set(vars(src.models))
    ja_registados = {
        modulo: [n for n in nomes if n in registados] for modulo, nomes in DIVIDA.items()
    }
    sobra = {m: n for m, n in ja_registados.items() if n}
    assert sobra == {}, f"já não são dívida — tirar da lista: {sobra}"
    # Eram 14 a 26/08; são 7 desde que os sete se registaram. O tecto desce
    # com a dívida — senão deixa de ser um tecto e passa a ser um sofá.
    assert sum(len(v) for v in DIVIDA.values()) <= 7


def test_o_space_crew_esta_la():
    """O caso concreto, nomeado, para não se perder no teste geral acima."""
    assert hasattr(src.models, "SpaceCrew")
    assert hasattr(src.models, "ConviteAoProjeto")
