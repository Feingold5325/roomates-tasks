"""
בדיקות לבדיקת התקינות: תשובה תקינה עוברת, וכל סוג של תשובה פגומה נתפס.
כל מקרה כאן הוא דבר שמודל AI עלול להחזיר בפועל.
הרצה:  python -m unittest discover tests -v
"""

import json
import unittest

from src import validator

GOOD = {"domain": "plumbing", "responsibility": "landlord",
        "urgency": 2, "effort": 1, "draft": "שלום, הברז במטבח מטפטף."}


def raw(**changes):
    """בונה תשובת AI כטקסט JSON, עם שינויים לעומת התשובה התקינה."""
    data = {**GOOD, **changes}
    return json.dumps({k: v for k, v in data.items() if v is not ...}, ensure_ascii=False)


class TestAiOutput(unittest.TestCase):
    def test_valid_output_passes(self):
        result, problems = validator.check_ai_output(raw())
        self.assertEqual(problems, [])
        self.assertEqual(result["urgency"], 2)

    def test_markdown_fence_is_removed(self):
        _, problems = validator.check_ai_output("```json\n" + raw() + "\n```")
        self.assertEqual(problems, [])

    def test_not_json(self):
        _, problems = validator.check_ai_output("נראה לי שזו בעיית אינסטלציה")
        self.assertIn("אינה JSON", problems[0])

    def test_json_list_instead_of_object(self):
        _, problems = validator.check_ai_output("[1, 2, 3]")
        self.assertIn("אינה אובייקט", problems[0])

    def test_missing_field(self):
        _, problems = validator.check_ai_output(raw(draft=...))
        self.assertIn("draft", problems[0])

    def test_invalid_domain(self):
        _, problems = validator.check_ai_output(raw(domain="gardening"))
        self.assertTrue(any("תחום" in p for p in problems))

    def test_invalid_responsibility(self):
        _, problems = validator.check_ai_output(raw(responsibility="plumber"))
        self.assertTrue(any("אחריות" in p for p in problems))

    def test_unclear_responsibility_is_valid(self):
        _, problems = validator.check_ai_output(raw(responsibility="unclear", domain="other"))
        self.assertEqual(problems, [])

    def test_score_out_of_range(self):
        _, problems = validator.check_ai_output(raw(urgency=5))
        self.assertTrue(any("מחוץ לטווח" in p for p in problems))

    def test_score_not_integer(self):
        for bad in (2.5, "גבוה", True, None):
            _, problems = validator.check_ai_output(raw(effort=bad))
            self.assertTrue(problems, f"הערך {bad!r} היה אמור להיכשל")

    def test_score_as_digit_string_is_accepted(self):
        result, problems = validator.check_ai_output(raw(effort="3"))
        self.assertEqual(problems, [])
        self.assertEqual(result["effort"], 3)

    def test_empty_or_long_draft(self):
        self.assertTrue(validator.check_ai_output(raw(draft="  "))[1])
        self.assertTrue(validator.check_ai_output(raw(draft="א" * 1000))[1])


class TestRequestInput(unittest.TestCase):
    def test_empty_text(self):
        req = {"request_id": "Q9", "request_text": "  "}
        self.assertTrue(validator.check_request_input(req))

    def test_good_request(self):
        req = {"request_id": "Q9", "request_text": "הברז מטפטף"}
        self.assertEqual(validator.check_request_input(req), [])


if __name__ == "__main__":
    unittest.main()
