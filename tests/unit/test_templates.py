import os
import re
import unittest

import helpers
from ftw_slo import edition, mathx, rules, spec, templates


class TemplateLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = templates.load_templates()
        cls.examples = spec.load_paths([helpers.EXAMPLES])

    def test_template_count_for_edition(self):
        expected = {n for n, t in edition.ALL_TEMPLATES.items() if edition.RANK[t] <= edition.RANK[edition.EDITION]}
        self.assertEqual(set(self.lib), expected)

    def test_every_template_used_by_an_example(self):
        used = {slo.template.name for svc in self.examples for slo in svc.slos}
        self.assertEqual(set(self.lib) - used, set())

    def test_every_template_has_promtool_timing_tests(self):
        for name in self.lib:
            for rel in (f"{name}.test.yml", os.path.join("specs", f"{name}.yaml"), os.path.join("rules", f"{name}.rules.yml")):
                self.assertTrue(os.path.isfile(os.path.join(helpers.PROMTOOL, rel)), f"{name}: missing tests/promtool/{rel}")
            with open(os.path.join(helpers.PROMTOOL, f"{name}.test.yml"), encoding="utf-8") as fh:
                text = fh.read()
            for tag in ("99.9%: fast burn", "99.5%: fast burn", "99.9%: healthy", "99.5%: healthy", "99.5%: slow burn"):
                self.assertIn(tag, text, f"{name}: missing scenario {tag}")

    def test_every_template_renders_all_windows(self):
        for name, t in self.lib.items():
            example = {k: p.get("example", p.get("default")) for k, p in t.params.items()}
            params = {k: templates.validate_param(t.params[k]["type"], v, k) for k, v in example.items()}
            for w in ("5m", "30m", "1h", "2h", "6h", "1d", "3d"):
                for q in t.queries:
                    out = templates.render(t, q, params, w)
                    self.assertNotIn("${", out, f"{name}.{q}")
                    if t.kind != "timeslice":
                        self.assertIn(f"[{w}]", out, f"{name}.{q} does not use the window")
                    self.assertEqual(out.count("("), out.count(")"), f"{name}.{q} unbalanced parentheses")
                    out_by = templates.render(t, q, params, w, ["cluster"])
                    if "${by}" in t.queries[q]:
                        self.assertIn(" by (cluster) ", out_by)

    def test_every_template_documents_params(self):
        for t in self.lib.values():
            self.assertTrue(t.summary and t.title and t.requires, t.name)
            for pname, p in t.params.items():
                self.assertTrue(p["description"], f"{t.name}.{pname}")
                if p.get("required"):
                    self.assertIn("example", p, f"{t.name}.{pname}: required params need an example")

    def test_template_test_fixture_series_parse(self):
        for t in self.lib.values():
            self.assertTrue(t.test and t.test["series"], t.name)
            for s in t.test["series"]:
                self.assertIn(s["type"], ("counter", "gauge", "native"), t.name)
                self.assertRegex(s["series"], r"^[a-zA-Z_:][a-zA-Z0-9_:]*\{.*\}$")


