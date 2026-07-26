"""Repository base.

Repositories are the only layer that knows SQLAlchemy exists. Services depend on
repositories, never on `AsyncSession` query construction. That boundary is what
makes the future service-extraction seams (docs/architecture.md §13) cheap: a
repository can be swapped for an HTTP client without touching business logic.

Repositories never commit. Transaction scope belongs to the service, so that a
single business operation spanning several repositories is one atomic unit.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Shared plumbing for concrete repositories."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """The unit of work this repository participates in."""
        return self._session

    async def flush(self) -> None:
        """Push pending changes to the database without committing.

        Used when subsequent logic in the same transaction needs
        database-generated values (defaults, sequences) to be populated.
        """
        await self._session.flush()
