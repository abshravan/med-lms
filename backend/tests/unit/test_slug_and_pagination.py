"""Tests for slug generation and cursor pagination.

Both produce values that end up in URLs and are therefore hard to change later,
so their edge cases are pinned here rather than discovered in production.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.exceptions import ValidationError
from app.utils.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)
from app.utils.slug import slugify, unique_slug


class TestSlugify:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Cardiology Basics", "cardiology-basics"),
            ("  Leading and trailing  ", "leading-and-trailing"),
            ("Multiple   spaces", "multiple-spaces"),
            ("Punctuation!!! Removed?", "punctuation-removed"),
            ("Already-slugged", "already-slugged"),
            ("MiXeD CaSe", "mixed-case"),
            ("Numbers 123 kept", "numbers-123-kept"),
            ("under_scores", "under-scores"),
            ("--edges--", "edges"),
        ],
    )
    def test_produces_url_safe_output(self, value: str, expected: str) -> None:
        assert slugify(value) == expected

    def test_folds_accented_characters_to_ascii(self) -> None:
        """Percent-encoded URLs are unreadable and break when copied around."""
        assert slugify("Cardiología Básica") == "cardiologia-basica"

    def test_returns_empty_when_nothing_is_sluggable(self) -> None:
        """Callers must supply a fallback — `unique_slug` does."""
        assert slugify("!!!") == ""
        assert slugify("心臓病学") == ""

    def test_truncates_on_a_word_boundary(self) -> None:
        result = slugify("alpha beta gamma delta epsilon", max_length=16)

        assert len(result) <= 16
        # Not cut mid-word, and no trailing hyphen left behind.
        assert result == "alpha-beta-gamma"
        assert not result.endswith("-")


class TestUniqueSlug:
    def test_returns_the_base_when_free(self) -> None:
        assert unique_slug("Anatomy", taken=set()) == "anatomy"

    def test_appends_a_suffix_on_collision(self) -> None:
        assert unique_slug("Anatomy", taken={"anatomy"}) == "anatomy-2"

    def test_keeps_incrementing_past_multiple_collisions(self) -> None:
        taken = {"anatomy", "anatomy-2", "anatomy-3"}
        assert unique_slug("Anatomy", taken=taken) == "anatomy-4"

    def test_uses_the_fallback_for_unsluggable_input(self) -> None:
        assert unique_slug("!!!", taken=set(), fallback="course") == "course"

    def test_suffix_never_exceeds_the_length_limit(self) -> None:
        """The base is shortened so the suffix fits, rather than overflowing."""
        base = "a" * 20
        result = unique_slug(base, taken={base}, max_length=20)

        assert len(result) <= 20
        assert result.endswith("-2")


class TestCursor:
    def test_round_trips(self) -> None:
        moment = datetime(2026, 7, 26, 12, 30, tzinfo=UTC)
        item_id = uuid.uuid4()

        decoded = decode_cursor(encode_cursor(moment, item_id))

        assert decoded.sort_value == moment
        assert decoded.item_id == item_id

    def test_is_opaque(self) -> None:
        """Encoded so clients do not build one by hand and depend on the format."""
        token = encode_cursor(datetime(2026, 7, 26, tzinfo=UTC), uuid.uuid4())

        assert "2026" not in token
        assert "|" not in token

    @pytest.mark.parametrize(
        "token",
        ["not-base64!!", "", "YWJj", "!!!!"],
    )
    def test_rejects_a_malformed_cursor_as_client_error(self, token: str) -> None:
        """A truncated or hand-edited cursor is a 422, never a 500."""
        with pytest.raises(ValidationError):
            decode_cursor(token)


class TestClampLimit:
    def test_defaults_when_absent(self) -> None:
        assert clamp_limit(None) == DEFAULT_PAGE_SIZE

    def test_caps_an_oversized_request(self) -> None:
        """An unbounded limit is a cheap denial-of-service."""
        assert clamp_limit(10_000) == MAX_PAGE_SIZE

    def test_raises_a_non_positive_limit_to_one(self) -> None:
        assert clamp_limit(0) == 1
        assert clamp_limit(-5) == 1

    def test_passes_a_reasonable_value_through(self) -> None:
        assert clamp_limit(25) == 25
