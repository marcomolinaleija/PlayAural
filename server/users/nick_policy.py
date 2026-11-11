"""Server-decided policy for approved nick (username) changes.

The server, not any client, decides how often an account may change its nick
and what the paid shortcuts cost. Operators can override the defaults through
the persistent ``nick_change_policy`` server setting; invalid or missing values
always fall back to the defaults so a corrupt setting can never disable the
cooldown or make a shortcut free by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

NICK_POLICY_SETTING_KEY = "nick_change_policy"

DEFAULT_NICK_CHANGE_COOLDOWN_DAYS = 90
DEFAULT_NICK_CHANGE_REDUCED_COOLDOWN_DAYS = 30
DEFAULT_NICK_CHANGE_BYPASS_PRICE = 30000
DEFAULT_NICK_CHANGE_REDUCTION_PRICE = 15000

MAX_NICK_COOLDOWN_DAYS = 3650
MAX_NICK_PRICE = 100_000_000


@dataclass(frozen=True)
class NickChangePolicy:
    """Effective cooldown lengths and coin prices for nick changes."""

    cooldown_days: int = DEFAULT_NICK_CHANGE_COOLDOWN_DAYS
    reduced_cooldown_days: int = DEFAULT_NICK_CHANGE_REDUCED_COOLDOWN_DAYS
    bypass_price: int = DEFAULT_NICK_CHANGE_BYPASS_PRICE
    reduction_price: int = DEFAULT_NICK_CHANGE_REDUCTION_PRICE

    def effective_cooldown_days(self, reduced: bool) -> int:
        """Return the cooldown length that applies to one account."""
        if reduced:
            return min(self.reduced_cooldown_days, self.cooldown_days)
        return self.cooldown_days

    def to_setting(self) -> dict[str, int]:
        """Return the JSON-safe persistent representation."""
        return {
            "cooldown_days": self.cooldown_days,
            "reduced_cooldown_days": self.reduced_cooldown_days,
            "bypass_price": self.bypass_price,
            "reduction_price": self.reduction_price,
        }


DEFAULT_NICK_CHANGE_POLICY = NickChangePolicy()


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Return a strict in-range integer or the supplied default."""
    if type(value) is not int:
        return default
    if value < minimum or value > maximum:
        return default
    return value


def policy_from_setting(value: Any) -> NickChangePolicy:
    """Build a safe policy from an untrusted persisted JSON value."""
    if not isinstance(value, dict):
        return DEFAULT_NICK_CHANGE_POLICY
    cooldown_days = _bounded_int(
        value.get("cooldown_days"),
        DEFAULT_NICK_CHANGE_COOLDOWN_DAYS,
        0,
        MAX_NICK_COOLDOWN_DAYS,
    )
    reduced_days = _bounded_int(
        value.get("reduced_cooldown_days"),
        DEFAULT_NICK_CHANGE_REDUCED_COOLDOWN_DAYS,
        0,
        MAX_NICK_COOLDOWN_DAYS,
    )
    return NickChangePolicy(
        cooldown_days=cooldown_days,
        reduced_cooldown_days=min(reduced_days, cooldown_days),
        bypass_price=_bounded_int(
            value.get("bypass_price"),
            DEFAULT_NICK_CHANGE_BYPASS_PRICE,
            0,
            MAX_NICK_PRICE,
        ),
        reduction_price=_bounded_int(
            value.get("reduction_price"),
            DEFAULT_NICK_CHANGE_REDUCTION_PRICE,
            0,
            MAX_NICK_PRICE,
        ),
    )


def parse_utc_timestamp(value: str) -> datetime | None:
    """Parse a stored ISO timestamp as an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cooldown_remaining(
    last_changed_at_utc: str,
    reduced: bool,
    policy: NickChangePolicy,
    now: datetime | None = None,
) -> timedelta:
    """Return the time left before a free nick change is allowed again.

    An account that never changed its nick has no cooldown. A stored timestamp
    that cannot be parsed is treated as an active full cooldown from "now" so
    corruption can never silently grant unlimited free changes.
    """
    if not last_changed_at_utc:
        return timedelta(0)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    last_changed = parse_utc_timestamp(last_changed_at_utc)
    if last_changed is None:
        return timedelta(days=policy.effective_cooldown_days(reduced))
    ready_at = last_changed + timedelta(
        days=policy.effective_cooldown_days(reduced)
    )
    remaining = ready_at - moment
    return remaining if remaining > timedelta(0) else timedelta(0)


def split_remaining(remaining: timedelta) -> tuple[int, int, int]:
    """Split a duration into whole days, hours and minutes (minutes round up)."""
    total_minutes = max(0, int(-(-remaining.total_seconds() // 60)))
    days, rest = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    return days, hours, minutes

