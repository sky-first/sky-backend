# -*- coding: utf-8 -*-
"""Os ficheiros locais da Biblioteca só se lêem e escrevem com endereço assinado.

Em produção (12/10/2026) `AZURE_STORAGE_ACCOUNT_NAME` estava vazia, o que
deixava activas duas rotas SEM sessão:

    PUT /api/v1/knowledge/local-upload/{caminho}
    GET /api/v1/knowledge/local-download/{caminho}

O caminho era colado à pasta base sem validação e o token do upload nunca
era verificado: `local-download/../../proc/self/environ` entregava as
variáveis do pod a qualquer pessoa. Estes testes fixam o comportamento:
caminho fora da pasta → 400; sem assinatura, com assinatura de outro
caminho, de outra operação ou fora do prazo → 403; endereço gerado pelo
servidor → funciona.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.v1 import knowledge as rotas
from src.azure import blob_helper


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(blob_helper, "_LOCAL_BASE", tmp_path / "knowledge")
    monkeypatch.setattr(blob_helper, "_USE_LOCAL", True)
    monkeypatch.setattr(rotas, "_USE_LOCAL", True)
    app = FastAPI()
    app.include_router(rotas.router, prefix="/api/v1/knowledge")
    return TestClient(app)


def _consulta(url: str) -> str:
    return urlsplit(url).query


CAMINHO = "space/abc/user1/0123456789abcdef.pdf"


def test_o_endereco_gerado_pelo_servidor_carrega_e_descarrega(cliente):
    up = blob_helper.generate_upload_sas_url(CAMINHO, "application/pdf", 1024)
    r = cliente.put(
        f"/api/v1/knowledge/local-upload/{CAMINHO}?{_consulta(up['url'])}", content=b"%PDF-1"
    )
    assert r.status_code == 201
    down = blob_helper.generate_download_sas_url(CAMINHO)
    r = cliente.get(f"/api/v1/knowledge/local-download/{CAMINHO}?{_consulta(down)}")
    assert r.status_code == 200
    assert r.content == b"%PDF-1"


@pytest.mark.parametrize(
    "caminho",
    [
        "../../proc/self/environ",
        "space/../../../etc/passwd",
        "/etc/passwd",
        "space\\..\\..\\x",
        "space//x",
        "./x",
    ],
)
def test_um_caminho_fora_da_pasta_e_recusado(cliente, caminho):
    with pytest.raises(blob_helper.CaminhoInvalido):
        blob_helper._local_path(caminho)
    r = cliente.get(f"/api/v1/knowledge/local-download/{caminho}")
    assert r.status_code in (400, 403, 404)  # o encaminhador pode já normalizar o caminho
    assert b"root:" not in r.content and b"PATH=" not in r.content


def test_sem_assinatura_nao_se_le_nem_escreve(cliente):
    blob_helper.save_local_blob(CAMINHO, b"segredo")
    assert cliente.get(f"/api/v1/knowledge/local-download/{CAMINHO}").status_code == 403
    assert cliente.put(f"/api/v1/knowledge/local-upload/{CAMINHO}", content=b"x").status_code == 403
    assert blob_helper._local_path(CAMINHO).read_bytes() == b"segredo"


def test_a_assinatura_de_outro_caminho_ou_operacao_nao_serve(cliente):
    outro = "space/abc/user1/ffff.pdf"
    up_outro = _consulta(blob_helper.generate_upload_sas_url(outro, "application/pdf", 1024)["url"])
    assert (
        cliente.put(
            f"/api/v1/knowledge/local-upload/{CAMINHO}?{up_outro}", content=b"x"
        ).status_code
        == 403
    )
    # Um endereço de upload não serve para descarregar.
    up = _consulta(blob_helper.generate_upload_sas_url(CAMINHO, "application/pdf", 1024)["url"])
    blob_helper.save_local_blob(CAMINHO, b"y")
    assert cliente.get(f"/api/v1/knowledge/local-download/{CAMINHO}?{up}").status_code == 403


def test_fora_do_prazo_e_recusado(cliente):
    blob_helper.save_local_blob(CAMINHO, b"z")
    q = blob_helper.assinar_local("download", CAMINHO, ttl_seconds=-5)
    assert cliente.get(f"/api/v1/knowledge/local-download/{CAMINHO}?{q}").status_code == 403


def test_o_tamanho_maximo_assinado_e_respeitado(cliente):
    up = blob_helper.generate_upload_sas_url(CAMINHO, "application/pdf", 4)
    r = cliente.put(
        f"/api/v1/knowledge/local-upload/{CAMINHO}?{_consulta(up['url'])}", content=b"12345"
    )
    assert r.status_code == 400
    # Mexer no max da query invalida a assinatura.
    q = parse_qs(_consulta(up["url"]))
    adulterado = f"exp={q['exp'][0]}&max=999999&sig={q['sig'][0]}"
    r = cliente.put(f"/api/v1/knowledge/local-upload/{CAMINHO}?{adulterado}", content=b"12345")
    assert r.status_code == 403
