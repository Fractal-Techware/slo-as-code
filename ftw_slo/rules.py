"""Prometheus rule generation: SLI recording rules, SLO metadata and burn-rate alerts.

Recording rules per SLO (labels slo_service, slo + your static labels + tenancy labels):

  ftw_slo:sli_errors:rate5m           bad events per second over 5m
  ftw_slo:sli_total:rate5m            all events per second over 5m
  ftw_slo:sli_error:ratio_rate<W>     error ratio over each alert window W (5m ... 3d)
  ftw_slo:sli_error:ratio_period      error ratio over the SLO window (28d / 30d),
                                      sum_over_time(errors 5m) / sum_over_time(total 5m)
  ftw_slo:objective:ratio             e.g. 0.999
  ftw_slo:error_budget:ratio          e.g. 0.001
  ftw_slo:period:days                 28 or 30
  ftw_slo:error_budget_remaining:ratio  1 - ratio_period / error_budget (1 = untouched, <0 = overspent)

For time-slice SLIs an "event" is one minute (bad or good), so the same formulas hold.
The ftw_slo: prefix keeps these series separate from other SLO rule sets (for example the
slo: rules in the FTW Prometheus Alert Rules Pack), so both can run side by side.
"""
from decimal import Decimal

from . import VERSION, mathx, templates, yamlio

SLI_ERRORS = "ftw_slo:sli_errors:rate5m"
SLI_TOTAL = "ftw_slo:sli_total:rate5m"
RATIO = "ftw_slo:sli_error:ratio_rate{}"
RATIO_PERIOD = "ftw_slo:sli_error:ratio_period"
OBJECTIVE = "ftw_slo:objective:ratio"
BUDGET = "ftw_slo:error_budget:ratio"
PERIOD_DAYS = "ftw_slo:period:days"
REMAINING = "ftw_slo:error_budget_remaining:ratio"

SEVERITY = {"page": "critical", "ticket": "warning"}
SUFFIX = {"page": "FastBurn", "ticket": "SlowBurn"}


