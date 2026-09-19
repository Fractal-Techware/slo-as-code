"""ftw-slo command line interface.

    ftw-slo validate SPEC_OR_DIR...
    ftw-slo generate SPEC_OR_DIR... --out DIR [--only rules,crd,dashboards,helm]
    ftw-slo templates [NAME] [--markdown]
    ftw-slo import SLOTH_OR_OPENSLO_FILE... --out DIR          (Pro, Studio)
    ftw-slo report --specs DIR --prometheus URL --month 2026-08  (Studio)
    ftw-slo version

Exit codes: 0 success, 1 invalid spec / failed check, 2 usage error.
"""
import argparse
import os
import sys

from . import VERSION, edition, mathx, rules, spec, templates, yamlio
from .errors import EditionError, SpecError, SpecErrors

OUTPUTS = ("rules", "crd", "dashboards", "helm")


def _err(msg):
    print(f"ftw-slo: {msg}", file=sys.stderr)


def _print_errors(e):
    errs = e.errors if isinstance(e, SpecErrors) else [e]
    for x in errs:
        print(f"error: {x}", file=sys.stderr)
    print(f"{len(errs)} error(s)", file=sys.stderr)


def cmd_validate(args):
    try:
        services = spec.load_paths(args.paths)
    except SpecErrors as e:
        _print_errors(e)
        return 1
    n_slo = sum(len(s.slos) for s in services)
    for svc in services:
        for slo in svc.slos:
            rec, alerts = len(rules.recording_rules(slo)[0]) + len(rules.recording_rules(slo)[1]), len(rules.alert_rules(slo))
            print(f"ok  {slo.id:40} {mathx.num(slo.objective)}% / {slo.window}  {slo.template.name}  "
                  f"({rec} recording rules, {alerts} alerts)")
    print(f"{len(services)} service(s), {n_slo} SLO(s) valid")
    return 0


def _write(path, text, written):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    written.append(path)


def default_outputs():
    out = ["rules"]
    if edition.has("crd"):
        out.append("crd")
    if edition.has("dashboards"):
        out.append("dashboards")
    return out


def cmd_generate(args):
    only = default_outputs() if not args.only else [x.strip() for x in args.only.split(",") if x.strip()]
    for o in only:
        if o not in OUTPUTS:
            _err(f"--only: unknown output {o!r} (choose from {', '.join(OUTPUTS)})")
            return 2
        feature = {"crd": "crd", "dashboards": "dashboards", "helm": "helm"}.get(o)
        if feature and not edition.has(feature):
            _err(edition.missing_message(feature, {"crd": "PrometheusRule CRD output", "dashboards": "Grafana dashboard generation",
                                                   "helm": "kube-prometheus-stack Helm values output"}[feature]))
            return 2
    crd_labels = {}
    for item in args.crd_label or []:
        if "=" not in item:
            _err(f"--crd-label must be key=value, got {item!r}")
            return 2
        k, v = item.split("=", 1)
        crd_labels[k] = v
    try:
        services = spec.load_paths(args.paths)
    except SpecErrors as e:
        _print_errors(e)
        return 1
    written = []
    for svc in sorted(services, key=lambda s: s.name):
        if "rules" in only:
            _write(os.path.join(args.out, "rules", f"{svc.name}.rules.yml"), rules.rule_file(svc), written)
        if "crd" in only:
            from . import crd
            _write(os.path.join(args.out, "prometheusrules", f"{svc.name}.yaml"),
                   crd.prometheus_rule(svc, args.namespace, crd_labels or None), written)
        if "dashboards" in only:
            from . import dashboards
            for slo in svc.slos:
                _write(os.path.join(args.out, "dashboards", f"{svc.name}-{slo.name}.json"), dashboards.dashboard_json(slo), written)
    if "helm" in only:
        from . import helm
        ordered = sorted(services, key=lambda s: s.name)
        _write(os.path.join(args.out, "helm", "values-ftw-slo-rules.yaml"), helm.values(ordered), written)
        _write(os.path.join(args.out, "helm", "grafana-dashboards.yaml"), helm.dashboard_configmaps(ordered, args.namespace), written)
    if "crd" in only:
        from . import crd
        _write(os.path.join(args.out, "prometheusrules", "kustomization.yaml"),
               crd.kustomization(sorted(s.name for s in services), args.namespace), written)
    for p in written:
        print(f"wrote {p}")
    n_slo = sum(len(s.slos) for s in services)
    print(f"{len(services)} service(s), {n_slo} SLO(s), {len(written)} file(s)")
    return 0


def template_markdown(lib):
    lines = ["# SLI template reference", "",
             f"ftw-slo {VERSION}, {edition.EDITION.title()} edition: {len(lib)} templates. "
             "Generated with `ftw-slo templates --markdown`.", "",
             "| Template | Kind | Category | Summary |", "|---|---|---|---|"]
    for t in lib.values():
        lines.append(f"| [`{t.name}`](#{t.name}) | {t.kind} | {t.category} | {t.summary} |")
    for t in lib.values():
        lines += ["", f"## {t.name}", "", f"**{t.title}** ({t.kind}, {t.category}). {t.summary}", ""]
        if t.description:
            lines += [t.description, ""]
        if t.requires:
            lines += [f"Requires: {t.requires}", ""]
        lines += ["| Parameter | Type | Default | Description |", "|---|---|---|---|"]
        for pname, p in t.params.items():
            default = "**required**" if p.get("required") else (f"`{p['default']}`" if p["default"] != "" else "(empty)")
            desc = p["description"] + (f" Example: `{p['example']}`" if "example" in p else "")
            lines.append(f"| `{pname}` | {p['type']} | {default} | {desc.replace('|', '&#124;')} |")
        lines += ["", "Query shapes (`${window}` is filled for every burn-rate window):", "", "```promql"]
        for qname, q in t.queries.items():
            lines.append(f"# {qname}")
            lines.append(q.strip())
        lines += ["```"]
        if t.notes:
            lines += ["", t.notes.strip()]
    return "\n".join(lines) + "\n"


