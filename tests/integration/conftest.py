"""Integration test conftest — DB rollback fixtures.

Inherits the root conftest.py fixtures (db_session, test_user, etc.)
and adds integration-specific markers.

All tests in this directory use the transaction-rollback pattern:
real SQL executes, but nothing persists.
"""

import pytest


@pytest.fixture(autouse=True)
def _mark_integration(request):
    """Auto-mark all tests in this directory as integration."""
    request.node.add_marker(pytest.mark.integration)
