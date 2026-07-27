"""Data access for media assets."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.media import MediaAsset, MediaStatus
from app.repositories.base import BaseRepository


class MediaRepository(BaseRepository[MediaAsset]):
    """Reads and writes `media_assets`."""

    model = MediaAsset

    async def get(self, asset_id: uuid.UUID) -> MediaAsset | None:
        """Load an asset by id."""
        return await self.session.get(MediaAsset, asset_id)

    async def get_many(self, asset_ids: list[uuid.UUID]) -> dict[uuid.UUID, MediaAsset]:
        """Load several assets at once, keyed by id.

        Used when rendering a course outline: fetching each lesson's video asset
        individually would be an N+1 across the whole course.
        """
        if not asset_ids:
            return {}
        result = await self.session.execute(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))
        return {asset.id: asset for asset in result.scalars().all()}

    async def list_abandoned(self, *, older_than: datetime, limit: int = 500) -> list[MediaAsset]:
        """Pending assets whose upload window has long passed.

        Feeds the orphan-cleanup job: a client that requests a ticket and never
        uploads leaves a `pending` row and, occasionally, a partial object. Both
        cost money and neither is reachable by any feature.
        """
        result = await self.session.execute(
            select(MediaAsset)
            .where(
                MediaAsset.status == MediaStatus.PENDING,
                MediaAsset.created_at < older_than,
            )
            .order_by(MediaAsset.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    def add(self, asset: MediaAsset) -> None:
        """Stage a new asset. The service owns the commit."""
        self.session.add(asset)

    async def delete(self, asset: MediaAsset) -> None:
        """Delete an asset row."""
        await self.session.delete(asset)
