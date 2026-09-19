import unittest
from decimal import Decimal

import helpers  # noqa: F401  (sets sys.path)
from ftw_slo import mathx


class DurationTests(unittest.TestCase):
    def test_parse_and_format_roundtrip(self):
        for text, seconds in (("5m", 300), ("30m", 1800), ("1h", 3600), ("6h", 21600), ("1d", 86400), ("3d", 259200),
                              ("30d", 2592000), ("4w", 2419200)):
            self.assertEqual(mathx.parse_duration(text), seconds)
        self.assertEqual(mathx.format_duration(86400 * 28), "28d")
        self.assertEqual(mathx.format_duration(5400), "90m")

    def test_invalid_durations_rejected(self):
        for bad in ("5", "1h30m", "0m", "-5m", "5M", "", "1.5h"):
            with self.assertRaises(ValueError, msg=bad):
                mathx.parse_duration(bad)


class ObjectiveTests(unittest.TestCase):
    def test_error_budget_is_exact(self):
        cases = {"99.9": "0.001", "99.95": "0.0005", "99.5": "0.005", "99": "0.01", "99.999": "0.00001", "95": "0.05"}
        for obj, budget in cases.items():
            self.assertEqual(mathx.num(mathx.error_budget(mathx.parse_objective(obj))), budget)
        # YAML floats arrive as Python floats
        self.assertEqual(mathx.num(mathx.error_budget(mathx.parse_objective(99.9))), "0.001")
        self.assertEqual(mathx.num(mathx.error_budget(mathx.parse_objective(99.95))), "0.0005")

    def test_objective_bounds(self):
        for bad in (100, 0, -1, 101, "abc", True, "nan", "99.123456"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                mathx.parse_objective(bad)
        self.assertEqual(mathx.parse_objective("99.12345"), Decimal("99.12345"))

    def test_num_formatting(self):
        self.assertEqual(mathx.num(Decimal("6.0")), "6")
        self.assertEqual(mathx.num(Decimal("0.00100")), "0.001")
        self.assertEqual(mathx.num(Decimal("14.4") * Decimal("0.001")), "0.0144")


class BurnRateTests(unittest.TestCase):
    def test_workbook_factors_for_30d(self):
        w = mathx.resolve_windows("30d", "default")
        self.assertEqual([(x["long"], x["short"], mathx.num(x["burn_rate"])) for x in w["page"]], [("1h", "5m", "14.4")])
        self.assertEqual([(x["long"], x["short"], mathx.num(x["burn_rate"])) for x in w["ticket"]],
                         [("6h", "30m", "6"), ("1d", "2h", "3"), ("3d", "6h", "1")])

    def test_factors_scale_with_28d_window(self):
        w = mathx.resolve_windows("28d", "default")
        self.assertEqual(mathx.num(w["page"][0]["burn_rate"]), "13.44")
        self.assertEqual([mathx.num(x["burn_rate"]) for x in w["ticket"]], ["5.6", "2.8", "0.933333"])

    def test_workbook_profile(self):
        w = mathx.resolve_windows("30d", "workbook")
        self.assertEqual([(x["long"], mathx.num(x["burn_rate"])) for x in w["page"]], [("1h", "14.4"), ("6h", "6")])
        self.assertEqual([(x["long"], mathx.num(x["burn_rate"])) for x in w["ticket"]], [("3d", "1")])

    def test_budget_consumption_matches_definition(self):
        # burn rate x long window / period = share of budget consumed when the alert fires
        for period in ("28d", "30d"):
            for cls in mathx.resolve_windows(period).values():
                for x in cls:
                    consumed = x["burn_rate"] * mathx.parse_duration(x["long"]) / mathx.parse_duration(period)
                    self.assertIn(round(consumed, 4), (Decimal("0.02"), Decimal("0.05"), Decimal("0.1")))

    def test_thresholds(self):
        budget = mathx.error_budget(mathx.parse_objective("99.9"))
        self.assertEqual(mathx.num(Decimal("14.4") * budget), "0.0144")
        budget = mathx.error_budget(mathx.parse_objective("99.5"))
        self.assertEqual(mathx.num(Decimal("14.4") * budget), "0.072")

    def test_exhaustion_time(self):
        self.assertEqual(mathx.hours_to_exhaustion("30d", Decimal("14.4")), Decimal(50))
        self.assertEqual(mathx.hours_to_exhaustion("30d", Decimal(1)), Decimal(720))

    def test_all_windows_sorted(self):
        self.assertEqual(mathx.all_windows(mathx.resolve_windows("30d")), ["5m", "30m", "1h", "2h", "6h", "1d", "3d"])

    def test_unknown_profile(self):
        with self.assertRaises(ValueError):
            mathx.resolve_windows("30d", "aggressive")


if __name__ == "__main__":
    unittest.main()
