"""Regression test for the 2026-04-15 startup crash.

The lifespan used to call ``init_context_events(AsyncSessionLocal)``.
`AsyncSessionLocal` is an `async_sessionmaker`, not a Session class,
and Session-level events (`after_flush`, `after_commit`,
`after_rollback`) don't exist on that target. Startup crashed with:

    sqlalchemy.exc.InvalidRequestError:
    No such event 'after_flush' for target 'async_sessionmaker(...)'

Fix: `init_context_events()` now always binds to
`sqlalchemy.orm.Session` (the sync base class that AsyncSession
internally flushes through). The `session_cls` kwarg is kept for test
compat but is ignored when it isn't a Session subclass.

These tests pin three things so the regression can't sneak back:

  1. Calling with NO argument doesn't raise.
  2. Calling with `async_sessionmaker(...)` doesn't raise
     (falls back to the base Session silently).
  3. Calling with `sqlalchemy.orm.Session` directly still works
     (tests rely on that path).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Session

from src.core.context_events import init_context_events


def test_init_with_no_arg_does_not_raise():
    # Should be a no-op on re-entry (idempotent guard inside the fn).
    init_context_events()


def test_init_with_async_sessionmaker_does_not_raise():
    """The original crash: passing an async_sessionmaker instance."""
    maker = async_sessionmaker()
    init_context_events(maker)


def test_init_with_base_session_class_is_accepted():
    """Tests explicitly bind hooks to Session — keep that path alive."""
    init_context_events(Session)


def test_init_with_random_object_falls_back_silently():
    """Anything that's not a Session subclass (stray dict, instance of
    some other class) should not crash — we use the base Session."""
    class NotASession:
        pass

    init_context_events(NotASession())
    init_context_events({"not": "a class"})
    init_context_events(42)
