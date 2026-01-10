"""Plan configuration - defines feature limits and pricing for each tier."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanConfig:
    """Configuration for a subscription plan tier."""

    tier: str
    display_name: str
    price_monthly: int  # cents
    base_repo_limit: int
    overage_repo_price: int  # cents per repo per month (0 = no overages allowed)
    allows_overages: bool  # Free tier: False, Paid tiers: True

    # Feature flags
    continuous_reconciliation: bool
    auto_close_tickets: bool
    proactive_matching: bool
    drift_detection: bool
    cross_repo_linking: bool
    autonomous_creation: bool
    incident_correlation: bool
    long_horizon_memory: bool
    agent_enabled: bool  # False on free tier when over limit

    # Limits
    analysis_frequency: str  # 'weekly', 'daily', 'realtime'

    def to_features_dict(self) -> dict[str, bool]:
        """Return feature flags as a dictionary for API responses."""
        return {
            "continuous_reconciliation": self.continuous_reconciliation,
            "auto_close_tickets": self.auto_close_tickets,
            "proactive_matching": self.proactive_matching,
            "drift_detection": self.drift_detection,
            "cross_repo_linking": self.cross_repo_linking,
            "autonomous_creation": self.autonomous_creation,
            "incident_correlation": self.incident_correlation,
            "long_horizon_memory": self.long_horizon_memory,
        }


PLANS: dict[str, PlanConfig] = {
    "observer": PlanConfig(
        tier="observer",
        display_name="Observer",
        price_monthly=0,
        base_repo_limit=1,
        overage_repo_price=0,
        allows_overages=False,  # Agent stops when limit exceeded
        continuous_reconciliation=False,
        auto_close_tickets=False,
        proactive_matching=False,
        drift_detection=False,
        cross_repo_linking=False,
        autonomous_creation=False,
        incident_correlation=False,
        long_horizon_memory=False,
        agent_enabled=True,  # Enabled until limit exceeded
        analysis_frequency="weekly",
    ),
    "foundations": PlanConfig(
        tier="foundations",
        display_name="Foundations",
        price_monthly=14900,  # $149
        base_repo_limit=3,
        overage_repo_price=1500,  # $15/repo
        allows_overages=True,
        continuous_reconciliation=True,
        auto_close_tickets=True,
        proactive_matching=False,
        drift_detection=False,
        cross_repo_linking=False,
        autonomous_creation=False,
        incident_correlation=False,
        long_horizon_memory=False,
        agent_enabled=True,
        analysis_frequency="daily",
    ),
    "core": PlanConfig(
        tier="core",
        display_name="Core",
        price_monthly=29900,  # $299
        base_repo_limit=10,
        overage_repo_price=2000,  # $20/repo
        allows_overages=True,
        continuous_reconciliation=True,
        auto_close_tickets=True,
        proactive_matching=True,
        drift_detection=True,
        cross_repo_linking=True,
        autonomous_creation=False,
        incident_correlation=False,
        long_horizon_memory=False,
        agent_enabled=True,
        analysis_frequency="realtime",
    ),
    "autonomous": PlanConfig(
        tier="autonomous",
        display_name="Autonomous",
        price_monthly=49900,  # $499
        base_repo_limit=25,
        overage_repo_price=2500,  # $25/repo
        allows_overages=True,
        continuous_reconciliation=True,
        auto_close_tickets=True,
        proactive_matching=True,
        drift_detection=True,
        cross_repo_linking=True,
        autonomous_creation=True,
        incident_correlation=True,
        long_horizon_memory=True,
        agent_enabled=True,
        analysis_frequency="realtime",
    ),
}


def get_plan(tier: str) -> PlanConfig:
    """Get plan configuration by tier name. Defaults to observer if not found."""
    return PLANS.get(tier, PLANS["observer"])
