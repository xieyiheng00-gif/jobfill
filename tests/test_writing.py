"""Written (tier-3) answers: the writing playbooks the agent gets, and the plain-Python draft check."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from jobfill import cli, db
from jobfill.catalog import PLAYBOOKS, QUESTIONS, playbook_for
from jobfill.store import Store
from jobfill.writing import check_answer

from .helpers import EXAMPLES


def levels(result):
    return [(i["level"], i["message"].split(":")[0].split(";")[0]) for i in result["issues"]]


class TestPlaybooks(unittest.TestCase):
    def test_every_written_question_has_a_known_playbook(self):
        for q in QUESTIONS:
            if "ai" in q["answer"]:
                self.assertIn(q["answer"]["ai"].get("playbook"), PLAYBOOKS, q["id"])

    def test_learned_questions_get_one_from_their_category(self):
        self.assertEqual(playbook_for({"mode": "adapt"}, "behavioral"), "star")
        self.assertEqual(playbook_for({"mode": "unique"}, "motivation"), "why_role")
        self.assertEqual(playbook_for({"mode": "unique"}, "custom"), "direct")
        self.assertEqual(playbook_for({"deliverable": "file"}, "documents"), "cover_letter")
        self.assertEqual(playbook_for({"playbook": "explain"}, "custom"), "explain")

    def test_playbooks_are_compact(self):
        for name, pb in PLAYBOOKS.items():
            self.assertEqual(set(pb), {"structure", "length", "avoid"}, name)
            self.assertLess(sum(len(v) for v in pb.values()), 600, name)


class TestCheckAnswer(unittest.TestCase):
    GOOD = ("Acme's decision to open-source its robot simulator is why I am applying. I used it to cut my "
            "lab's grasping test time from 40 minutes to 6, and I would like to help make it faster for others.")

    def test_clean_answer(self):
        r = check_answer(self.GOOD, question_id="why_company", company="Acme Robotics, Inc.", max_chars=1000)
        self.assertEqual((r["ok"], r["issues"]), (True, []))
        self.assertEqual(r["words"], len(self.GOOD.split()))

    def test_limits(self):
        r = check_answer(self.GOOD, max_chars=50, max_words=10, min_words=100)
        self.assertFalse(r["ok"])
        self.assertEqual([lv for lv, _ in levels(r)], ["fix", "fix", "fix"])

    def test_placeholders(self):
        for text in ("I admire [Company] for its work.", "I admire {company}.", "I led <project name>.", "TODO: add"):
            self.assertFalse(check_answer(text)["ok"], text)
        self.assertTrue(check_answer("p95 latency fell below 50 ms and stayed > 99.9% available.")["ok"])

    def test_other_company_name_carried_over(self):
        r = check_answer("I have long admired Stripe's API design.", company="Acme", other_companies=["Stripe, Inc."])
        self.assertFalse(r["ok"])
        self.assertIn("Stripe", r["issues"][0]["message"])
        # The current company in another spelling is not "another company".
        self.assertTrue(check_answer("Acme's simulator", company="Acme, Inc.", other_companies=["Acme"])["ok"])

    def test_near_copy_of_another_companys_answer(self):
        earlier = [{"company": "Stripe", "value": self.GOOD.replace("Acme", "Stripe")}]
        self.assertFalse(check_answer(self.GOOD, company="Acme", earlier=earlier)["ok"])
        # The same company asking again may get the same answer (scope: company).
        self.assertTrue(check_answer(self.GOOD, company="Acme", earlier=[{"company": "Acme", "value": self.GOOD}])["ok"])

    def test_review_items_do_not_block(self):
        r = check_answer("I am passionate about robots and a team player.\n- I like teams", question_id="why_company",
                         company="Acme")
        self.assertTrue(r["ok"])
        self.assertEqual([lv for lv, _ in levels(r)], ["review", "review", "review"])
        self.assertIn("passionate about", r["issues"][1]["message"])


class TestAnswerCommands(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "jobfill.db")
        store = Store(db.connect(self.db))
        store.import_patch(json.loads((EXAMPLES / "sample_profile.json").read_text(encoding="utf-8")), dry_run=False)
        self.old = store.start_application("Stripe", "Engineer")
        store.record_answer(self.old, "why", "Why Stripe?", "I admire Stripe's API design.", question_id="why_company",
                            source="ai", tier=3)
        self.app = store.start_application("Acme Robotics, Inc.", "ML Infrastructure Engineer",
                                           posting="Acme builds robot arms.")
        store.conn.close()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--db", self.db, *argv])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_check_then_record(self):
        base = ["--app", str(self.app), "--question", "why_company"]
        bad = "I have long admired Stripe's API design and would love to join Acme."
        check = self.run_cli("answer", "check", *base, "--text", bad, "--max-chars", "40")
        self.assertFalse(check["ok"])
        self.assertEqual({i["message"].split(" ")[0] for i in check["issues"]}, {"68", "names"})
        refused = self.run_cli("answer", "record", *base, "--text", bad)
        self.assertFalse(refused["recorded"])
        good = "Acme's robot arms are what I want to work on: I built a grasp planner for one last year."
        recorded = self.run_cli("answer", "record", *base, "--text", good, "--label", "Why Acme?")
        self.assertEqual((recorded["recorded"], recorded["issues"]), (True, []))

    def test_own_employer_is_not_flagged(self):
        """A company the candidate worked at may be named, even when they also applied there."""
        store = Store(db.connect(self.db))
        employer = store.records("experience")[0]["company"]
        store.start_application(employer, "Engineer")
        store.conn.close()
        text = f"At {employer} I built the data pipeline Acme's robot arms would need."
        self.assertTrue(self.run_cli("answer", "check", "--app", str(self.app), "--question", "why_company",
                                     "--text", text)["ok"])


if __name__ == "__main__":
    unittest.main()
