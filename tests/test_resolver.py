import json
import unittest

from jobfill.resolver import Resolver, ai_task_for

from .helpers import EXAMPLES, TODAY, fresh_store


def by_id(result):
    return {f["id"]: f for f in result["fields"]}


class TestSampleForm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = fresh_store(with_profile=True, owner=cls)
        cls.app = cls.store.start_application("Acme Robotics, Inc.", "ML Infrastructure Engineer", country="US")
        form = json.loads((EXAMPLES / "sample_form.json").read_text(encoding="utf-8"))
        cls.result = Resolver(cls.store, cls.app, today=TODAY).resolve(form["fields"])
        cls.f = by_id(cls.result)

    def value(self, fid):
        self.assertEqual(self.f[fid]["status"], "filled", self.f[fid])
        return self.f[fid]["value"]

    def test_most_fields_need_no_ai(self):
        s = self.result["summary"]
        self.assertGreaterEqual(s["filled"], 38)
        self.assertLessEqual(s.get("needs_ai", 0), 5)

    def test_identity_and_contact(self):
        self.assertEqual(self.value("first_name"), "Jordan")
        self.assertEqual(self.value("preferred"), "Jo")
        self.assertEqual(self.value("location"), "Madison, WI")
        self.assertEqual(self.value("resume"), "documents/resume/jordan_rivera_resume.pdf")

    def test_work_authorization(self):
        self.assertEqual(self.value("auth"), "Yes")
        self.assertEqual(self.value("sponsor"), "Yes")
        self.assertEqual(self.value("auth_nosponsor"), "No")

    def test_eeo_options(self):
        self.assertEqual(self.value("gender"), "Non-binary")
        self.assertEqual(self.value("hispanic"), "Yes")
        self.assertEqual(self.value("race"), "Decline To Self Identify")
        self.assertEqual(self.value("veteran"), "I am not a protected veteran")
        self.assertEqual(self.value("disability"), "I do not want to answer")

    def test_derived_answers(self):
        self.assertEqual(self.value("py_years"), "5+ years")
        self.assertEqual(self.value("k8s"), "Yes")          # skill alias "k8s"
        self.assertEqual(self.value("go"), "No")            # recorded with level none
        self.assertEqual(self.value("worked_before"), "No")
        self.assertEqual(self.value("office"), "Yes")
        self.assertEqual(self.value("office_loc"), "Seattle, WA")
        self.assertEqual(self.value("heard"), "LinkedIn")
        self.assertEqual(self.value("degree"), "Master's Degree")
        self.assertEqual(self.value("highest"), "Master's")
        self.assertEqual(self.value("spanish"), "Yes")
        self.assertEqual(self.value("french"), "No")
        self.assertIs(self.value("certify"), True)

    def test_dates_are_formatted(self):
        self.assertEqual(self.value("start"), "06/01/2027")
        self.assertEqual(self.value("grad"), "05/2027")
        self.assertEqual(self.value("exp0_from"), "06/2026")

    def test_repeating_sections_use_index(self):
        self.assertEqual(self.value("exp0_company"), "Example Analytics")
        self.assertEqual(self.value("edu1_school"), "Universidad Nacional Autonoma de Mexico")
        self.assertIn("feature store", self.value("exp0_desc"))

    def test_unknown_skill_asks_user(self):
        self.assertEqual(self.f["rust_years"]["status"], "needs_user")
        self.assertIn("Rust", self.f["rust_years"]["ask"])
        self.assertEqual(self.f["rust_years"]["store"]["record"], "skill")

    def test_tier3_goes_to_ai_with_small_context(self):
        self.assertEqual(self.f["why"]["status"], "needs_ai")
        self.assertEqual(self.f["why"]["ai_task"]["question_id"], "why_company")
        self.assertEqual(self.f["why"]["ai_task"]["limits"], {"max_chars": 1000})
        # Unknown open question on an optional field: skipped, not sent to the AI.
        self.assertEqual((self.f["oss"]["status"], self.f["oss"]["question_id"]), ("skipped", "open_ended_custom"))
        required = Resolver(self.store, self.app, today=TODAY).resolve(
            [{"id": "q", "label": "What would you build in your first month?", "type": "textarea", "required": True}])
        self.assertEqual(required["fields"][0]["ai_task"]["question_id"], "open_ended_custom")
        self.assertIn("learning", self.f["learn"]["ai_task"]["themes"])
        ctx = json.dumps(self.result["ai_context"])
        # Sensitive and irrelevant data never reaches the model.
        for secret in ("non_binary", "veteran", "disability", "608-555", "123 Example St", "f1_opt"):
            self.assertNotIn(secret, ctx)
        self.assertLess(len(ctx), 6000)

    def test_optional_ai_fields_are_skipped(self):
        self.assertEqual(self.f["anything"]["status"], "skipped")
        self.assertEqual(self.f["cover"]["status"], "skipped")

    def test_unknown_short_question_is_queued(self):
        self.assertEqual(self.f["tshirt"]["status"], "unmatched")
        self.assertIn("t shirt size", [p["normalized"] for p in self.store.pending()])


