"""Unit tests for plan configuration and tier resolution."""

from app.config.plans import PlanConfig, get_plan, get_price_id_for_tier


class TestGetPlan:
    """Tests for get_plan() tier resolution."""

    def test_returns_indie_config(self):
        plan = get_plan("indie")
        assert plan.tier == "indie"
        assert plan.price_monthly == 4900
        assert plan.base_repo_limit == 5

    def test_returns_pro_config(self):
        plan = get_plan("pro")
        assert plan.tier == "pro"
        assert plan.price_monthly == 29900
        assert plan.allows_overages is True

    def test_returns_scale_config(self):
        plan = get_plan("scale")
        assert plan.tier == "scale"
        assert plan.autonomous_creation is True
        assert plan.dedicated_support is True

    def test_returns_none_config_for_pending(self):
        plan = get_plan("none")
        assert plan.tier == "none"
        assert plan.price_monthly == 0
        assert plan.base_repo_limit == 0
        assert plan.team_collaboration is False

    def test_maps_legacy_observer_to_indie(self):
        plan = get_plan("observer")
        assert plan.tier == "indie"

    def test_maps_legacy_core_to_pro(self):
        plan = get_plan("core")
        assert plan.tier == "pro"

    def test_defaults_unknown_tier_to_indie(self):
        plan = get_plan("nonexistent_tier")
        assert plan.tier == "indie"


class TestPlanConfigFeatures:
    """Tests for PlanConfig.features property."""

    def test_features_returns_dict_of_bools(self):
        plan = get_plan("pro")
        features = plan.features
        assert isinstance(features, dict)
        assert len(features) == 8
        assert features["team_collaboration"] is True
        assert features["autonomous_creation"] is False


class TestGetPriceIdForTier:
    """Tests for get_price_id_for_tier()."""

    def test_returns_formatted_setting_name(self):
        assert get_price_id_for_tier("indie") == "stripe_price_indie_base"
        assert get_price_id_for_tier("pro") == "stripe_price_pro_base"

    def test_normalizes_legacy_tier(self):
        assert get_price_id_for_tier("observer") == "stripe_price_indie_base"
