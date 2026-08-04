"""FastAPI dependencies."""

# Forward reference
from typing import TYPE_CHECKING, AsyncGenerator, Optional
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.exceptions import UnauthorizedError
from src.models.user import User

if TYPE_CHECKING:
    pass

# Create HTTPBearer security scheme for Swagger
security = HTTPBearer(
    bearerFormat="JWT",
    description="Enter JWT token obtained from /api/v1/auth/login endpoint",
    auto_error=False,
)


async def get_db_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """Tenant-aware database session (Projeto A — PR #6).

    Routes the session through ``TenantConnectionManager.session_for``
    so handlers that depend on this function automatically operate on
    the tenant attached by the resolver middleware. When
    ``MULTI_TENANT_ENABLED`` is False every request gets the default
    context, the manager hands back the global ``AsyncSessionLocal``,
    and the legacy behaviour is preserved exactly.

    FastAPI injects ``request`` automatically. Tests that override
    this dependency via ``app.dependency_overrides[get_db_session]``
    keep working unchanged — the override is keyed on the function
    object, not on the signature. Callers that need a tenant-scoped
    session outside the request scope should use
    :func:`get_db_session_for_context` below.
    """
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.core.tenant_context import DEFAULT_TENANT_CONTEXT

    ctx = getattr(request.state, "tenant_context", None) or DEFAULT_TENANT_CONTEXT
    session = tenant_connection_manager.session_for(ctx)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """
    Get current authenticated user.

    Args:
        request: FastAPI request
        credentials: HTTP Bearer token credentials (for Swagger UI)
        db: Database session

    Returns:
        User: Current user

    Raises:
        UnauthorizedError: If user not authenticated
    """
    import logging

    logger = logging.getLogger(__name__)

    # IMPORTANT: In FastAPI, dependencies are resolved BEFORE HTTP middlewares execute.
    # So we need to validate the token directly here, not rely on middleware.
    # However, we also check request.state in case middleware already set it (for consistency).

    user_id = None

    # First, try to get user_id from request.state (set by middleware if it executed)
    if hasattr(request, "state"):
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            logger.debug(f"🔍 Found user_id in request.state: {user_id}")

    # If not in state, extract and validate token directly from Authorization header
    if not user_id:
        authorization = request.headers.get("Authorization")
        if authorization:
            try:
                scheme, token = authorization.split(
                    " ", 1
                )  # Use maxsplit=1 to handle tokens with spaces
                if scheme.lower() == "bearer":
                    # Try to verify as custom JWT first
                    from src.core.security import verify_token

                    payload = None
                    auth_type = "custom"
                    try:
                        payload = verify_token(token, token_type="access")
                        user_id = payload.get("sub")
                        logger.debug(f"🔍 Token verified as custom JWT: {user_id}")
                    except Exception:
                        # If custom JWT fails, try Auth0 token
                        try:
                            from src.config.auth0 import auth0_settings
                            from src.services.auth0_service import Auth0Service

                            if auth0_settings.is_auth0_enabled:
                                auth0_service = Auth0Service(db)
                                payload = await auth0_service.verify_auth0_token(token)
                                auth0_id = payload.get("sub")
                                if auth0_id:
                                    # Get user from Auth0 ID
                                    user = await auth0_service.get_user_from_auth0(auth0_id)
                                    if user:
                                        user_id = str(user.id)
                                        auth_type = "auth0"
                                        logger.debug(
                                            f"🔍 Token verified as Auth0, user_id: {user_id}"
                                        )
                                    else:
                                        logger.warning(
                                            f"Auth0 token valid but user not found: {auth0_id}"
                                        )
                        except (ImportError, ValueError) as e:
                            logger.debug(f"Auth0 verification not available: {str(e)}")

                    if user_id:
                        # Ensure request.state exists
                        if not hasattr(request, "state"):
                            # This shouldn't happen, but just in case
                            logger.warning("request.state doesn't exist, creating it")
                        # Store in request.state for other middlewares/dependencies
                        request.state.user_id = str(user_id)
                        request.state.user_role = payload.get("role", "user") if payload else "user"
                        request.state.auth_type = auth_type
                        logger.debug(
                            f"🔍 Validated token and set user_id in state: {user_id}, auth_type: {auth_type}"
                        )
            except ValueError as e:
                # Invalid authorization header format
                logger.debug(f"🔍 Invalid authorization header format: {str(e)}")
            except Exception as e:
                logger.debug(f"🔍 Token validation failed: {str(e)}")
                # Fall through to error below

    # If no Authorization header succeeded, try the ``?access_token=…``
    # query parameter. Streaming endpoints (SSE / WebSocket) cannot send
    # custom headers from the browser, so the FE appends the JWT to the
    # URL — mirrored convention used by ``tenantLogsWsUrl`` and
    # ``jobEventsSseUrl`` on the FE. Only ``access_token`` is honoured to
    # avoid colliding with the legacy ``?token=`` used by chat/cursor WS
    # handlers (which validate the token themselves, bypassing this dep).
    if not user_id:
        qs_token = request.query_params.get("access_token")
        if qs_token:
            try:
                from src.core.security import verify_token

                payload = verify_token(qs_token, token_type="access")
                user_id = payload.get("sub")
                if user_id:
                    request.state.user_id = str(user_id)
                    request.state.user_role = payload.get("role", "user")
                    request.state.auth_type = "custom_query"
                    logger.debug(f"🔍 Token verified from query param: {user_id}")
            except Exception as e:
                logger.debug(f"🔍 Query-param token validation failed: {str(e)}")

    # Also check credentials from Swagger UI (HTTPBearer)
    if not user_id and credentials:
        try:
            from src.core.security import verify_token

            payload = None
            auth_type = "custom"
            try:
                payload = verify_token(credentials.credentials, token_type="access")
                user_id = payload.get("sub")
                logger.debug(f"🔍 Credentials verified as custom JWT: {user_id}")
            except Exception:
                # Try Auth0 token
                try:
                    from src.config.auth0 import auth0_settings
                    from src.services.auth0_service import Auth0Service

                    if auth0_settings.is_auth0_enabled:
                        auth0_service = Auth0Service(db)
                        payload = await auth0_service.verify_auth0_token(credentials.credentials)
                        auth0_id = payload.get("sub")
                        if auth0_id:
                            user = await auth0_service.get_user_from_auth0(auth0_id)
                            if user:
                                user_id = str(user.id)
                                auth_type = "auth0"
                                logger.debug(
                                    f"🔍 Credentials verified as Auth0, user_id: {user_id}"
                                )
                except (ImportError, ValueError) as e:
                    logger.debug(f"Auth0 verification not available: {str(e)}")

            if user_id:
                request.state.user_id = str(user_id)
                request.state.user_role = payload.get("role", "user") if payload else "user"
                request.state.auth_type = auth_type
                logger.debug(
                    f"🔍 Validated token from credentials and set user_id: {user_id}, auth_type: {auth_type}"
                )
        except Exception as e:
            logger.debug(f"🔍 Credentials validation failed: {str(e)}")

    if not user_id:
        logger.warning(
            f"❌ User not authenticated - no valid token found. Path: {request.url.path}"
        )
        raise UnauthorizedError("User not authenticated")

    from src.repositories.user import UserRepository

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(UUID(user_id))
    if not user:
        raise UnauthorizedError("User not found")

    # Atomic activity tracking — fire-and-forget, does NOT block the request.
    # The WHERE clause inside update_last_active_atomic() ensures only one
    # concurrent writer wins (the rest skip silently). No lock storm possible.
    import asyncio

    from src.config.database import AsyncSessionLocal

    async def _track_activity(uid: UUID) -> None:
        try:
            async with AsyncSessionLocal() as tracking_session:
                repo = UserRepository(tracking_session)
                await repo.update_last_active_atomic(uid, cooldown_seconds=60)
        except Exception as exc:
            logger.debug(f"Activity tracking skipped: {exc}")

    asyncio.ensure_future(_track_activity(UUID(user_id)))

    return user


