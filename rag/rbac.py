"""
RBAC: user registry with clearance hierarchy.

Tier order (ascending): public < internal < confidential
A user with tier T can access all documents with tier <= T.
"""

from dataclasses import dataclass
from typing import Optional

# Numeric rank — higher = more privileged
TIER_RANK: dict[str, int] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
}

# Tiers a given clearance level can access (inclusive downward)
_ACCESSIBLE: dict[str, list[str]] = {
    tier: [t for t, rank in TIER_RANK.items() if rank <= TIER_RANK[tier]]
    for tier in TIER_RANK
}


@dataclass
class User:
    user_id: str
    clearance: str          # one of TIER_RANK keys
    departments: list[str]  # empty list = access all departments


# In production this would be backed by a database / identity provider.
_USER_REGISTRY: dict[str, User] = {
    "alice": User("alice", "confidential", []),          # all departments, all tiers
    "bob":   User("bob",   "internal",     ["finance"]), # finance only, up to internal
    "carol": User("carol", "public",       []),          # all departments, public only
    "dave":  User("dave",  "internal",     ["hr", "finance"]),
}


def get_user(user_id: str) -> User:
    user = _USER_REGISTRY.get(user_id)
    if user is None:
        raise PermissionError(f"Unknown user: '{user_id}'")
    return user


def build_chroma_filter(user: User) -> dict:
    """
    Build a ChromaDB `where` filter that enforces RBAC.
    Combines accessible tiers with optional department restriction.
    """
    accessible_tiers = _ACCESSIBLE[user.clearance]

    tier_filter: dict = (
        {"access_tier": accessible_tiers[0]}
        if len(accessible_tiers) == 1
        else {"access_tier": {"$in": accessible_tiers}}
    )

    if not user.departments:
        return tier_filter

    dept_filter: dict = (
        {"department": user.departments[0]}
        if len(user.departments) == 1
        else {"department": {"$in": user.departments}}
    )

    return {"$and": [tier_filter, dept_filter]}


def assert_result_access(user: User, metadata: dict) -> None:
    """
    Secondary server-side check on each returned chunk.
    Raises PermissionError if a chunk slips through the filter.
    """
    tier = metadata.get("access_tier", "public")
    dept = metadata.get("department", "unknown")

    if TIER_RANK.get(tier, 0) > TIER_RANK[user.clearance]:
        raise PermissionError(
            f"User '{user.user_id}' (clearance={user.clearance}) "
            f"attempted to access {tier} document."
        )
    if user.departments and dept not in user.departments:
        raise PermissionError(
            f"User '{user.user_id}' has no access to department '{dept}'."
        )
