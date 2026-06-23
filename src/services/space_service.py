"""Space service."""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.http_client import AIServiceHTTPClient
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.crew import Crew
from src.models.space import SpaceConnection
from src.models.user import User
from src.repositories.connection import ConnectionMetadataRepository, ConnectionRepository
from src.repositories.space import SpaceMemberRepository, SpaceRepository, SpaceTableRepository
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
        if user.role in ("admin", "owner", "super_admin"):
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

        if space.created_by != user.id and user.role not in ("admin", "owner", "super_admin"):
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

    async def delete_space(self, space_id: UUID, user: User) -> None:
        """
        Delete space.

        Args:
            space_id: Space ID
            user: Current user

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        import logging

        from src.config.settings import get_settings

        logger = logging.getLogger(__name__)

        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

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
            if user.role not in ("admin", "owner", "super_admin") and space.created_by != user.id:
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
        is_admin = (user.role or "").lower() in ("admin", "owner", "super_admin")
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

        if space.created_by != user.id and user.role not in ("admin", "owner", "super_admin"):
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

        if space.created_by != user.id and user.role not in ("admin", "owner", "super_admin"):
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

        if space.created_by != user.id and user.role not in ("admin", "owner", "super_admin"):
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

        if space.created_by != user.id and user.role not in ("admin", "owner", "super_admin"):
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
