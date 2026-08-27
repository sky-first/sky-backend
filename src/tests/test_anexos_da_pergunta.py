"""Os documentos anexados a uma pergunta chegam ao modelo — dos DOIS lados.

> *"Os ficheiros estão a funcionar, tanto mobile quanto web?"* — Lucas

Estavam a meio, e o meio não era o botão.

O telemóvel anexa documentos a uma pergunta desde sempre. A web não tinha a
funcionalidade — e o bloqueio não era de interface: **o `/ai/chat`, que é o
endpoint da web, não lia anexos nenhuns.** Só o `/chat/stream`, que a web não
usa. Podia ter-se feito o botão todo que o documento nunca chegava ao modelo.

A leitura vive agora num sítio só (`services/anexos_da_pergunta`) e os dois
caminhos chamam-na.

---

**O que estes testes guardam, por ordem de importância:**

1. **O dono.** Um `file_id` conhecido não pode ler o documento de outra
   pessoa. É a única linha aqui que, se falhar, é uma fuga de dados.
2. **A ordem.** Um contrato e o seu aditamento pela ordem errada são outra
   coisa.
3. **O silêncio.** Um anexo ilegível — uma fotografia, por exemplo — é
   ignorado em vez de rebentar a pergunta.
"""

import uuid

import pytest

from src.models.file import FileUpload
from src.models.user import User
from src.services.anexos_da_pergunta import (
    MAX_CARACTERES_POR_ANEXO,
    juntar_aos_dados,
    leads_dos_anexos,
)


async def _pessoa(db, nome):
    u = User(
        id=uuid.uuid4(),
        email=f"{nome}-{uuid.uuid4().hex[:6]}@exemplo.pt",
        name=nome,
        password_hash="x",
        role="member",
    )
    db.add(u)
    await db.flush()
    return u


async def _anexo(db, dono, nome, texto):
    f = FileUpload(
        id=uuid.uuid4(),
        user_id=dono.id,
        filename=nome,
        original_name=nome,
        mime_type="application/pdf",
        size=len(texto or ""),
        url="inline://chat/x",
        storage="inline",
        parsed_data={"text": texto, "chars": len(texto or "")},
    )
    db.add(f)
    await db.flush()
    return f


@pytest.mark.asyncio
async def test_o_texto_do_documento_chega(db_session):
    dono = await _pessoa(db_session, "ana")
    f = await _anexo(db_session, dono, "contrato.pdf", "265 EUR por dia útil")

    leads = await leads_dos_anexos(db_session, {"file_ids": [str(f.id)]}, dono)
    assert len(leads) == 1
    assert "265 EUR por dia útil" in leads[0]
    assert "contrato.pdf" in leads[0]


@pytest.mark.asyncio
async def test_o_anexo_de_outra_pessoa_nao_se_le(db_session):
    """**A linha que, se falhar, é uma fuga de dados.**

    Saber um `file_id` não pode chegar para ler o documento de outra pessoa
    através de uma pergunta.
    """
    dona = await _pessoa(db_session, "ana")
    intruso = await _pessoa(db_session, "intruso")
    f = await _anexo(db_session, dona, "salarios.pdf", "tabela de vencimentos")

    leads = await leads_dos_anexos(db_session, {"file_ids": [str(f.id)]}, intruso)
    assert leads == []


@pytest.mark.asyncio
async def test_a_ordem_e_a_do_utilizador(db_session):
    """Um contrato e o seu aditamento pela ordem errada são outra coisa."""
    dono = await _pessoa(db_session, "ana")
    a = await _anexo(db_session, dono, "contrato.pdf", "PRIMEIRO")
    b = await _anexo(db_session, dono, "aditamento.pdf", "SEGUNDO")

    leads = await leads_dos_anexos(
        db_session, {"file_ids": [str(a.id), str(b.id)]}, dono
    )
    assert len(leads) == 2
    assert "PRIMEIRO" in leads[0] and "SEGUNDO" in leads[1]


@pytest.mark.asyncio
async def test_uma_fotografia_e_ignorada_em_silencio(db_session):
    """Imagens sobem mas não têm texto — não há OCR nem modelo com visão.

    Ignorar é o certo: mandar bytes decodificados como texto dava ao modelo
    uma página de lixo sobre a qual ele responderia com toda a confiança.
    """
    dono = await _pessoa(db_session, "ana")
    foto = await _anexo(db_session, dono, "fatura.jpg", "")

    assert await leads_dos_anexos(db_session, {"file_ids": [str(foto.id)]}, dono) == []


@pytest.mark.asyncio
async def test_um_id_que_nao_existe_nao_rebenta(db_session):
    dono = await _pessoa(db_session, "ana")
    assert await leads_dos_anexos(db_session, {"file_ids": [str(uuid.uuid4())]}, dono) == []
    assert await leads_dos_anexos(db_session, {"file_ids": ["nao-e-um-uuid"]}, dono) == []


@pytest.mark.asyncio
async def test_sem_anexos_nao_ha_leads(db_session):
    dono = await _pessoa(db_session, "ana")
    assert await leads_dos_anexos(db_session, {}, dono) == []
    assert await leads_dos_anexos(db_session, None, dono) == []


@pytest.mark.asyncio
async def test_um_documento_enorme_e_cortado(db_session):
    """Um PDF de 300 páginas não cabe na janela — cortar é melhor do que
    estourar e perder a pergunta com ele."""
    dono = await _pessoa(db_session, "ana")
    f = await _anexo(db_session, dono, "enorme.pdf", "x" * (MAX_CARACTERES_POR_ANEXO + 5000))

    leads = await leads_dos_anexos(db_session, {"file_ids": [str(f.id)]}, dono)
    assert leads[0].count("x") == MAX_CARACTERES_POR_ANEXO


def test_os_documentos_vao_a_frente_das_instrucoes():
    """O que vem primeiro no prompt enquadra a leitura do resto."""
    junto = juntar_aos_dados(["DOC"], "instrucoes existentes")
    assert junto.index("DOC") < junto.index("instrucoes existentes")


def test_sem_documentos_as_instrucoes_ficam_como_estavam():
    assert juntar_aos_dados([], "instrucoes") == "instrucoes"
    assert juntar_aos_dados([], None) is None


def test_os_dois_caminhos_usam_a_mesma_leitura():
    """**O ponto todo desta mudança.**

    Se um deles voltar a ler ficheiros por sua conta, volta a haver dois
    comportamentos — e o que fica para trás é o que decide o que o modelo vê.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    rota = (raiz / "api" / "v1" / "ai.py").read_text(encoding="utf-8")
    servico = (raiz / "services" / "ai_service.py").read_text(encoding="utf-8")

    assert "leads_dos_anexos" in rota, "o /chat/stream deixou de usar a leitura comum"
    assert "leads_dos_anexos" in servico, "o /ai/chat (web) deixou de ler anexos"
    # A cópia antiga, à mão, dentro do endpoint.
    assert "_file_leads" not in rota
