"""O host `<slug>.skyfirstlabs.com` e o `custom_domain` passam a resolver.

Contexto, porque isto não é uma funcionalidade nova mas uma reparação:

O pipeline de provisionamento cria, para cada cliente, DNS + ingress +
certificado em ``<slug>.skyfirstlabs.com``. A aplicação nunca soube ler esse
formato — o regex de sub-domínio só aceitava ``workspace-<slug>.``,
``api-<slug>.`` ou ``<slug>-stg.``. Verificado em produção:
``sandbox.skyfirstlabs.com`` devolvia ``tenant_slug: null``. Estávamos a
provisionar infraestrutura inerte a cada cliente novo.

O ``custom_domain`` tinha o mesmo problema, pior: a coluna existe, a Console
grava-a, e nada no código alguma vez a lia. Quem a preenchesse ficava a
acreditar que tinha dado um endereço próprio ao cliente.

A armadilha que estes testes guardam
------------------------------------
A correcção óbvia era alargar o regex para ``<label>.<base>``. Isso **partia
produção**: um host sem linha no registo passaria a produzir um slug, e um
slug que não resolve devolve 404. ``grafana-prd``, ``auth-prd``, ``app`` —
todos os hosts da plataforma — deixariam de responder a quem ainda não
entrou. É o mesmo erro que o comentário do ``_RESERVED_SLUGS`` já avisava
para o caso do ``sky``, e que voltaria por outra porta.

Por isso a resolução é uma **consulta ao registo**, não um reconhecimento de
padrão: host desconhecido → ``None`` → contexto da plataforma, nunca 404. Os
testes de ``test_hosts_da_plataforma_nao_sao_clientes`` são os que falham no
dia em que alguém trocar isto por um regex.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import List, Optional
from uuid import uuid4

import pytest

from src.api.middleware import tenant_resolver as tr


def _linha(slug: str, *, custom_domain: Optional[str] = None, activa: bool = True):
    """Uma linha de ``tenant_registry`` com o mínimo que o resolvedor lê."""
    return SimpleNamespace(
        slug=slug,
        id=uuid4(),
        custom_domain=custom_domain,
        is_active=activa,
        display_name=slug,
        tier="starter",
        db_host=None,
        db_name=f"tenant_{slug}",
        db_credentials_secret_arn=None,
        redis_host=None,
        redis_credentials_secret_arn=None,
        bedrock_inference_profile_arn=None,
        rate_limit_rpm=None,
        rate_limit_tpm=None,
        feature_flags={},
        capacity_limits={},
        auth_methods={},
        sso_provider=None,
        logo_url=None,
    )


@pytest.fixture(autouse=True)
def _limpar_cache():
    tr.clear_tenant_cache()
    yield
    tr.clear_tenant_cache()


@pytest.fixture
def registo(monkeypatch):
    """Substitui a ida à base de dados por uma lista em memória.

    Devolve as linhas que satisfazem o mesmo critério que o SQL: o host bate
    certo com o ``custom_domain``, ou o primeiro rótulo bate certo com o slug.
    """
    linhas: List[SimpleNamespace] = []

    class _FakeResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return list(self._items)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            # Reproduz as MESMAS condições que o código monta. O rótulo só
            # conta quando `rotulo_candidato_a_slug` o aceita — usar aqui a
            # função real é o que impede este duplo de contornar a regra que
            # está a ser testada (foi o que aconteceu à primeira versão
            # deste ficheiro: dava verde a hosts que deviam ser recusados).
            host = _FakeSession.host_actual
            rotulo = tr.rotulo_candidato_a_slug(host)
            achadas = [
                r
                for r in linhas
                if (r.custom_domain or "").lower() == host
                or (rotulo is not None and r.slug == rotulo)
            ]
            return _FakeResult(achadas)

    def _sessao():
        return _FakeSession()

    monkeypatch.setattr(tr, "AsyncSessionLocal", _sessao)

    # O host tem de chegar ao fake; o `select()` real não é inspeccionável
    # aqui sem acoplar o teste ao SQL gerado, o que o tornaria frágil.
    original = tr._tenant_from_host_registry

    async def _envolvido(host_header):
        _FakeSession.host_actual = (host_header or "").split(":")[0].lower()
        return await original(host_header)

    monkeypatch.setattr(tr, "_tenant_from_host_registry", _envolvido)
    return linhas


async def _resolve(host: str):
    return await tr._tenant_from_host_registry(host)


# ─── O que passa a funcionar ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_subdominio_simples_resolve_o_cliente(registo):
    registo.append(_linha("gbt"))
    ctx = await _resolve("gbt.skyfirstlabs.com")
    assert ctx is not None and ctx.slug == "gbt"


@pytest.mark.asyncio
async def test_o_dominio_proprio_do_cliente_resolve(registo):
    """A coluna que a Console gravava e ninguém lia."""
    registo.append(_linha("gbt", custom_domain="sky.gbtsolutions.pt"))
    ctx = await _resolve("sky.gbtsolutions.pt")
    assert ctx is not None and ctx.slug == "gbt"


@pytest.mark.asyncio
async def test_a_porta_e_maiusculas_nao_atrapalham(registo):
    registo.append(_linha("gbt"))
    ctx = await _resolve("GBT.SkyFirstLabs.com:8443")
    assert ctx is not None and ctx.slug == "gbt"


# ─── O que NÃO pode acontecer ─────────────────────────────────────────
@pytest.mark.parametrize(
    "host",
    [
        "app.skyfirstlabs.com",
        "console.skyfirstlabs.com",
        "api.skyfirstlabs.com",
        "demo.skyfirstlabs.com",
        "grafana-prd.skyfirstlabs.com",
        "auth-prd.skyfirstlabs.com",
        "prometheus-prd.skyfirstlabs.com",
        "alertmanager-prd.skyfirstlabs.com",
    ],
)
@pytest.mark.asyncio
async def test_hosts_da_plataforma_nao_sao_clientes(registo, host):
    """Nenhum destes tem linha no registo — e nenhum pode dar 404.

    Este é o teste que falha se alguém trocar a consulta por um regex.
    Com um regex, ``grafana-prd`` viraria um slug, o slug não resolveria, e
    o middleware devolveria 404 a quem só queria ver o login.
    """
    registo.append(_linha("gbt"))
    assert await _resolve(host) is None


@pytest.mark.asyncio
async def test_o_tenant_semente_sky_continua_a_nao_resolver(registo):
    """``sky`` existe no registo, aponta para a base da plataforma.

    Se resolvesse, ``sky-prd.skyfirstlabs.com`` mandava toda a gente para uma
    base cujo segredo o IAM nem consegue ler. Está na lista de reservados
    precisamente por isso.
    """
    registo.append(_linha("sky"))
    assert await _resolve("sky.skyfirstlabs.com") is None


@pytest.mark.asyncio
async def test_dominio_de_terceiros_nao_escolhe_cliente(registo):
    """``gbt.dominio-qualquer.com`` apontado ao nosso ingress não serve a GBT.

    Sem esta regra, bastava a qualquer pessoa apontar um CNAME ao nosso
    balanceador e escolher o cliente que quisesse pelo primeiro rótulo.
    """
    registo.append(_linha("gbt"))
    assert await _resolve("gbt.dominio-de-terceiros.com") is None


@pytest.mark.asyncio
async def test_cliente_suspenso_nao_resolve(registo):
    registo.append(_linha("gbt", activa=False))
    assert await _resolve("gbt.skyfirstlabs.com") is None


@pytest.mark.asyncio
async def test_host_sem_ponto_nao_resolve(registo):
    registo.append(_linha("localhost"))
    assert await _resolve("localhost") is None


# ─── Precedência e cache ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dominio_proprio_ganha_ao_rotulo(registo):
    """Dois clientes podem colidir: um chama-se ``gbt``, outro declarou
    ``gbt.skyfirstlabs.com`` como domínio próprio. O declarado ganha —
    é o mais explícito dos dois."""
    registo.append(_linha("gbt"))
    registo.append(_linha("outro", custom_domain="gbt.skyfirstlabs.com"))
    ctx = await _resolve("gbt.skyfirstlabs.com")
    assert ctx is not None and ctx.slug == "outro"


@pytest.mark.asyncio
async def test_a_resposta_negativa_tambem_e_cacheada(registo, monkeypatch):
    """Senão cada pedido a ``app.`` pagava uma consulta à base de dados.

    A plataforma serve os seus próprios hosts em todos os pedidos de quem
    ainda não entrou; é o caminho mais quente que existe.
    """
    idas = {"n": 0}
    original = tr.AsyncSessionLocal

    def _contando():
        idas["n"] += 1
        return original()

    monkeypatch.setattr(tr, "AsyncSessionLocal", _contando)

    await _resolve("app.skyfirstlabs.com")
    await _resolve("app.skyfirstlabs.com")
    await _resolve("app.skyfirstlabs.com")
    assert idas["n"] == 1
