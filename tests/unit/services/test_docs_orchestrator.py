"""
Tests for DocumentOrchestrator service.

Tests cover:
- V2 flow: analyze → plan → generate (success and fallback paths)
- V1 flow: legacy BlueprintAgent-based generation
- Mode selection: full vs additive
- Timeout handling with _run_with_timeout
- Fingerprint skip-if-unchanged optimization
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.docs.types import (
    BatchGeneratorResult,
    BlueprintResult,
    ChangelogResult,
    DocumentationPlan,
    OrchestratorResult,
    PlannedDocument,
    PlannerResult,
    PlansResult,
)


def _make_orchestrator():
    """Create an orchestrator with all dependencies and internal methods mocked.

    Bypasses __init__ with __new__, then attaches mock collaborators and
    stubs out methods that touch the DB or external sessions.
    """
    from app.services.docs.orchestrator import DocumentOrchestrator

    orch = DocumentOrchestrator.__new__(DocumentOrchestrator)
    orch.db = AsyncMock()
    orch.product = MagicMock()
    orch.product.id = uuid.uuid4()
    orch.product.user_id = uuid.uuid4()
    orch.product.docs_codebase_fingerprint = None
    orch.github_service = AsyncMock()

    # V2 collaborators
    orch.codebase_analyzer = AsyncMock()
    orch.documentation_planner = AsyncMock()
    orch.document_generator = AsyncMock()

    # V1 sub-agents
    orch.blueprint_agent = AsyncMock()
    orch.changelog_agent = AsyncMock()
    orch.plans_agent = AsyncMock()

    # Stub internal methods that hit DB or create fresh sessions
    orch._update_progress = AsyncMock()
    orch._get_linked_repos = AsyncMock(return_value=[])
    orch._get_existing_docs = AsyncMock(return_value=[])
    orch._save_fingerprint = AsyncMock()

    return orch


def _make_planner_result(doc_count: int = 2) -> PlannerResult:
    """Create a successful PlannerResult with N planned docs."""
    plan = DocumentationPlan(
        summary="Documentation plan",
        planned_documents=[
            PlannedDocument(
                title=f"Doc {i}",
                doc_type="overview",
                purpose="Testing",
                key_topics=[],
                source_files=[],
                priority=i,
                folder="blueprints",
            )
            for i in range(doc_count)
        ],
        skipped_existing=[],
        codebase_summary="A test codebase",
    )
    return PlannerResult(plan=plan, success=True)


def _make_batch_result(generated: int = 2, failed: list[str] | None = None):
    """Create a BatchGeneratorResult."""
    return BatchGeneratorResult(
        documents=[MagicMock() for _ in range(generated)],
        failed=failed or [],
        total_planned=generated + len(failed or []),
        total_generated=generated,
    )


def _make_codebase_context():
    """Create a minimal mock CodebaseContext."""
    ctx = MagicMock()
    ctx.total_files = 50
    ctx.total_tokens = 10000
    return ctx


class TestOrchestratorV2Flow:
    """Tests for the v2 documentation generation flow."""

    @pytest.mark.asyncio
    @patch("app.services.docs.orchestrator.compute_codebase_fingerprint", return_value="abc123")
    @patch("app.services.docs.orchestrator.should_skip_generation", return_value=False)
    async def test_v2_full_flow_success(self, mock_skip, mock_fp):
        """V2 flow: analyze → plan → generate → complete."""
        orch = _make_orchestrator()
        orch.codebase_analyzer.analyze = AsyncMock(return_value=_make_codebase_context())
        orch.documentation_planner.create_plan = AsyncMock(
            return_value=_make_planner_result(2)
        )
        orch.document_generator.generate_batch = AsyncMock(
            return_value=_make_batch_result(2)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        result = await orch.run(use_v2=True, mode="full")

        assert isinstance(result, OrchestratorResult)
        assert len(result.blueprints) == 2
        orch.codebase_analyzer.analyze.assert_called_once()
        orch.documentation_planner.create_plan.assert_called_once()
        orch.document_generator.generate_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_v2_analysis_failure_falls_back_to_v1(self):
        """If codebase analysis fails, orchestrator falls back to V1."""
        orch = _make_orchestrator()
        orch.codebase_analyzer.analyze = AsyncMock(side_effect=RuntimeError("Analysis failed"))
        orch.blueprint_agent.run = AsyncMock(
            return_value=BlueprintResult(documents=[MagicMock()], created_count=1)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="found_existing", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        result = await orch.run(use_v2=True)

        # V1 was invoked as fallback
        orch.blueprint_agent.run.assert_called_once()
        # V2 planner was NOT called
        orch.documentation_planner.create_plan.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.docs.orchestrator.compute_codebase_fingerprint", return_value="abc")
    @patch("app.services.docs.orchestrator.should_skip_generation", return_value=False)
    async def test_v2_planning_failure_falls_back_to_v1(self, mock_skip, mock_fp):
        """If documentation planner returns failure, orchestrator falls back to V1."""
        orch = _make_orchestrator()
        orch.codebase_analyzer.analyze = AsyncMock(return_value=_make_codebase_context())
        orch.documentation_planner.create_plan = AsyncMock(
            return_value=PlannerResult(
                plan=MagicMock(), success=False, error="Planning failed"
            )
        )
        orch.blueprint_agent.run = AsyncMock(
            return_value=BlueprintResult(documents=[], created_count=0)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="found_existing", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        result = await orch.run(use_v2=True)

        # V1 fallback triggered
        orch.blueprint_agent.run.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.docs.orchestrator.compute_codebase_fingerprint", return_value="abc123")
    @patch("app.services.docs.orchestrator.should_skip_generation", return_value=False)
    async def test_v2_partial_generation_failure_continues(self, mock_skip, mock_fp):
        """If some docs fail to generate, others still complete."""
        orch = _make_orchestrator()
        orch.codebase_analyzer.analyze = AsyncMock(return_value=_make_codebase_context())
        orch.documentation_planner.create_plan = AsyncMock(
            return_value=_make_planner_result(3)
        )
        orch.document_generator.generate_batch = AsyncMock(
            return_value=_make_batch_result(2, failed=["Architecture Doc"])
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        result = await orch.run(use_v2=True)

        assert len(result.blueprints) == 2  # 2 succeeded despite 1 failure

    @pytest.mark.asyncio
    @patch("app.services.docs.orchestrator.compute_codebase_fingerprint", return_value="fp")
    @patch("app.services.docs.orchestrator.should_skip_generation", return_value=True)
    async def test_v2_skips_if_fingerprint_unchanged(self, mock_skip, mock_fp):
        """If codebase fingerprint matches, generation is skipped."""
        orch = _make_orchestrator()
        orch.product.docs_codebase_fingerprint = "fp"
        orch.codebase_analyzer.analyze = AsyncMock(return_value=_make_codebase_context())

        result = await orch.run(use_v2=True)

        orch.documentation_planner.create_plan.assert_not_called()
        orch.document_generator.generate_batch.assert_not_called()
        assert result.blueprints == []

    @pytest.mark.asyncio
    @patch("app.services.docs.orchestrator.compute_codebase_fingerprint", return_value="abc")
    @patch("app.services.docs.orchestrator.should_skip_generation", return_value=False)
    async def test_v2_saves_fingerprint_on_success(self, mock_skip, mock_fp):
        """On successful generation, codebase fingerprint is saved."""
        orch = _make_orchestrator()
        orch.codebase_analyzer.analyze = AsyncMock(return_value=_make_codebase_context())
        orch.documentation_planner.create_plan = AsyncMock(
            return_value=_make_planner_result(1)
        )
        orch.document_generator.generate_batch = AsyncMock(
            return_value=_make_batch_result(1)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        await orch.run(use_v2=True)

        orch._save_fingerprint.assert_called_once_with("abc")


class TestOrchestratorV1Flow:
    """Tests for the v1 legacy documentation flow."""

    @pytest.mark.asyncio
    async def test_v1_flow_runs_blueprint_agent(self):
        """V1 flow delegates to BlueprintAgent."""
        orch = _make_orchestrator()
        orch.blueprint_agent.run = AsyncMock(
            return_value=BlueprintResult(documents=[MagicMock()], created_count=1)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        result = await orch.run(use_v2=False)

        orch.blueprint_agent.run.assert_called_once()
        assert len(result.blueprints) == 1

    @pytest.mark.asyncio
    async def test_v1_blueprint_failure_continues_to_changelog(self):
        """If blueprint agent fails, changelog and plans still run."""
        orch = _make_orchestrator()
        orch.blueprint_agent.run = AsyncMock(side_effect=RuntimeError("Blueprint failed"))
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        result = await orch.run(use_v2=False)

        orch.changelog_agent.run.assert_called_once()
        assert result.changelog is not None

    @pytest.mark.asyncio
    async def test_v1_no_repos_still_runs_agents(self):
        """V1 runs agents even when no repos are linked."""
        orch = _make_orchestrator()
        orch._get_linked_repos = AsyncMock(return_value=[])
        orch.blueprint_agent.run = AsyncMock(
            return_value=BlueprintResult(documents=[], created_count=0)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="found_existing", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        result = await orch.run(use_v2=False)

        orch.blueprint_agent.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_v1_progress_updates_called(self):
        """V1 flow sends progress updates at each stage."""
        orch = _make_orchestrator()
        orch.blueprint_agent.run = AsyncMock(
            return_value=BlueprintResult(documents=[], created_count=0)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        await orch.run(use_v2=False)

        # Verify progress was updated multiple times
        stages = [call.args[0] for call in orch._update_progress.call_args_list]
        assert "starting" in stages
        assert "complete" in stages


class TestOrchestratorMode:
    """Tests for generation mode selection."""

    @pytest.mark.asyncio
    @patch("app.services.docs.orchestrator.compute_codebase_fingerprint", return_value="abc")
    @patch("app.services.docs.orchestrator.should_skip_generation", return_value=False)
    async def test_full_mode_passes_full_to_planner(self, mock_skip, mock_fp):
        """Full mode passes planner_mode='full' to documentation planner."""
        orch = _make_orchestrator()
        orch.codebase_analyzer.analyze = AsyncMock(return_value=_make_codebase_context())
        orch.documentation_planner.create_plan = AsyncMock(
            return_value=_make_planner_result(0)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        await orch.run(use_v2=True, mode="full")

        call_kwargs = orch.documentation_planner.create_plan.call_args
        assert call_kwargs.kwargs.get("mode") == "full"

    @pytest.mark.asyncio
    @patch("app.services.docs.orchestrator.compute_codebase_fingerprint", return_value="abc")
    @patch("app.services.docs.orchestrator.should_skip_generation", return_value=False)
    async def test_additive_mode_passes_expand_to_planner(self, mock_skip, mock_fp):
        """Additive mode maps to planner_mode='expand'."""
        orch = _make_orchestrator()
        orch.codebase_analyzer.analyze = AsyncMock(return_value=_make_codebase_context())
        orch.documentation_planner.create_plan = AsyncMock(
            return_value=_make_planner_result(0)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        await orch.run(use_v2=True, mode="additive")

        call_kwargs = orch.documentation_planner.create_plan.call_args
        assert call_kwargs.kwargs.get("mode") == "expand"


class TestOrchestratorTimeout:
    """Tests for timeout handling with _run_with_timeout."""

    @pytest.mark.asyncio
    async def test_run_with_timeout_success(self):
        """_run_with_timeout returns result on success within timeout."""
        orch = _make_orchestrator()

        async def fast_coro():
            return "result"

        result = await orch._run_with_timeout(fast_coro(), timeout=5, stage_name="Test")
        assert result == "result"

    @pytest.mark.asyncio
    async def test_run_with_timeout_raises_on_timeout(self):
        """_run_with_timeout raises TimeoutError when operation exceeds timeout."""
        orch = _make_orchestrator()

        async def slow_coro():
            await asyncio.sleep(10)

        with pytest.raises(TimeoutError):
            await orch._run_with_timeout(slow_coro(), timeout=0.01, stage_name="Slow Op")

    @pytest.mark.asyncio
    async def test_v2_analysis_timeout_falls_back_to_v1(self):
        """If analysis times out, V2 falls back to V1."""
        orch = _make_orchestrator()

        async def slow_analyze(*args, **kwargs):
            await asyncio.sleep(10)

        orch.codebase_analyzer.analyze = slow_analyze
        orch.blueprint_agent.run = AsyncMock(
            return_value=BlueprintResult(documents=[], created_count=0)
        )
        orch.changelog_agent.run = AsyncMock(
            return_value=ChangelogResult(action="created", document=MagicMock())
        )
        orch.plans_agent.run = AsyncMock(return_value=PlansResult(organized_count=0))

        with patch("app.services.docs.orchestrator.AGENT_TIMEOUT_HEAVY", 0.01):
            result = await orch.run(use_v2=True)

        orch.blueprint_agent.run.assert_called_once()
