"""Workday's prompt widget ("How Did You Hear About Us?"): pick a menu choice, read the pill."""

import importlib.util
import unittest
from pathlib import Path

from jobfill.apply import adapters
from jobfill.apply.runner import fill_frame, summarize

from .helpers import fresh_store

PAGE = (Path(__file__).resolve().parent / "fixtures" / "workday_like.html").as_uri()


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright not installed")
class TestWorkdayPrompt(unittest.TestCase):
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
        self.store = fresh_store(with_profile=True, owner=self)   # how-heard default: LinkedIn
        self.app = self.store.start_application("Visa", "Engineer", ats="workday")
        self.workday = adapters.get("workday")

    def open(self, flags=""):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.goto(PAGE + flags)
        return page

    def fill(self, page, overwrite=False):
        report = fill_frame(self.workday.frame(page), self.store, self.app, self.workday, overwrite=overwrite)
        return report, summarize(report, self.app)

    def pills(self, page):
        return page.evaluate("() => Array.from(document.querySelectorAll('[data-automation-id=selectedItem]')).map(p => p.title)")

    def source_entry(self, report):
        return next(v for v in report["fields"].values() if v["label"].startswith("How Did You Hear"))

    def test_read_as_a_menu_not_a_text_box(self):
        page = self.open()
        report, _ = self.fill(page, overwrite=True)
        entry = self.source_entry(report)
        self.assertEqual((entry["kind"], entry["question_id"], entry["fill"]), ("selectinput", "how_heard", "ok"))
        self.assertEqual(self.pills(page), ["LinkedIn"])
        self.assertEqual(page.input_value("#source--source"), "")       # the box stays empty: only the pill counts

    def test_linkedin_found_through_job_boards_when_search_finds_nothing(self):
        page = self.open("#nosearch")
        report, summary = self.fill(page, overwrite=True)
        self.assertEqual(self.source_entry(report)["fill"], "ok")
        self.assertEqual(self.pills(page), ["LinkedIn"])
        self.assertNotIn("fill_failed", summary)

    def test_menu_without_category_marks_undoes_wrong_picks(self):
        page = self.open("#nosearch&nomarks")    # "Career Site" etc. look like categories but are choices
        self.fill(page, overwrite=True)
        self.assertEqual(self.pills(page), ["LinkedIn"])

    def test_existing_pill_is_left_alone(self):
        page = self.open()
        page.evaluate("() => pick('LinkedIn')")
        report, _ = self.fill(page, overwrite=True)
        self.assertEqual(self.pills(page), ["LinkedIn"])
        self.assertEqual(page.evaluate("() => window.picks"), 1)
        self.assertEqual(self.source_entry(report)["fill"], "ok")

    def test_two_failed_runs_hand_off_with_the_real_choices(self):
        self.store.set_fact("source.how_heard_default", "Hacker News")   # not in Visa's menu
        page = self.open()
        first, s1 = self.fill(page, overwrite=True)
        self.assertEqual([f["label"] for f in s1["fill_failed"]], ["How Did You Hear About Us?*"])
        second, s2 = self.fill(page)
        hand = s2["handoff"][0]
        self.assertEqual(hand["attempts"], 2)
        self.assertIn("Job Boards > LinkedIn", hand["why"])              # options to choose from, for the agent
        self.assertIn("Career Site", hand["why"])
        third, s3 = self.fill(page)
        self.assertTrue(self.source_entry(third)["fill"].startswith("not tried"))
        self.assertEqual(self.pills(page), [])


if __name__ == "__main__":
    unittest.main()
