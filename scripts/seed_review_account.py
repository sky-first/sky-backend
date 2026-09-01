"""Cria uma conta de revisão das lojas. **Nada o corre automaticamente.**

Não está ligado a Job nenhum
----------------------------
O Job ``demo-review-account`` que o corria foi removido a 01/09/2026
(sky-infra #807). Semeava o valor por omissão daqui,
``demo@skyfirstlabs.com``, que é o endereço de **desenvolvimento local**
do ``seed_demo.py`` — não é a conta que as lojas usam.

A conta das lojas está em ``sky-mobile/apps/mobile/docs/FICHA-DAS-LOJAS.md``:
``reviewer@sandbox.skyfirstlabs.com``, com a password em
``sky/production/tenant-sandbox/admin``. Vive na base do **tenant**
``sandbox``; este script, quando corria em produção, apontava à base da
**plataforma** — daí o duplicado.

Se um dia se quiser voltar a automatizar isto, o script serve: passa-se
``REVIEW_ACCOUNT_EMAIL``, ``REVIEW_TENANT_SLUG`` e um ``DATABASE_URL`` que
aponte à base do tenant. Mas cuidado com o mapeamento de domínio no fim —
``domain_of_email`` de um email ``@skyfirstlabs.com`` dá o domínio da
equipa inteira, e associá-lo a um tenant de demonstração levava lá dentro
toda a gente da SkyFirst.

Porque não se usa o ``seed_demo.py``
------------------------------------
O ``seed_demo.py`` da raiz existe para desenvolvimento local e **tem uma
guarda que o impede de correr contra uma base não local**. A guarda está
certa: aquele script cria um utilizador ``role="admin"`` com uma password
escrita em código (``SkyDemo!2026``) e — pior — um segredo TOTP fixo,
também em código (``SKYMOBILEDEMO234``).

Um segredo TOTP fixo não é MFA. Quem tiver acesso ao repositório gera
códigos válidos para sempre. Em produção seria uma porta de administrador
com a chave publicada. O próprio cabeçalho daquele ficheiro diz isso.

Este script faz o mesmo trabalho sem nenhuma dessas propriedades:

* **Password vinda do ambiente**, nunca de código. Sem
  ``REVIEW_ACCOUNT_PASSWORD`` definido, recusa-se a correr.
* **Sem inscrição de MFA.** O revisor entra só com email + password porque
  o email está em ``MFA_EXEMPT_EMAILS`` — que é exactamente para isso que
  essa lista existe. Não há segundo fator a fingir.
* **Papel ``member``**, não ``admin``. O revisor precisa de ver a app a
  funcionar, não de administrar a plataforma.
* Ligado ao **tenant de demonstração**, com os dados de demonstração que
  os Jobs de seed já criam.

Idempotente: se a conta existir, actualiza a password e mantém o resto.

Uso
---
    REVIEW_ACCOUNT_PASSWORD='<password forte>' python scripts/seed_review_account.py

Opcionais:
    REVIEW_ACCOUNT_EMAIL   (por omissão demo@skyfirstlabs.com)
    REVIEW_TENANT_SLUG     (por omissão demo)
    REVIEW_ACCOUNT_NAME    (por omissão "Sky Demo")

A password deve ser gerada e guardada no Secrets Manager, ao lado das
restantes. Nunca a escrever aqui.
"""

from __future__ import annotations

import asyncio
import os
import sys

from src.config.database import AsyncSessionLocal
from src.core.security import get_password_hash
from src.models.tenant import Tenant
from src.models.tenant_domain import TenantDomain, domain_of_email
from src.repositories.user import UserRepository

EMAIL = os.getenv("REVIEW_ACCOUNT_EMAIL", "demo@skyfirstlabs.com")
NAME = os.getenv("REVIEW_ACCOUNT_NAME", "Sky Demo")
TENANT_SLUG = os.getenv("REVIEW_TENANT_SLUG", "demo")

# Comprimento mínimo por baixo do qual não vale a pena o esforço. Não é
# uma política de passwords — é uma travessa contra "demo123" passar aqui
# por distracção num Job.
_MIN_PASSWORD_LEN = 16


