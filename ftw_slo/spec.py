"""SLO spec loading and strict validation (apiVersion: ftw-slo/v1).

    apiVersion: ftw-slo/v1
    service: checkout
    labels: {team: payments}                  # optional, added to every rule
    slos:
      - name: availability
        objective: 99.9                       # percent
        window: 30d                           # 28d or 30d (default 30d)
        sli:
          template: http-availability
          params: {selector: 'job="checkout"'}
        alerting:                             # optional
          name: CheckoutAvailability
          profile: default                    # default | workbook
          page: {labels: {}, annotations: {}}
          ticket: {enabled: true}

All problems are collected and reported together with the file and key path.
"""
import difflib
import os
import re

from . import edition, mathx, templates, yamlio
from .errors import EditionError, SpecError, SpecErrors

API_VERSION = "ftw-slo/v1"
NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
ALERT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LABEL_RE = templates.LABEL_RE
RESERVED_LABELS = {"slo", "slo_service", "slo_alert", "alertname"}

SPEC_KEYS = {"apiVersion", "service", "description", "labels", "tenancy", "slos"}
SLO_KEYS = {"name", "description", "objective", "window", "labels", "sli", "alerting"}
SLI_KEYS = {"template", "params"}
ALERTING_KEYS = {"enabled", "name", "profile", "labels", "annotations", "page", "ticket"}
CLASS_KEYS = {"enabled", "labels", "annotations", "windows"}
WINDOW_KEYS = {"long", "short", "burn_rate"}
TENANCY_KEYS = {"labels"}


