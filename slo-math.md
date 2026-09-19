# The math behind the generated rules

Everything ftw-slo generates comes from four numbers: the objective, the error budget,
the error ratio over a window and the burn rate. This page shows exactly how they are
computed, so you can defend the alerts in a review.

## Objective and error budget

An objective of `99.9` means 99.9% of events must be good over the SLO window:

```
error budget = (100 - objective) / 100        99.9  -> 0.001      (0.1% of events)
                                              99.95 -> 0.0005
                                              99.5  -> 0.005
```

ftw-slo does this arithmetic with decimals, not binary floating point, so `99.9` gives
exactly `0.001` and `14.4 * 0.001` is exactly `0.0144` — no `0.0014400000000000001`
in your rules. Objectives may have up to 5 decimals; `100` is rejected (a zero budget
can never be met) and so is `0`.

Over a 30-day window an error budget of 0.001 is about **43 minutes** of full outage
(0.001 x 30 x 24 x 60), or 0.1% of all requests failing continuously.

## Error ratio (the SLI)

Every SLI template produces the same thing: the share of bad events in a window.

```
ratio(W) = bad events in W / all events in W
```

All three SLI templates in this repository are **event SLIs** (`kind: ratio`):
`sum(rate(errors[W])) / sum(rate(total[W]))`. If the error series does not exist yet
(nothing has failed), ftw-slo adds `or 0 * sum(rate(total[W]))`, so the ratio is `0`,
not "no data".

Over the SLO window ftw-slo does not run `rate(...[30d])` (expensive, and it would need
raw data for 30 days). It records the 5-minute numerator and denominator and integrates
them instead:

```
ftw_slo:sli_error:ratio_period
  = sum_over_time(ftw_slo:sli_errors:rate5m[30d]) / sum_over_time(ftw_slo:sli_total:rate5m[30d])
```

This is **weighted by traffic** (a busy hour counts more than a quiet one), which is what
"99.9% of requests" means. Tools that average the 5m ratio over 30 days instead answer a
different question ("99.9% of minutes").

Remaining budget:

```
ftw_slo:error_budget_remaining:ratio = 1 - ratio_period / error_budget
```

`1` = untouched, `0` = exactly spent, negative = overspent (`-0.5` = 150% of the budget used).

## Burn rate

```
burn rate = error ratio / error budget
```

A burn rate of 1 consumes the whole budget in exactly one SLO window; 14.4 consumes it in
30d / 14.4 = 50 hours. An alert should fire when a given **share of the budget** would be
spent within the alert's long window, which gives the factor:

```
burn rate = budget consumption x SLO window / long window
```

| Alert | Long / short window | Budget consumed | Factor (30d) | Factor (28d) | Error ratio threshold at 99.9% |
|---|---|---|---:|---:|---:|
| page (fast burn) | 1h / 5m | 2% | 14.4 | 13.44 | 0.0144 |
| ticket (slow burn) | 6h / 30m | 5% | 6 | 5.6 | 0.006 |
| ticket (slow burn) | 1d / 2h | 10% | 3 | 2.8 | 0.003 |
| ticket (slow burn) | 3d / 6h | 10% | 1 | 0.933333 | 0.001 |

With `profile: workbook` the 6h/30m window pages instead of opening a ticket and the
1d/2h window is dropped — table 5-8 of the SRE Workbook exactly.

The **short window** (always 1/12 of the long one) is the "is it still happening?" check:
both windows must be above the threshold, so the alert resolves quickly after the incident
ends instead of hanging on for the length of the long window.

Generated alert (99.9%, page):

```promql
(
  ftw_slo:sli_error:ratio_rate1h{slo_service="checkout", slo="availability"} > (14.4 * 0.001)
  and
  ftw_slo:sli_error:ratio_rate5m{slo_service="checkout", slo="availability"} > (14.4 * 0.001)
)
```

The threshold is written as `factor * budget` so the numbers stay readable in the alert.

## Detection time

For a constant error ratio `r`, the long window crosses the threshold after

```
detection time = long window x factor x budget / r
```

100% errors on a 99.9% SLO: `60min x 14.4 x 0.001 / 1` = **52 seconds** (plus your
evaluation interval). At 99.5%: `60 x 14.4 x 0.005` = 4.3 minutes. The promtool tests in
`tests/promtool/` assert exactly this: the page alert is firing 3 minutes (99.9%) and
7 minutes (99.5%) after the outage starts, and nothing fires before it.

Low objectives cannot page on fast burn at all: at 90% the threshold would be
`14.4 x 0.1 = 1.44`, an error ratio of 144%, which is impossible. ftw-slo rejects that
spec with a message instead of generating an alert that can never fire.

## Why not `for:`?

Workbook-style alerts use a short window instead of a `for:` duration: the short window
already filters out single spikes and, unlike `for:`, it does not delay a real outage.
If you want extra damping anyway, use custom windows with a lower burn rate.
