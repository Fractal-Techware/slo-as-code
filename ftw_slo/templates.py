"""SLI template library: loading, parameter validation and query rendering.

A template is a YAML file in ftw_slo/templates/. It declares typed parameters and
PromQL query shapes with ${placeholders}. Rendering is plain string substitution of
validated values (no eval, no Jinja): every parameter type has a strict pattern, so
a parameter cannot inject PromQL outside its slot (except `promql` parameters, which
are PromQL by definition and are checked by promtool).

Placeholders:
  ${name}          a parameter value
  ${a+b}           matcher parameters joined with ", " (empty ones skipped)
  ${window}        the range window (5m, 1h, ...)
  ${by}            " by (label, ...) " for multi-tenant grouping, or ""

Kinds:
  ratio      errors (or good) and total event queries -> error ratio = errors / total
  timeslice  a `bad` query evaluating to 1 (bad) / 0 (good) per minute -> error ratio =
             fraction of bad minutes, avg_over_time((bad)[window:1m])
  direct     an `error_ratio` query that already returns errors / total for ${window}
"""
import os
import re

from . import mathx, yamlio
from .errors import SpecError

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
KINDS = {"ratio", "timeslice", "direct"}
TIERS = ("starter", "pro", "studio")
PARAM_TYPES = {"metric", "matchers", "number", "le", "duration", "promql"}

METRIC_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
LABEL_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_MATCHER = r'[a-zA-Z_][a-zA-Z0-9_]*\s*(?:=~|!~|!=|=)\s*"(?:[^"\\\n]|\\.)*"'
MATCHERS_RE = re.compile(r"^\s*(?:%s(?:\s*,\s*%s)*)?\s*,?\s*$" % (_MATCHER, _MATCHER))
PLACEHOLDER_RE = re.compile(r"\$\{([a-z_][a-z0-9_]*(?:\+[a-z_][a-z0-9_]*)*)\}")
TEMPLATE_KEYS = {"name", "tier", "title", "category", "kind", "summary", "description", "requires",
                 "params", "queries", "test", "notes"}
QUERY_KEYS = {"ratio": ({"total"}, {"errors", "good"}), "timeslice": ({"bad"}, set()), "direct": ({"error_ratio"}, set())}


class Template:
    def __init__(self, data, path):
        self.path = path
        self.data = data
        self.name = data["name"]
        self.tier = data["tier"]
        self.title = data["title"]
        self.category = data["category"]
        self.kind = data["kind"]
        self.summary = data["summary"]
        self.description = data.get("description", "").strip()
        self.requires = data.get("requires", "")
        self.params = data.get("params") or {}
        self.queries = data["queries"]
        self.test = data.get("test")
        self.notes = data.get("notes", "")


def _check_template(data, path):
    where = os.path.basename(path)
    if not isinstance(data, dict):
        raise SpecError(where, "", "template must be a mapping")
    for key in data:
        if key not in TEMPLATE_KEYS:
            raise SpecError(where, key, "unknown template key")
    for key in ("name", "tier", "title", "category", "kind", "summary", "queries"):
        if key not in data:
            raise SpecError(where, key, "missing required template key")
    if data["name"] + ".yaml" != os.path.basename(path):
        raise SpecError(where, "name", "template name must match its file name")
    if data["tier"] not in TIERS:
        raise SpecError(where, "tier", f"must be one of {TIERS}")
    if data["kind"] not in KINDS:
        raise SpecError(where, "kind", f"must be one of {sorted(KINDS)}")
    required, one_of = QUERY_KEYS[data["kind"]]
    keys = set(data["queries"])
    if not required <= keys or (one_of and len(keys & one_of) != 1) or keys - required - one_of:
        raise SpecError(where, "queries", f"kind {data['kind']} needs {sorted(required)}"
                        + (f" and exactly one of {sorted(one_of)}" if one_of else ""))
    for pname, p in (data.get("params") or {}).items():
        if not LABEL_RE.match(pname) or pname in ("window", "by"):
            raise SpecError(where, f"params.{pname}", "invalid parameter name")
        if p.get("type") not in PARAM_TYPES:
            raise SpecError(where, f"params.{pname}.type", f"must be one of {sorted(PARAM_TYPES)}")
        if "default" in p and p.get("required"):
            raise SpecError(where, f"params.{pname}", "a required parameter cannot have a default")
        if "default" not in p and not p.get("required"):
            raise SpecError(where, f"params.{pname}", "optional parameters need a default")
        if "description" not in p:
            raise SpecError(where, f"params.{pname}.description", "missing")
    names = set((data.get("params") or {})) | {"window", "by"}
    for qname, q in data["queries"].items():
        for ref in PLACEHOLDER_RE.findall(q):
            for part in ref.split("+"):
                if part not in names:
                    raise SpecError(where, f"queries.{qname}", f"unknown placeholder {part!r}")
            if "+" in ref and any(data["params"][x]["type"] != "matchers" for x in ref.split("+")):
                raise SpecError(where, f"queries.{qname}", f"${{{ref}}} may only join matchers parameters")
        if data["kind"] != "timeslice" and "${window}" not in q and not _uses_windowed_promql(q, data):
            raise SpecError(where, f"queries.{qname}", "query must use ${window}")


