"""Open motivation questions: Python picks the real background a posting is about; the agent writes examples."""

import unittest

from jobfill import relevance
from jobfill.resolver import Resolver

from .helpers import TODAY, fresh_store

POSTING = """Acme Robotics builds autonomy software that helps farmers harvest more with fewer resources.
Our mission is to make agriculture sustainable for millions of people.
Responsibilities:
- Build data pipelines in Python and SQL that feed our ML training platform.
- Scale distributed PyTorch training on Kubernetes clusters.
Requirements: experience with Airflow or similar orchestration. Go is a plus."""

QUESTIONS = {"Why do you want to work at our company?": "why_company",
             "Why are you interested in this role?": "why_role",
             "What do you know about our product, mission or customers?": "interest_product",
             "Why are you leaving (or why did you leave) your current job?": "leaving_reason"}


class TestRelevance(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store(with_profile=True, owner=self)   # 1 internship, 1 project, 1 story, 5 skills
        self.app = self.store.application(self.store.start_application("Acme Robotics", "ML Engineer Intern",
                                                                         posting=POSTING))

    def test_skills_the_posting_names(self):
        m = relevance.match(self.store, self.app, TODAY)
        self.assertEqual(m["matched_skills"], ["Python (5y)", "SQL (3y)", "PyTorch (2y)", "Kubernetes (1y)", "Airflow"])
        # Go is stored with level "none": a skill the candidate lacks is never offered as a match.
        self.assertFalse(any(s.startswith("Go") for s in m["matched_skills"]))

    def test_each_angle_pairs_a_posting_line_with_real_evidence(self):
        m = relevance.match(self.store, self.app, TODAY)
        self.assertEqual([(a["posting"][:28], a["evidence"][:30]) for a in m["angles"]], [
            ("Build data pipelines in Pyth", "Data Engineering Intern, Examp"),
            ("Scale distributed PyTorch tr", "Project: Distributed Training "),
            ("Requirements: experience wit", "Story: Learning Airflow in a w")])
        for a in m["angles"]:   # nothing invented: posting lines come from the posting, evidence from records
            self.assertIn(a["posting"], POSTING)
        # The evidence's own lines that carry the match come first: the Airflow line for an Airflow posting.
        self.assertEqual(m["evidence"][0]["lines"][0], "Wrote Airflow DAGs and data quality checks for 40+ tables")

    def test_company_lines_for_product_and_mission_questions(self):
        lines = relevance.match(self.store, self.app, TODAY)["company_lines"]
        self.assertIn("Our mission is to make agriculture sustainable for millions of people.", lines)

    def test_without_a_posting_it_says_so(self):
        app = self.store.application(self.store.start_application("Globex", "Data Engineer"))
        self.assertIn("No posting is saved", relevance.match(self.store, app, TODAY)["note"])

    def test_nothing_relevant_means_ask_not_generic(self):
        store = fresh_store(owner=self)
        app = store.application(store.start_application("Globex", "Chef", posting="Cook pasta for our guests."))
        m = relevance.match(store, app, TODAY)
        self.assertEqual((m["evidence"], m["angles"]), ([], []))
        self.assertIn("ask the candidate", m["note"])


class TestMotivationTasks(unittest.TestCase):
    def test_open_questions_ask_for_examples_with_the_posting_match(self):
        store = fresh_store(with_profile=True, owner=self)
        app = store.start_application("Acme Robotics", "ML Engineer Intern", posting=POSTING)
        out = Resolver(store, app, today=TODAY, log=False).resolve(
            [{"id": f"q{i}", "label": label, "type": "textarea"} for i, label in enumerate(QUESTIONS)])
        self.assertEqual({f["label"]: f.get("question_id") for f in out["fields"]}, QUESTIONS)
        for f in out["fields"]:
            self.assertEqual((f["status"], f["ai_task"]["examples"]), ("needs_ai", 2), f["label"])
            self.assertIn("angles", f["ai_task"]["examples_how"])
        self.assertEqual(len(out["ai_context"]["relevant"]["angles"]), 3)


if __name__ == "__main__":
    unittest.main()