def _password_or_exit() -> str:
    password = os.environ.get("REVIEW_ACCOUNT_PASSWORD", "")
    if not password:
        print(
            "REVIEW_ACCOUNT_PASSWORD não está definida.\n"
            "\n"
            "Este script não traz password nenhuma em código, e é de\n"
            "propósito: uma password de produção escrita no repositório é\n"
            "uma credencial publicada. Gera uma e passa-a pelo ambiente,\n"
            "a partir do Secrets Manager.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if len(password) < _MIN_PASSWORD_LEN:
        print(
            f"REVIEW_ACCOUNT_PASSWORD tem {len(password)} caracteres; "
            f"o mínimo aqui são {_MIN_PASSWORD_LEN}.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return password


async def seed() -> None:
    password = _password_or_exit()

    async with AsyncSessionLocal() as db:
        users = UserRepository(db)

        # ── Apagada nao e inexistente. ────────────────────────────────
        #
        # O `get_by_email` filtra `deleted_at IS NULL`. Se a conta do
        # revisor foi apagada em soft-delete, a procura devolve `None`, o
        # seed acredita que tem de a criar, e o INSERT bate no indice
        # unico de email:
        #
        #     duplicate key value violates unique constraint
        #     Key (email)=(demo@skyfirstlabs.com) already exists
        #
        # O Job morre, o `sky-demo-seed` fica Degraded, e — o que
        # realmente importa — o revisor da App Store fica sem conta para
        # entrar, que e a causa n1 de rejeicao de apps atras de login.
        #
        # O callback do SSO ja tinha este problema e ja lhe deu resposta:
        # ver a linha apagada e ressuscita-la. Aqui e a mesma coisa, e por
        # uma razao mais forte — esta conta EXISTE POR CONTRATO com as
        # lojas. Nao ha estado nenhum em que a deixar apagada seja o
        # comportamento certo.
        user = await users.get_by_email_including_deleted(EMAIL)
        if user is not None and user.deleted_at is not None:
            user.deleted_at = None
            print(f"[seed] conta {EMAIL} estava apagada — reposta em servico.")
        if user is None:
            user = await users.create(
                email=EMAIL,
                password_hash=get_password_hash(password),
                name=NAME,
                # `member`, não `admin`. O revisor tem de ver a app a
                # trabalhar; não tem de poder administrar nada.
                role="member",
                # Sem `is_active`: o User não tem esse campo. O que existe
                # é `status`, e é presença (active/away/offline), não
                # habilitação da conta — pôr "active" aqui diria que o
                # revisor está online, que é outra coisa. O seed_demo.py
                # cria a conta dele exactamente assim, sem nada disto.
            )
            created = True
        else:
            user.password_hash = get_password_hash(password)
            created = False
        await db.commit()
        await db.refresh(user)

        # Login à maneira do Teams: o domínio do email identifica o
        # workspace, por isso a app não precisa de enviar slug nenhum.
        tenant = (
            await db.execute(Tenant.__table__.select().where(Tenant.slug == TENANT_SLUG))
        ).first()
        domain = domain_of_email(EMAIL)
        if tenant is None:
            print(
                f"AVISO: não existe tenant com slug '{TENANT_SLUG}'. A conta foi\n"
                f"criada, mas sem workspace o revisor entra e não vê nada.\n"
                f"Corre primeiro os Jobs de seed do conteúdo de demonstração.",
                file=sys.stderr,
            )
        elif domain:
            existing = (
                await db.execute(
                    TenantDomain.__table__.select().where(TenantDomain.domain == domain)
                )
            ).first()
            if existing is None:
                db.add(TenantDomain(domain=domain, tenant_id=tenant.id, is_active=True))
                await db.commit()
                print(f"Domínio '{domain}' associado ao tenant '{TENANT_SLUG}'.")

        print(f"Conta de revisão {'criada' if created else 'actualizada'}: {EMAIL}")
        print("Sem MFA inscrito — o acesso do revisor depende de o email")
        print("estar em MFA_EXEMPT_EMAILS neste ambiente.")

        exempt = {
            e.strip().lower()
            for e in (os.getenv("MFA_EXEMPT_EMAILS", "") or "").split(",")
            if e.strip()
        }
        if EMAIL.lower() not in exempt:
            print(
                f"\nAVISO: {EMAIL} não está em MFA_EXEMPT_EMAILS.\n"
                f"Sem isso o login do revisor não pede TOTP (não há MFA\n"
                f"inscrito) mas qualquer política futura de MFA obrigatório\n"
                f"tranca-o. Confirma a variável neste ambiente.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    asyncio.run(seed())