class TestLearningLoop(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store(with_profile=True, owner=self)
        self.app = self.store.start_application("Globex", "Data Engineer")

    def resolve(self, fields, app=None):
        return Resolver(self.store, app or self.app, today=TODAY).resolve(fields)["fields"]

    def test_missing_fact_asked_once_then_answered_by_python(self):
        field = {"id": "dl", "label": "Do you have a valid driver's license?", "type": "radio",
                 "options": ["Yes", "No"], "required": True}
        first = self.resolve([field])[0]
        self.assertEqual((first["status"], first["fact"]), ("needs_user", "legal.drivers_license"))
        self.store.set_fact("legal.drivers_license", "yes")
        self.assertEqual(self.resolve([field])[0]["value"], "Yes")

    def test_new_rephrasing_learned_as_alias(self):
        field = {"id": "x", "label": "Mention the city where you currently reside", "type": "text", "required": True}
        self.assertIn(self.resolve([field])[0]["status"], ("unmatched", "uncertain"))
        pending = next(p for p in self.store.pending() if "reside" in p["normalized"])
        self.store.add_alias("current_location", pending["label"])
        self.store.close_pending(pending["id"], "learned", "alias_of:current_location")
        again = self.resolve([field])[0]
        self.assertEqual((again["status"], again["match"]["how"], again["value"]), ("filled", "exact", "Madison, WI"))

    def test_new_question_with_new_fact(self):
        field = {"id": "t", "label": "T-shirt size", "type": "select", "options": ["S", "M", "L"], "required": True}
        self.assertEqual(self.resolve([field])[0]["status"], "unmatched")
        self.store.define_fact("prefs.tshirt_size", 2, "string", "T-shirt size", "Your T-shirt size (S/M/L/XL)")
        self.store.add_question("tshirt_size", 2, "custom", "T-shirt size", {"fact": "prefs.tshirt_size"})
        self.store.set_fact("prefs.tshirt_size", "M")
        self.assertEqual(self.resolve([field])[0]["value"], "M")

    def test_tier3_answers_are_unique_per_company(self):
        why_co = {"id": "w", "label": "Why do you want to work at Globex?", "type": "textarea", "required": True}
        why_role = {"id": "r", "label": "Why are you interested in this role?", "type": "textarea", "required": True}
        self.assertEqual(self.resolve([why_co])[0]["status"], "needs_ai")
        self.store.record_answer(self.app, "w", why_co["label"], "Globex answer", question_id="why_company", source="ai")
        self.store.record_answer(self.app, "r", why_role["label"], "Role answer", question_id="why_role", source="ai")
        # Same application: reused (e.g. the form is re-opened).
        self.assertEqual(self.resolve([why_co])[0]["value"], "Globex answer")
        # Same company, another role: "why us" is reusable, "why this role" is not.
        second = self.store.start_application("Globex Corporation", "ML Engineer")
        out = self.resolve([why_co, why_role], app=second)
        self.assertEqual(out[0]["value"], "Globex answer")
        self.assertEqual(out[1]["status"], "needs_ai")
        # Different company: always written fresh.
        other = self.store.start_application("Initech", "Data Engineer")
        out = self.resolve([{**why_co, "label": "Why do you want to work at Initech?"}], app=other)
        self.assertEqual(out[0]["status"], "needs_ai")

    def test_previous_application_detected(self):
        second = self.store.start_application("Globex", "Analytics Engineer")
        field = {"id": "p", "label": "Have you previously applied to Globex?", "type": "radio", "options": ["Yes", "No"]}
        self.assertEqual(self.resolve([field], app=second)[0]["value"], "Yes")

    def test_skill_record_without_years_or_level_means_yes(self):
        # Resume imports store skills by name only; that must not read as "No".
        self.store.add_record("skill", {"name": "Docker"})
        self.store.add_record("skill", {"name": "Scala", "years": 0, "level": "beginner"})
        self.store.add_record("skill", {"name": "Rust", "years": 0})
        self.store.add_record("skill", {"name": "Haskell", "level": "none"})
        answers = {}
        for name in ("Docker", "Scala", "Rust", "Haskell"):
            field = {"id": name, "label": f"Do you have experience with {name}?", "type": "radio",
                     "options": ["Yes", "No"]}
            answers[name] = self.resolve([field])[0]["value"]
        self.assertEqual(answers, {"Docker": "Yes", "Scala": "Yes", "Rust": "No", "Haskell": "No"})
        listed = self.resolve([{"id": "s", "label": "Skills", "type": "text"}])[0]["value"]
        self.assertIn("Docker", listed)
        self.assertNotIn("Rust", listed)
        self.assertNotIn("Haskell", listed)
        years = self.resolve([{"id": "y", "label": "How many years of experience do you have with Haskell?",
                               "type": "number"}])[0]
        self.assertEqual(years["value"], "0")
        unknown = self.resolve([{"id": "d", "label": "How many years of experience do you have with Docker?",
                                 "type": "number", "required": True}])[0]
        self.assertEqual(unknown["status"], "needs_user")

    def test_years_of_experience_never_guessed_from_internships(self):
        field = {"id": "y", "label": "Years of professional experience", "type": "number", "required": True}
        first = self.resolve([field])[0]
        self.assertEqual((first["status"], first["fact"]), ("needs_user", "profile.years_experience_override"))
        self.store.set_fact("profile.years_experience_override", 0.5)
        self.assertEqual(self.resolve([field])[0]["value"], "0.5")

    def test_country_and_state_options(self):
        fields = [{"id": "c", "label": "Country", "type": "select", "options": ["Canada", "USA", "Mexico"]},
                  {"id": "s", "label": "State", "type": "select", "options": ["Washington", "Wisconsin", "Wyoming"]}]
        out = self.resolve(fields)
        self.assertEqual([o["value"] for o in out], ["USA", "Wisconsin"])

    def test_context_command_for_single_question(self):
        task = ai_task_for(self.store, "bh_conflict", self.app)
        self.assertEqual(task["status"], "needs_ai")
        self.assertIn("stories", task["ai_context"]["candidate"])
        self.assertNotIn("projects", task["ai_context"]["candidate"])


if __name__ == "__main__":
    unittest.main()
