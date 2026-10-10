"""Conector REST: defeitos D1, D3 e D6 do Anexo C (docs/ESTUDO_DADOS_PUBLICOS_2026-10.md).

* D1 — a chave escrita na web (``auth_type``/``auth_header``/``auth_value``)
  não era lida; não havia chave na query string.
* D3 — XML (DGT DATEX2) e CSV (BCE SDMX) voltavam como ``[{"text": …}]``; o
  MITECO voltava como 1 linha com 277 postos aninhados.
* D6 — ``test_connection`` dava ✅ com 401.

As amostras em ``fixtures/api_publicas`` são recortes das respostas reais de
10/10/2026. Sem rede: o transporte do httpx é falso.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.connectors import rest_api
from src.connectors.rest_api import RestAPIConnector

FIX = Path(__file__).parent / "fixtures" / "api_publicas"


@pytest.fixture(autouse=True)
def _sem_dns(monkeypatch):
    # O guarda SSRF resolve o host; estes testes são sobre HTTP.
    monkeypatch.setattr(rest_api, "validate_outbound_url", lambda url, **_kw: url)


@pytest.fixture
def servidor(monkeypatch):
    """Substitui o httpx.AsyncClient por um com transporte falso.

    ``servidor.responde(fn)`` define a resposta; ``servidor.pedidos`` guarda
    os pedidos feitos."""

    class _Servidor:
        pedidos: list = []
        fn = staticmethod(lambda r: httpx.Response(200, json=[]))

        def responde(self, fn):
            self.fn = fn

    srv = _Servidor()
    srv.pedidos = []
    real = httpx.AsyncClient

    def fake(*args, **kwargs):
        def handler(request):
            srv.pedidos.append(request)
            return srv.fn(request)

        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(rest_api.httpx, "AsyncClient", fake)
    return srv


BASE = "https://api.exemplo.test/v1"


# ── D1 ──────────────────────────────────────────────────────────────


class TestD1AutenticacaoDaWeb:
    async def test_bearer_token_da_web_vai_no_cabecalho(self, servidor):
        await RestAPIConnector().execute_query(
            {"base_url": BASE, "auth_type": "bearer_token", "auth_value": "tok-123456"}, "/x"
        )
        assert servidor.pedidos[0].headers["authorization"] == "Bearer tok-123456"

    async def test_api_key_com_cabecalho_proprio(self, servidor):
        await RestAPIConnector().execute_query(
            {
                "base_url": BASE,
                "auth_type": "api_key",
                "auth_header": "api_key",
                "auth_value": "aemet-chave",
            },
            "/x",
        )
        assert servidor.pedidos[0].headers["api_key"] == "aemet-chave"

    async def test_api_key_na_query_string(self, servidor):
        """TomTom ``?key=``: escreve-se ``?key`` no campo do cabeçalho."""
        await RestAPIConnector().execute_query(
            {"base_url": BASE, "auth_type": "api_key", "auth_header": "?key", "auth_value": "tt-k"},
            '{"path": "/route", "params": {"key": "do-llm", "x": "1"}}',
        )
        url = servidor.pedidos[0].url
        assert url.params["key"] == "tt-k"
        assert url.params["x"] == "1"
        assert "key" not in servidor.pedidos[0].headers

    async def test_basic_auth_da_web(self, servidor):
        await RestAPIConnector().execute_query(
            {"base_url": BASE, "auth_type": "basic_auth", "auth_value": "ana:segredo1"}, "/x"
        )
        assert servidor.pedidos[0].headers["authorization"].startswith("Basic ")

    async def test_contrato_antigo_auth_continua(self, servidor):
        await RestAPIConnector().execute_query(
            {"base_url": BASE, "auth": {"type": "bearer", "token": "t-999999"}}, "/x"
        )
        assert servidor.pedidos[0].headers["authorization"] == "Bearer t-999999"

    async def test_erro_nao_mostra_a_chave_da_query(self, servidor):
        servidor.responde(lambda r: httpx.Response(500, text="boom"))
        with pytest.raises(Exception) as exc:
            await RestAPIConnector().execute_query(
                {
                    "base_url": BASE,
                    "auth_type": "api_key",
                    "auth_header": "?key",
                    "auth_value": "chave-secreta",
                },
                "/x",
            )
        assert "chave-secreta" not in str(exc.value)
        assert "500" in str(exc.value)


# ── D3 ──────────────────────────────────────────────────────────────


def _ficheiro(nome, content_type):
    corpo = (FIX / nome).read_bytes()
    return lambda r: httpx.Response(200, content=corpo, headers={"content-type": content_type})


class TestD3RespostasViramLinhas:
    async def test_miteco_desembrulha_a_lista(self, servidor):
        servidor.responde(
            _ficheiro("miteco_badajoz_gasoleo_a.json", "application/json; charset=utf-8")
        )
        linhas = await RestAPIConnector().execute_query(
            {"base_url": BASE}, "/EstacionesTerrestres/FiltroProvinciaProducto/06/4"
        )
        assert len(linhas) == 4
        assert linhas[0]["Municipio"] == "Acedera"
        assert linhas[0]["PrecioProducto"] == "1,749"

    async def test_datex2_xml(self, servidor):
        servidor.responde(_ficheiro("dgt_datex2_v37.xml", "text/xml; charset=utf-8"))
        linhas = await RestAPIConnector().execute_query({"base_url": BASE}, "/datex2_v37.xml")
        assert len(linhas) == 2
        assert linhas[0]["roadName"] == "N-400"
        assert linhas[0]["to.municipality"] == "Ontígola"

    async def test_datex2_records_path_no_endpoint(self, servidor):
        servidor.responde(_ficheiro("dgt_datex2_v37.xml", "text/xml"))
        cfg = {
            "base_url": BASE,
            "endpoints": [
                {
                    "name": "incidencias",
                    "path": "/datex2_v37.xml",
                    "records_path": "situation.situationRecord",
                }
            ],
        }
        linhas = await RestAPIConnector().execute_query(cfg, "/datex2_v37.xml")
        assert len(linhas) == 3
        meta = await RestAPIConnector().get_metadata(cfg)
        assert meta["tables"][0]["metadata"]["records_path"] == "situation.situationRecord"

    async def test_bce_csv(self, servidor):
        servidor.responde(_ficheiro("ecb_exr_usd.csv", "text/csv"))
        linhas = await RestAPIConnector().execute_query(
            {"base_url": BASE}, "/data/EXR/D.USD.EUR.SP00.A"
        )
        assert [r["OBS_VALUE"] for r in linhas] == ["1.1177", "1.1186", "1.1206"]

    async def test_json_com_content_type_errado(self, servidor):
        servidor.responde(
            lambda r: httpx.Response(
                200,
                content=b'{"data": [{"a": 1}, {"a": 2}]}',
                headers={"content-type": "text/plain"},
            )
        )
        linhas = await RestAPIConnector().execute_query({"base_url": BASE}, "/x")
        assert linhas == [{"a": 1}, {"a": 2}]


# ── D6 ──────────────────────────────────────────────────────────────


class TestD6TesteDaLigacao:
    async def test_401_falha(self, servidor):
        """AEMET sem chave: 401 com corpo vazio."""
        servidor.responde(lambda r: httpx.Response(401, text=""))
        assert await RestAPIConnector().test_connection({"base_url": BASE}) is False

    async def test_403_com_credenciais_falha(self, servidor):
        servidor.responde(lambda r: httpx.Response(403, text="forbidden"))
        cfg = {"base_url": BASE, "auth_type": "bearer_token", "auth_value": "tok-123456"}
        assert await RestAPIConnector().test_connection(cfg) is False

    async def test_403_na_raiz_nua_sem_credenciais_e_so_pasta_fechada(self, servidor):
        """DGT: a pasta do DATEX2 dá 403 a toda a gente; o ficheiro dá 200."""
        servidor.responde(lambda r: httpx.Response(403, text="forbidden"))
        assert await RestAPIConnector().test_connection({"base_url": BASE}) is True

    async def test_endpoint_declarado_e_o_que_se_sonda(self, servidor):
        """AEMET: a raiz responde sem chave; o endpoint dá 401."""

        def fn(r):
            if r.url.path == "/v1":
                return httpx.Response(404)
            return httpx.Response(401, text="")

        servidor.responde(fn)
        cfg = {"base_url": BASE, "endpoints": [{"name": "a", "path": "/avisos"}]}
        assert await RestAPIConnector().test_connection(cfg) is False
        assert servidor.pedidos[0].url.path == "/v1/avisos"

    async def test_404_na_raiz_continua_acessivel(self, servidor):
        servidor.responde(lambda r: httpx.Response(404, text="not found"))
        assert await RestAPIConnector().test_connection({"base_url": BASE}) is True

    async def test_raiz_401_mas_endpoint_com_chave_passa(self, servidor):
        def fn(r):
            if r.url.path == "/v1":
                return httpx.Response(401)
            ok = r.headers.get("api_key") == "boa"
            return httpx.Response(200 if ok else 401, json=[])

        servidor.responde(fn)
        cfg = {
            "base_url": BASE,
            "auth_type": "api_key",
            "auth_header": "api_key",
            "auth_value": "boa",
            "endpoints": [{"name": "x", "path": "/avisos", "method": "GET"}],
        }
        assert await RestAPIConnector().test_connection(cfg) is True
        cfg["auth_value"] = "ma-chave"
        assert await RestAPIConnector().test_connection(cfg) is False

    async def test_a_chave_vai_tambem_no_teste(self, servidor):
        servidor.responde(lambda r: httpx.Response(200, json={}))
        await RestAPIConnector().test_connection(
            {
                "base_url": BASE,
                "auth_type": "api_key",
                "auth_header": "?key",
                "auth_value": "k-1234",
            }
        )
        assert servidor.pedidos[0].url.params["key"] == "k-1234"
