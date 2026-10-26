"""Approval identity never grants availability to a historical capability."""
import unittest

from verif_harness.approval_policy import assessment, dependency_subject, retain_head


class ApprovalPolicyTest(unittest.TestCase):
    def test_temporarily_withdrawn_head_retains_only_identity(self):
        version = {"version": 2, "signature": "accepted"}
        withdrawn = retain_head({"derived": True, "current": None}, {"current": version})
        self.assertIsNone(withdrawn["current"])
        self.assertEqual(withdrawn["last_current"], version)
        again = retain_head({"current": None}, withdrawn)
        self.assertEqual(again["last_current"], version)
        self.assertNotIn("last_current", retain_head({"current": version}, again))
        self.assertNotIn("last_current", retain_head({"current": None}, {}))

    def test_version_fallback_does_not_turn_available_missing_head_into_valid_input(self):
        base = {"id": "cap.fixture:ready", "title": "验证能力", "status": "VALID",
                "current": {"version": 1, "signature": "one"}}
        withdrawn = {**base, "status": "REVALIDATION_REQUIRED", "current": None,
                     "last_current": base["current"]}
        self.assertEqual(dependency_subject([base]), dependency_subject([withdrawn]))
        malformed = {**withdrawn, "status": "VALID"}
        self.assertIsNone(dependency_subject([malformed])[0]["current"])
        changed = {**base, "current": {"version": 2, "signature": "two"}}
        self.assertNotEqual(dependency_subject([base]), dependency_subject([changed]))

    def test_approval_is_not_permission_to_use_stale_evidence(self):
        blocked = assessment(True, blockers=["依赖暂时不可用"], has_history=True)
        self.assertTrue(blocked["approval_valid"])
        self.assertFalse(blocked["available"])
        self.assertFalse(blocked["reapproval_required"])
        self.assertTrue(assessment(True, has_history=True)["available"])
        self.assertFalse(assessment(True, evidence_current=False)["available"])
        stale = assessment(False, evidence_current=False, has_history=True)
        self.assertFalse(stale["available"])
        self.assertTrue(stale["reapproval_required"])
        self.assertFalse(assessment(False)["reapproval_required"])
