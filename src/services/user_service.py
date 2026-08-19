"""User service."""

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.core.permissions import validar_atribuicao_de_papel, check_permission, get_user_permissions, is_tenant_admin
from src.core.security import get_password_hash
from src.models.user import User
from src.repositories.user import UserRepository
from src.schemas.user import UserCreate, UserResponse, UserUpdate
from src.services.auth_service import user_to_response_dict
from src.services.email_service import EmailService
from src.services.onboarding_service import ensure_default_page_and_space

logger = logging.getLogger(__name__)


class UserService:
    """User service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize user service.

        Args:
            db: Database session
        """
        self.db = db
        self.user_repo = UserRepository(db)

    async def list_users(
        self, current_user: User, skip: int = 0, limit: int = 100
    ) -> List[UserResponse]:
        """
        List all users.

        Args:
            current_user: Current authenticated user
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List[UserResponse]: List of users

        Raises:
            ForbiddenError: If user doesn't have permission
        """
        if not check_permission(current_user, "user", "read"):
            raise ForbiddenError("You don't have permission to list users")

        users = await self.user_repo.get_all(skip=skip, limit=limit)
        return [UserResponse.model_validate(user_to_response_dict(user)) for user in users]

    async def get_user(self, user_id: UUID, current_user: User) -> UserResponse:
        """
        Get user by ID.

        Args:
            user_id: User ID
            current_user: Current authenticated user

        Returns:
            UserResponse: User data

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        # Users can view their own profile, admins can view any
        if user_id != current_user.id and not check_permission(current_user, "user", "read"):
            raise ForbiddenError("You don't have permission to view this user")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        return UserResponse.model_validate(user_to_response_dict(user))

    async def _tenant_auth_methods(self) -> dict:
        """Como é que se entra AQUI — no cliente, ou na plataforma.

        Espelha a ordem do ``/api/v1/auth/methods``, e a distinção importa:

        * **Há cliente resolvido** → a linha dele, assente no
          ``DEFAULT_AUTH_METHODS``. O defeito serve de chão para uma linha com
          chaves em falta, não de resposta.
        * **Não há cliente** → quem está a responder é a **plataforma**, e a
          plataforma é só SSO (``PLATFORM_FALLBACK_AUTH_METHODS``).

        Usar o defeito dos clientes também para este caso seria dizer que
        acrescentar alguém à equipa da Sky é um convite por palavra-passe — e a
        pessoa recebia um link para definir uma palavra-passe que o login da
        plataforma já não aceita. O convite tem de seguir a porta que existe.
        """
        from sqlalchemy import select

        from src.core.tenant_context import current_tenant
        from src.models.tenant import (
            DEFAULT_AUTH_METHODS,
            PLATFORM_FALLBACK_AUTH_METHODS,
            Tenant,
        )

        try:
            ctx = current_tenant()
        except Exception:
            ctx = None
        tenant_slug = getattr(ctx, "slug", None) if ctx else None

        if not tenant_slug:
            return dict(PLATFORM_FALLBACK_AUTH_METHODS)

        methods = dict(DEFAULT_AUTH_METHODS)
        row = (
            await self.db.execute(
                select(Tenant.auth_methods).where(Tenant.slug == tenant_slug)
            )
        ).first()
        if row and isinstance(row[0], dict):
            methods.update(row[0])
        return methods

    @staticmethod
    def _sso_provider_label(methods: dict) -> str:
        """O nome que o convidado vai reconhecer no botão de entrar."""
        for key, label in (("google", "Google"), ("azure", "Microsoft"), ("okta", "Okta")):
            if methods.get(key):
                return label
        return "single sign-on"

    async def _assert_password_invite_allowed(self) -> None:
        """Refuse the email+password invite flow when the tenant's
        ``auth_methods`` config has ``password`` disabled.

        Mantido para quem precise MESMO de uma palavra-passe. O convite normal
        já não passa por aqui — ver ``create_user``.
        """
        methods = await self._tenant_auth_methods()
        if not methods.get("password"):
            raise BadRequestError(
                "This workspace is configured for SSO sign-in only, so there is no "
                "password to set."
            )

    async def create_user(self, user_data: UserCreate, current_user: User) -> UserResponse:
        """
        Create a new user.

        Args:
            user_data: User creation data
            current_user: Current authenticated user

        Returns:
            UserResponse: Created user

        Raises:
            ForbiddenError: If user doesn't have permission
            BadRequestError: If email already exists
        """
        if not check_permission(current_user, "user", "create"):
            raise ForbiddenError("You don't have permission to create users")

        # Check if email already exists
        existing_user = await self.user_repo.get_by_email(user_data.email)
        if existing_user:
            raise BadRequestError("User with this email already exists")

        # Duas maneiras de dar acesso, conforme o cliente entra.
        #
        # Um cliente só-SSO não tem palavra-passe para o convidado definir —
        # e, ATÉ AQUI, isso recusava a criação. O efeito era um cliente
        # fechado sobre si próprio: ninguém podia ser criado, e o retorno do
        # SSO (desde o #611) só deixa entrar quem já existe. Resultado: um
        # workspace só-SSO nunca mais podia acrescentar um colega, e a
        # mensagem de erro mandava-o "entrar com o fornecedor de identidade",
        # coisa que o gate do SSO recusa.
        #
        # Convidar não é mandar definir uma palavra-passe: é DAR ACESSO. Num
        # cliente só-SSO isso significa provisionar a pessoa e dizer-lhe por
        # que porta entra. A palavra-passe é um meio, não o fim.
        import secrets
        from datetime import datetime, timedelta, timezone

        methods = await self._tenant_auth_methods()
        password_login = bool(methods.get("password"))

        # Em qualquer dos casos a palavra-passe fica aleatória e inutilizável:
        # no caminho de password é substituída pelo convidado; no de SSO nunca
        # chega a servir para nada.
        secure_random_password = secrets.token_urlsafe(16)
        invite_token = secrets.token_urlsafe(32) if password_login else None
        invite_expires_at = (
            datetime.now(timezone.utc) + timedelta(days=7) if password_login else None
        )

        user = await self.user_repo.create(
            email=user_data.email,
            password_hash=get_password_hash(secure_random_password),
            name=user_data.name,
            avatar=user_data.avatar,
            role=user_data.role,
            invite_token=invite_token,
            invite_expires_at=invite_expires_at,
            invited_by=current_user.id,
        )

        await self.db.commit()
        await self.db.refresh(user)

        # Ensure default page/space for new users created by admins
        await ensure_default_page_and_space(self.db, user)

        sent = await self._send_access_email(
            user=user,
            inviter_name=current_user.name,
            invite_token=invite_token,
            methods=methods,
        )

        # O acesso é a conta existir; o email é o aviso. Separá-los na resposta
        # deixa quem convida saber que tem de avisar à mão, em vez de assumir.
        return UserResponse.model_validate(
            {**user_to_response_dict(user), "access_email_sent": sent}
        )

    async def _send_access_email(
        self,
        *,
        user,
        inviter_name: str,
        invite_token: Optional[str],
        methods: dict,
    ) -> bool:
        """Diz à pessoa que tem acesso, e por que porta entra.

        Devolve se o envio foi aceite. O chamador decide o que fazer com isso —
        até aqui a falha era engolida e a API respondia sucesso na mesma, o que
        dava o pior dos cenários: o administrador via "convidado", o convidado
        nunca recebia nada, e ninguém percebia porquê.
        """
        frontend_url = "http://localhost:3000"
        if getattr(settings, "CORS_ORIGINS", None):
            frontend_url = settings.CORS_ORIGINS.split(",")[0].strip()

        try:
            email_service = EmailService()
            if invite_token:
                link = f"{frontend_url}/auth/accept-invite?token={invite_token}"
                ok = email_service.send_invite_email(user.email, link, inviter_name)
            else:
                ok = email_service.send_sso_access_email(
                    user.email,
                    login_link=f"{frontend_url}/login",
                    inviter_name=inviter_name,
                    provider_label=self._sso_provider_label(methods),
                )
        except Exception:
            logger.exception("Failed to send access email to %s", user.email)
            return False
        if not ok:
            logger.warning("Access email not accepted for %s", user.email)
        return bool(ok)

    async def update_user(
        self, user_id: UUID, user_data: UserUpdate, current_user: User
    ) -> UserResponse:
        """
        Update user.

        Args:
            user_id: User ID
            user_data: User update data
            current_user: Current authenticated user

        Returns:
            UserResponse: Updated user

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        # Users can update their own profile (limited fields), admins can update any
        if user_id != current_user.id and not check_permission(current_user, "user", "update"):
            raise ForbiddenError("You don't have permission to update this user")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        # Non-admin users can only update limited fields
        if not is_tenant_admin(current_user) and user_id != current_user.id:
            raise ForbiddenError("You can only update your own profile")

        # Update fields
        update_data = user_data.model_dump(exclude_unset=True)

        # Non-admin users cannot change role
        if not is_tenant_admin(current_user) and "role" in update_data:
            del update_data["role"]

        # ...e um admin não pode nomear fundadores, nem a si próprio.
        #
        # Sem esta linha, `PUT /users/{meu_id}` com {"role": "super_admin"}
        # devolvia 200 e o admin passava a fundador — o que torna inútil
        # `permissions.edit`, `billing.manage` e `tenant.delete` serem
        # exclusivos do fundador, porque o caminho para lá estava aberto.
        # Confirmado em produção no cliente `sandbox` antes de corrigir.
        if "role" in update_data:
            validar_atribuicao_de_papel(current_user, update_data["role"])

        # Handle preferences specifically to merge instead of replace
        ai_fields = ["ai_tone", "ai_style", "ai_context"]
        has_ai_updates = any(field in update_data for field in ai_fields)

        if has_ai_updates or "preferences" in update_data:
            current_preferences = user.preferences or {}

            # Merge explicit AI fields
            for field in ai_fields:
                if field in update_data:
                    current_preferences[field] = update_data.pop(field)

            # Merge general preferences if provided
            if "preferences" in update_data:
                prefs_to_merge = update_data.pop("preferences")
                if isinstance(prefs_to_merge, dict):
                    current_preferences.update(prefs_to_merge)

            user.preferences = current_preferences
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(user, "preferences")

        # Update remaining fields
        for key, value in update_data.items():
            setattr(user, key, value)

        await self.db.commit()
        await self.db.refresh(user)

        return UserResponse.model_validate(user_to_response_dict(user))

    async def update_onboarding(
        self,
        user_id: UUID,
        step: Optional[int],
        version: Optional[int],
        current_user: User,
    ) -> UserResponse:
        """
        Update user onboarding progress.

        Args:
            user_id: User ID
            step: Current onboarding step
            version: Onboarding version (e.g., when completed)
            current_user: Current authenticated user

        Returns:
            UserResponse: Updated user data
        """
        if user_id != current_user.id:
            raise ForbiddenError("You can only update your own onboarding progress")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        if step is not None:
            user.onboarding_step = step
        if version is not None:
            user.onboarding_version = version
            if version >= 1:  # Assuming 1 is the completed version for now
                user.has_completed_onboarding = True
                user.onboarding_step = None  # Clear step on completion

        await self.db.commit()
        await self.db.refresh(user)

        return UserResponse.model_validate(user_to_response_dict(user))

    async def delete_user(self, user_id: UUID, current_user: User) -> None:
        """
        Delete user (soft delete).

        Args:
            user_id: User ID
            current_user: Current authenticated user

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
            BadRequestError: If trying to delete own account
        """
        if not check_permission(current_user, "user", "delete"):
            raise ForbiddenError("You don't have permission to delete users")

        if user_id == current_user.id:
            raise BadRequestError("You cannot delete your own account")

        user = await self.user_repo.get_by_id(user_id)

        # Sky operator guard. SKY internal staff doing JIT support of
        # customer tenants carry is_sky_operator=True and must NEVER be
        # auto-deactivated by the demo TTL sweep, the orphan-agent
        # reaper, or an admin who clicks the wrong button.
        if user and getattr(user, "is_sky_operator", False):
            raise ForbiddenError(
                "Cannot deactivate a SKY operator account. Clear "
                "is_sky_operator first if this is intentional."
            )

        # Tenant Owner guard. Tenant founders carry role="owner" and
        # cannot be deactivated by anyone except via an explicit
        # ownership-transfer flow. Lucas's 2026-04-30 follow-up: the
        # 2026-04-17 incident on Lais was a regression *because* her
        # row could be soft-deleted by a sweep; protecting all owners
        # at this same chokepoint closes the same hole for the actual
        # tenant founders without needing to abuse the is_sky_operator
        # flag (which is for SKY internal staff, not for customers).
        if user and getattr(user, "role", None) in ("super_admin", "owner"):
            raise ForbiddenError(
                "Cannot deactivate the tenant owner. Transfer ownership "
                "first via the tenant settings."
            )
        if not user:
            raise NotFoundError("User not found")

        await self.user_repo.delete(user_id)

        # W12 wire-in — pause every active agent the deactivated user
        # created, regardless of scope (Personal / Space / Crew / Org).
        # Best-effort: failures here are logged but do NOT roll back
        # the user deletion. The 15-min periodic sweep
        # (sweep_orphan_agents) catches any miss.
        try:
            from src.services.agent_revocation_service import (
                AgentRevocationService,
            )
            await AgentRevocationService(self.db).revoke_on_user_deactivation(
                user_id=user_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            import logging
            logging.getLogger(__name__).warning(
                "Agent revocation on user deactivation failed (user=%s): %s. "
                "Periodic sweep will catch up.",
                user_id, exc,
            )

        await self.db.commit()

    async def restore_user(self, user_id: UUID, current_user: User) -> UserResponse:
        """
        Restore a soft-deleted user.

        Reverses delete_user() — clears `deleted_at` so the user can
        sign in via SSO again. Required because the SSO callback now
        REJECTS soft-deleted users (with a clear "deactivated" error)
        instead of silently auto-restoring them on login. This gives
        admins explicit, opt-in control: a delete that shouldn't have
        happened can be undone here without a SQL UPDATE.

        Same permission as delete (`user:delete`) — the same group of
        people who can deactivate are the ones who can reactivate.

        Raises:
            NotFoundError: if no soft-deleted user with that id exists
            ForbiddenError: if caller lacks user:delete permission
        """
        if not check_permission(current_user, "user", "delete"):
            raise ForbiddenError("You don't have permission to restore users")

        # Use the explicit "including deleted" lookup — get_by_id
        # filters deleted_at IS NULL so it would 404 the very user
        # we're trying to restore.
        from sqlalchemy import select as _select

        from src.models.user import User as _User

        result = await self.db.execute(_select(_User).where(_User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found")
        if user.deleted_at is None:
            # Idempotent — already active, nothing to do
            return UserResponse.model_validate(user_to_response_dict(user))

        user.deleted_at = None
        await self.db.commit()
        await self.db.refresh(user)

        import logging
        logging.getLogger(__name__).info(
            "🔄 User restored by admin: user_id=%s admin_id=%s",
            user_id, current_user.id,
        )
        return UserResponse.model_validate(user_to_response_dict(user))

    async def get_user_permissions(self, user_id: UUID, current_user: User) -> dict:
        """
        Get user permissions.

        Args:
            user_id: User ID
            current_user: Current authenticated user

        Returns:
            dict: User permissions

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        # Users can view their own permissions, admins can view any
        if user_id != current_user.id and not check_permission(current_user, "user", "read"):
            raise ForbiddenError("You don't have permission to view this user's permissions")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        return get_user_permissions(user)

    async def update_user_permissions(
        self, user_id: UUID, permissions: dict, current_user: User
    ) -> dict:
        """
        Update user permissions (by changing role).

        Args:
            user_id: User ID
            permissions: Permissions data (contains role)
            current_user: Current authenticated user

        Returns:
            dict: Updated permissions

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        if not check_permission(current_user, "user", "update"):
            raise ForbiddenError("You don't have permission to update user permissions")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        # Update role if provided
        if "role" in permissions:
            new_role = permissions["role"]
            # A lista à mão dizia ["admin", "user", "viewer"]: recusava
            # `member` — o papel normal de toda a gente — e aceitava `viewer`,
            # que nem sequer é um papel de cliente (é de espaço/equipa). Passa
            # a usar a mesma validação do outro caminho, que é a única forma
            # de as duas não voltarem a divergir.
            validar_atribuicao_de_papel(current_user, new_role)
            user.role = new_role
            await self.db.commit()
            await self.db.refresh(user)

        return get_user_permissions(user)

    async def invite_user(
        self,
        user_id: UUID,
        invite_data: dict,
        current_user: User,
        base_url: Optional[str] = None,
    ) -> UserResponse:
        """
        Invite user (resend invitation or send welcome email).

        Args:
            user_id: User ID
            invite_data: Invite data (e.g., workspace_id, role)
            current_user: Current authenticated user

        Returns:
            UserResponse: User data

        Raises:
            NotFoundError: If user not found
            ForbiddenError: If user doesn't have permission
        """
        if not check_permission(current_user, "user", "update"):
            raise ForbiddenError("You don't have permission to invite users")

        # A mesma bifurcação do ``create_user``: num cliente só-SSO não há
        # palavra-passe para reenviar, mas continua a fazer sentido relembrar a
        # pessoa de que tem acesso e por que porta entra. Recusar era deixar o
        # administrador sem forma nenhuma de insistir.
        methods = await self._tenant_auth_methods()
        password_login = bool(methods.get("password"))

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        # Check if user needs a new invite token
        import secrets
        from datetime import datetime, timedelta, timezone

        should_generate_token = False
        if not user.invite_token:
            should_generate_token = True
        elif user.invite_expires_at:
            # Check expiry (normalize to UTC)
            expires_at = user.invite_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at < datetime.now(timezone.utc):
                should_generate_token = True

        if should_generate_token and password_login:
            user.invite_token = secrets.token_urlsafe(32)
            user.invite_expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            user.invited_by = current_user.id
            await self.db.commit()
            await self.db.refresh(user)

        # Prefer the tenant host the admin is actually on (``base_url``) so the
        # invitee lands on the tenant front-end and the token validates against
        # the tenant DB. Fall back to the platform CORS origin only for
        # non-request callers.
        frontend_url = base_url
        if not frontend_url and getattr(settings, "CORS_ORIGINS", None):
            frontend_url = settings.CORS_ORIGINS.split(",")[0].strip()
        if not frontend_url:
            frontend_url = "http://localhost:3000"
        frontend_url = frontend_url.rstrip("/")

        email_success = False
        try:
            email_service = EmailService()
            if password_login:
                link = f"{frontend_url}/auth/accept-invite?token={user.invite_token}"
                email_success = email_service.send_invite_email(
                    user.email, link, current_user.name
                )
            else:
                email_success = email_service.send_sso_access_email(
                    user.email,
                    login_link=f"{frontend_url}/login",
                    inviter_name=current_user.name,
                    provider_label=self._sso_provider_label(methods),
                )
            if not email_success:
                logger.warning("Access email not accepted for %s", user.email)
        except Exception:
            logger.exception("Error sending access email to %s", user.email)

        return UserResponse.model_validate(
            {**user_to_response_dict(user), "access_email_sent": bool(email_success)}
        )
