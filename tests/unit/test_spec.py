import os
import unittest

import helpers
from ftw_slo import edition, spec
from ftw_slo.errors import SpecErrors


def errors_for(text):
    with helpers.TempDir() as d:
        path = helpers.write_spec(d, text)
        try:
            spec.load_file(path)
        except SpecErrors as e:
            return [str(x) for x in e.errors]
    return []


def base(extra_slo="", top="", objective="99.9", params="selector: 'job=\"checkout\"'"):
    return f"""
apiVersion: ftw-slo/v1
service: checkout
{top}
slos:
  - name: availability
    objective: {objective}
    sli:
      template: http-availability
      params:
        {params}
{extra_slo}
"""


class ValidSpecTests(unittest.TestCase):
    def test_minimal_spec_defaults(self):
        with helpers.TempDir() as d:
            svc = spec.load_file(helpers.write_spec(d, helpers.MINIMAL))[0]
        slo = svc.slos[0]
        self.assertEqual(slo.window, "30d")
        self.assertEqual(str(slo.budget), "0.001")
        self.assertEqual(slo.alerting["name"], "CheckoutAvailability")
        self.assertEqual(slo.params["error_matcher"], 'code=~"5.."')
        self.assertTrue(slo.alerting["page"]["enabled"] and slo.alerting["ticket"]["enabled"])

    def test_every_example_validates(self):
        services = spec.load_paths([helpers.EXAMPLES])
        self.assertGreater(len(services), 0)


class ValidationErrorTests(unittest.TestCase):
    def assertError(self, text, *needles):
        errs = errors_for(text)
        self.assertTrue(errs, "expected a validation error")
        joined = "\n".join(errs)
        for n in needles:
            self.assertIn(n, joined)

    def test_unknown_key_with_suggestion(self):
        self.assertError(base().replace("objective:", "objectve:"), "slos[0].objectve", "did you mean 'objective'")

    def test_missing_objective(self):
        self.assertError(base().replace("    objective: 99.9\n", ""), "slos[0].objective", "required")

    def test_objective_out_of_range(self):
        self.assertError(base(objective="100"), "slos[0].objective", "between 0 and 100")
        self.assertError(base(objective="0.999"), "could never fire")

    def test_objective_not_a_number(self):
        self.assertError(base(objective="high"), "objective must be a number")

    def test_bad_window(self):
        self.assertError(base().replace("    objective: 99.9\n", "    objective: 99.9\n    window: 7d\n"), "slos[0].window", "28d, 30d")

    def test_bad_service_name(self):
        self.assertError(base().replace("service: checkout", "service: Checkout_API"), "service", "lowercase")

    def test_wrong_api_version(self):
        self.assertError(base().replace("ftw-slo/v1", "ftw-slo/v2"), "apiVersion")

    def test_duplicate_yaml_key(self):
        self.assertError(base().replace("service: checkout", "service: checkout\nservice: other"), "duplicate key 'service'")

    def test_invalid_yaml(self):
        self.assertError("apiVersion: [unclosed", "invalid YAML")

    def test_unknown_template_suggestion(self):
        self.assertError(base().replace("http-availability", "http-availabilty"), "unknown template", "did you mean 'http-availability'")

    def test_missing_required_param(self):
        self.assertError(base(params="metric: http_requests_total"), "sli.params.selector", "required by template")

    def test_unknown_param(self):
        self.assertError(base(params="selector: 'job=\"x\"'\n        selectr: 'a=\"b\"'"), "sli.params.selectr", "did you mean 'selector'")

    def test_promql_injection_in_matchers_rejected(self):
        self.assertError(base(params="selector: 'job=\"x\"}) or vector(1) #'"), "sli.params.selector", "label matchers")
        self.assertError(base(params="selector: 'job=\"x\", code=~5..'"), "label matchers")

    def test_bad_metric_name(self):
        self.assertError(base(params="selector: 'job=\"x\"'\n        metric: 'http requests'"), "metric name")

    def test_reserved_label(self):
        self.assertError(base(top="labels: {slo: x}"), "labels.slo", "reserved")

    def test_invalid_label_name(self):
        self.assertError(base(top="labels: {team-name: x}"), "invalid label name")

    def test_duplicate_slo_names(self):
        dup = """  - name: availability
    objective: 99
    sli:
      template: http-availability
      params: {selector: 'job="x"'}"""
        self.assertError(base(extra_slo=dup), "duplicate SLO name")

    def test_alert_name_invalid(self):
        text = base() + "    alerting:\n      name: 'bad-name'\n"
        self.assertError(text, "alerting.name")

    def test_summary_annotation_is_generated(self):
        text = base() + "    alerting:\n      annotations: {summary: custom}\n"
        self.assertError(text, "summary and description are generated")

    def test_custom_windows_checked(self):
        text = base() + "    alerting:\n      page:\n        windows:\n          - {long: 5m, short: 1h, burn_rate: 14.4}\n"
        self.assertError(text, "short window must be shorter")
        text = base() + "    alerting:\n      page:\n        windows:\n          - {long: 1h, short: 5m}\n"
        self.assertError(text, "burn_rate", "required")

    def test_unreachable_threshold(self):
        self.assertError(base(objective="90"), "could never fire", "burn rate 14.4")

    def test_low_objective_with_alerting_disabled_is_valid(self):
        self.assertEqual(errors_for(base(objective="90") + "    alerting:\n      enabled: false\n"), [])

    def test_all_errors_reported_at_once(self):
        text = base(objective="100", params="metric: 'bad metric'").replace("service: checkout", "service: BAD")
        self.assertGreaterEqual(len(errors_for(text)), 4)

    def test_duplicate_service_across_files(self):
        with helpers.TempDir() as d:
            helpers.write_spec(d, helpers.MINIMAL, "a.yaml")
            helpers.write_spec(d, helpers.MINIMAL, "b.yaml")
            with self.assertRaises(SpecErrors) as ctx:
                spec.load_paths([d])
        self.assertIn("also defined in", str(ctx.exception))

    def test_empty_file_and_missing_path(self):
        self.assertError("", "file is empty")
        with self.assertRaises(SpecErrors):
            spec.load_paths([os.path.join("does", "not", "exist.yaml")])

    @unittest.skipIf(edition.has("tenancy"), "tenancy is available in this edition")
    def test_tenancy_needs_studio(self):
        self.assertError(base(top="tenancy: {labels: [cluster]}"), "Studio edition")

    @unittest.skipIf(edition.has("importers"), "importers are available in this edition")
    def test_sloth_needs_pro(self):
        self.assertError('version: "prometheus/v1"\nservice: x\nslos: []\n', "Pro edition")

    def test_template_from_higher_edition_named(self):
        higher = [n for n, t in edition.ALL_TEMPLATES.items() if edition.RANK[t] > edition.RANK[edition.EDITION]]
        if not higher:
            self.skipTest("every template is included in this edition")
        self.assertError(base().replace("http-availability", higher[0]), "is included in the")


if __name__ == "__main__":
    unittest.main()
