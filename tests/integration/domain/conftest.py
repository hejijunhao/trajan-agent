"""Domain integration test fixtures.

Extends the root conftest fixtures (db_session, test_user, test_org,
test_subscription, test_product) with additional entities needed for
cross-user and cross-org testing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.document_operations import document_ops
from app.domain.organization_operations import organization_ops
from app.domain.repository_operations import repository_ops
from app.domain.work_item_operations import work_item_ops
from app.models.organization import MemberRole, OrganizationMember
from app.models.user import User


@pytest.fixture
async def second_user(db_session: AsyncSession):
    """A second user — NOT in test_org. For access control / isolation tests."""
    user = User(
        id=uuid.uuid4(),
        email=f"__test_second_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Second User",
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def second_org(db_session: AsyncSession, second_user):
    """A second organization owned by second_user."""
    org = await organization_ops.create(
        db_session,
        name=f"[TEST] Second Org {uuid.uuid4().hex[:8]}",
        owner_id=second_user.id,
    )
    await db_session.flush()
    return org


@pytest.fixture
async def test_org_member(db_session: AsyncSession, test_org, second_user):
    """Add second_user as a MEMBER of test_org."""
    member = OrganizationMember(
        organization_id=test_org.id,
        user_id=second_user.id,
        role=MemberRole.MEMBER.value,
        invited_by=test_org.owner_id,
        invited_at=datetime.now(UTC),
        joined_at=datetime.now(UTC),
    )
    db_session.add(member)
    await db_session.flush()
    await db_session.refresh(member)
    return member


# ─────────────────────────────────────────────────────────────────────────────
# Product-scoped entity fixtures (for 5.3 remaining domain tests)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def test_repository(db_session: AsyncSession, test_user, test_product):
    """A test repository in test_product."""
    repo = await repository_ops.create(
        db_session,
        obj_in={
            "name": f"test-repo-{uuid.uuid4().hex[:8]}",
            "full_name": f"testorg/test-repo-{uuid.uuid4().hex[:8]}",
            "product_id": test_product.id,
            "github_id": 100000 + int(uuid.uuid4().int % 900000),
            "url": "https://github.com/testorg/test-repo",
            "default_branch": "main",
            "language": "Python",
        },
        imported_by_user_id=test_user.id,
    )
    return repo


@pytest.fixture
async def test_document(db_session: AsyncSession, test_user, test_product):
    """A test document in test_product."""
    doc = await document_ops.create(
        db_session,
        obj_in={
            "title": f"Test Document {uuid.uuid4().hex[:8]}",
            "content": "# Test Content\n\nThis is a test document.",
            "type": "note",
            "product_id": test_product.id,
            "is_generated": True,
            "folder": {"path": "blueprints"},
        },
        created_by_user_id=test_user.id,
    )
    return doc


@pytest.fixture
async def test_work_item(db_session: AsyncSession, test_user, test_product):
    """A test work item in test_product."""
    item = await work_item_ops.create(
        db_session,
        obj_in={
            "title": f"Test Task {uuid.uuid4().hex[:8]}",
            "description": "Test work item description",
            "type": "feature",
            "status": "todo",
            "product_id": test_product.id,
        },
        created_by_user_id=test_user.id,
    )
    return item
