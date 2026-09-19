# Contributing

Thanks for helping improve `ftw-slo`.

- **Bug reports** (a template generates a wrong query, an alert fires when it should not,
  a spec is rejected that should be valid): open an issue with your spec, the generated
  rule file and your Prometheus version.
- **Pull requests**: every change to the generator or a template needs tests.
  - A generator change needs a unit test in `tests/unit/`.
  - A template change needs its promtool timing tests regenerated in `tests/promtool/`
    and the golden files under `generated/` refreshed
    (`python3 ftw-slo generate examples --out generated`).
  - `template-reference.md` is generated: `python3 ftw-slo templates --markdown > template-reference.md`.
- Run `./run-tests.sh` before opening the PR; CI runs the same checks.

Conventions: exact decimal arithmetic (no binary floats) for objectives, budgets and
thresholds; every SLI template has a `test:` fixture so its timing tests can be generated;
every generated alert carries `severity`, `slo`, `slo_service` and `slo_alert` labels.

By contributing you agree that your contribution is licensed under the MIT License.
