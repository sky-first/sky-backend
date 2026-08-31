"""Space service."""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import BackgroundTasks
# `select` era usado em cinco sítios deste ficheiro e nunca importado ao
# nível do módulo. Cada um deles rebentava com `NameError: name 'select' is
# not defined` — e os cinco são exactamente o bloco que dá acesso a quem
# pertence a uma **equipa** dentro do projeto sem ser membro directo dele.
# Alguém já tinha tropeçado nisto e contornou com um `import select as
# _select` local (linha ~663) em vez de corrigir aqui.
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.crew import Crew
from src.models.space import Space, SpaceConnection, SpaceMember
from src.models.user import User
from src.repositories.connection import ConnectionMetadataRepository, ConnectionRepository
from src.repositories.space import SpaceMemberRepository, SpaceRepository, SpaceTableRepository
from src.core.permissions import TENANT_ADMIN_ROLES
from src.schemas.space import (
    SpaceCreate,
    SpaceMemberCreate,
    SpaceMemberResponse,
    SpaceResponse,
    SpaceStatsResponse,
    SpaceTableCreate,
    SpaceUpdate,
)

logger = logging.getLogger(__name__)

# Space→Crew model (2026-06): the name of the default crew auto-created
# with every space. Lucas's directive: "General" (the other candidate was
# "all"). Kept as a module constant so the resolver, backfill and tests
# all agree on the canonical name.
DEFAULT_CREW_NAME = "General"


