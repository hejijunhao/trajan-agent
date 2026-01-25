"""Plan configuration - defines feature limits and pricing for each tier."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanConfig:
    """Configuration for a subscription plan tier."""

    tier: str
    display_name: str
    price_monthly: int  # Monthly price in cents
    base_repo_limit: int
    overage_repo_price: int  # cents per repo per month ($10 = 1000)
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


# Current plans (Indie/Pro/Scale) plus "none" for pending signups
PLANS: dict[str, PlanConfig] = {
    "none": PlanConfig(
        tier="none",
        display_name="No Plan",
        price_monthly=0,
        base_repo_limit=0,
        overage_repo_price=0,
        allows_overages=False,
        priority_doc_generation=False,
        cross_repo_linking=False,
        team_collaboration=False,
        api_access=False,
        autonomous_creation=False,
        long_horizon_memory=False,
        custom_integrations=False,
        dedicated_support=False,
        analysis_frequency="none",
    ),
    "indie": PlanConfig(
        tier="indie",
        display_name="Indie",
        price_monthly=4900,  # $49/mo
        base_repo_limit=5,
        overage_repo_price=1000,  # $10/repo
        allows_overages=True,
        priority_doc_generation=False,
        cross_repo_linking=False,
        team_collaboration=False,
        api_access=False,
        autonomous_creation=False,
        long_horizon_memory=False,
        custom_integrations=False,
        dedicated_support=False,
        analysis_frequency="daily",
    ),
    "pro": PlanConfig(
        tier="pro",
        display_name="Pro",
        price_monthly=29900,  # $299/mo
        base_repo_limit=10,
        overage_repo_price=1000,  # $10/repo
        allows_overages=True,
        priority_doc_generation=True,
        cross_repo_linking=True,
        team_collaboration=True,
        api_access=True,
        autonomous_creation=False,
        long_horizon_memory=False,
        custom_integrations=False,
        dedicated_support=False,
        analysis_frequency="realtime",
    ),
    "scale": PlanConfig(
        tier="scale",
        display_name="Scale",
        price_monthly=49900,  # $499/mo
        base_repo_limit=50,
        overage_repo_price=1000,  # $10/repo
        allows_overages=True,
        priority_doc_generation=True,
        cross_repo_linking=True,
        team_collaboration=True,
        api_access=True,
        autonomous_creation=True,
        long_horizon_memory=True,
        custom_integrations=True,
        dedicated_support=True,
        analysis_frequency="realtime",
    ),
}

# Legacy plan mappings (for backwards compatibility with existing data)
LEGACY_TIER_MAP: dict[str, str] = {
    "observer": "indie",  # Free tier → lowest paid tier
    "foundations": "indie",
    "core": "pro",
    "autonomous": "scale",
}


def get_plan(tier: str) -> PlanConfig:
    """
    Get plan configuration by tier name.

    Handles legacy tier names by mapping them to current tiers.
    Defaults to 'indie' if tier not found (except for 'none' which is explicit).
    """
    # Check for legacy tier name
    if tier in LEGACY_TIER_MAP:
        tier = LEGACY_TIER_MAP[tier]

    # "none" is a valid tier for pending subscriptions
    if tier == "none":
        return PLANS["none"]

    return PLANS.get(tier, PLANS["indie"])


def get_price_id_for_tier(tier: str) -> str:
    """Get the Stripe price ID setting name for a tier."""
    # Normalize legacy tiers
    if tier in LEGACY_TIER_MAP:
        tier = LEGACY_TIER_MAP[tier]

    return f"stripe_price_{tier}_base"
