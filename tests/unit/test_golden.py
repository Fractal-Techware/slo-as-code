"""Golden-file tests: the shipped generator reproduces generated/ and tests/promtool/rules/ byte for byte."""
import os
import unittest

import helpers


class GoldenTests(unittest.TestCase):
    def test_examples_match_generated(self):
        with helpers.TempDir() as d:
            code, out, err = helpers.run_cli("generate", helpers.EXAMPLES, "--out", d, "--only", helpers.default_only())
            self.assertEqual(code, 0, err)
            actual = helpers.tree(d)
        expected = helpers.tree(helpers.GENERATED)
        self.assertEqual(sorted(actual), sorted(expected))
        for name in expected:
            self.assertEqual(actual[name].decode(), expected[name].decode(), f"generated/{name} differs")

    def test_promtool_fixture_rules_match(self):
        # one spec per template; they reuse alert names on purpose, so generate them one by one
        specs = os.path.join(helpers.PROMTOOL, "specs")
        with helpers.TempDir() as d:
            for f in sorted(os.listdir(specs)):
                code, out, err = helpers.run_cli("generate", os.path.join(specs, f), "--out", d, "--only", "rules")
                self.assertEqual(code, 0, err)
            actual = helpers.tree(os.path.join(d, "rules"))
        expected = helpers.tree(os.path.join(helpers.PROMTOOL, "rules"))
        self.assertEqual(sorted(actual), sorted(expected))
        for name in expected:
            self.assertEqual(actual[name], expected[name], f"tests/promtool/rules/{name} differs")

    def test_generation_is_deterministic(self):
        with helpers.TempDir() as a, helpers.TempDir() as b:
            helpers.run_cli("generate", helpers.EXAMPLES, "--out", a, "--only", helpers.default_only())
            helpers.run_cli("generate", helpers.EXAMPLES, "--out", b, "--only", helpers.default_only())
            self.assertEqual(helpers.tree(a), helpers.tree(b))


if __name__ == "__main__":
    unittest.main()
