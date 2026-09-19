"""SLO math: objectives, error budgets, SLO periods and burn-rate windows.

All arithmetic uses decimal.Decimal so 99.9 means exactly 0.001 of error budget
and 14.4 * 0.001 is exactly 0.0144 (no binary floating point surprises).

Burn rate (Google SRE Workbook, chapter "Alerting on SLOs"):

    burn_rate = error_ratio / error_budget

A burn rate of 1 consumes exactly the whole budget over the SLO period. An alert
window that should fire when `consumption` (a fraction of the budget) is spent
within `long_window` uses

    burn_rate = consumption * period / long_window

For a 30d period this gives the Workbook factors: 2% in 1h -> 14.4, 5% in 6h -> 6,
10% in 1d -> 3, 10% in 3d -> 1. For a 28d period the same budget consumption
gives 13.44, 5.6, 2.8 and 0.933333.
"""
import re
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

DURATION_RE = re.compile(r"^([0-9]+)(s|m|h|d|w)$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
PERIODS = ("28d", "30d")
MAX_OBJECTIVE_DECIMALS = 5

# (long window, short window, budget consumption) per alert class.
PROFILES = {
    # Page on fast burn, ticket on everything slower.
    "default": {
        "page": [("1h", "5m", "0.02")],
        "ticket": [("6h", "30m", "0.05"), ("1d", "2h", "0.10"), ("3d", "6h", "0.10")],
    },
    # Table 5-8 of the SRE Workbook verbatim: two page windows, one ticket window.
    "workbook": {
        "page": [("1h", "5m", "0.02"), ("6h", "30m", "0.05")],
        "ticket": [("3d", "6h", "0.10")],
    },
}


def parse_duration(text):
    """'5m' -> 300. Only single-unit durations (s, m, h, d, w) are accepted."""
    m = DURATION_RE.match(str(text).strip())
    if not m or int(m.group(1)) == 0:
        raise ValueError(f"invalid duration {text!r} (use e.g. 5m, 1h, 3d)")
    return int(m.group(1)) * UNIT_SECONDS[m.group(2)]


def format_duration(seconds):
    """300 -> '5m', 86400 -> '1d'. Largest unit that divides exactly (weeks shown as days)."""
    seconds = int(seconds)
    for unit in ("d", "h", "m", "s"):
        if seconds % UNIT_SECONDS[unit] == 0:
            return f"{seconds // UNIT_SECONDS[unit]}{unit}"
    raise ValueError(seconds)


def to_decimal(value, what="value"):
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number, got {value!r}")
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a number, got {value!r}") from None
    if not d.is_finite():
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    return d


def parse_objective(value):
    """Objective in percent (99.9) -> Decimal. Must be 0 < objective < 100."""
    d = to_decimal(value, "objective")
    if d <= 0 or d >= 100:
        raise ValueError(f"objective must be between 0 and 100 exclusive (percent, e.g. 99.9), got {value!r}")
    if -d.normalize().as_tuple().exponent > MAX_OBJECTIVE_DECIMALS:
        raise ValueError(f"objective {value!r} has more than {MAX_OBJECTIVE_DECIMALS} decimal places")
    return d


def error_budget(objective):
    """Decimal objective percent -> error budget ratio. 99.9 -> 0.001."""
    return (Decimal(100) - objective) / Decimal(100)


def num(d):
    """Plain decimal string without exponent or trailing zeros: 0.0010 -> '0.001', 6.0 -> '6'."""
    d = Decimal(d)
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    s = format(d.normalize(), "f")
    return s


def burn_rate(consumption, period, long_window):
    """Burn-rate factor, rounded to 6 decimal places (half-even)."""
    f = Decimal(str(consumption)) * Decimal(parse_duration(period)) / Decimal(parse_duration(long_window))
    return f.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN).normalize()


def hours_to_exhaustion(period, factor):
    """How long the whole budget lasts at this burn rate, in hours."""
    return Decimal(parse_duration(period)) / Decimal(3600) / Decimal(factor)


def resolve_windows(period, profile="default", custom=None):
    """Return {'page': [...], 'ticket': [...]} of dicts with long, short, burn_rate (Decimal).

    `custom` maps an alert class to a list of {long, short, burn_rate} (burn_rate
    taken verbatim) and replaces the profile for that class."""
    if profile not in PROFILES:
        raise ValueError(f"unknown alerting profile {profile!r} (choose: {', '.join(PROFILES)})")
    out = {}
    for cls in ("page", "ticket"):
        if custom and cls in custom and custom[cls] is not None:
            out[cls] = [{"long": w["long"], "short": w["short"], "burn_rate": to_decimal(w["burn_rate"], "burn_rate")}
                        for w in custom[cls]]
        else:
            out[cls] = [{"long": lw, "short": sw, "burn_rate": burn_rate(c, period, lw)} for lw, sw, c in PROFILES[profile][cls]]
    return out


def all_windows(windows):
    """Sorted unique window durations used by alert rules (always includes 5m)."""
    seen = {"5m"}
    for cls in windows.values():
        for w in cls:
            seen.add(w["long"])
            seen.add(w["short"])
    return sorted(seen, key=parse_duration)