def _uses_windowed_promql(query, data):
    params = data.get("params") or {}
    return any(params.get(ref, {}).get("type") == "promql" for ref in PLACEHOLDER_RE.findall(query))


_cache = {}


def load_templates(directory=TEMPLATE_DIR):
    """name -> Template for every *.yaml in the template directory."""
    if directory in _cache:
        return _cache[directory]
    out = {}
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".yaml"):
            continue
        path = os.path.join(directory, fname)
        with open(path, encoding="utf-8") as fh:
            data = yamlio.load(fh.read())
        _check_template(data, path)
        out[data["name"]] = Template(data, path)
    _cache[directory] = out
    return out


def _fmt_number(d):
    return mathx.num(d)


def validate_param(ptype, value, pname):
    """Return the canonical rendered string for a parameter value, or raise ValueError."""
    if isinstance(value, (dict, list)) or value is None:
        raise ValueError(f"{pname} must be a scalar value")
    if ptype == "metric":
        s = str(value).strip()
        if not METRIC_RE.match(s):
            raise ValueError(f"{pname} must be a metric name like http_requests_total, got {value!r}")
        return s
    if ptype == "matchers":
        s = str(value).strip()
        if s.startswith("{") and s.endswith("}"):
            s = s[1:-1].strip()
        if not MATCHERS_RE.match(s):
            raise ValueError(f'{pname} must be label matchers like job="api", code=~"5..", got {value!r}')
        return s.rstrip(" ,")
    if ptype == "number":
        d = mathx.to_decimal(value, pname)
        if d < 0:
            raise ValueError(f"{pname} must be >= 0, got {value!r}")
        return _fmt_number(d)
    if ptype == "le":
        s = str(value).strip()
        if s in ("+Inf", "Inf", "inf"):
            return "+Inf"
        d = mathx.to_decimal(s, pname)
        if d <= 0:
            raise ValueError(f"{pname} must be a positive bucket boundary, got {value!r}")
        # Prometheus 3 normalizes classic histogram `le` labels to float notation: 1 -> "1.0".
        return repr(float(d))
    if ptype == "duration":
        return str(mathx.parse_duration(value))
    if ptype == "promql":
        s = str(value).strip()
        if not s:
            raise ValueError(f"{pname} must not be empty")
        refs = set(PLACEHOLDER_RE.findall(s))
        if "${" in PLACEHOLDER_RE.sub("", s) or refs - {"window"}:
            raise ValueError(f"{pname} may only use the ${{window}} placeholder")
        if "${window}" not in s:
            raise ValueError(f"{pname} must contain ${{window}} as the range, e.g. rate(my_errors_total[${{window}}])")
        return s
    raise ValueError(f"unknown parameter type {ptype}")


def resolve_params(template, given, source, path):
    """Validate user params against the template. Returns name -> rendered string."""
    errors = []
    given = given or {}
    if not isinstance(given, dict):
        raise SpecError(source, path, "params must be a mapping")
    for k in given:
        if k not in template.params:
            hint = _suggest(k, template.params)
            errors.append(SpecError(source, f"{path}.{k}", f"unknown parameter for template {template.name}{hint} "
                                    f"(available: {', '.join(sorted(template.params)) or 'none'})"))
    out = {}
    for pname, p in template.params.items():
        if pname in given:
            value = given[pname]
        elif p.get("required"):
            ex = f" (example: {pname}: '{p['example']}')" if "example" in p else ""
            errors.append(SpecError(source, f"{path}.{pname}", f"required by template {template.name}{ex}"))
            continue
        else:
            value = p["default"]
        try:
            out[pname] = validate_param(p["type"], value, pname)
        except ValueError as e:
            errors.append(SpecError(source, f"{path}.{pname}", str(e)))
    if errors:
        from .errors import SpecErrors
        raise SpecErrors(errors)
    return out


def _suggest(word, options):
    import difflib
    m = difflib.get_close_matches(word, list(options), n=1)
    return f" (did you mean {m[0]!r}?)" if m else ""


def by_clause(labels):
    return f" by ({', '.join(labels)}) " if labels else ""


def render(template, qname, params, window, by_labels=()):
    """Render one query of the template for a window."""
    query = template.queries[qname].strip()

    def sub(m):
        ref = m.group(1)
        if ref == "window":
            return window
        if ref == "by":
            return by_clause(by_labels)
        parts = ref.split("+")
        if len(parts) > 1:
            return ", ".join(params[p] for p in parts if params[p])
        value = params[ref]
        if template.params[ref]["type"] == "promql":
            value = value.replace("${window}", window)
        return value

    out = PLACEHOLDER_RE.sub(sub, query)
    out = re.sub(r"(?<=[a-zA-Z0-9_:])\{\s*\}", "", out)  # metric{} -> metric (empty selector)
    if "${" in out:
        raise ValueError(f"unresolved placeholder in {template.name}.{qname}: {out}")
    return out