class SpaceService:
    """Space service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize space service.

        Args:
            db: Database session
        """
        self.db = db
        self.space_repo = SpaceRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.member_repo = SpaceMemberRepository(db)
        self.metadata_repo = ConnectionMetadataRepository(db)
        self.table_repo = SpaceTableRepository(db)
        self.ai_client = AIServiceHTTPClient()

    async def _require_space_role(
        self,
        space_id: UUID,
        user: User,
        *,
        min_role: str = "viewer",
    ) -> None:
        """Two-axis RBAC helper (Phase 7).

        Rule: platform `owner`/`admin` bypass unconditionally. Otherwise
        the user must be a space_member AND their per-space role must
        be at least `min_role` (ranked viewer < editor < owner).
        Anything outside that triple is treated as below-floor and
        denied — callers must speak Phase 7 vocabulary.
        """
        if user.role in TENANT_ADMIN_ROLES:
            return
        member = await self.member_repo.get_by_space_and_user(space_id, user.id)
        if not member:
            raise ForbiddenError("Access denied to this space")
        rank = {"viewer": 0, "editor": 1, "owner": 2}
        member_rank = rank.get(member.role, -1)
        min_rank = rank.get(min_role, 0)
        if member_rank < min_rank:
            raise ForbiddenError(f"Requires space role '{min_role}' (you have '{member.role}')")

    async def list_spaces(self, user: User, skip: int = 0, limit: int = 100) -> List[SpaceResponse]:
        """
        List spaces.

        Args:
            user: Current user
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[SpaceResponse]: List of spaces

        Notes:
            Tenant owner / admin / sky_operator see ALL non-deleted
            Spaces (including demo ones they didn't personally create
            or join). Lucas reported missing demo Spaces in his
            sidebar — he is owner of the tenant and should see every
            Space the demo flow has provisioned.
        """
        try:
            is_admin_like = getattr(user, "role", None) in (
                "admin",
                "owner",
                "super_admin",
            ) or getattr(user, "is_sky_operator", False)
            if is_admin_like:
                spaces_data = await self.space_repo.get_all_with_stats(skip=skip, limit=limit)
            else:
                spaces_data = await self.space_repo.get_by_user_with_stats(
                    user.id, skip=skip, limit=limit
                )
            result = []
            for space_data in spaces_data:
                try:
                    result.append(SpaceResponse.model_validate(space_data))
                except Exception as e:
                    logger.error(
                        f"Error validating space {space_data.get('id')}: {str(e)}",
                        exc_info=True,
                    )
                    try:
                        space_data["color"] = None
                        result.append(SpaceResponse.model_validate(space_data))
                    except Exception as e2:
                        logger.error(
                            f"Error validating space {space_data.get('id')} with color=None: {str(e2)}",
                            exc_info=True,
                        )
                        continue
            return result
        except Exception as e:
            logger.error(f"Error listing spaces for user {user.id}: {str(e)}", exc_info=True)
            raise

    async def get_space(self, space_id: UUID, user: User) -> SpaceResponse:
        """
        Get space by ID.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            SpaceResponse: Space data

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id and user.role not in TENANT_ADMIN_ROLES:
            is_member = await self.member_repo.get_by_space_and_user(space_id, user.id) is not None
            if not is_member:
                # Phase 2.5 — Crew membership inside the Space also
                # grants visibility (a Crew is a sub-team of the Space).
                from src.models.crew import Crew as _Crew
                from src.models.crew import CrewMember as _CrewMember

                _crew_check = await self.db.execute(
                    select(_CrewMember.id)
                    .join(_Crew, _Crew.id == _CrewMember.crew_id)
                    .where(_CrewMember.user_id == user.id, _Crew.space_id == space_id)
                    .limit(1)
                )
                if _crew_check.scalar_one_or_none() is None:
                    raise ForbiddenError("Access denied to this space")

        return SpaceResponse.model_validate(space)

    async def create_space(self, user: User, space_data: SpaceCreate) -> SpaceResponse:
        """
        Create a new space.

        Args:
            user: Current user
            space_data: Space creation data

        Returns:
            SpaceResponse: Created space
        """
        space = await self.space_repo.create(
            name=space_data.name,
            description=space_data.description,
            color=space_data.color,
            icon=space_data.icon,
            created_by=user.id,
        )

        # Auto-add creator as the first member of the space, with the
        # `owner` role. The role is required: SpaceMember.role defaults
        # to "editor" at the model level, which would leave the creator
        # unable to delete or admin their own Space. The Phase 7 RBAC
        # rewrite tightened `spaces.create` to admin_or_above, so a
        # platform Member can no longer reach this code path via the
        # API anyway — the only callers are platform Owner/Admin and
        # the demo signup factory, both of whom should own what they
        # create. See feat/rbac-spaces-create-admin-only-and-creator-owner.
        await self.member_repo.create(
            space_id=space.id,
            user_id=user.id,
            role="owner",
        )

        # Auto-create a service principal for this space (C3 in master plan).
        # Collaborative agents created on space-scoped pages run as this
        # identity so they survive the creator leaving the org.
        from src.models.service_principal import ServicePrincipal

        sp = ServicePrincipal(
            space_id=space.id,
            name=f"sa-space-{str(space.id)[:8]}",
        )
        self.db.add(sp)

        await self.db.commit()
        await self.db.refresh(space)

        # Ingest the Space into the knowledge graph so RAG knows about
        # it. Without this the chat/agents never have a concept of the
        # Space they're scoped to beyond its id. Failures here are
        # logged and swallowed — a broken AI side must not block Space
        # creation (see Bug 6a phase 3 in session checkpoint).
        try:
            # A Space is collaborative by definition — its embedding must
            # be visible to every member, not just the creator. Leaving
            # owner_user_id NULL lets the RAG's Personal-vs-collaborative
            # filter treat it as space-wide. Stamping the creator here
            # (pre-fix) caused the Space record to behave like a Personal
            # entity and silently hid it from other members.
            await self.ai_client.ingest_knowledge_graph(
                {
                    "id": str(space.id),
                    "entity_type": "space",
                    "name": space.name,
                    "description": space.description,
                    "space_id": str(space.id),
                    "crew_id": None,
                    "owner_user_id": None,
                    "entity_details": {
                        "created_by": str(user.id),
                        "color": space.color,
                        "icon": space.icon,
                    },
                }
            )
        except Exception as exc:
            logger.warning(f"AI ingest failed for space {space.id}: {exc}")

        # Space→Crew model (2026-06): every space owns at least one crew,
        # the default "General" crew. Questions/agents are ALWAYS scoped to
        # a crew (never a bare space) — see the crew-required guard in
        # src/api/v1/ai.py and src/api/v1/agents.py. "General" means
        # "shared with every member of this space" but it is still
        # permission-restricted at the table level (TableMetadata.crew_id);
        # it is NOT an unrestricted "all tables" surface. Creating it here
        # guarantees the UI can always force a crew selection. Failure to
        # create it is logged + swallowed so it never blocks Space creation;
        # the backfill (ensure_default_crew) repairs any miss.
        try:
            from src.schemas.crew import CrewCreate
            from src.services.crew_service import CrewService

            await CrewService(self.db).create_crew(
                user,
                CrewCreate(
                    name=DEFAULT_CREW_NAME,
                    description="Default crew — shared with every member of this space.",
                    space_id=space.id,
                ),
            )
        except Exception as exc:
            logger.warning(f"Default crew creation failed for space {space.id}: {exc}")

        return SpaceResponse.model_validate(space)

    async def ensure_default_crew(self, space_id: UUID, user: User) -> None:
        """Idempotent backfill: guarantee a space has its default "General"
        crew. Safe to call on existing spaces created before the Space→Crew
        model (2026-06). No-op when a crew named "General" already exists.
        """
        from src.schemas.crew import CrewCreate
        from src.services.crew_service import CrewService

        crew_service = CrewService(self.db)
        existing = await crew_service.list_crews(user, space_id=space_id, limit=500)
        if any((c.name or "").strip().lower() == DEFAULT_CREW_NAME.lower() for c in existing):
            return
        await crew_service.create_crew(
            user,
            CrewCreate(
                name=DEFAULT_CREW_NAME,
                description="Default crew — shared with every member of this space.",
                space_id=space_id,
            ),
        )

    async def update_space(
        self, space_id: UUID, user: User, space_data: SpaceUpdate
    ) -> SpaceResponse:
        """
        Update space.

        Args:
            space_id: Space ID
            user: Current user
            space_data: Space update data

        Returns:
            SpaceResponse: Updated space

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        await self._require_space_role(space_id, user, min_role="owner")

        update_data = space_data.model_dump(exclude_unset=True)
        space = await self.space_repo.update(space_id, **update_data)
        await self.db.commit()
        await self.db.refresh(space)

        return SpaceResponse.model_validate(space)

    async def delete_space(
        self, space_id: UUID, user: User, confirmacao: Optional[str] = None
    ) -> None:
        """Apaga um projeto — com o nome escrito à mão.

        **O travão existe porque «Apagar» fica ao lado de «Arquivar».** Um
        toque a mais e vai-se um projeto inteiro com os seus dados e conversas.
        Escrever o nome é o mesmo travão que o GitHub usa para apagar um
        repositório, e funciona: obriga a ler o que se está a apagar.

        `confirmacao` a `None` mantém o comportamento antigo, para os
        chamadores internos (limpeza de demo, testes) não terem de o saber.

        Args:
            space_id: Space ID
            user: Current user
            confirmacao: o nome do projeto, escrito por quem apaga

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
            BadRequestError: se o nome não bater certo
        """
        import logging

        from src.config.settings import get_settings

        logger = logging.getLogger(__name__)

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if confirmacao is not None and confirmacao.strip() != (space.name or "").strip():
            raise BadRequestError("Type the project name exactly to delete it.")

        settings = get_settings()

        # In development, allow any user to delete any space
        # In production, only admin or owner can delete
        if settings.is_development:
            # Development mode: allow any authenticated user to delete
            logger.info(
                f"🔴 [DELETE SPACE SERVICE] Development mode: Allowing user {user.id} to delete space {space_id} (created by {space.created_by})"
            )
        else:
            # Production mode: only admin or owner can delete
            if user.role not in TENANT_ADMIN_ROLES and space.created_by != user.id:
                raise ForbiddenError("Access denied to this space")

        # C6: end every agent scoped to this space before cascade-deleting.
        # The agents rows are kept (audit), but moved to status='ended' so
        # the worker / beat never schedules them again.
        from sqlalchemy import update as sa_update

        from src.models.agent import Agent

        await self.db.execute(
            sa_update(Agent)
            .where(
                Agent.scope == "space",
                Agent.scope_id == str(space_id),
                Agent.status != "ended",
            )
            .values(status="ended")
        )

        await self.space_repo.delete(space_id)
        await self.db.commit()
        logger.info(f"🔴 [DELETE SPACE SERVICE] Space {space_id} deleted successfully")

    async def get_space_crews(self, space_id: UUID, user: User) -> List[Crew]:
        """
        Get crews for a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[Crew]: List of crews

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        # Tenant admins/owners may list any space's crews (navigation/management
        # plane) — mirrors get_space_connections. Without this an admin who
        # isn't a member of a space got a 403 when entering it, so the FE never
        # resolved the default "General" crew (landed on a bare space + empty
        # page). Listing crews is not content; the per-crew content gates still
        # apply downstream.
        is_creator = space.created_by == user.id
        is_admin = (user.role or "").lower() in TENANT_ADMIN_ROLES
        is_member = await self.member_repo.get_by_space_and_user(space_id, user.id) is not None
        if not is_creator and not is_admin and not is_member:
            raise ForbiddenError("Access denied to this space")

        crews = await self.space_repo.get_space_crews(space_id)
        return crews

    async def get_space_connections(self, space_id: UUID, user: User) -> List[SpaceConnection]:
        """
        Get connections for a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[SpaceConnection]: List of space connections

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id and user.role not in TENANT_ADMIN_ROLES:
            is_member = await self.member_repo.get_by_space_and_user(space_id, user.id) is not None
            if not is_member:
                # Phase 2.5 — Crew membership inside the Space also
                # grants visibility (a Crew is a sub-team of the Space).
                from src.models.crew import Crew as _Crew
                from src.models.crew import CrewMember as _CrewMember

                _crew_check = await self.db.execute(
                    select(_CrewMember.id)
                    .join(_Crew, _Crew.id == _CrewMember.crew_id)
                    .where(_CrewMember.user_id == user.id, _Crew.space_id == space_id)
                    .limit(1)
                )
                if _crew_check.scalar_one_or_none() is None:
                    raise ForbiddenError("Access denied to this space")

        connections = await self.space_repo.get_space_connections(space_id)
        return connections

    async def add_space_connection(
        self, space_id: UUID, connection_id: UUID, user: User, background_tasks: BackgroundTasks
    ) -> SpaceConnection:
        """
        Add a connection to a space.

        Args:
            space_id: Space ID
            connection_id: Connection ID
            user: Current user
            background_tasks: FastAPI BackgroundTasks object

        Returns:
            SpaceConnection: The created association

        Raises:
            NotFoundError: If space or connection not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        await self._require_space_role(space_id, user, min_role="owner")

        connection = await self.connection_repo.get_by_id(connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        # Check if already exists
        existing = await self.space_repo.get_space_connection(space_id, connection_id)
        if existing:
            return existing

        # Create association using the repository's helper or manually
        space_connection = SpaceConnection(space_id=space_id, connection_id=connection_id)
        self.db.add(space_connection)
        await self.db.commit()
        await self.db.refresh(space_connection)

        # Trigger AI discovery for the connection in the background using BackgroundTasks abstraction
        background_tasks.add_task(
            self._trigger_ai_discovery,
            connection_id=str(connection_id),
            space_id=str(space_id),
        )

        return space_connection

    async def _trigger_ai_discovery(self, connection_id: str, space_id: str) -> None:
        """Helper to trigger AI discovery with proper error handling for BackgroundTasks."""
        try:
            await self.ai_client.discover_connection(
                connection_id=connection_id,
                space_id=space_id,
                run_in_background=True,
            )
        except Exception as e:
            logger.error(
                f"Background task failed: Auto-discovery for space {space_id} and connection {connection_id} failed: {str(e)}"
            )

    async def remove_space_connection(
        self, space_id: UUID, connection_id: UUID, user: User
    ) -> None:
        """
        Remove a connection from a space.

        Args:
            space_id: Space ID
            connection_id: Connection ID
            user: Current user

        Raises:
            NotFoundError: If space or association not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        await self._require_space_role(space_id, user, min_role="owner")

        association = await self.space_repo.get_space_connection(space_id, connection_id)
        if not association:
            raise NotFoundError("Connection not linked to this space")

        await self.db.delete(association)
        await self.db.commit()

    async def get_space_members(self, space_id: UUID, user: User) -> List[SpaceMemberResponse]:
        """
        Get all members of a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[SpaceMemberResponse]: List of members

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id and user.role not in TENANT_ADMIN_ROLES:
            is_member = await self.member_repo.get_by_space_and_user(space_id, user.id) is not None
            if not is_member:
                # Phase 2.5 — Crew membership inside the Space also
                # grants visibility (a Crew is a sub-team of the Space).
                from src.models.crew import Crew as _Crew
                from src.models.crew import CrewMember as _CrewMember

                _crew_check = await self.db.execute(
                    select(_CrewMember.id)
                    .join(_Crew, _Crew.id == _CrewMember.crew_id)
                    .where(_CrewMember.user_id == user.id, _Crew.space_id == space_id)
                    .limit(1)
                )
                if _crew_check.scalar_one_or_none() is None:
                    raise ForbiddenError("Access denied to this space")

        members = await self.member_repo.get_space_members(space_id)
        # Refresh user objects to ensure they're loaded
        for member in members:
            await self.db.refresh(member, ["user"])
        # Skip rows whose user has data the response schema cannot
        # validate (e.g. legacy emails with reserved TLDs like `.local`).
        # Without this the entire endpoint 500s and the FE permission
        # gate sees an empty membership list, which collapses every
        # space/crew role to "Member" in the UI.
        out: List[SpaceMemberResponse] = []
        for m in members:
            try:
                out.append(SpaceMemberResponse.model_validate(m))
            except Exception as exc:
                logger.warning(
                    "Skipping space_member %s with invalid payload: %s",
                    m.id,
                    exc,
                )
        return out

    async def update_space_member_role(self, space_id: UUID, user_id: UUID, role: str):
        """Change an existing member's per-space role (two-axis RBAC)."""
        from src.schemas.space import SPACE_MEMBER_ROLES

        role = (role or "").lower()
        if role not in SPACE_MEMBER_ROLES:
            raise BadRequestError(
                f"Invalid space role '{role}'. Use one of: {sorted(SPACE_MEMBER_ROLES)}"
            )

        member = await self.member_repo.get_by_space_and_user(space_id, user_id)
        if not member:
            raise NotFoundError("User is not a member of this space")

        member.role = role
        await self.db.commit()
        await self.db.refresh(member, ["user"])
        return member

    async def arquivar(self, space_id: UUID, user: User, arquivar: bool = True) -> Dict[str, Any]:
        """Arquiva um projeto — ou reabre-o.

        **Sai das listas; os dados e as conversas ficam.** Um projeto de teste
        que não se pode tirar da frente polui a lista para sempre, e apagar é
        demasiado para o que muitas vezes se quer, que é só arrumar.

        **E pausa os agentes.** Um projeto arquivado que continua a correr
        agentes é uma fatura que ninguém percebe. Ver §4.3 de
        ``docs/pessoas-equipas-e-projetos.md``.
        """
        from datetime import datetime, timezone

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")
        await self._require_space_role(space_id, user, min_role="owner")

        space.archived_at = datetime.now(timezone.utc) if arquivar else None

        pausados = 0
        if arquivar:
            from src.models.agent import Agent

            # O agente aponta ao projeto por `scope`/`scope_id`, e não por
            # uma coluna `space_id` — há agentes pessoais e de organização.
            agentes = (
                await self.db.execute(
                    select(Agent).where(
                        Agent.scope == "space",
                        Agent.scope_id == str(space_id),
                        Agent.status == "active",
                    )
                )
            ).scalars().all()
            for a in agentes:
                a.status = "paused"
                pausados += 1

        await self.db.commit()
        from src.services.notificar_o_projeto import notificar_o_projeto

        await notificar_o_projeto(
            self.db,
            space_id,
            tipo="system",
            title_key="notif.projectArchived" if arquivar else "notif.projectReopened",
            title_params={"project": space.name},
            excepto=user.id,
        )
        logger.info(
            "projeto_%s: space=%s por=%s agentes_pausados=%d",
            "arquivado" if arquivar else "reaberto",
            space_id,
            user.id,
            pausados,
        )
        return {"space_id": str(space_id), "arquivado": arquivar, "agentes_pausados": pausados}

    async def sair(self, space_id: UUID, user: User) -> Dict[str, Any]:
        """Tira-se a si próprio do projeto.

        Não existia: só o dono podia tirar alguém, e quem quisesse sair de um
        projeto onde já não trabalha não tinha por onde.

        **O último dono não sai.** Um projeto sem dono é um projeto que
        ninguém volta a gerir — a mesma regra que trava a despromoção (A2).
        """
        from src.services.acesso_ao_projeto import papel_no_projeto

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        meu = await papel_no_projeto(self.db, user.id, space_id)
        if meu is None:
            raise NotFoundError("You are not in this project.")

        if meu == "owner":
            outros = (
                await self.db.execute(
                    select(func.count())
                    .select_from(SpaceMember)
                    .where(
                        SpaceMember.space_id == space_id,
                        SpaceMember.role == "owner",
                        SpaceMember.user_id != user.id,
                    )
                )
            ).scalar_one()
            if not outros or space.created_by == user.id:
                raise BadRequestError(
                    "You are the only owner. Make someone else an owner first."
                )

        linha = (
            await self.db.execute(
                select(SpaceMember).where(
                    SpaceMember.space_id == space_id, SpaceMember.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if linha is not None:
            await self.db.delete(linha)
        await self.db.commit()
        logger.info("saiu_do_projeto: space=%s user=%s", space_id, user.id)
        # Quem continua a alcançar por equipa continua — e é honesto dizê-lo,
        # em vez de fingir que a saída cortou tudo.
        resta = await papel_no_projeto(self.db, user.id, space_id)
        return {"space_id": str(space_id), "ainda_alcanca_por_equipa": resta is not None}

    async def duplicar(self, space_id: UUID, user: User, nome: str) -> Dict[str, Any]:
        """Um projeto novo com as mesmas ligações e os mesmos acessos.

        **Não leva conversas.** Duplicar é montar a estrutura outra vez, não
        copiar o trabalho de ninguém — e conversas copiadas seriam respostas
        antigas a parecer novas.

        **E não leva ligações que quem duplica não pode ligar.** Duplicar não
        pode ser uma forma de contornar a permissão de ligar dados (A5): as
        que ficam de fora são devolvidas, para se dizer quais.
        """
        from src.models.space_crew import SpaceCrew

        origem = await self.space_repo.get_by_id(space_id)
        if not origem:
            raise NotFoundError("Space not found")
        await self._require_space_role(space_id, user, min_role="viewer")

        novo = await self.space_repo.create(
            name=nome, description=origem.description, created_by=user.id
        )
        await self.db.flush()

        # `assert_permission` lança; aqui quer-se um sim/não, porque
        # duplicar sem poder ligar dados **continua a duplicar** — só deixa as
        # ligações de fora, e diz quais.
        from src.services.rbac_service import RBACService as _RBAC

        try:
            await _RBAC(self.db).assert_permission(user, "connections.edit")
            pode_ligar = True
        except Exception:
            pode_ligar = False
        ligadas, de_fora = [], []
        for (conn_id,) in (
            await self.db.execute(
                select(SpaceConnection.connection_id).where(SpaceConnection.space_id == space_id)
            )
        ).all():
            if pode_ligar:
                self.db.add(SpaceConnection(space_id=novo.id, connection_id=conn_id))
                ligadas.append(str(conn_id))
            else:
                de_fora.append(str(conn_id))

        for crew_id, papel in (
            await self.db.execute(
                select(SpaceCrew.crew_id, SpaceCrew.role).where(SpaceCrew.space_id == space_id)
            )
        ).all():
            self.db.add(
                SpaceCrew(space_id=novo.id, crew_id=crew_id, role=papel, added_by=user.id)
            )

        for uid, papel in (
            await self.db.execute(
                select(SpaceMember.user_id, SpaceMember.role).where(
                    SpaceMember.space_id == space_id
                )
            )
        ).all():
            if uid != user.id:
                self.db.add(SpaceMember(space_id=novo.id, user_id=uid, role=papel))

        await self.db.commit()
        logger.info(
            "projeto_duplicado: origem=%s novo=%s por=%s ligacoes=%d de_fora=%d",
            space_id,
            novo.id,
            user.id,
            len(ligadas),
            len(de_fora),
        )
        return {
            "space_id": str(novo.id),
            "name": nome,
            "ligacoes": len(ligadas),
            "ligacoes_de_fora": len(de_fora),
        }

    async def equipa_geral(self, space_id: UUID) -> Optional[Crew]:
        """A equipa **Geral** deste projeto — a casa de quem é convidado à unidade.

        Ideia do Lucas a 26/08, e simplifica o modelo: em vez de uma segunda
        lista de "pessoas convidadas directamente" ao lado das equipas,
        convidar alguém é pô-lo na Geral. Passa a haver **um** sítio onde se
        procura gente — a equipa — e a regra fica de uma frase: *se não veio
        por uma equipa sua, veio pela Geral*.
        """
        return (
            await self.db.execute(
                select(Crew).where(
                    Crew.space_id == space_id,
                    Crew.name == DEFAULT_CREW_NAME,
                    Crew.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def pessoas_para_convidar(
        self, space_id: UUID, user: User, procura: str = "", limite: int = 20
    ) -> List[Dict[str, Any]]:
        """Procura gente na empresa inteira para convidar para este projeto.

        **Porque não se reutiliza `GET /users`.** Três razões. O portão é
        outro — quem manda aqui é ser dono *deste* projeto, e não uma
        permissão global de administrar utilizadores. Devolve no máximo 100 e
        sem procura, o que numa empresa de 300 pessoas é uma lista onde não se
        encontra ninguém. E não sabe esconder **quem já está no projeto** —
        que é a diferença entre uma lista útil e uma lista onde se convida
        alguém que já lá está para receber um erro a dizê-lo.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")
        await self._require_space_role(space_id, user, min_role="owner")

        from src.services.notificar_o_projeto import quem_esta_no_projeto

        ja_la = set(await quem_esta_no_projeto(self.db, space_id))

        # Só `deleted_at`. **Não** `status`: nesta tabela `status` é presença
        # (active/away/offline), e não estado de conta — filtrar por ele
        # esconderia toda a gente que não estivesse com a app aberta naquele
        # instante, e a pesquisa devolveria quase sempre uma lista vazia.
        q = select(User).where(User.deleted_at.is_(None))
        procura = (procura or "").strip()
        if procura:
            # Por nome **ou** email: procura-se pelo nome, mas há homónimos e
            # há quem só saiba o email de um colega.
            like = f"%{procura}%"
            q = q.where(or_(User.name.ilike(like), User.email.ilike(like)))
        # Pede-se mais do que se mostra porque quem já está no projeto é
        # descartado depois: pedir `limite` devolveria menos do que `limite`.
        linhas = (await self.db.execute(q.order_by(User.name).limit(limite + len(ja_la) + 10))).scalars().all()

        fora = [u for u in linhas if u.id not in ja_la][:limite]
        return [
            {"id": str(u.id), "name": u.name, "email": u.email, "avatar": u.avatar}
            for u in fora
        ]

    async def convidar_pessoa(
        self, space_id: UUID, user: User, alvo_id: UUID, papel: str = "editor"
    ) -> Dict[str, Any]:
        """Convida UMA pessoa. **Não lhe dá acesso** — só quando aceitar.

        Se convidar já desse acesso, o botão de aceitar era decoração e o de
        recusar era uma mentira: a pessoa já teria estado lá dentro, a ver
        números de uma área que talvez não seja a dela.
        """
        from src.models.convite_ao_projeto import ConviteAoProjeto
        from src.services.notificar_o_projeto import quem_esta_no_projeto

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")
        await self._require_space_role(space_id, user, min_role="owner")

        if papel not in ("owner", "editor", "viewer"):
            raise BadRequestError("Unknown role.")

        alvo = (
            await self.db.execute(
                select(User).where(User.id == alvo_id, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if alvo is None:
            raise NotFoundError("User not found")

        if alvo_id in set(await quem_esta_no_projeto(self.db, space_id)):
            raise BadRequestError("This person is already in the project.")

        pendente = (
            await self.db.execute(
                select(ConviteAoProjeto).where(
                    ConviteAoProjeto.space_id == space_id,
                    ConviteAoProjeto.user_id == alvo_id,
                    ConviteAoProjeto.estado == "pendente",
                )
            )
        ).scalar_one_or_none()
        if pendente is not None:
            raise BadRequestError("This person already has a pending invite.")

        convite = ConviteAoProjeto(
            space_id=space_id,
            user_id=alvo_id,
            papel=papel,
            estado="pendente",
            convidado_por=user.id,
        )
        self.db.add(convite)
        await self.db.commit()
        await self.db.refresh(convite)

        # Só a pessoa convidada é avisada. O projeto fica a saber quando ela
        # **entrar** — anunciar uma entrada que pode nunca acontecer é ruído,
        # e ruído é o que faz desligar as notificações todas.
        from src.schemas.notification import NotificationCreate
        from src.services.notification_service import NotificationService

        try:
            await NotificationService(self.db).create_notification(
                NotificationCreate(
                    user_id=alvo_id,
                    type="space_invite",
                    title="notif.projectInvite",
                    title_key="notif.projectInvite",
                    title_params={"person": user.name or user.email, "project": space.name},
                    entity_type="space",
                    entity_id=str(space_id),
                )
            )
        except Exception as exc:  # pragma: no cover - defensivo
            logger.warning("convite %s: aviso falhou: %s", convite.id, exc)

        logger.info(
            "convite_ao_projeto: space=%s alvo=%s papel=%s por=%s",
            space_id,
            alvo_id,
            papel,
            user.id,
        )
        return {
            "id": str(convite.id),
            "user_id": str(alvo_id),
            "name": alvo.name,
            "email": alvo.email,
            "papel": papel,
            "estado": "pendente",
        }

    async def meus_convites(self, user: User) -> List[Dict[str, Any]]:
        """Os convites que estão à espera de resposta desta pessoa."""
        from src.models.convite_ao_projeto import ConviteAoProjeto

        linhas = (
            await self.db.execute(
                select(ConviteAoProjeto, Space)
                .join(Space, Space.id == ConviteAoProjeto.space_id)
                .where(
                    ConviteAoProjeto.user_id == user.id,
                    ConviteAoProjeto.estado == "pendente",
                    Space.deleted_at.is_(None),
                )
                .order_by(ConviteAoProjeto.created_at.desc())
            )
        ).all()
        return [
            {
                "id": str(c.id),
                "space_id": str(c.space_id),
                "projeto": s.name,
                "papel": c.papel,
                "convidado_por": str(c.convidado_por) if c.convidado_por else None,
            }
            for c, s in linhas
        ]

    async def responder_ao_convite(
        self, convite_id: UUID, user: User, aceitar: bool
    ) -> Dict[str, Any]:
        """A pessoa aceita ou recusa. **Só ela** — nem o dono responde por ela.

        Ao aceitar entra pela equipa **Geral**: um sítio só onde se procura
        gente, e a regra de uma frase — *se não veio por uma equipa sua, veio
        pela Geral*.
        """
        from src.models.convite_ao_projeto import ConviteAoProjeto
        from src.models.crew import CrewMember

        convite = (
            await self.db.execute(
                select(ConviteAoProjeto).where(ConviteAoProjeto.id == convite_id)
            )
        ).scalar_one_or_none()
        if convite is None:
            raise NotFoundError("Invite not found")
        if convite.user_id != user.id:
            # Não se diz "existe mas não é teu": quem não é o destinatário não
            # tem de saber que o convite existe.
            raise NotFoundError("Invite not found")
        if convite.estado != "pendente":
            raise BadRequestError("This invite was already answered.")

        space = await self.space_repo.get_by_id(convite.space_id)
        if not space:
            raise NotFoundError("Space not found")

        convite.estado = "aceite" if aceitar else "recusado"
        convite.respondido_em = func.now()

        if aceitar:
            geral = await self.equipa_geral(convite.space_id)
            if geral is None:
                # Projeto criado antes desta regra. Cria-se em vez de recusar:
                # recusar deixaria o convite impossível de aceitar por uma
                # razão que não é da pessoa que o recebeu.
                geral = await self.crew_repo.create(
                    name=DEFAULT_CREW_NAME,
                    description=None,
                    space_id=convite.space_id,
                    created_by=space.created_by,
                )
                await self.db.flush()
            ja = (
                await self.db.execute(
                    select(CrewMember).where(
                        CrewMember.crew_id == geral.id, CrewMember.user_id == user.id
                    )
                )
            ).scalar_one_or_none()
            if ja is None:
                self.db.add(CrewMember(crew_id=geral.id, user_id=user.id, role=convite.papel))

        await self.db.commit()

        from src.services.notificar_o_projeto import notificar_o_projeto

        if aceitar:
            # O projeto inteiro fica a saber quem passou a alcançar os seus
            # dados — incluindo quem convidou, que é quem espera a resposta.
            await notificar_o_projeto(
                self.db,
                convite.space_id,
                tipo="space_member_added",
                title_key="notif.personJoinedProject",
                title_params={"person": user.name or user.email, "project": space.name},
                excepto=user.id,
            )
        elif convite.convidado_por:
            from src.schemas.notification import NotificationCreate
            from src.services.notification_service import NotificationService

            try:
                await NotificationService(self.db).create_notification(
                    NotificationCreate(
                        user_id=convite.convidado_por,
                        type="space_invite",
                        title="notif.projectInviteDeclined",
                        title_key="notif.projectInviteDeclined",
                        title_params={
                            "person": user.name or user.email,
                            "project": space.name,
                        },
                        entity_type="space",
                        entity_id=str(convite.space_id),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensivo
                logger.warning("recusa %s: aviso falhou: %s", convite_id, exc)

        logger.info(
            "convite_respondido: convite=%s space=%s user=%s estado=%s",
            convite_id,
            convite.space_id,
            user.id,
            convite.estado,
        )
        return {"id": str(convite_id), "estado": convite.estado}

    async def equipas_do_projeto(self, space_id: UUID, user: User) -> List[Dict[str, Any]]:
        """As equipas com acesso a este projeto, e com que papel."""
        from src.models.crew import Crew, CrewMember
        from src.services.acesso_ao_projeto import equipas_que_alcancam

        await self._require_space_role(space_id, user, min_role="viewer")
        alcancam = await equipas_que_alcancam(self.db, space_id)
        if not alcancam:
            return []
        linhas = (
            await self.db.execute(
                select(Crew.id, Crew.name, Crew.space_id).where(
                    Crew.id.in_(list(alcancam.keys())), Crew.deleted_at.is_(None)
                )
            )
        ).all()
        saida = []
        for crew_id, nome, dono_do_projeto in linhas:
            n = (
                await self.db.execute(
                    select(func.count()).select_from(CrewMember).where(CrewMember.crew_id == crew_id)
                )
            ).scalar_one()
            saida.append(
                {
                    "crew_id": str(crew_id),
                    "name": nome,
                    "role": alcancam[crew_id],
                    "member_count": int(n or 0),
                    # As que nasceram dentro do projeto não se podem tirar por
                    # aqui — pertencem-lhe. A interface precisa de o saber.
                    "nativa": dono_do_projeto is not None,
                    # **A equipa que ninguém pediu.**
                    #
                    # Todo o projeto nasce com uma «General» para haver onde
                    # pôr quem foi convidado directamente. É plumbing nosso, e
                    # estava a aparecer no ecrã: o Lucas viu-se dentro de uma
                    # equipa que nunca criou, com um papel que não escolheu, e
                    # pôde remover-se dela — perdendo o acesso ao seu próprio
                    # projeto.
                    #
                    # Continua a existir na base; a interface esconde-a e
                    # mostra essas pessoas como convidadas directamente.
                    "e_a_de_omissao": nome == DEFAULT_CREW_NAME and dono_do_projeto == space_id,
                }
            )
        return saida

    async def convidar_equipa(
        self, space_id: UUID, user: User, crew_id: UUID, role: str = "editor"
    ) -> Dict[str, Any]:
        """Dá a uma equipa acesso a este projeto, **com um papel**.

        A ligação é **viva**: quem entrar na equipa amanhã passa a alcançar
        este projeto, e quem sair deixa de o alcançar na pergunta seguinte.

        Substitui a cópia de pessoas de 25/08. Copiar resolvia a armadilha do
        S6 destruindo a razão de a equipa existir — acrescentar alguém à
        Comercial não o metia nos projetos onde a Comercial trabalha, que foi
        exactamente a queixa do Lucas. A armadilha resolve-se mostrando a
        proveniência (`de_onde_vem_o_acesso`), não copiando.
        """
        from src.models.crew import Crew
        from src.models.space_crew import SpaceCrew

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")
        await self._require_space_role(space_id, user, min_role="owner")

        equipa = (
            await self.db.execute(select(Crew).where(Crew.id == crew_id, Crew.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if equipa is None:
            raise NotFoundError("Crew not found")
        if equipa.space_id is not None and equipa.space_id != space_id:
            # Uma equipa que pertence a OUTRO projeto não se empresta: o seu
            # nome e a sua gente foram pensados para lá. Convidá-la daqui
            # seria dar a este projeto uma lista que outro dono controla.
            raise BadRequestError("This team belongs to another project.")

        ja = (
            await self.db.execute(
                select(SpaceCrew).where(
                    SpaceCrew.space_id == space_id, SpaceCrew.crew_id == crew_id
                )
            )
        ).scalar_one_or_none()
        if ja is not None:
            ja.role = role
        else:
            self.db.add(
                SpaceCrew(space_id=space_id, crew_id=crew_id, role=role, added_by=user.id)
            )
        await self.db.commit()
        logger.info(
            "equipa_no_projeto: space=%s crew=%s papel=%s por=%s",
            space_id,
            crew_id,
            role,
            user.id,
        )
        # **Quem está no projeto fica a saber.** Um convite em massa muda quem
        # alcança os dados; toda a gente que já lá está tem direito a ver isso
        # acontecer, e não só quem convidou.
        from src.services.notificar_o_projeto import notificar_o_projeto

        await notificar_o_projeto(
            self.db,
            space_id,
            tipo="crew_member_added",
            title_key="notif.teamJoinedProject",
            title_params={"team": equipa.name, "project": space.name},
            excepto=user.id,
        )
        return {"crew_id": str(crew_id), "crew_name": equipa.name, "role": role}

    async def tirar_equipa(self, space_id: UUID, user: User, crew_id: UUID) -> Dict[str, Any]:
        """Tira a uma equipa o acesso a este projeto.

        Quem lá estiver **também** por linha directa continua — e é por isso
        que a interface mostra a proveniência antes de alguém carregar aqui.
        """
        from src.models.space_crew import SpaceCrew

        await self._require_space_role(space_id, user, min_role="owner")
        linha = (
            await self.db.execute(
                select(SpaceCrew).where(
                    SpaceCrew.space_id == space_id, SpaceCrew.crew_id == crew_id
                )
            )
        ).scalar_one_or_none()
        if linha is None:
            raise NotFoundError("This team is not in this project.")
        await self.db.delete(linha)
        await self.db.commit()
        logger.info("equipa_fora_do_projeto: space=%s crew=%s por=%s", space_id, crew_id, user.id)
        from src.services.notificar_o_projeto import notificar_o_projeto

        await notificar_o_projeto(
            self.db,
            space_id,
            tipo="crew_member_removed",
            title_key="notif.teamLeftProject",
            title_params={"team": str(crew_id)},
            excepto=user.id,
        )
        return {"crew_id": str(crew_id)}

    async def acesso_das_pessoas(self, space_id: UUID, user: User) -> List[Dict[str, Any]]:
        """Quem alcança este projeto, e **por onde**.

        É esta lista que evita a armadilha do S6: mostra "via equipa
        Comercial" ao lado de quem lá está por essa via, para ninguém julgar
        que tirar a linha directa lhe corta o acesso.
        """
        from src.models.crew import CrewMember
        from src.services.acesso_ao_projeto import de_onde_vem_o_acesso, equipas_que_alcancam

        await self._require_space_role(space_id, user, min_role="viewer")

        ids = {
            r[0]
            for r in (
                await self.db.execute(
                    select(SpaceMember.user_id).where(SpaceMember.space_id == space_id)
                )
            ).all()
        }
        alcancam = await equipas_que_alcancam(self.db, space_id)
        if alcancam:
            ids |= {
                r[0]
                for r in (
                    await self.db.execute(
                        select(CrewMember.user_id).where(
                            CrewMember.crew_id.in_(list(alcancam.keys()))
                        )
                    )
                ).all()
            }
        space = await self.space_repo.get_by_id(space_id)
        if space:
            ids.add(space.created_by)

        saida = []
        for uid in ids:
            pessoa = (
                await self.db.execute(select(User).where(User.id == uid))
            ).scalar_one_or_none()
            if pessoa is None or pessoa.deleted_at is not None:
                continue
            vem = await de_onde_vem_o_acesso(self.db, uid, space_id)
            saida.append(
                {
                    "user_id": str(uid),
                    "name": pessoa.name,
                    "email": pessoa.email,
                    "papel": vem["papel"],
                    "directo": vem["directo"],
                    "por_equipa": vem["por_equipa"],
                    "criador": bool(space and space.created_by == uid),
                }
            )
        return saida

    async def add_space_member(
        self, space_id: UUID, user: User, member_data: SpaceMemberCreate
    ) -> SpaceMemberResponse:
        """
        Add member to space.

        Args:
            space_id: Space ID
            user: Current user
            member_data: Member data

        Returns:
            SpaceMemberResponse: Created member

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
            BadRequestError: If member already exists
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        await self._require_space_role(space_id, user, min_role="owner")

        # A pessoa que se está a acrescentar tem de existir.
        #
        # Não havia verificação nenhuma: o `create` metia a linha e a chave
        # estrangeira `space_members.user_id -> users.id` rebentava, o que
        # saía como 500. Quem está a convidar alguém vê "erro do servidor" em
        # vez de "essa pessoa não existe", e fica sem saber se o problema é o
        # convite, a permissão ou a plataforma.
        from src.models.user import User as _Utilizador

        alvo = (
            await self.db.execute(
                select(_Utilizador.id).where(
                    _Utilizador.id == member_data.user_id,
                    _Utilizador.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if alvo is None:
            raise NotFoundError("User not found")

        # Check if member already exists
        existing = await self.member_repo.get_by_space_and_user(space_id, member_data.user_id)
        if existing:
            raise BadRequestError("User is already a member of this space")

        # Demo Space invite gate (item C): in a demo sandbox, the
        # owner can only add members whose email domain matches
        # the Space owner's domain. Without this, the owner could
        # subvert the same-domain grouping invariant set up by item D
        # (where colleagues from one company merge into one Space) by
        # bringing in arbitrary outside emails.
        if space.is_demo:
            from sqlalchemy import select as _select

            from src.models.user import User as _User

            owner_q = await self.db.execute(
                _select(_User.email).where(_User.id == space.created_by)
            )
            owner_email = (owner_q.scalar_one_or_none() or "").lower()
            owner_domain = owner_email.split("@", 1)[1] if "@" in owner_email else ""

            target_q = await self.db.execute(
                _select(_User.email).where(_User.id == member_data.user_id)
            )
            target_email = (target_q.scalar_one_or_none() or "").lower()
            target_domain = target_email.split("@", 1)[1] if "@" in target_email else ""

            if not owner_domain or owner_domain != target_domain:
                raise ForbiddenError(
                    "Demo Spaces only accept teammates from the same email "
                    f"domain (@{owner_domain}). To bring an outside collaborator "
                    "in, sign up for a workspace at skyfirstlabs.com — paid "
                    "plans support cross-domain teams."
                )

        # Validate the requested Space role (two-axis RBAC, Phase 1).
        from src.schemas.space import SPACE_MEMBER_ROLES

        role = (member_data.role or "editor").lower()
        if role not in SPACE_MEMBER_ROLES:
            raise BadRequestError(
                f"Invalid space role '{role}'. Use one of: {sorted(SPACE_MEMBER_ROLES)}"
            )

        # Create new member with the chosen role.
        member = await self.member_repo.create(
            space_id=space_id,
            user_id=member_data.user_id,
            role=role,
        )

        await self.db.commit()
        await self.db.refresh(member, ["user"])

        # Notify the new member they've been added to the space
        try:
            from src.core.locale import get_message, resolve_locale
            from src.schemas.notification import NotificationCreate
            from src.services.notification_service import NotificationService

            # Localize in the new member's own language, not the actor's.
            recipient_locale = resolve_locale(None, getattr(member, "user", None))
            actor_name = user.name or user.email

            notif_svc = NotificationService(self.db)
            await notif_svc.create(
                NotificationCreate(
                    user_id=member_data.user_id,
                    type="space_member_added",
                    title=get_message("notif_space_added_title", recipient_locale).format(
                        space=space.name
                    ),
                    description=get_message("notif_space_added_desc", recipient_locale).format(
                        actor=actor_name
                    ),
                    entity_type="space",
                    entity_id=str(space_id),
                    deep_link=f"/page?space={space_id}",
                    title_key="notif_space_added_title",
                    title_params={"space": space.name},
                    description_key="notif_space_added_desc",
                    description_params={"actor": actor_name},
                )
            )
        except Exception:
            pass  # Non-fatal

        return SpaceMemberResponse.model_validate(member)

    async def remove_space_member(self, space_id: UUID, user_id: UUID, current_user: User) -> None:
        """
        Remove member from space.

        Args:
            space_id: Space ID
            user_id: User ID to remove
            current_user: Current user

        Raises:
            NotFoundError: If space or member not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != current_user.id and current_user.role not in (
            "admin",
            "owner",
            "super_admin",
        ):
            raise ForbiddenError("Access denied to this space")

        # Check if member exists
        member = await self.member_repo.get_by_space_and_user(space_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Don't allow removing the space creator
        if space.created_by == user_id:
            raise ForbiddenError("Cannot remove space creator")

        await self.member_repo.delete(member.id)

        # W12 wire-in — pause every active agent the removed user
        # created against this space (or org-scoped agents that list it).
        # Privilege persistence (HI-002): without this the agent keeps
        # running under the orphaned creator's identity. Errors here are
        # logged but do NOT roll back the membership removal — the
        # primary action (revocation of access) already happened.
        try:
            from src.services.agent_revocation_service import AgentRevocationService

            await AgentRevocationService(self.db).revoke_on_space_removal(
                user_id=user_id,
                space_id=space_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            logging.getLogger(__name__).warning(
                "Agent revocation on space-member-removal failed "
                "(user=%s space=%s): %s. Periodic sweep will catch up.",
                user_id,
                space_id,
                exc,
            )

        await self.db.commit()

    async def get_space_tables(
        self, space_id: UUID, user: User, only_selected: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all tables from connections in a space.

        Args:
            space_id: Space ID
            user: Current user
            only_selected: If True, only return tables that were explicitly linked to the space.

        Returns:
            List[Dict[str, Any]]: List of tables with connection info
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id and user.role not in TENANT_ADMIN_ROLES:
            is_member = await self.member_repo.get_by_space_and_user(space_id, user.id) is not None
            if not is_member:
                # Phase 2.5 — Crew membership inside the Space also
                # grants visibility (a Crew is a sub-team of the Space).
                from src.models.crew import Crew as _Crew
                from src.models.crew import CrewMember as _CrewMember

                _crew_check = await self.db.execute(
                    select(_CrewMember.id)
                    .join(_Crew, _Crew.id == _CrewMember.crew_id)
                    .where(_CrewMember.user_id == user.id, _Crew.space_id == space_id)
                    .limit(1)
                )
                if _crew_check.scalar_one_or_none() is None:
                    raise ForbiddenError("Access denied to this space")

        # Get space connections
        space_connections = await self.space_repo.get_space_connections(space_id)

        # Get explicitly selected tables, building a lookup set that covers
        # both the canonical (conn_id, bare_name, schema) tuple AND the legacy
        # format where the full "schema.table" name was stored as table_name.
        selected_tables_entities = await self.table_repo.get_space_tables(space_id)
        selected_tables_set: set = set()
        for t in selected_tables_entities:
            conn_str = str(t.connection_id)
            # Canonical key: (conn_id, bare_table_name, schema_name)
            selected_tables_set.add((conn_str, t.table_name, t.schema_name))
            # Legacy: if someone previously stored "schema.table" as table_name,
            # add a split variant so it can still match against metadata tuples
            if "." in t.table_name:
                parts = t.table_name.split(".", 1)
                selected_tables_set.add((conn_str, parts[1], parts[0]))
                # Also allow matching when schema is None in metadata
                selected_tables_set.add((conn_str, parts[1], None))

        # Get tables from each connection
        tables = []
        for space_conn in space_connections:
            connection = space_conn.connection
            metadata = await self.metadata_repo.get_by_connection_id(space_conn.connection_id)
            if not metadata or not metadata.tables:
                continue

            # Extract table information
            for table_data in metadata.tables:
                t_name = None
                t_schema = None

                if isinstance(table_data, dict):
                    t_name = table_data.get("name")
                    t_schema = table_data.get("schema")
                else:
                    # If it's already a TableMetadata object
                    t_name = getattr(table_data, "name", None)
                    t_schema = getattr(table_data, "schema", None)

                if t_name:
                    conn_str = str(space_conn.connection_id)
                    is_selected = (conn_str, t_name, t_schema) in selected_tables_set or (
                        conn_str,
                        t_name,
                        None,
                    ) in selected_tables_set

                    if only_selected and not is_selected:
                        continue

                    tables.append(
                        {
                            "id": f"{space_conn.connection_id}-{t_name}",
                            "connection_id": str(space_conn.connection_id),
                            "connection_name": connection.name,
                            "connection_type": getattr(connection, "connector_id", None),
                            "table_name": t_name,
                            "name": t_name,
                            "schema": t_schema,
                            "schema_name": t_schema,
                            "row_count": (
                                table_data.get("row_count")
                                if isinstance(table_data, dict)
                                else getattr(table_data, "row_count", None)
                            ),
                            "selected": is_selected,
                        }
                    )

        return tables

    async def add_space_table(
        self, space_id: UUID, table_data: SpaceTableCreate, user: User
    ) -> dict:
        """
        Add a specific table to a space.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        # Owners and admins can link tables to any space; creators can
        # link tables to their own. The endpoint already RBAC-checks
        # `spaces.members.manage` — this guard is defence-in-depth for
        # internal callers that bypass the route.
        await self._require_space_role(space_id, user, min_role="owner")

        # Verify the connection exists — if not, fail fast with a 404
        # instead of letting the FK blow up inside commit() and surface
        # as an opaque 500.
        connection = await self.connection_repo.get_by_id(table_data.connection_id)
        if not connection:
            raise NotFoundError("Connection not found")

        # Check if already exists
        existing = await self.table_repo.get_space_table(
            space_id,
            table_data.connection_id,
            table_data.table_name,
            table_data.schema_name,
        )
        if existing:
            return {"message": "Table already linked", "id": str(existing.id)}

        # Create association
        from sqlalchemy.exc import IntegrityError

        from src.models.space import SpaceTable

        space_table = SpaceTable(
            space_id=space_id,
            connection_id=table_data.connection_id,
            table_name=table_data.table_name,
            schema_name=table_data.schema_name,
        )
        self.db.add(space_table)
        try:
            await self.db.commit()
            await self.db.refresh(space_table)
        except IntegrityError as e:
            # Race condition (concurrent link) or unique-constraint hit —
            # roll back and treat as an idempotent success. Logging the
            # actual error here keeps the 500 off the wire so the user
            # sees the correct linked state.
            await self.db.rollback()
            logger.warning(
                "add_space_table integrity error (treated as already linked): %s",
                str(e),
            )
            existing = await self.table_repo.get_space_table(
                space_id,
                table_data.connection_id,
                table_data.table_name,
                table_data.schema_name,
            )
            if existing:
                return {"message": "Table already linked", "id": str(existing.id)}
            raise BadRequestError("Could not link table — integrity check failed")
        except Exception as e:
            # Any other DB error: roll back and surface a clean 400 with
            # the exception type so the frontend stops showing a generic
            # 500 that reverts the optimistic Link state.
            await self.db.rollback()
            logger.exception("add_space_table failed")
            raise BadRequestError(f"Could not link table: {type(e).__name__}")

        return {"message": "Table linked successfully", "id": str(space_table.id)}

    async def remove_space_table(
        self,
        space_id: UUID,
        connection_id: UUID,
        table_name: str,
        schema_name: Optional[str],
        user: User,
    ) -> None:
        """
        Remove a specific table from a space.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        await self._require_space_role(space_id, user, min_role="owner")

        association = await self.table_repo.get_space_table(
            space_id, connection_id, table_name, schema_name
        )
        if not association:
            raise NotFoundError("Table association not found")

        await self.db.delete(association)
        await self.db.commit()

    async def set_space_table_hidden_columns(
        self,
        space_id: UUID,
        connection_id: UUID,
        table_name: str,
        schema_name: Optional[str],
        hidden_columns: list[str],
        user: User,
    ) -> None:
        """Replace the hidden_columns list for a space-linked table.

        `hidden_columns` is a whitelist-inverse: every column in the
        list is filtered out of retrieval / render for this Space only.
        The RBAC gate at the endpoint layer (`connections.edit`) is the
        authoritative permission check; the ownership guard below is a
        defence-in-depth against rogue internal callers that bypass the
        route handler.
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")
        await self._require_space_role(space_id, user, min_role="owner")

        association = await self.table_repo.get_space_table(
            space_id, connection_id, table_name, schema_name
        )
        if not association:
            raise NotFoundError("Table association not found — link the table first")

        # Deduplicate + strip while preserving UI order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for col in hidden_columns:
            key = col.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(key)
        association.hidden_columns = cleaned
        await self.db.commit()

    async def get_space_stats(self, space_id: UUID, user: User) -> SpaceStatsResponse:
        """
        Get statistics for a space.
        """
        from src.repositories.ai import AIQueryRepository

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id and user.role not in TENANT_ADMIN_ROLES:
            is_member = await self.member_repo.get_by_space_and_user(space_id, user.id) is not None
            if not is_member:
                # Phase 2.5 — Crew membership inside the Space also
                # grants visibility (a Crew is a sub-team of the Space).
                from src.models.crew import Crew as _Crew
                from src.models.crew import CrewMember as _CrewMember

                _crew_check = await self.db.execute(
                    select(_CrewMember.id)
                    .join(_Crew, _Crew.id == _CrewMember.crew_id)
                    .where(_CrewMember.user_id == user.id, _Crew.space_id == space_id)
                    .limit(1)
                )
                if _crew_check.scalar_one_or_none() is None:
                    raise ForbiddenError("Access denied to this space")

        # Get space connections
        space_connections = await self.space_repo.get_space_connections(space_id)
        connection_ids = [sc.connection_id for sc in space_connections]

        # Get stats from AI History (scoped by space_id — the authoritative source)
        ai_repo = AIQueryRepository(self.db)
        total_queries = await ai_repo.count_queries_by_space_id(str(space_id))
        active_users = await ai_repo.get_active_users_by_space_id(str(space_id))

        # Data usage from connection metrics
        total_usage_bytes = 0
        for sc in space_connections:
            conn = await self.connection_repo.get_by_id(sc.connection_id)
            if conn and conn.metrics and isinstance(conn.metrics, dict):
                raw_bytes = conn.metrics.get("usage_bytes", 0)
                total_usage_bytes += int(raw_bytes) if raw_bytes else 0

        # Compliance status derived from space sensitivity (authoritative source)
        _sensitivity_map = {
            "restricted": (
                "RESTRICTED",
                "This space contains restricted data. Enhanced access controls and monitoring are active.",
            ),
            "confidential": (
                "CONFIDENTIAL",
                "This space contains confidential data. Access is logged and subject to periodic review.",
            ),
            "internal": ("INTERNAL", "This space operates under standard internal data policies."),
        }
        _status, _desc = _sensitivity_map.get(
            space.sensitivity or "internal",
            ("INTERNAL", "This space operates under standard internal data policies."),
        )

        def _format_bytes(b: int) -> str:
            if not b or b <= 0:
                return "0B"
            import math

            size_name = ("B", "KB", "MB", "GB", "TB")
            i = int(math.floor(math.log(b, 1024)))
            p = math.pow(1024, i)
            s = round(b / p, 1)
            return f"{s}{size_name[i]}"

        def _format_number(n: int) -> str:
            if not n:
                return "0"
            if n >= 1000:
                return f"{round(n / 1000, 1)}k"
            return str(n)

        from src.services.audit_service import AuditService

        audit_service = AuditService(self.db)
        audit_result = await audit_service.list_events(
            resource_kind="space",
            resource_id=str(space_id),
            limit=20,
        )
        activity_feed = [
            {
                "id": str(e["id"]),
                "user": e["actor_email"] or e["actor_kind"] or "system",
                "action": e["action"] or "unknown",
                "target": f"{e['resource_kind'] or ''}/{e['resource_id'] or ''}".strip("/"),
                "time": e["occurred_at"] or "",
                "status": e["decision"] or "allow",
            }
            for e in audit_result["items"]
        ]

        return SpaceStatsResponse(
            total_queries={
                "value": _format_number(total_queries),
                "change": "+0%",
                "trend": "neutral",
            },
            active_users={
                "value": _format_number(active_users),
                "change": "+0%",
                "trend": "neutral",
            },
            data_usage={
                "value": _format_bytes(total_usage_bytes),
                "change": "+0%",
                "trend": "neutral",
            },
            compliance_status={
                "status": _status,
                "description": _desc,
            },
            activity_feed=activity_feed,
        )
