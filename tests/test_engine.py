"""Unit tests for the MathLens engine. Run: python -m unittest discover -s tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import parser, step_checker  # noqa: E402
from engine.feedback_engine import build_feedback, check_diagnostic, load_taxonomy  # noqa: E402


def first_error_and_label(text):
    r = step_checker.analyze(text)
    idx = None if r.first_error_index is None else r.first_error_index + 1
    return idx, r.misconception_id


class TestParser(unittest.TestCase):
    def test_implicit_multiplication(self):
        st = parser.parse_step("3(x+2)")
        self.assertTrue(st.ok)
        self.assertEqual(str(st.obj.expand()), "3*x + 6")

    def test_caret_power(self):
        st = parser.parse_step("x^2 + 1")
        self.assertTrue(st.ok)
        self.assertIn("x**2", str(st.obj))

    def test_equation(self):
        st = parser.parse_step("2x + 4 = 10")
        self.assertTrue(st.is_equation)

    def test_unicode_and_comma(self):
        st = parser.parse_step("2,5 \u00d7 x")
        self.assertTrue(st.ok)

    def test_bad_input(self):
        self.assertFalse(parser.parse_step("3x +* ").ok)


class TestCorrectSolutions(unittest.TestCase):
    def test_linear_correct(self):
        idx, _ = first_error_and_label("2x + 4 = 10\n2x = 6\nx = 3")
        self.assertIsNone(idx)

    def test_expand_correct(self):
        idx, _ = first_error_and_label("(x+2)^2\nx^2 + 4x + 4")
        self.assertIsNone(idx)

    def test_quadratic_correct(self):
        idx, _ = first_error_and_label("x^2 - 9 = 0\n(x-3)(x+3) = 0\nx = 3")
        # x = 3 loses the root x = -3
        self.assertEqual(idx, 3)


class TestMisconceptions(unittest.TestCase):
    cases = [
        ("3(x+2)\n3x+2", 2, "ALG-DIST-01"),
        ("10-(x+4)\n10-x+4", 2, "ALG-DIST-02"),
        ("(x+2)^2\nx^2+4", 2, "ALG-EXP-01"),
        ("(x-2)^2\nx^2-4", 2, "ALG-EXP-02"),
        ("x+3 = 5\nx = 5+3", 2, "ALG-SIGN-01"),
        ("-x+2 = 5\nx+2 = -5", 2, "ALG-SIGN-02"),
        ("(x+2)/x\n2", 2, "ALG-FRAC-01"),
        ("1/x + 1/y\n1/(x+y)", 2, "ALG-FRAC-03"),
        ("x^2 + x^3\nx^5", 2, "ALG-POW-01"),
        ("x^2 * x^3\nx^6", 2, "ALG-POW-02"),
        ("(x+y)^3\nx^3+y^3", 2, "ALG-POW-04"),
        ("sqrt(x+y)\nsqrt(x)+sqrt(y)", 2, "ALG-RAD-01"),
        ("2x+4 = 10\nx+4 = 5", 2, "ALG-EQ-03"),
        ("(x-1)(x-2) = 6\nx-1 = 6", 2, "ALG-EQ-04"),
        ("x^2 = 9\nx = 3", 2, "ALG-QUAD-01"),
        ("x^2 - 9\n(x-3)^2", 2, "ALG-FACT-01"),
        ("x^2 = 3x\nx = 3", 2, "ALG-EQ-01"),
    ]

    def test_all(self):
        for text, want_step, want_id in self.cases:
            with self.subTest(text=text):
                idx, mid = first_error_and_label(text)
                self.assertEqual(idx, want_step, f"first invalid step for: {text!r}")
                self.assertEqual(mid, want_id, f"label for: {text!r}")


class TestFirstErrorOnly(unittest.TestCase):
    def test_reports_first_not_last(self):
        text = "3(x+2) = 12\n3x+2 = 12\n3x = 10\nx = 10/3"
        r = step_checker.analyze(text)
        self.assertEqual(r.first_error_index, 1)
        self.assertEqual(r.misconception_id, "ALG-DIST-01")


class TestFeedback(unittest.TestCase):
    def test_taxonomy_complete(self):
        tax = load_taxonomy()
        self.assertGreaterEqual(len(tax), 20)
        for mid, m in tax.items():
            if mid == "ALG-UNK-00":
                continue
            for field in (m.name_vi, m.name_en, m.feedback_vi, m.feedback_en,
                          m.diagnostic_question, m.diagnostic_question_en,
                          m.diagnostic_answer, m.group, m.group_en):
                self.assertTrue(field.strip(), mid)

    def test_feedback_has_diagnostic(self):
        r = step_checker.analyze("3(x+2)\n3x+2")
        fb = build_feedback(r)
        self.assertEqual(fb["status"], "error")
        for key in ("headline", "detail", "diagnostic_question"):
            self.assertTrue(fb[key]["vi"].strip(), key)
            self.assertTrue(fb[key]["en"].strip(), key)
            self.assertNotEqual(fb[key]["vi"], fb[key]["en"], key)

    def test_diagnostic_grading(self):
        self.assertTrue(check_diagnostic("5x + 15", "5x+15"))
        self.assertTrue(check_diagnostic("15 + 5x", "5x+15"))
        self.assertFalse(check_diagnostic("5x + 3", "5x+15"))
        self.assertTrue(check_diagnostic("x=4 hoặc x=-4", "x=4 hoặc x=-4"))
        self.assertFalse(check_diagnostic("x=4", "x=4 hoặc x=-4"))


class TestDiagnosticAnswersAreCorrect(unittest.TestCase):
    """Every diagnostic question must grade its own answer key as correct."""

    def test_self_consistent(self):
        for mid, m in load_taxonomy().items():
            if not m.diagnostic_answer.strip():
                continue
            with self.subTest(mid=mid):
                self.assertTrue(check_diagnostic(m.diagnostic_answer, m.diagnostic_answer))


if __name__ == "__main__":
    unittest.main(verbosity=2)
