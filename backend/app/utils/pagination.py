"""Cursor pagination.

**Why cursors rather than `LIMIT`/`OFFSET`.** At 100k users the catalogue is the
hottest read in the product, and offset paging degrades on two axes: Postgres must
scan and discard every skipped row, and rows shift under the reader between pages
so items are duplicated or missed as content is published. A keyset cursor over
`(sort_column, id)` uses the index directly and is stable under concurrent writes.

The cursor is opaque to clients on purpose — it is an implementation detail, and
encoding it discourages hand-crafting one that would break when the sort changes.
It is *not* a security boundary: it is base64, not encrypted, and carries only a
timestamp and an id the caller already sees.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core.exceptions import ValidationError

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

_SEPARATOR = "|"


@dataclass(frozen=True, slots=True)
class Cursor:
    """A decoded keyset position."""

    sort_value: datetime
    item_id: uuid.UUID


def encode_cursor(sort_value: datetime, item_id: uuid.UUID) -> str:
    """Encode a keyset position into an opaque token."""
    raw = f"{sort_value.isoformat()}{_SEPARATOR}{item_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> Cursor:
    """Decode a cursor token.

    Raises:
        ValidationError: The token is malformed. Surfaced as a 422 rather than a
            500, because a bad cursor is a client error — usually a truncated or
            hand-edited query string.
    """
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding).decode("utf-8")
        sort_part, id_part = raw.split(_SEPARATOR, 1)
        return Cursor(
            sort_value=datetime.fromisoformat(sort_part),
            item_id=uuid.UUID(id_part),
        )
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationError(
            "The pagination cursor is not valid.",
            details=[{"field": "cursor", "message": "Malformed or expired cursor."}],
        ) from exc


def clamp_limit(limit: int | None) -> int:
    """Constrain a client-supplied page size.

    An unbounded `limit` is a cheap denial-of-service: one request asking for a
    million rows can exhaust memory on both the database and the API.
    """
    if limit is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(limit, MAX_PAGE_SIZE))