class ParamValidationTests(unittest.TestCase):
    def test_matchers(self):
        ok = ['job="a"', 'job="a", code=~"5.."', '{job="a"}', 'path="/a,b"', 'x!~"y\\"z"', "", 'job="a",']
        for v in ok:
            templates.validate_param("matchers", v, "selector")
        bad = ['job=a', 'job="a"} or vector(1)', 'job="a"; drop', '1abc="x"', 'job="a" code="b"', 'job="a\n"']
        for v in bad:
            with self.assertRaises(ValueError, msg=v):
                templates.validate_param("matchers", v, "selector")

    def test_le_normalized_like_prometheus_3(self):
        self.assertEqual(templates.validate_param("le", 1, "t"), "1.0")
        self.assertEqual(templates.validate_param("le", "0.3", "t"), "0.3")
        self.assertEqual(templates.validate_param("le", 250, "t"), "250.0")
        self.assertEqual(templates.validate_param("le", "+Inf", "t"), "+Inf")
        with self.assertRaises(ValueError):
            templates.validate_param("le", "-1", "t")

    def test_duration_and_number(self):
        self.assertEqual(templates.validate_param("duration", "26h", "max_age"), "93600")
        self.assertEqual(templates.validate_param("number", 1000, "max_lag"), "1000")
        self.assertEqual(templates.validate_param("number", "0.50", "x"), "0.5")
        for bad in ("-1", "abc", [1]):
            with self.assertRaises(ValueError):
                templates.validate_param("number", bad, "x")

    def test_promql_params_need_window(self):
        templates.validate_param("promql", "sum(rate(x[${window}]))", "q")
        for bad in ("sum(rate(x[5m]))", "sum(rate(x[${window}])) + ${other}", "  "):
            with self.assertRaises(ValueError):
                templates.validate_param("promql", bad, "q")

    def test_matchers_join_skips_empty(self):
        t = templates.load_templates()["http-latency"]
        params = {"selector": 'job="a"', "metric": "m", "threshold": "0.3", "request_matcher": ""}
        self.assertEqual(templates.render(t, "total", params, "5m"), 'sum(rate(m_count{job="a"}[5m]))')


class RuleShapeTests(unittest.TestCase):
    def test_every_example_slo_has_expected_rules(self):
        for svc in spec.load_paths([helpers.EXAMPLES]):
            for slo in svc.slos:
                sli, meta = rules.recording_rules(slo)
                names = [r["record"] for r in sli + meta]
                for required in (rules.SLI_ERRORS, rules.SLI_TOTAL, rules.RATIO.format("5m"), rules.RATIO_PERIOD,
                                 rules.REMAINING, rules.OBJECTIVE, rules.BUDGET):
                    self.assertIn(required, names, slo.id)
                for r in sli + meta:
                    self.assertEqual(r["labels"]["slo_service"], slo.service)
                    self.assertEqual(r["labels"]["slo"], slo.name)
                for alert in rules.alert_rules(slo):
                    for window in re.findall(r"ratio_rate(\w+)\{", alert["expr"]):
                        self.assertIn(f"ftw_slo:sli_error:ratio_rate{window}", names, f"{slo.id}: alert uses unrecorded window")
                    self.assertIn(alert["labels"]["severity"], ("critical", "warning"))

    def test_threshold_rendering(self):
        with helpers.TempDir() as d:
            slo = spec.load_file(helpers.write_spec(d, helpers.MINIMAL.replace("99.9", "99.95")))[0].slos[0]
        expr = rules.alert_expr(slo, "page")
        self.assertIn("> (14.4 * 0.0005)", expr)
        self.assertIn("ratio_rate1h", expr)
        self.assertIn("ratio_rate5m", expr)
        self.assertIn("> (1 * 0.0005)", rules.alert_expr(slo, "ticket"))
        self.assertEqual(mathx.num(slo.objective / 100), "0.9995")

    def test_disabled_alert_classes(self):
        text = helpers.MINIMAL + "    alerting:\n      page:\n        enabled: false\n"
        with helpers.TempDir() as d:
            slo = spec.load_file(helpers.write_spec(d, text))[0].slos[0]
        self.assertEqual([a["alert"] for a in rules.alert_rules(slo)], ["CheckoutAvailabilitySlowBurn"])
        text = helpers.MINIMAL + "    alerting:\n      enabled: false\n"
        with helpers.TempDir() as d:
            slo = spec.load_file(helpers.write_spec(d, text))[0].slos[0]
        self.assertEqual(rules.alert_rules(slo), [])
        self.assertEqual(rules.windows_for(slo), ["5m"])

    def test_empty_error_series_counts_as_zero(self):
        with helpers.TempDir() as d:
            slo = spec.load_file(helpers.write_spec(d, helpers.MINIMAL))[0].slos[0]
        self.assertIn("or\n  0 * sum(rate(http_requests_total", rules.error_ratio_expr(slo, "1h"))


if __name__ == "__main__":
    unittest.main()
