# -*- coding: utf-8 -*-
"""O agendador percorre cada cliente — e rebentava em todos.

**Encontrado nos registos de produção, 31/08/2026.** O `celery beat` estava
implantado e a despachar; o worker dizia que a tarefa tinha sucesso; e o
resultado era sempre `{'agents_scheduled': 0}`.

Zero lia-se como «não havia nada por correr». Era outra coisa:

    agent-scheduler[sandbox] falhou: _cache_put() takes 1 positional
    argument but 2 were given
    agent-scheduler[sky] falhou: ...
    agent-scheduler[skyfirstlabs] falhou: ...

43 vezes por cliente, de cinco em cinco minutos, desde que o agendador
entrou em produção. `_cache_put` recebe só o contexto — o slug vem de
dentro dele — e era chamada com dois argumentos.

**Nenhum agente correu a horas em produção.** O «Diariamente» da app
continuava decorativo, mesmo depois de o agendador existir.

---

**Porque é que ninguém deu por isso.** O `por_cada_cliente` apanha a
excepção por cliente e segue — o que está certo: um cliente com a base em
baixo não pode travar os outros. Só que a contagem que sai no fim não
distingue «não havia nada» de «não cheguei a olhar», e é a contagem que
aparece nos registos.
"""
from __future__ import annotations

import inspect

from src.api.middleware.tenant_resolver import _cache_put
from src.workers import por_cada_cliente as modulo


class TestAChamadaBateCertoComAAssinatura:
    def test_cache_put_recebe_so_o_contexto(self):
        parametros = list(inspect.signature(_cache_put).parameters)
        assert parametros == ["ctx"]

    def test_e_e_assim_que_e_chamada(self):
        fonte = inspect.getsource(modulo)
        codigo = "\n".join(
            l for l in fonte.splitlines() if not l.lstrip().startswith("#")
        )
        assert "_cache_put(ctx)" in codigo
        assert "_cache_put(slug, ctx)" not in codigo

    def test_o_slug_vem_de_dentro_do_contexto(self):
        """A razão de a assinatura ser essa — e de a chamada estar errada."""
        fonte = inspect.getsource(_cache_put)
        assert "ctx.slug" in fonte


class TestOSilencioQueEscondeuIsto:
    """Zero clientes com sucesso não se lê como zero agentes por correr."""

    def test_a_passagem_conta_quem_correu_e_quem_falhou(self):
        fonte = inspect.getsource(modulo.por_cada_cliente)
        assert "correram" in fonte and "falharam" in fonte

    def test_e_grita_quando_falharam_TODOS(self):
        """Um aviso por passagem, e só quando não sobrou ninguém: se um
        cliente respondeu, a passagem correu, e um alarme por causa de outro
        seria ruído de cinco em cinco minutos."""
        fonte = inspect.getsource(modulo.por_cada_cliente)
        assert "if falharam and not correram:" in fonte
        assert "logger.error" in fonte

    def test_a_mensagem_diz_o_que_significa(self):
        """«0 enfileirados» sozinho é o que enganou durante semanas."""
        fonte = inspect.getsource(modulo.por_cada_cliente)
        assert "nao chegou a acontecer" in fonte
