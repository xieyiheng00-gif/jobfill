"""The candidate shares the window: jobfill follows them forward, keeps their answers, and waits when they go back."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from jobfill.apply import adapters, pages

from .helpers import fresh_store

PAGE = (Path(__file__).resolve().parent / "fixtures" / "wizard_like.html").as_uri()


def info(title="", labels=(), url="https://acme.wd5.myworkdayjobs.com/apply"):
    return {"title": title, "labels": sorted(labels), "url": url}


class TestPlacing(unittest.TestCase):
    def test_title_decides_when_both_pages_have_one(self):
        self.assertTrue(pages.same(info("My Information", ["a"]), info("My Information", ["b"])))
        self.assertFalse(pages.same(info("My Information", ["a"]), info("Review", ["a"])))

    def test_follow_up_questions_keep_the_page(self):
        first = info(labels=["first name", "last name", "email", "phone"])
        grown = info(labels=["first name", "last name", "email", "phone", "phone type", "extension"])
        self.assertTrue(pages.same(first, grown))
        self.assertFalse(pages.same(first, info(labels=["why us", "sponsorship"])))

    def test_locate(self):
        steps = [info("A", ["x"]), info("B", ["y"]), info("C", ["z"])]
        self.assertEqual(pages.locate([], info("A")), ("new", 0))
        self.assertEqual(pages.locate(steps, info("C")), ("current", 2))
        self.assertEqual(pages.locate(steps, info("A")), ("earlier", 0))
        self.assertEqual(pages.locate(steps, info("D")), ("new", 3))

    def test_remember_merges_labels_of_the_same_page(self):
        steps = [info(labels=["a", "b"])]
        pages.remember(steps, "current", 0, info(labels=["b", "c"]))
        self.assertEqual(steps[0]["labels"], ["a", "b", "c"])
        pages.remember(steps, "new", 1, info("Next"))
        self.assertEqual(len(steps), 2)


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright not installed")
class TestSharedWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        from jobfill.apply import runner
        self.runner = runner
        self.store = fresh_store(with_profile=True, owner=self)   # sponsorship: Yes, authorized: Yes
        self.app = self.store.start_application("Acme Robotics", "ML Engineer", ats="workday")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        self.state = {"pages": [], "typed": {}}
        self.workday = adapters.get("workday")
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.goto(PAGE)

    # The agent's commands, run on the open page.
    def fill(self, **kw):
        return self.runner.fill_page(self.store, self.data, self.app, self.state, self.page, self.workday, **kw)

    def next(self):
        return self.runner.next_page(self.state, self.page, self.workday, self.app)

    def watch(self, timeout=10):
        return self.runner.watch_page(self.store, self.data, self.app, self.state, self.page, self.workday,
                                      timeout=timeout, interval=0.3)

    # What the candidate does in the window.
    def click(self, which):
        sel = "previous" if which == "back" else "next"
        self.page.click(f"[data-automation-id=bottom-navigation-{sel}-button]")

    def value(self, sel):
        return self.page.input_value(sel)

    def step(self):
        return self.page.inner_text("[data-automation-id=progressBarActiveStep]")

    def test_candidate_moves_on_and_answers_some_questions(self):
        first = self.fill(fresh=True)
        self.assertEqual(first["page"], {"n": 1, "of": 1, "title": "My Information"})
        self.assertEqual(self.value("#first"), "Jordan")
        # The candidate clicks Save and Continue and picks sponsorship themselves.
        self.click("next")
        self.page.select_option("#sponsor", "No")
        # The agent meant to click Next: jobfill sees the candidate already did, and does not skip a page.
        out = self.next()
        self.assertEqual((out["clicked"], out["moved_by_candidate"], out["page"]["n"]), (None, True, 2))
        self.assertEqual(self.step(), "Application Questions")
        out = self.fill()
        self.assertTrue(out["moved_by_candidate"])
        self.assertEqual(out["page"], {"n": 2, "of": 2, "title": "Application Questions"})
        self.assertEqual(self.page.input_value("#auth"), "Yes")      # jobfill answered the rest
        self.assertEqual(self.page.input_value("#sponsor"), "No")    # and kept the candidate's choice
        self.assertEqual([c["label"] for c in out["by_candidate"]],
                         ["Will you now or in the future require sponsorship for employment visa status?"])
        rows = {r["label"]: r for r in self.store.answers(self.app)}
        self.assertEqual(rows["Will you now or in the future require sponsorship for employment visa status?"]
                         ["source"], "user")

    def test_candidate_edit_is_never_reverted(self):
        self.fill(fresh=True)
        self.page.fill("#phone", "608-555-9999")
        out = self.fill(overwrite=True)    # even --overwrite re-types only jobfill's own values
        self.assertEqual(self.value("#phone"), "608-555-9999")
        self.assertEqual([(c["label"], c["value"]) for c in out["by_candidate"]], [("Phone Number", "608-555-9999")])

    def test_candidate_answer_to_an_open_question_is_not_written_again(self):
        self.fill(fresh=True)
        self.next()
        self.page.fill("#why", "I wrote this myself.")
        out = self.fill()
        self.assertNotIn("needs_ai", out)
        self.assertEqual(self.page.input_value("#why"), "I wrote this myself.")

    def test_going_back_pauses_everything_until_the_candidate_returns(self):
        self.fill(fresh=True)
        self.next()
        self.fill()
        self.click("back")                      # the candidate checks page 1
        self.page.fill("#email", "")            # ...and clears a field while there
        out = self.fill()
        self.assertEqual((out["paused"], out["page"]["n"], out["furthest_page"]), ("candidate_went_back", 1, 2))
        self.assertEqual(self.value("#email"), "")                  # nothing typed
        self.assertEqual(self.next()["paused"], "candidate_went_back")
        self.assertEqual(self.step(), "My Information")             # nothing clicked
        set_out = self.runner.set_field(self.store, self.app, self.state, self.page, self.workday, "x", "y")
        self.assertEqual(set_out["paused"], "candidate_went_back")
        # Asked to, jobfill fills the page they are on, still keeping their answers.
        out = self.fill(here=True)
        self.assertNotIn("paused", out)
        self.assertTrue(self.value("#email"))
        # Back on the furthest page: work goes on as normal.
        self.click("next")
        out = self.fill()
        self.assertNotIn("paused", out)
        self.assertEqual(out["page"]["n"], 2)
        nxt = self.next()
        self.assertEqual((nxt["moved"], nxt["page"]["n"], self.step()), (True, 3, "Review"))

    def test_watch_reports_each_move(self):
        self.fill(fresh=True)
        self.next()
        self.fill()
        self.assertEqual(self.watch(timeout=1)["event"], "timeout")
        self.page.evaluate("go('back')")
        out = self.watch()
        self.assertEqual((out["event"], out["page"]["n"], out["paused"]), ("went_back", 1, "candidate_went_back"))
        self.page.evaluate("go('next')")
        self.assertEqual(self.watch()["event"], "returned")
        self.page.evaluate("go('next')")
        out = self.watch()
        self.assertEqual((out["event"], out["page"]["n"]), ("moved_on", 3))
        self.fill()
        self.page.evaluate("go('next')")        # the candidate clicks Submit themselves
        self.assertEqual(self.watch()["event"], "submitted")
        self.assertEqual(self.store.application(self.app)["status"], "submitted")


if __name__ == "__main__":
    unittest.main()
