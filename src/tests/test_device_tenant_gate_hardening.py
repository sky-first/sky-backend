"""O portão de tenant de dispositivo não pode ter saída de emergência.

Dois buracos fechados aqui, ambos encontrados a rever o PR do mobile:

1. ``enforce_device_tenant`` decidia "isto é um pedido web" olhando para
   o header ``X-Tenant-Slug``. Bastava um cliente móvel enviá-lo para
   saltar o portão inteiro — e com ele a garantia de off-boarding
   (T-01.8), que é a única razão de o portão existir.

2. ``POST /ai/scan-insights/notify`` estava guardado por
   ``get_current_user``. O ``space_id`` vem no corpo do pedido, portanto
   qualquer funcionário autenticado podia forjar um insight num espaço
   a que não tem acesso — e a app apresenta-o como apurado pela AI.

Nenhum dos dois atravessava a fronteira entre clientes: a sessão é
scoped ao tenant, o utilizador não existe na base do outro cliente, e o
pedido morre em 401. São falhas de promessa e de integridade, não de
isolamento — e continuam a ser falhas.
"""

from __future__ import annotations

import pytest

from src.api.deps import SERVICE_CLAIM
from src.core.device_tenant import (
    TENANT_CLAIM,
    DeviceResolution,
    resolve_device_tenant,
)

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


class _Ctx:
    def __init__(self, tid):
        self.id = tid
        self.slug = "acme"
        self.is_default = False


async def _load_ok(tid):
    return _Ctx(tid)


async def _load_none(_tid):
    return None


# ─── a política em si ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_membro_passa():
    async def is_member(_u, _t):
        return True

    result = await resolve_device_tenant(
        {"sub": "u1", TENANT_CLAIM: TENANT_A},
        load_tenant_by_id=_load_ok,
        is_member=is_member,
    )

    assert result.resolution is DeviceResolution.RESOLVED


@pytest.mark.asyncio
async def test_token_valido_de_quem_ja_saiu_e_recusado():
    """A garantia central: sair da empresa tira o acesso no momento em
    que a linha de pertença desaparece, não quando o token expira."""

    async def is_member(_u, _t):
        return False

    result = await resolve_device_tenant(
        {"sub": "u1", TENANT_CLAIM: TENANT_A},
        load_tenant_by_id=_load_ok,
        is_member=is_member,
    )

    assert result.resolution is DeviceResolution.FORBIDDEN


@pytest.mark.asyncio
async def test_tenant_desconhecido_nao_cai_no_default():
    """Nunca resolver para o tenant por omissão — seria dar acesso ao
    espaço errado em vez de recusar."""

    async def is_member(_u, _t):
        return True

    result = await resolve_device_tenant(
        {"sub": "u1", TENANT_CLAIM: TENANT_B},
        load_tenant_by_id=_load_none,
        is_member=is_member,
    )

    assert result.resolution is DeviceResolution.UNRESOLVED


# ─── a fuga pelo header ─────────────────────────────────────────────


def _source():
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1].joinpath("api", "deps.py").read_text(encoding="utf-8")
    )


def _code_only(text: str) -> str:
    """O corpo executável, sem comentários.

    Os testes abaixo leem código-fonte, e a primeira versão falhou
    contra o comentário que explica a própria correcção. Um teste que
    lê prosa em vez de código mede a coisa errada.
    """
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0]
        if stripped.strip():
            out.append(stripped)
    return "\n".join(out)


def test_token_com_tid_e_verificado_antes_de_qualquer_header():
    """A propriedade é a **ordem**, não a ausência do header.

    O header `X-Tenant-Slug` é legítimo — o Internal Package Console fala
    com o hostname da própria plataforma e depende dele. O que não pode
    acontecer é ser consultado *antes* do `tid`: era assim que um
    cliente móvel saltava o portão, bastando acrescentá-lo.

    A primeira versão deste teste proibia o header no portão inteiro.
    Estava a medir a coisa errada — proibia a solução em vez do defeito,
    e teria forçado a partir o console para o satisfazer.
    """
    src = _source()
    gate = src[src.index("async def enforce_device_tenant") :]
    gate = _code_only(gate[: gate.index("async def get_db_session_for_context")])

    tid_check = gate.index("TENANT_CLAIM")
    header_check = gate.lower().index("x-tenant-slug")

    assert tid_check < header_check, (
        "o header é consultado antes do claim do token — um cliente "
        "móvel pode enviá-lo e saltar a verificação de pertença"
    )


def test_pedido_de_dispositivo_sem_tenant_e_recusado():
    """Sem `tid` e sem pista nenhuma de tenant, recusar explicitamente em
    vez de cair no tenant por omissão — servir o espaço errado é pior do
    que admitir que não se sabe qual é. (T-01.4, regra do Felipe.)"""
    src = _source()
    gate = src[src.index("async def enforce_device_tenant") :]
    gate = gate[: gate.index("async def get_db_session_for_context")]

    assert "BadRequestError" in gate


def test_endpoint_de_scan_exige_servico():
    """Guardado por `get_current_user`, qualquer funcionário autenticado
    podia injectar um insight forjado em qualquer espaço do seu
    cliente."""
    from pathlib import Path

    ai = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("api", "v1", "ai.py")
        .read_text(encoding="utf-8")
    )
    body = ai[ai.index("async def scan_insights_notify") :]
    signature = _code_only(body[: body.index("-> ScanInsightNotifyResponse:")])

    assert "require_service_principal" in signature
    assert "get_current_user" not in signature


def test_claim_de_servico_e_o_mesmo_dos_dois_lados():
    """O backend exige `svc`; o emissor em sky-poc-ai assina `svc`. Se
    os nomes divergirem o endpoint recusa tudo em silêncio."""
    assert SERVICE_CLAIM == "svc"
