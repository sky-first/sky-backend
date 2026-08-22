"""O worker não conseguia ler o segredo da base de nenhum cliente.

`_fetch_secret` fazia `boto3.client("secretsmanager")` sem região. Sem
região no ambiente, o boto3 rebenta com `NoRegionError` ANTES de fazer o
pedido. Nos pods da API a região vem do ambiente; no worker do Celery
não vinha.

O efeito, visto nos logs de produção a 22/08/2026: **todas** as execuções
de agentes falhavam com "tenant 'sandbox' data plane unavailable",
tentavam outra vez ao fim de 2 minutos e desistiam. Nenhum agente chegou
a correr — de nenhum cliente — enquanto a app dizia a quem carregava em
"Perguntar agora" que aquilo corria em segundo plano.

A região passa a sair do próprio ARN, que é onde ela está de facto.
"""

from __future__ import annotations

from src.config.tenant_connection_manager import _regiao_do_arn


def test_a_regiao_sai_do_arn():
    arn = "arn:aws:secretsmanager:eu-west-1:032080729567:secret:sky/prd/tenant-sandbox-AbCdEf"
    assert _regiao_do_arn(arn) == "eu-west-1"


def test_outra_regiao_e_lida_como_esta():
    """Não pode ficar cravada: os clientes não vivem todos na mesma."""
    arn = "arn:aws:secretsmanager:us-east-1:1:secret:x"
    assert _regiao_do_arn(arn) == "us-east-1"


def test_um_nome_de_segredo_nao_tem_regiao():
    """O `SecretId` também aceita o nome. Aí não há região para ler, e
    devolver `None` deixa quem chama cair na configuração — rebentar aqui
    trocava uma avaria por outra."""
    assert _regiao_do_arn("sky/prd/tenant-sandbox") is None
    assert _regiao_do_arn("") is None
    assert _regiao_do_arn("arn:aws:secretsmanager::1:secret:x") is None


def test_o_cliente_de_segredos_leva_sempre_uma_regiao():
    """O guarda que importa.

    Os testes acima provam que a função sabe ler um ARN. Não provam que
    alguém a usa — e o defeito era precisamente uma chamada sem região.
    Este lê a fonte.
    """
    import inspect

    from src.config import tenant_connection_manager

    # Sem os comentários: o comentário que explica a avaria CITA a chamada
    # antiga, e o guarda apanhava-se a si próprio. (Apanhado a escrever isto,
    # tal como o guarda das traduções na app.)
    fonte = "\n".join(
        l
        for l in inspect.getsource(tenant_connection_manager).splitlines()
        if not l.lstrip().startswith("#")
    )
    assert 'boto3.client("secretsmanager")' not in fonte, (
        "cliente de secretsmanager sem region_name — foi assim que o worker "
        "deixou de conseguir ler o segredo de qualquer cliente"
    )
    assert 'boto3.client("secretsmanager", region_name=' in fonte