async def enforce_device_tenant(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """BE-01 — enforce the signed tenant claim on device (no-subdomain) requests.

    Previously the ``resolve_device_tenant`` policy existed and was unit-tested
    but was **never wired into the request path** — so a device token with no
    tid, or a tid the user has been off-boarded from, was silently accepted.
    This dependency is that missing wiring.

    - No-op unless ``MULTI_TENANT_ENABLED`` (single-tenant mode is unaffected).
    - Um pedido é "de dispositivo" quando o **token** carrega ``tid``. Tokens
      da web e do Internal Console não o carregam e passam sem verificação,
      como sempre passaram.
    - Pedidos de dispositivo aplicam a política: tid que não resolve → 400,
      ou tid de que o utilizador não é membro → 403 (a pertença é reverificada
      a cada pedido, portanto o off-boarding morde mesmo com token válido).

    O discriminador é o token e nunca um header. Decidir por header deixava
    um cliente móvel escolher se queria ou não ser verificado.
    """
    from src.config.settings import settings

    if not settings.MULTI_TENANT_ENABLED:
        return

    from src.api.middleware.tenant_resolver import _load_tenant_by_id, _slug_from_host

    from src.core.device_tenant import (
        TENANT_CLAIM,
        DeviceResolution,
        resolve_device_tenant,
    )
    from src.core.exceptions import BadRequestError, ForbiddenError
    from src.core.security import verify_token
    from src.services.tenant_membership_service import TenantMembershipService

    authorization = request.headers.get("Authorization") or ""
    claims: dict = {}
    if authorization.lower().startswith("bearer "):
        try:
            claims = verify_token(authorization.split(" ", 1)[1], token_type="access")
        except Exception:
            claims = {}

    # A ordem aqui é a correcção, e é subtil.
    #
    # Um token que carrega `tid` é sempre verificado — antes de olhar
    # para qualquer header. Era este o buraco: a versão anterior
    # perguntava primeiro "veio um X-Tenant-Slug?" e, em caso
    # afirmativo, devolvia sem verificar nada. Bastava um cliente móvel
    # acrescentar o header para saltar o portão inteiro, e com ele a
    # garantia de que quem sai da empresa perde acesso assim que a linha
    # de pertença desaparece (T-01.8) — a única razão de o portão
    # existir. Um token assinado não pode perder o seu `tid`, portanto
    # verificar primeiro pelo token não é contornável.
    #
    # Não era brecha entre clientes: a sessão é scoped ao tenant, o
    # utilizador não existe na base do outro cliente e o pedido morre em
    # 401. Era brecha na promessa de off-boarding.
    if not claims.get(TENANT_CLAIM):
        # Sem `tid`. Se veio sub-domínio ou X-Tenant-Slug, é a web ou o
        # Internal Console — que fala com o hostname da própria
        # plataforma e por isso depende do header. Passa, como sempre
        # passou.
        if _slug_from_host(request.headers.get("host")) or request.headers.get("x-tenant-slug"):
            return
        # Sem tid e sem nenhuma pista de tenant: pedido de dispositivo
        # mal formado. Recusar explicitamente (400) em vez de deixar cair
        # no tenant por omissão, que seria servir o espaço errado em vez
        # de dizer que não sabe qual é. Regra do Felipe, mantida (T-01.4).
        raise BadRequestError(
            "Tenant unresolved — a device request must carry a valid tenant claim."
        )

    async def _is_member(user_id: str, tid: str) -> bool:
        return await TenantMembershipService.is_member(db, user_id, tid)

    result = await resolve_device_tenant(
        claims, load_tenant_by_id=_load_tenant_by_id, is_member=_is_member
    )
    if result.resolution is DeviceResolution.UNRESOLVED:
        raise BadRequestError(
            "Tenant unresolved — a device request must carry a valid tenant claim."
        )
    if result.resolution is DeviceResolution.FORBIDDEN:
        raise ForbiddenError("You are not a member of the requested workspace.")


async def get_db_session_for_context(ctx=None) -> AsyncGenerator[AsyncSession, None]:
    """Tenant-aware session for non-FastAPI callers (Celery, scripts).

    Reads ``current_tenant()`` when no context is provided. The default
    tenant routes back to the global pool, so this remains a drop-in
    replacement for ``async with AsyncSessionLocal as session: ...``
    in code that does not have access to ``request``.
    """
    from src.config.tenant_connection_manager import tenant_connection_manager
    from src.core.tenant_context import current_tenant

    if ctx is None:
        ctx = current_tenant()

    session = tenant_connection_manager.session_for(ctx)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ─── Autenticação de serviço (motor de AI → backend) ────────────────

# Claim que distingue um token emitido pelo serviço de AI de um token de
# pessoa. Ambos são assinados com o mesmo JWT_SECRET_KEY — sem esta
# marca o backend não os consegue distinguir, e foi por isso que
# `/ai/scan-insights/notify` ficou aberto a qualquer utilizador
# autenticado.
SERVICE_CLAIM = "svc"


async def require_service_principal(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """Só o motor de AI passa. Uma pessoa autenticada não.

    O caso que isto fecha: ``POST /ai/scan-insights/notify`` recebe um
    ``space_id`` no corpo e escreve um ``AgentFinding`` com ele. Estando
    guardado apenas por :func:`get_current_user`, qualquer funcionário
    autenticado podia forjar um insight num espaço a que não tem acesso
    — e o insight aparece na app como se tivesse sido produzido pela AI.
    Não atravessa a fronteira entre clientes (a sessão é scoped ao
    tenant, portanto a escrita fica na base do próprio cliente), mas
    dentro de um cliente é falsificação de conteúdo que o produto
    apresenta como verdade apurada por máquina.

    A verificação é sobre o **token**, não sobre o utilizador: o serviço
    de AI assina os seus pedidos com a identidade de um utilizador real
    (``AI_SERVICE_USER_ID``), portanto olhar para o papel do utilizador
    não distinguiria nada. O que distingue é o claim ``svc``, que só o
    emissor com posse do segredo consegue produzir.
    """
    from src.core.exceptions import ForbiddenError
    from src.core.security import verify_token

    authorization = request.headers.get("Authorization") or ""
    claims: dict = {}
    if authorization.lower().startswith("bearer "):
        try:
            claims = verify_token(authorization.split(" ", 1)[1], token_type="access")
        except Exception:  # noqa: BLE001 — token inválido cai no 403 abaixo
            claims = {}

    if not claims.get(SERVICE_CLAIM):
        raise ForbiddenError("This endpoint is reserved for internal service calls.")
    return current_user
