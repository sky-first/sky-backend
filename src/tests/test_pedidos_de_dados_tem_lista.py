"""Um pedido de dados tem para onde ir, e volta com resposta.

> *"«O seu pedido foi enviado» — que pedido? Não há lista nenhuma."*
> *"O projeto tem de mostrar os pedidos pendentes — é a lista de tarefas de
> quem trata dos dados."*
> *"Notificação quando um pedido é respondido."* — Lucas

O modelo, o serviço e as rotas de decidir já existiam. Faltavam as duas
listas e o aviso de volta — e, por baixo disso, um defeito que fazia o pedido
**desaparecer**.

**O pedido que desaparecia.** `_pertence_ao_projeto` olhava só para
`space_members` e para quem tinha criado o projeto. Com o modelo de 26/08 isso
deixou de chegar: quem é convidado entra pela equipa **Geral**, e quem vem de
uma equipa da empresa nunca teve linha em `space_members`.

Quando essa função diz «não», a resposta é **a mesma de sempre** — «o seu
pedido foi enviado» — de propósito, para não confirmar que o projeto existe. O
resultado: a pessoa escrevia o que precisava, lia que tinha sido enviado, e
não tinha sido. Nada gravado, ninguém avisado, e nenhuma maneira de dar por
isso. Medido a 26/08: a tabela ficava vazia.
"""

import inspect

from src.api.v1 import data_access_requests as rotas
from src.services import data_access_request_service as servico


def test_pertencer_ao_projeto_conta_quem_vem_por_equipa():
    """**O defeito que fazia o pedido desaparecer.**

    Pergunta-se ao mesmo sítio que decide o acesso aos dados. Uma segunda
    definição de «pertence» acabaria por divergir — e a divergência aparece
    assim: em silêncio, com uma frase a dizer que correu bem.
    """
    fonte = inspect.getsource(rotas._pertence_ao_projeto)
    assert "papel_no_projeto" in fonte, (
        "voltou a decidir por conta própria quem pertence — quem entra por "
        "equipa perde os pedidos sem dar por isso"
    )
    # E não sobrou a leitura directa que ignorava as equipas.
    assert "SpaceMember.user_id == user.id" not in fonte


def test_ha_uma_lista_do_que_EU_pedi():
    """Era isto que faltava a quem lê «o seu pedido foi enviado»."""
    caminhos = [r.path for r in rotas.router.routes]
    assert "/meus" in caminhos


def test_a_minha_lista_nao_precisa_de_ser_admin():
    """São os pedidos da própria pessoa; um portão aqui esvaziava a lista."""
    fonte = inspect.getsource(rotas.meus_pedidos)
    assert "_so_admin" not in fonte


def test_a_minha_lista_leva_o_estado_e_o_motivo():
    """Sem o estado é uma lista de textos; é o estado que se quer saber.

    E o motivo é o que faz a diferença entre «não» e «não, porque isto vive
    noutro sítio — peça ali».
    """
    fonte = inspect.getsource(rotas.meus_pedidos)
    assert '"status": pedido.status' in fonte
    assert '"motivo_decisao": pedido.motivo_decisao' in fonte


def test_a_minha_lista_NAO_leva_a_proposta():
    """**A proposta é a tradução do pedido em tabelas concretas.**

    Corre do lado de quem aprova. Mostrá-la a quem pediu era mostrar-lhe nomes
    de tabelas a que pode não ter acesso — exactamente o que o pedido existe
    para evitar.
    """
    # Verifica-se o que a função **devolve**, não o texto do ficheiro: a
    # primeira versão disto apanhava a própria explicação lá em cima, que
    # nomeia a proposta para dizer que não vai.
    corpo = inspect.getsource(rotas.meus_pedidos)
    devolve = corpo[corpo.index("return ["):]
    assert '"proposta"' not in devolve


def test_ha_uma_lista_dos_pedidos_DO_PROJETO():
    """A lista de tarefas de quem trata dos dados deste projeto."""
    caminhos = [r.path for r in rotas.router.routes]
    assert "/do-projeto/{space_id}" in caminhos


def test_a_lista_do_projeto_e_de_quem_manda_no_projeto():
    """**Quem manda aqui é o projeto, não a plataforma.**

    A lista global é de administradores do cliente. Esta é de quem trata dos
    dados **deste** projeto — que muitas vezes não é a mesma pessoa, e que era
    quem estava a ficar sem saber que havia pedidos à espera.
    """
    fonte = inspect.getsource(rotas.pedidos_do_projeto)
    assert "papel_no_projeto" in fonte
    assert '("owner", "editor")' in fonte
    # O administrador do cliente também entra — mas por acréscimo, não em vez.
    assert "is_tenant_admin" in fonte


def test_quem_decide_avisa_quem_pediu():
    """Sem isto, quem pede volta a abrir a app todos os dias a ver se já tem."""
    for funcao in (servico.aprovar, servico.recusar):
        assert "_avisar_quem_pediu" in inspect.getsource(funcao), funcao.__name__


def test_o_aviso_vai_traduzivel_e_nao_em_ingles():
    """`title_key`, e não uma frase montada no servidor.

    A língua escolhe-se quando se lê; o servidor não sabe a de quem vai abrir
    a caixa.
    """
    fonte = inspect.getsource(servico._avisar_quem_pediu)
    assert "title_key=chave" in fonte
    # O **título** vem de quem chama (aprovar/recusar); só a descrição é que
    # tem chave própria, porque é a mesma nos dois casos.
    assert "title=chave" in fonte
    assert "notif.dataRequestApproved" not in fonte


def test_a_recusa_leva_o_motivo_e_a_aprovacao_nao():
    """O motivo é o que salva uma recusa de ser uma parede."""
    assert 'motivo=motivo or ""' in inspect.getsource(servico.recusar)
    aprovar = inspect.getsource(servico.aprovar)
    assert 'chave="notif.dataRequestApproved"' in aprovar


def test_falhar_o_aviso_nao_desfaz_a_decisao():
    """**Avisar é o remate, não a decisão.**

    A decisão já foi tomada e gravada; falhar o aviso não pode devolver um
    erro a quem aprovou, nem desfazer a aprovação.
    """
    fonte = inspect.getsource(servico._avisar_quem_pediu)
    assert "except Exception" in fonte
    assert "raise" not in fonte.split("except Exception")[1]
