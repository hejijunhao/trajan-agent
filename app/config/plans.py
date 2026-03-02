"""Plan configuration — Community Edition.

Single permissive plan for the open-source distribution.
All features enabled, generous limits.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanConfig:
    """Configuration for a subscription plan tier."""

    tier: str
    display_name: str
    price_monthly: int  # Monthly price in cents
    base_repo_limit: int
    overage_repo_price: int  # cents per repo per month
    allows_overages: bool

    # Feature flags
    priority_doc_generation: bool
    cross_repo_linking: bool
    team_collaboration: bool
    api_access: bool
    autonomous_creation: bool
    long_horizon_memory: bool
    custom_integrations: bool
    dedicated_support: bool

    # Limits
    analysis_frequency: str  # 'weekly', 'daily', 'realtime'

    @property
    def features(self) -> dict[str, bool]:
        """Return feature flags as a dictionary for API responses."""
        return {
            "priority_doc_generation": self.priority_doc_generation,
            "cross_repo_linking": self.cross_repo_linking,
            "team_collaboration": self.team_collaboration,
            "api_access": self.api_access,
            "autonomous_creation": self.autonomous_creation,
            "long_horizon_memory": self.long_horizon_memory,
            "custom_integrations": self.custom_integrations,
            "dedicated_support": self.dedicated_support,
        }


PLANS: dict[str, PlanConfig] = {
    "community": PlanConfig(
        tier="community",
        display_name="Community",
        price_monthly=0,
        base_repo_limit=999,
        overage_repo_price=0,
        allows_overages=True,
        priority_doc_generation=True,
        cross_repo_linking=True,
        team_collaboration=True,
        api_access=True,
        autonomous_creation=True,
        long_horizon_memory=True,
        custom_integrations=True,
        dedicated_support=False,
        analysis_frequency="realtime",
    ),
}

# Community edition — all tiers resolve to the single community plan.
LEGACY_TIER_MAP: dict[str, str] = {}

_COMMUNITY = PLANS["community"]


def get_plan(tier: str) -> PlanConfig:
    """Get plan configuration by tier name.

    Community edition: always returns the community plan regardless of tier.
    """
    return _COMMUNITY
