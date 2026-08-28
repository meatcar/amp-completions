import unittest

from amp_completions import failure_escalation


class FailureEscalationTest(unittest.TestCase):
    def test_first_failure_is_quiet(self) -> None:
        result = failure_escalation.transition(
            {}, "failure", "1.2.3", "generate", "https://example.test/run/1"
        )

        self.assertEqual(result["state"]["count"], 1)
        self.assertFalse(result["escalate"])
        self.assertEqual(result["close_key"], "")

    def test_repeated_failure_escalates_same_key(self) -> None:
        first = failure_escalation.transition(
            {}, "failure", "1.2.3", "generate", "https://example.test/run/1"
        )
        second = failure_escalation.transition(
            first["state"],
            "failure",
            "1.2.3",
            "generate",
            "https://example.test/run/2",
        )
        third = failure_escalation.transition(
            second["state"],
            "failure",
            "1.2.3",
            "generate",
            "https://example.test/run/3",
        )

        self.assertTrue(second["escalate"])
        self.assertEqual(second["key"], third["key"])
        self.assertEqual(third["state"]["count"], 3)
        self.assertIn("Amp version: 1.2.3", second["body"])
        self.assertIn("Failing step: generate", second["body"])
        self.assertIn("https://example.test/run/2", second["body"])
        self.assertIn("Recommended next action:", second["body"])

    def test_success_closes_matching_issue(self) -> None:
        failed = failure_escalation.transition(
            {}, "failure", "1.2.3", "generate", "https://example.test/run/1"
        )

        recovered = failure_escalation.transition(
            failed["state"], "success", "1.2.3", "", "https://example.test/run/2"
        )

        self.assertEqual(recovered["close_key"], failed["key"])
        self.assertEqual(recovered["state"], {})
        self.assertFalse(recovered["escalate"])

    def test_new_version_closes_old_issue_and_starts_at_one(self) -> None:
        failed = failure_escalation.transition(
            {}, "failure", "1.2.3", "generate", "https://example.test/run/1"
        )

        changed = failure_escalation.transition(
            failed["state"],
            "failure",
            "1.2.4",
            "generate",
            "https://example.test/run/2",
        )

        self.assertEqual(changed["close_key"], failed["key"])
        self.assertEqual(changed["state"]["count"], 1)
        self.assertFalse(changed["escalate"])


if __name__ == "__main__":
    unittest.main()
