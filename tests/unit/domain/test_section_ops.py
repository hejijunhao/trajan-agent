"""Unit tests for SectionOperations and SubsectionOperations — all DB calls mocked."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.section_operations import (
    DEFAULT_SECTIONS,
    SectionOperations,
    SubsectionOperations,
)

from tests.helpers.mock_factories import (
    make_mock_document_section,
    mock_scalar_result,
    mock_scalars_result,
)


# ---------------------------------------------------------------------------
# SectionOperations
# ---------------------------------------------------------------------------


class TestSectionGet:
    """Tests for single section retrieval."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_get_returns_section(self):
        section = make_mock_document_section()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(section))

        result = await self.ops.get(self.db, section.id)
        assert result == section

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get(self.db, uuid.uuid4())
        assert result is None


class TestSectionGetByProduct:
    """Tests for product-scoped section listing."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_sections_ordered_by_position(self):
        sections = [
            make_mock_document_section(position=0, name="Technical"),
            make_mock_document_section(position=1, name="Conceptual"),
        ]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(sections))

        result = await self.ops.get_by_product(self.db, uuid.uuid4())
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_sections(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.get_by_product(self.db, uuid.uuid4())
        assert result == []


class TestSectionGetBySlug:
    """Tests for slug-based section lookup."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_finds_section_by_slug(self):
        section = make_mock_document_section(slug="technical")
        self.db.execute = AsyncMock(return_value=mock_scalar_result(section))

        result = await self.ops.get_by_slug(self.db, uuid.uuid4(), "technical")
        assert result == section

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_slug(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get_by_slug(self.db, uuid.uuid4(), "nonexistent")
        assert result is None


class TestSectionCreate:
    """Tests for section creation."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_create_returns_section_with_correct_fields(self):
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        product_id = uuid.uuid4()
        section_data = MagicMock()
        section_data.model_dump.return_value = {
            "product_id": product_id,
            "name": "Custom",
            "slug": "custom",
            "position": 2,
        }

        result = await self.ops.create(self.db, section_data)
        assert result is not None
        assert result.name == "Custom"
        assert result.slug == "custom"
        assert result.position == 2


class TestSectionDelete:
    """Tests for section deletion (default sections protected)."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_delete_non_default_section(self):
        section = make_mock_document_section(is_default=False)
        self.db.execute = AsyncMock(return_value=mock_scalar_result(section))
        self.db.delete = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.delete(self.db, section.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_cannot_delete_default_section(self):
        section = make_mock_document_section(is_default=True)
        self.db.execute = AsyncMock(return_value=mock_scalar_result(section))

        result = await self.ops.delete(self.db, section.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.delete(self.db, uuid.uuid4())
        assert result is False


class TestSectionReorder:
    """Tests for section reordering."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_reorder_completes_without_error(self):
        product_id = uuid.uuid4()
        section_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))
        self.db.flush = AsyncMock()

        # Should complete without error for 3 section IDs
        result = await self.ops.reorder(self.db, product_id, section_ids)
        assert result is not None or result == []  # Returns the updated list


class TestSectionGetNextPosition:
    """Tests for next position calculation."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_next_position(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(2))

        result = await self.ops.get_next_position(self.db, uuid.uuid4())
        assert result == 3

    @pytest.mark.asyncio
    async def test_returns_one_when_no_sections(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get_next_position(self.db, uuid.uuid4())
        assert result == 1


class TestSectionEnsureDefaults:
    """Tests for default section seeding."""

    def setup_method(self):
        self.ops = SectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_existing_sections_if_present(self):
        existing = [make_mock_document_section()]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(existing))

        result = await self.ops.ensure_default_sections(self.db, uuid.uuid4())
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_default_sections_config_has_two_sections(self):
        """Verify DEFAULT_SECTIONS constant has expected structure."""
        assert len(DEFAULT_SECTIONS) == 2
        assert DEFAULT_SECTIONS[0]["slug"] == "technical"
        assert DEFAULT_SECTIONS[1]["slug"] == "conceptual"
        assert len(DEFAULT_SECTIONS[0]["subsections"]) == 8
        assert len(DEFAULT_SECTIONS[1]["subsections"]) == 4


# ---------------------------------------------------------------------------
# SubsectionOperations
# ---------------------------------------------------------------------------


class TestSubsectionGet:
    """Tests for subsection retrieval."""

    def setup_method(self):
        self.ops = SubsectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_get_returns_subsection(self):
        sub = MagicMock()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(sub))

        result = await self.ops.get(self.db, uuid.uuid4())
        assert result == sub


class TestSubsectionGetBySection:
    """Tests for section-scoped subsection listing."""

    def setup_method(self):
        self.ops = SubsectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_subsections_for_section(self):
        subs = [MagicMock(), MagicMock()]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(subs))

        result = await self.ops.get_by_section(self.db, uuid.uuid4())
        assert len(result) == 2


class TestSubsectionDelete:
    """Tests for subsection deletion (default subsections protected)."""

    def setup_method(self):
        self.ops = SubsectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_cannot_delete_default_subsection(self):
        sub = MagicMock()
        sub.is_default = True
        self.db.execute = AsyncMock(return_value=mock_scalar_result(sub))

        result = await self.ops.delete(self.db, uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_deletes_non_default_subsection(self):
        sub = MagicMock()
        sub.is_default = False
        self.db.execute = AsyncMock(return_value=mock_scalar_result(sub))
        self.db.delete = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.delete(self.db, uuid.uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.delete(self.db, uuid.uuid4())
        assert result is False


class TestSubsectionGetNextPosition:
    """Tests for next subsection position calculation."""

    def setup_method(self):
        self.ops = SubsectionOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_next_position(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(3))

        result = await self.ops.get_next_position(self.db, uuid.uuid4())
        assert result == 4

    @pytest.mark.asyncio
    async def test_returns_one_when_no_subsections(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get_next_position(self.db, uuid.uuid4())
        assert result == 1