def cmd_templates(args):
    lib = templates.load_templates()
    if args.markdown:
        sys.stdout.write(template_markdown(lib))
        return 0
    if args.name:
        if args.name not in lib:
            _err(f"unknown template {args.name!r}")
            return 1
        t = lib[args.name]
        print(f"{t.name}: {t.title} ({t.kind}, {t.category})\n\n{t.summary}\n")
        if t.description:
            print(t.description + "\n")
        print("Parameters:")
        for pname, p in t.params.items():
            default = "required" if p.get("required") else f"default: {p['default']!r}"
            print(f"  {pname:18} {p['type']:9} {default}\n  {'':18} {p['description']}")
        example = {"apiVersion": "ftw-slo/v1", "service": "my-service", "slos": [{
            "name": t.category, "objective": 99.9, "window": "30d",
            "sli": {"template": t.name, "params": {k: p["example"] for k, p in t.params.items() if p.get("required")}}}]}
        print("\nExample spec:\n")
        print(yamlio.dump(example))
        return 0
    for t in lib.values():
        print(f"{t.name:32} {t.kind:10} {t.summary}")
    print(f"\n{len(lib)} templates ({edition.EDITION.title()} edition). `ftw-slo templates NAME` shows parameters.")
    return 0


def cmd_import(args):
    if not edition.has("importers"):
        _err(edition.missing_message("importers", "Sloth and OpenSLO import"))
        return 2
    from . import importers
    written, errors = [], []
    for path in spec.expand_paths(args.paths):
        try:
            for name, text in importers.import_file(path):
                _write(os.path.join(args.out, f"{name}.yaml"), text, written)
        except (SpecErrors, SpecError) as e:
            errors.append(e)
    for p in written:
        print(f"wrote {p}")
    if errors:
        for e in errors:
            _print_errors(e)
        return 1
    return 0


def cmd_report(args):
    if not edition.has("report"):
        _err(edition.missing_message("report", "The error budget report"))
        return 2
    from . import report
    return report.main(args)


def build_parser():
    p = argparse.ArgumentParser(prog="ftw-slo", description="SLO-as-Code: Prometheus SLO rules, alerts and dashboards from YAML.")
    sub = p.add_subparsers(dest="command")
    v = sub.add_parser("validate", help="validate SLO specs")
    v.add_argument("paths", nargs="+", help="spec files or directories")
    v.set_defaults(func=cmd_validate)
    g = sub.add_parser("generate", help="generate rules (and CRDs, dashboards) from SLO specs")
    g.add_argument("paths", nargs="+", help="spec files or directories")
    g.add_argument("--out", "-o", required=True, help="output directory")
    g.add_argument("--only", help=f"comma-separated outputs: {', '.join(OUTPUTS)} (default: all in this edition except helm)")
    g.add_argument("--namespace", default="monitoring", help="namespace of PrometheusRule objects (default: monitoring)")
    g.add_argument("--crd-label", action="append", metavar="KEY=VALUE",
                   help="label for PrometheusRule objects (repeatable; default: release=kube-prometheus-stack)")
    g.set_defaults(func=cmd_generate)
    t = sub.add_parser("templates", help="list SLI templates or show one")
    t.add_argument("name", nargs="?")
    t.add_argument("--markdown", action="store_true", help="print the template reference as Markdown")
    t.set_defaults(func=cmd_templates)
    i = sub.add_parser("import", help="convert Sloth or OpenSLO v1 specs to ftw-slo specs (Pro)")
    i.add_argument("paths", nargs="+")
    i.add_argument("--out", "-o", required=True)
    i.set_defaults(func=cmd_import)
    r = sub.add_parser("report", help="error budget report from the Prometheus HTTP API (Studio)")
    r.add_argument("--specs", nargs="+", required=True, help="spec files or directories")
    src = r.add_mutually_exclusive_group(required=True)
    src.add_argument("--prometheus", help="Prometheus base URL, e.g. http://prometheus:9090")
    src.add_argument("--fixture", help="replay responses recorded with --record (offline)")
    r.add_argument("--record", help="save every API response to this JSON file")
    period = r.add_mutually_exclusive_group(required=True)
    period.add_argument("--month", help="calendar month in UTC, e.g. 2026-08")
    period.add_argument("--range", nargs=2, metavar=("START", "END"), help="RFC 3339 start and end, e.g. 2026-08-01T00:00:00Z")
    r.add_argument("--format", choices=("markdown", "html"), default="markdown")
    r.add_argument("--out", "-o", help="output file (default: stdout)")
    r.add_argument("--title", default="Error budget report")
    r.add_argument("--timeout", type=float, default=30.0)
    r.add_argument("--fail-on-missed", action="store_true", help="exit 1 if any SLO missed its objective in the period")
    r.set_defaults(func=cmd_report)
    ver = sub.add_parser("version", help="print version and edition")
    ver.set_defaults(func=lambda a: print(f"ftw-slo {VERSION} ({edition.EDITION.title()} edition)") or 0)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except SpecErrors as e:
        _print_errors(e)
        return 1
    except EditionError as e:
        _err(str(e))
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
