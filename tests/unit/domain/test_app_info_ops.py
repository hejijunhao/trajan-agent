"""Unit tests for AppInfoOperations — tag normalization, validation, encryption."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.app_info_operations import normalize_tags, validate_tags


class TestNormalizeTags:
    """Pure logic tests for tag normalization."""

    def test_empty_input_returns_empty(self):
        assert normalize_tags(None) == []
        assert normalize_tags([]) == []

    def test_lowercases_and_strips(self):
        result = normalize_tags(["  Backend  ", "FRONTEND"])
        assert result == ["backend", "frontend"]

    def test_deduplicates(self):
        result = normalize_tags(["api", "API", "Api"])
        assert result == ["api"]

    def test_drops_invalid_characters(self):
        result = normalize_tags(["valid-tag", "invalid tag!", "also@invalid"])
        assert result == ["valid-tag"]

    def test_respects_max_tag_length(self):
        long_tag = "a" * 31  # Over 30 char limit
        short_tag = "a" * 30
        result = normalize_tags([long_tag, short_tag])
        assert result == [short_tag]

    def test_respects_max_tags_per_entry(self):
        tags = [f"tag{i}" for i in range(15)]  # Over 10 limit
        result = normalize_tags(tags)
        assert len(result) == 10

    def test_sorts_alphabetically(self):
        result = normalize_tags(["zebra", "alpha", "middle"])
        assert result == ["alpha", "middle", "zebra"]

    def test_must_start_with_alphanumeric(self):
        result = normalize_tags(["_starts-underscore", "valid-tag"])
        assert result == ["valid-tag"]


class TestValidateTags:
    """Pure logic tests for tag validation (returns errors)."""

    def test_empty_returns_no_errors(self):
        assert validate_tags(None) == []
        assert validate_tags([]) == []

    def test_returns_error_for_too_many_tags(self):
        tags = [f"tag{i}" for i in range(12)]
        errors = validate_tags(tags)
        assert any("Maximum" in e for e in errors)

    def test_returns_error_for_long_tag(self):
        errors = validate_tags(["a" * 35])
        assert any("exceeds" in e for e in errors)

    def test_returns_error_for_invalid_chars(self):
        errors = validate_tags(["has spaces"])
        assert any("invalid characters" in e for e in errors)
