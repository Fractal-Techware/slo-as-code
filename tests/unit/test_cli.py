import os
import unittest

import helpers
from ftw_slo import VERSION, edition


class CliTests(unittest.TestCase):
    def test_version(self):
        code, out, _ = helpers.run_cli("version")
        self.assertEqual(code, 0)
        self.assertIn(VERSION, out)
        self.assertIn(edition.EDITION.title(), out)

    def test_validate_examples(self):
        code, out, err = helpers.run_cli("validate", helpers.EXAMPLES)
        self.assertEqual(code, 0, err)
        self.assertIn("SLO(s) valid", out)

    def test_validate_reports_errors_with_exit_1(self):
        with helpers.TempDir() as d:
            path = helpers.write_spec(d, helpers.MINIMAL.replace("99.9", "100"))
            code, out, err = helpers.run_cli("validate", path)
        self.assertEqual(code, 1)
        self.assertIn("slos[0].objective", err)
        self.assertIn("1 error(s)", err)

    def test_generate_writes_rules(self):
        with helpers.TempDir() as d:
            spec_path = helpers.write_spec(d, helpers.MINIMAL)
            out_dir = os.path.join(d, "out")
            code, out, err = helpers.run_cli("generate", spec_path, "--out", out_dir)
            self.assertEqual(code, 0, err)
            with open(os.path.join(out_dir, "rules", "checkout.rules.yml"), encoding="utf-8") as fh:
                text = fh.read()
        self.assertIn("alert: CheckoutAvailabilityFastBurn", text)
        self.assertIn("record: ftw_slo:error_budget_remaining:ratio", text)

    def test_generate_rejects_unknown_output(self):
        with helpers.TempDir() as d:
            code, _, err = helpers.run_cli("generate", helpers.write_spec(d, helpers.MINIMAL), "--out", d, "--only", "pdf")
        self.assertEqual(code, 2)
        self.assertIn("unknown output", err)

    @unittest.skipIf(edition.has("crd"), "CRDs are available in this edition")
    def test_edition_gated_outputs(self):
        with helpers.TempDir() as d:
            code, _, err = helpers.run_cli("generate", helpers.write_spec(d, helpers.MINIMAL), "--out", d, "--only", "crd")
        self.assertEqual(code, 2)
        self.assertIn("Pro edition", err)

    def test_templates_list_and_show(self):
        code, out, _ = helpers.run_cli("templates")
        self.assertEqual(code, 0)
        self.assertIn("http-availability", out)
        code, out, _ = helpers.run_cli("templates", "http-latency")
        self.assertEqual(code, 0)
        self.assertIn("threshold", out)
        self.assertIn("apiVersion: ftw-slo/v1", out)
        code, _, _ = helpers.run_cli("templates", "nope")
        self.assertEqual(code, 1)

    def test_template_markdown_matches_shipped_reference(self):
        code, out, _ = helpers.run_cli("templates", "--markdown")
        with open(os.path.join(helpers.KIT, "template-reference.md"), encoding="utf-8") as fh:
            self.assertEqual(out, fh.read())

    def test_no_command_prints_help(self):
        code, _, _ = helpers.run_cli()
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