def _single_call(expr):
    """True if expr is one function call / aggregation, e.g. sum(rate(x[5m])), so parentheses are redundant."""
    import re
    m = re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(?: by \([^()]*\) )?\(", expr)
    if not m:
        return False
    depth, quote, i = 0, False, m.end() - 1
    while i < len(expr):
        c = expr[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == '"':
                quote = False
        elif c == '"':
            quote = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i == len(expr) - 1
        i += 1
    return False


def _p(expr):
    return expr if _single_call(expr) else f"({expr})"


def _q(slo, qname, window):
    return templates.render(slo.template, qname, slo.params, window, slo.tenancy)


def error_ratio_expr(slo, window):
    """PromQL for the SLI error ratio over `window`, straight from the raw metrics."""
    t = slo.template
    if t.kind == "ratio":
        total = _q(slo, "total", window)
        if "errors" in t.queries:
            errors = f"(\n  {_p(_q(slo, 'errors', window))}\n  or\n  0 * {_p(total)}\n)"
        else:
            good = _q(slo, "good", window)
            errors = f"(\n  {_p(total)}\n  -\n  (\n    {_p(good)}\n    or\n    0 * {_p(total)}\n  )\n)"
        return f"{errors}\n/\n{_p(total)}"
    if t.kind == "timeslice":
        return f"avg_over_time(\n  ({_q(slo, 'bad', window)})[{window}:1m]\n)"
    return f"(\n  {_q(slo, 'error_ratio', window)}\n)"


def errors_total_5m(slo):
    t = slo.template
    total = _q(slo, "total", "5m") if t.kind == "ratio" else None
    if t.kind == "ratio":
        if "errors" in t.queries:
            errors = f"{_p(_q(slo, 'errors', '5m'))}\nor\n0 * {_p(total)}"
        else:
            good = _q(slo, "good", "5m")
            errors = f"{_p(total)}\n-\n(\n  {_p(good)}\n  or\n  0 * {_p(total)}\n)"
        return errors, total
    ratio = f"{RATIO.format('5m')}{{{slo.selector}}}"
    # NaN-safe (no traffic): comparisons drop NaN samples, so sum_over_time stays finite.
    return f"{ratio} >= 0", f"({ratio} >= 0) * 0 + 1"


def _labels(slo):
    labels = {"slo_service": slo.service, "slo": slo.name}
    labels.update(sorted(slo.labels.items()))
    return labels


def windows_for(slo):
    active = {cls: w["windows"] for cls, w in ((c, slo.alerting[c]) for c in ("page", "ticket")) if w["enabled"]} \
        if slo.alerting and slo.alerting["enabled"] else {}
    return mathx.all_windows(active)


def recording_rules(slo):
    labels = _labels(slo)
    sel = slo.selector
    sli = []
    errors, total = errors_total_5m(slo)
    ratio5 = {"record": RATIO.format("5m"), "expr": None, "labels": labels}
    if slo.template.kind == "ratio":
        sli.append({"record": SLI_ERRORS, "expr": errors, "labels": labels})
        sli.append({"record": SLI_TOTAL, "expr": total, "labels": labels})
        ratio5["expr"] = f"{SLI_ERRORS}{{{sel}}}\n/\n{SLI_TOTAL}{{{sel}}}"
        sli.append(ratio5)
    else:
        ratio5["expr"] = error_ratio_expr(slo, "5m")
        sli.append(ratio5)
        sli.append({"record": SLI_ERRORS, "expr": errors, "labels": labels})
        sli.append({"record": SLI_TOTAL, "expr": total, "labels": labels})
    for w in windows_for(slo):
        if w == "5m":
            continue
        sli.append({"record": RATIO.format(w), "expr": error_ratio_expr(slo, w), "labels": labels})
    budget = mathx.num(slo.budget)
    meta = [
        {"record": RATIO_PERIOD,
         "expr": f"sum_over_time({SLI_ERRORS}{{{sel}}}[{slo.window}])\n/\nsum_over_time({SLI_TOTAL}{{{sel}}}[{slo.window}])",
         "labels": labels},
        {"record": REMAINING, "expr": f"1 - ({RATIO_PERIOD}{{{sel}}} / {budget})", "labels": labels},
        {"record": OBJECTIVE, "expr": f"vector({mathx.num(slo.objective / 100)})", "labels": labels},
        {"record": BUDGET, "expr": f"vector({budget})", "labels": labels},
        {"record": PERIOD_DAYS, "expr": f"vector({mathx.parse_duration(slo.window) // 86400})", "labels": labels},
    ]
    return sli, meta


def _hours(period, factor):
    h = mathx.hours_to_exhaustion(period, factor)
    if h >= 48:
        return f"{float(round(h / 24, 1)):g} days"
    return f"{float(round(h, 1)):g} hours"


def alert_name(slo, cls):
    return slo.alerting["name"] + SUFFIX[cls]


def alert_expr(slo, cls):
    sel = slo.selector
    budget = mathx.num(slo.budget)
    parts = []
    for w in slo.alerting[cls]["windows"]:
        thr = f"({mathx.num(w['burn_rate'])} * {budget})"
        parts.append(f"(\n  {RATIO.format(w['long'])}{{{sel}}} > {thr}\n  and\n  {RATIO.format(w['short'])}{{{sel}}} > {thr}\n)")
    return "\nor\n".join(parts)


def alert_annotations(slo, cls):
    title = f"{slo.service} {slo.name}"
    prefix = "".join(f"[{{{{ $labels.{label} }}}}] " for label in slo.tenancy)
    how = "fast" if cls == "page" else "slow"
    conds = "; ".join(
        f"{w['long']} and {w['short']} error ratio above {mathx.num(w['burn_rate'])}x the budget "
        f"(whole budget gone in {_hours(slo.window, w['burn_rate'])} at that rate)"
        for w in slo.alerting[cls]["windows"])
    ann = {
        "summary": f"{prefix}{title}: error budget {how} burn ({cls})",
        "description": (f"{prefix}The {title} SLO ({mathx.num(slo.objective)}% over {slo.window}) is consuming its error "
                        f"budget too fast. Firing condition(s): {conds}."),
    }
    ann.update(sorted(slo.alerting[cls]["annotations"].items()))
    return ann


def alert_labels(slo, cls):
    labels = {"severity": SEVERITY[cls], "slo_alert": cls}
    labels.update(sorted(slo.alerting[cls]["labels"].items()))
    return labels


def alert_rules(slo):
    if not slo.alerting or not slo.alerting["enabled"]:
        return []
    out = []
    for cls in ("page", "ticket"):
        if not slo.alerting[cls]["enabled"]:
            continue
        out.append({"alert": alert_name(slo, cls), "expr": alert_expr(slo, cls),
                    "labels": alert_labels(slo, cls), "annotations": alert_annotations(slo, cls)})
    return out


def groups_for_service(service):
    groups = []
    for slo in service.slos:
        sli, meta = recording_rules(slo)
        base = f"ftw-slo:{slo.service}:{slo.name}"
        groups.append({"name": f"{base}:sli", "rules": sli})
        groups.append({"name": f"{base}:meta", "rules": meta})
        alerts = alert_rules(slo)
        if alerts:
            groups.append({"name": f"{base}:alerts", "rules": alerts})
    return groups


def header(service, kind="Prometheus rule file"):
    import os
    return (f"# {kind} generated by ftw-slo {VERSION} from {os.path.basename(service.source)}.\n"
            f"# Do not edit by hand: change the SLO spec and run `ftw-slo generate` again.\n")


def rule_file(service):
    return header(service) + yamlio.dump({"groups": groups_for_service(service)})


def count_rules(service):
    rec = alerts = 0
    for g in groups_for_service(service):
        for r in g["rules"]:
            if "record" in r:
                rec += 1
            else:
                alerts += 1
    return rec, alerts


__all__ = ["rule_file", "groups_for_service", "error_ratio_expr", "alert_name", "Decimal"]
