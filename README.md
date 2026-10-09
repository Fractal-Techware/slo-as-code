# SLO-as-Code for Prometheus — YAML in, tested burn-rate alerts out

[![tests](https://github.com/Fractal-Techware/slo-as-code/actions/workflows/test.yml/badge.svg)](https://github.com/Fractal-Techware/slo-as-code/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Prometheus 2.40+ | 3.x](https://img.shields.io/badge/Prometheus-2.40%2B%20%7C%203.x-e6522c?logo=prometheus&logoColor=white)
![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776ab?logo=python&logoColor=white)
![SLI templates: 3](https://img.shields.io/badge/SLI%20templates-3-informational)
![tests: 70 unit + 18 promtool](https://img.shields.io/badge/tests-70%20unit%20%2B%2018%20promtool-brightgreen)

Ten lines of YAML per SLO. `ftw-slo` turns them into Prometheus **recording rules** and
**multi-window multi-burn-rate alerts** (SRE Workbook style: page on fast burn, ticket on
slow burn) — and ships the promtool tests that prove a real outage pages within minutes
and healthy traffic never does.

```yaml
# slos/checkout.yaml
apiVersion: ftw-slo/v1
service: checkout
slos:
  - name: availability
    objective: 99.9
    sli:
      template: http-availability
      params:
        selector: 'job="checkout"'
```

```bash
python3 ftw-slo generate slos/ --out generated/
# -> generated/rules/checkout.rules.yml: 14 recording rules + 2 alerts
```

Python 3.9+ and PyYAML are the only requirements. Works with Prometheus 2.40+ and 3.x,
kube-prometheus-stack, Grafana Mimir, Thanos and VictoriaMetrics.

By [Fractal Techware](https://store.fractaltechware.com/?utm_source=github&utm_medium=readme&utm_campaign=free-repo). MIT licensed.

## What's included

| | What you get |
|---|---|
| `ftw-slo` CLI | `validate`, `generate`, `templates`, `version` — stdlib + PyYAML, no install needed |
| SLI templates | **3**: `http-availability`, `http-latency`, `generic-ratio` ([reference](template-reference.md)) |
| Recording rules | Per SLO: 5m/30m/1h/2h/6h/1d/3d error ratios, SLO-window error ratio, objective, error budget, budget remaining |
| Alerts | Page on fast burn (1h/5m at 14.4x), ticket on slow burn (6h/30m, 1d/2h, 3d/6h); `profile: workbook` also available |
| Exact math | Decimal arithmetic: `99.9` is `0.001`, `14.4 * 0.001` is `0.0144`; 28-day windows get their own factors (13.44 / 5.6 / 2.8 / 0.933333) |
| Example specs | 3 specs / 4 SLOs in `examples/`, with the exact generated output in `generated/` |
| promtool tests | **18 timing scenarios** (fast burn, slow burn, healthy × 99.9% and 99.5% × 3 templates) |
| Unit tests | **70** for the parser, validation errors, decimal math, templates and golden files |
| Docs | [`slo-math.md`](slo-math.md) — objectives, budgets, burn-rate factors, detection times |
| `run-tests.sh` | All of the above in one command (local `promtool`, or the pinned Docker image) |

### SLI templates in this repository

| Template | Kind | Summary |
|---|---|---|
| `http-availability` | ratio | Share of HTTP requests that did not fail with a server error (5xx). |
| `http-latency` | ratio | Share of HTTP requests served faster than a threshold, from a classic histogram. |
| `generic-ratio` | ratio | Any event-based SLI from your own "bad events" and "all events" PromQL expressions. |

## 60-second quick start

```bash
git clone https://github.com/Fractal-Techware/slo-as-code.git
cd slo-as-code
python3 -m pip install --user pyyaml

python3 ftw-slo templates                       # the 3 SLI templates
python3 ftw-slo validate examples               # 3 services, 4 SLOs valid
python3 ftw-slo generate examples --out out/    # rule files for each service
```

Prove it, including the burn-rate timing:

```bash
./run-tests.sh          # local promtool, or the pinned prom/prometheus image via Docker
```

```
==> unit tests
70 passed
==> ftw-slo validate examples/
  SUCCESS
==> promtool check rules (6 files)
  SUCCESS
==> promtool test rules (3 files, 18 scenarios, ~30s)
  SUCCESS
All checks passed.
```

### Load the rules into Prometheus

Copy the generated files next to your Prometheus config and add:

```yaml
rule_files:
  - /etc/prometheus/rules/*.yml
```

Reload (`curl -X POST http://localhost:9090/-/reload` with `--web.enable-lifecycle`) and check
**Status → Rule Health**: every `ftw-slo:*` group must be `ok`. The SLO-window rule uses
`sum_over_time(...[30d])`, so give Prometheus at least the SLO window of retention.

For Mimir or Grafana Cloud: `mimirtool rules load generated/rules/*.yml`.
For Thanos Ruler: `--rule-file=generated/rules/*.yml`. For vmalert: `-rule=generated/rules/*.yml`.

### Write your first SLO

```bash
python3 ftw-slo templates http-availability   # parameters + a ready-to-edit example spec
```

| Spec field | Meaning |
|---|---|
| `service` | Becomes the `slo_service` label and the rule file name |
| `slos[].name` | Becomes the `slo` label; `service/name` is the SLO id |
| `slos[].objective` | 0 < objective < 100, up to 5 decimals (`99.9`, `99.95`) |
| `slos[].window` | SLO window, default `30d` (`28d` gets its own burn-rate factors) |
| `slos[].sli.template` / `.params` | Which SLI template and its parameters |
| `slos[].alerting` | `name`, `profile`, extra `labels` / `annotations`, or `page`/`ticket` overrides (`enabled: false`, custom `windows`) |
| `labels` | Extra labels copied onto every generated rule (e.g. `team`) |

## What the tests actually prove

Burn-rate alerting is easy to copy from a blog post and hard to verify before an incident.
Each SLI template here has six [promtool](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)
timing scenarios, run against synthetic traffic at 1000 events/minute:

- **Fast burn pages, fast.** After 6 hours of clean traffic, errors jump to 100%. Nothing is
  firing at the end of the healthy phase; the page alert *is* firing 3 minutes later at 99.9%
  and 7 minutes later at 99.5% — exactly the detection time
  `long window × factor × budget / error ratio` predicts.
- **Slow burn does not page.** A sustained 2× burn opens a ticket at 2h and 6h while the page
  alert stays quiet.
- **Healthy traffic stays quiet.** At half the error budget, nothing fires across a full day of
  data, and `ftw_slo:error_budget_remaining:ratio` is exactly `0.5` at the end.

Plus 70 unit tests: the generated files are byte-identical on re-generation, every template
renders for every burn-rate window with balanced parentheses, every alert only references
error ratios that are actually recorded, invalid specs fail with a field path and exit 1, and
`promtool check rules` accepts every rule file. CI runs the same `./run-tests.sh` on every push.

## Repository layout

```
ftw-slo                 run without installing: python3 ftw-slo --help
ftw_slo/                the package (stdlib + PyYAML) and templates/
pyproject.toml          optional install: pipx install .
examples/               3 example SLO specs (4 SLOs)
generated/              exactly what ftw-slo generates from examples/ (golden files)
tests/unit/             70 unit tests (pytest or unittest)
tests/promtool/         18 burn-rate timing scenarios + the specs and rules they use
run-tests.sh            everything above in one command
slo-math.md             objectives, error budgets, burn rates, detection times
template-reference.md   every SLI template and its parameters (generated)
```

## Want the full pack?

This repository is a free, fully working subset of the
**[SLO-as-Code Kit](https://store.fractaltechware.com/l/slo-as-code-kit?utm_source=github&utm_medium=readme&utm_campaign=free-repo)**
— same generator, same test standard. If these three templates cover your HTTP services but
not your mesh, your queues or your dashboards, the paid tiers pick up where this leaves off:

| | **Free** (this repo) | **Starter** $19 | **Pro** $49 | **Agency** $299 |
|---|:---:|:---:|:---:|:---:|
| `ftw-slo` generator, recording rules, page/ticket burn-rate alerts | yes | yes | yes | yes |
| SLI templates | 3 | 5 | 21 | 21 |
| gRPC, ingress-nginx | – | yes | yes | yes |
| Istio, Envoy, Traefik, Linkerd, Kafka lag, queues, CronJobs, PostgreSQL, blackbox, OTel span metrics, native histograms | – | – | yes | yes |
| promtool timing scenarios | 18 | 30 | 122 | 123 |
| Unit tests | 70 | 70 | 89 | 108 |
| PrometheusRule CRDs, a Grafana dashboard per SLO, Sloth/OpenSLO import, Alertmanager page/ticket routing, error budget policy | – | – | yes | yes |
| Error budget report (Markdown/HTML from the Prometheus API), multi-tenant labels, Helm values, CI workflow, SLO workshop guide | – | – | – | yes |
| License | MIT | own organization | own organization | client / agency use |

[See the full kit on Gumroad →](https://store.fractaltechware.com/l/slo-as-code-kit?utm_source=github&utm_medium=readme&utm_campaign=free-repo)

## More free repos

Other MIT-licensed samples from Fractal Techware — tested Prometheus alert rules and runbooks,
OpenTelemetry Collector recipes, Kubernetes hardening baselines, Grafana dashboards:
**[github.com/Fractal-Techware](https://github.com/Fractal-Techware)**

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Every generator or template change needs a test.

## More free editions from Fractal Techware

Every pack has a free, MIT-licensed edition. These are the other nine — all runnable, all with
their own tests.

- [Prometheus Alert Rules & Runbooks](https://github.com/Fractal-Techware/prometheus-alert-rules) — tested alert rules, each with a runbook
- [Kubernetes Hardening Baseline](https://github.com/Fractal-Techware/kubernetes-hardening-baseline) — Kyverno policies proven with enforce semantics
- [Production Helm Chart](https://github.com/Fractal-Techware/helm-production-chart) — library chart with secure defaults and helm-unittest suites
- [OpenTelemetry Collector Recipes](https://github.com/Fractal-Techware/opentelemetry-collector-recipes) — collector configs: tail sampling, PII redaction, Kubernetes
- [Grafana Dashboards](https://github.com/Fractal-Techware/grafana-dashboards) — provisioned dashboards for hosts, Kubernetes and Prometheus
- [VPS Observability Stack](https://github.com/Fractal-Techware/vps-observability-stack) — single-server Prometheus, Grafana and Loki behind Caddy
- [n8n Production Compose](https://github.com/Fractal-Techware/n8n-production-compose) — hardened n8n with Postgres and automatic HTTPS
- [n8n Incident Triage](https://github.com/Fractal-Techware/n8n-incident-triage-workflow) — Alertmanager to LLM triage to chat, as n8n workflows
- [n8n GitHub PR Summary](https://github.com/Fractal-Techware/n8n-github-pr-summary) — AI pull-request review and summary workflows

The paid tiers and the full catalogue are at [fractaltechware.com](https://fractaltechware.com).

## License

[MIT](LICENSE) © 2026 Fractal Techware SRL