class SLO:
    """A validated, normalized SLO ready for rule generation."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def id(self):
        return f"{self.service}/{self.name}"

    @property
    def selector(self):
        return f'slo_service="{self.service}", slo="{self.name}"'


class Service:
    def __init__(self, name, source, description, labels, tenancy, slos):
        self.name = name
        self.source = source
        self.description = description
        self.labels = labels
        self.tenancy = tenancy
        self.slos = slos


class _Ctx:
    def __init__(self, source):
        self.source = source
        self.errors = []

    def err(self, path, msg):
        self.errors.append(SpecError(self.source, path, msg))

    def keys(self, obj, allowed, path, required=()):
        if not isinstance(obj, dict):
            self.err(path, f"must be a mapping, got {type(obj).__name__}")
            return False
        for k in obj:
            if k not in allowed:
                m = difflib.get_close_matches(str(k), sorted(allowed), n=1)
                hint = f" (did you mean {m[0]!r}?)" if m else f" (allowed: {', '.join(sorted(allowed))})"
                self.err(f"{path}.{k}" if path else str(k), f"unknown key{hint}")
        for k in required:
            if k not in obj:
                self.err(f"{path}.{k}" if path else k, "required key is missing")
        return True


def camel(text):
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[-_]", text) if part)


def _labels(ctx, obj, path, reserved=RESERVED_LABELS):
    out = {}
    if obj is None:
        return out
    if not isinstance(obj, dict):
        ctx.err(path, "must be a mapping of label name to value")
        return out
    for k, v in obj.items():
        if not isinstance(k, str) or not LABEL_RE.match(k) or k.startswith("__"):
            ctx.err(f"{path}.{k}", "invalid label name (use [a-zA-Z_][a-zA-Z0-9_]*)")
            continue
        if k in reserved:
            ctx.err(f"{path}.{k}", f"label {k!r} is reserved by ftw-slo")
            continue
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            ctx.err(f"{path}.{k}", "label value must be a string")
            continue
        out[k] = str(v)
    return out


def _string(ctx, obj, key, path, default=""):
    v = obj.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        ctx.err(f"{path}.{key}", "must be a string")
        return default
    return v.strip()


def _windows(ctx, value, path, period, budget):
    if not isinstance(value, list) or not value:
        ctx.err(path, "must be a non-empty list of {long, short, burn_rate}")
        return None
    out = []
    for i, w in enumerate(value):
        wp = f"{path}[{i}]"
        if not ctx.keys(w, WINDOW_KEYS, wp, required=WINDOW_KEYS):
            continue
        try:
            long_s, short_s = mathx.parse_duration(w.get("long")), mathx.parse_duration(w.get("short"))
            rate = mathx.to_decimal(w.get("burn_rate"), "burn_rate")
        except (ValueError, TypeError) as e:
            ctx.err(wp, str(e))
            continue
        if short_s >= long_s:
            ctx.err(wp, "short window must be shorter than the long window")
        if long_s > mathx.parse_duration(period):
            ctx.err(f"{wp}.long", f"long window cannot exceed the SLO window {period}")
        if rate <= 0:
            ctx.err(f"{wp}.burn_rate", "must be > 0")
        out.append({"long": mathx.format_duration(long_s), "short": mathx.format_duration(short_s), "burn_rate": rate})
    return out


def validate_doc(doc, source, doc_index=0):
    """Validate one ftw-slo/v1 document. Returns a Service or raises SpecErrors."""
    ctx = _Ctx(source)
    if not ctx.keys(doc, SPEC_KEYS, "", required=("apiVersion", "service", "slos")):
        raise SpecErrors(ctx.errors)
    if doc.get("apiVersion") != API_VERSION:
        ctx.err("apiVersion", f"must be {API_VERSION!r}, got {doc.get('apiVersion')!r}")
    service = doc.get("service")
    if not isinstance(service, str) or not NAME_RE.match(service):
        ctx.err("service", f"must be a lowercase DNS-style name (a-z, 0-9, -), got {service!r}")
        service = "invalid"
    labels = _labels(ctx, doc.get("labels"), "labels")
    tenancy = []
    if "tenancy" in doc:
        if not edition.has("tenancy"):
            ctx.err("tenancy", edition.missing_message("tenancy", "Multi-tenant / multi-cluster label grouping"))
        elif ctx.keys(doc["tenancy"], TENANCY_KEYS, "tenancy", required=("labels",)):
            tl = doc["tenancy"].get("labels")
            if not isinstance(tl, list) or not tl:
                ctx.err("tenancy.labels", "must be a non-empty list of label names, e.g. [cluster, tenant]")
            else:
                for i, name in enumerate(tl):
                    if not isinstance(name, str) or not LABEL_RE.match(name) or name.startswith("__"):
                        ctx.err(f"tenancy.labels[{i}]", f"invalid label name {name!r}")
                    elif name in RESERVED_LABELS or name in labels or name in tenancy:
                        ctx.err(f"tenancy.labels[{i}]", f"label {name!r} is reserved, duplicated or also a static label")
                    else:
                        tenancy.append(name)
    slos_raw = doc.get("slos")
    slos = []
    if not isinstance(slos_raw, list) or not slos_raw:
        ctx.err("slos", "must be a non-empty list")
        slos_raw = []
    seen = {}
    lib = templates.load_templates()
    for i, raw in enumerate(slos_raw):
        p = f"slos[{i}]"
        if not ctx.keys(raw, SLO_KEYS, p, required=("name", "objective", "sli")):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            ctx.err(f"{p}.name", f"must be a lowercase DNS-style name (a-z, 0-9, -), got {name!r}")
            name = f"invalid-{i}"
        elif name in seen:
            ctx.err(f"{p}.name", f"duplicate SLO name {name!r} (also slos[{seen[name]}])")
        seen[name] = i
        objective = budget = None
        if "objective" in raw:
            try:
                objective = mathx.parse_objective(raw["objective"])
                budget = mathx.error_budget(objective)
            except ValueError as e:
                ctx.err(f"{p}.objective", str(e))
        window = raw.get("window", "30d")
        if window not in mathx.PERIODS:
            ctx.err(f"{p}.window", f"must be one of {', '.join(mathx.PERIODS)} (rolling window), got {window!r}")
            window = "30d"
        slo_labels = dict(labels)
        slo_labels.update(_labels(ctx, raw.get("labels"), f"{p}.labels"))
        template = params = None
        sli = raw.get("sli")
        if ctx.keys(sli, SLI_KEYS, f"{p}.sli", required=("template",)):
            tname = sli.get("template")
            if tname in lib:
                template = lib[tname]
                try:
                    params = templates.resolve_params(template, sli.get("params"), source, f"{p}.sli.params")
                except SpecErrors as e:
                    ctx.errors.extend(e.errors)
                except SpecError as e:
                    ctx.errors.append(e)
            elif tname in edition.ALL_TEMPLATES:
                ctx.err(f"{p}.sli.template", f"template {tname!r} is included in the {edition.ALL_TEMPLATES[tname].title()} "
                        f"edition (this is {edition.EDITION.title()})")
            else:
                m = difflib.get_close_matches(str(tname), sorted(lib), n=1)
                hint = f" (did you mean {m[0]!r}?)" if m else ""
                ctx.err(f"{p}.sli.template", f"unknown template {tname!r}{hint}; run `ftw-slo templates` to list them")
        alerting = _alerting(ctx, raw.get("alerting"), f"{p}.alerting", service, name, window, budget)
        if objective is not None and alerting:
            for cls in ("page", "ticket"):
                if not alerting[cls]["enabled"]:
                    continue
                for w in alerting[cls]["windows"]:
                    if w["burn_rate"] * budget >= 1:
                        ctx.err(f"{p}.alerting.{cls}", f"burn rate {mathx.num(w['burn_rate'])} x error budget {mathx.num(budget)} = "
                                f"{mathx.num(w['burn_rate'] * budget)} >= 1: the {w['long']}/{w['short']} alert could never fire. "
                                f"Raise the objective, or set custom windows with a lower burn_rate.")
        slos.append(SLO(service=service, name=name, description=_string(ctx, raw, "description", p),
                        objective=objective, budget=budget, window=window, labels=slo_labels,
                        template=template, params=params, tenancy=tenancy, alerting=alerting, source=source))
    if ctx.errors:
        raise SpecErrors(ctx.errors)
    return Service(service, source, _string(ctx, doc, "description", ""), labels, tenancy, slos)


def _alerting(ctx, raw, path, service, slo_name, window, budget):
    raw = {} if raw is None else raw
    if not ctx.keys(raw, ALERTING_KEYS, path):
        return None
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        ctx.err(f"{path}.enabled", "must be true or false")
        enabled = True
    name = raw.get("name", camel(service) + camel(slo_name))
    if not isinstance(name, str) or not ALERT_NAME_RE.match(name):
        ctx.err(f"{path}.name", f"must be a Prometheus alert name prefix like CheckoutAvailability, got {name!r}")
    profile = raw.get("profile", "default")
    if profile not in mathx.PROFILES:
        ctx.err(f"{path}.profile", f"must be one of {', '.join(mathx.PROFILES)}, got {profile!r}")
        profile = "default"
    base = mathx.resolve_windows(window, profile)
    common_labels = _labels(ctx, raw.get("labels"), f"{path}.labels")
    common_ann = _annotations(ctx, raw.get("annotations"), f"{path}.annotations")
    out = {"enabled": enabled, "name": name, "profile": profile}
    for cls in ("page", "ticket"):
        c = raw.get(cls) or {}
        cp = f"{path}.{cls}"
        if not ctx.keys(c, CLASS_KEYS, cp):
            c = {}
        cls_enabled = c.get("enabled", True)
        if not isinstance(cls_enabled, bool):
            ctx.err(f"{cp}.enabled", "must be true or false")
            cls_enabled = True
        labels = dict(common_labels)
        labels.update(_labels(ctx, c.get("labels"), f"{cp}.labels"))
        ann = dict(common_ann)
        ann.update(_annotations(ctx, c.get("annotations"), f"{cp}.annotations"))
        windows = base[cls]
        if "windows" in c:
            windows = _windows(ctx, c["windows"], f"{cp}.windows", window, budget) or base[cls]
        out[cls] = {"enabled": enabled and cls_enabled, "labels": labels, "annotations": ann, "windows": windows,
                    "custom": "windows" in c}
    return out


def _annotations(ctx, obj, path):
    out = {}
    if obj is None:
        return out
    if not isinstance(obj, dict):
        ctx.err(path, "must be a mapping")
        return out
    for k, v in obj.items():
        if not isinstance(k, str) or not LABEL_RE.match(k):
            ctx.err(f"{path}.{k}", "invalid annotation name")
        elif k in ("summary", "description"):
            ctx.err(f"{path}.{k}", "summary and description are generated; add your own keys such as runbook_url")
        elif not isinstance(v, str):
            ctx.err(f"{path}.{k}", "annotation value must be a string")
        else:
            out[k] = v
    return out


def detect_format(doc):
    if not isinstance(doc, dict):
        return None
    if doc.get("apiVersion") == API_VERSION:
        return "ftw-slo"
    if doc.get("version") == "prometheus/v1" or doc.get("apiVersion") == "sloth.slok.dev/v1":
        return "sloth"
    if str(doc.get("apiVersion", "")).startswith("openslo/"):
        return "openslo"
    return None


def load_file(path):
    """Load a spec file in any supported format. Returns a list of Service."""
    source = os.path.relpath(path) if not os.path.isabs(path) else path
    try:
        with open(path, encoding="utf-8") as fh:
            docs = yamlio.load_all(fh.read())
    except OSError as e:
        raise SpecErrors([SpecError(source, "", f"cannot read file: {e.strerror}")])
    except Exception as e:  # yaml errors carry line/column marks
        raise SpecErrors([SpecError(source, "", f"invalid YAML: {e}")])
    if not docs:
        raise SpecErrors([SpecError(source, "", "file is empty")])
    formats = {detect_format(d) for d in docs}
    if None in formats:
        raise SpecErrors([SpecError(source, "apiVersion", f"unrecognized document: expected apiVersion {API_VERSION!r}"
                                    + (", a Sloth spec (version: prometheus/v1) or OpenSLO v1" if edition.has("importers") else ""))])
    if formats != {"ftw-slo"}:
        if not edition.has("importers"):
            raise SpecErrors([SpecError(source, "", edition.missing_message("importers", "Sloth and OpenSLO import"))])
        from . import importers
        docs = importers.convert_docs(docs, source)
    services, errors = [], []
    for i, doc in enumerate(docs):
        try:
            services.append(validate_doc(doc, source, i))
        except SpecErrors as e:
            errors.extend(e.errors)
    if errors:
        raise SpecErrors(errors)
    return services


def expand_paths(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames.sort()
                for f in sorted(filenames):
                    if f.endswith((".yaml", ".yml")):
                        files.append(os.path.join(dirpath, f))
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise SpecErrors([SpecError(p, "", "no such file or directory")])
    if not files:
        raise SpecErrors([SpecError(", ".join(paths), "", "no .yaml/.yml spec files found")])
    return files


def load_paths(paths):
    """Load and cross-validate every spec under paths (unique services, SLOs and alert names)."""
    services, errors = [], []
    for f in expand_paths(paths):
        try:
            services.extend(load_file(f))
        except SpecErrors as e:
            errors.extend(e.errors)
    seen_service, seen_alert = {}, {}
    for svc in services:
        if svc.name in seen_service:
            errors.append(SpecError(svc.source, "service", f"service {svc.name!r} is also defined in {seen_service[svc.name]}; "
                                    "keep all SLOs of a service in one spec"))
        seen_service[svc.name] = svc.source
        for slo in svc.slos:
            if slo.alerting:
                n = slo.alerting["name"]
                if n in seen_alert:
                    errors.append(SpecError(svc.source, f"slos[{slo.name}].alerting.name",
                                            f"alert name {n!r} is also used by {seen_alert[n]}"))
                seen_alert[n] = slo.id
    if errors:
        raise SpecErrors(errors)
    return services


__all__ = ["SLO", "Service", "load_file", "load_paths", "validate_doc", "EditionError"]
