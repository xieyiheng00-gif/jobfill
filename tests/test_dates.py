"""Dates: read in any common format, stored one way, written the way each field asks."""

import importlib.util
import unittest
from pathlib import Path

from jobfill.resolver import Resolver
from jobfill.store import ValidationError
from jobfill.text import detect_date_format, iso_date

from .helpers import TODAY, fresh_store

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


class TestReading(unittest.TestCase):
    def test_common_formats(self):
        cases = {
            "2025/9": "2025-09", "Sep/2025": "2025-09", "9/2025": "2025-09", "Sep,2025": "2025-09",
            "September 2025": "2025-09", "Sept. 2025": "2025-09", "2025 Sep": "2025-09", "09-2025": "2025-09",
            "2025-09-01": "2025-09-01", "09/01/2025": "2025-09-01", "Sep 1, 2025": "2025-09-01",
            "1 Sep 2025": "2025-09-01", "September 1st 2025": "2025-09-01", "13/09/2025": "2025-09-13",
            "2025": "2025",
        }
        self.assertEqual({k: iso_date(k) for k in cases}, cases)

    def test_rejects_what_it_cannot_read_safely(self):
        for text in ("next week", "09/25", "2025-13", "Feb 30 2025", "Present", ""):
            self.assertIsNone(iso_date(text), text)

    def test_format_from_label_or_placeholder(self):
        cases = {"MM/YYYY": "MM/YYYY", "mm/dd/yyyy": "MM/DD/YYYY", "e.g. 09/2025": "MM/YYYY",
                 "Graduation date (Month YYYY)": "MMMM YYYY", "Start (Mon YYYY)": "MMM YYYY", "YYYY-MM": "YYYY-MM",
                 "Do you have an M.D.?": None, "Your name": None}
        self.assertEqual({k: detect_date_format(k) for k in cases}, cases)


class TestStoring(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store(owner=self)

    def test_facts_accept_any_format(self):
        self.assertEqual(self.store.set_fact("availability.earliest_start", "Jun 2027"), "2027-06")
        self.assertEqual(self.store.set_fact("availability.earliest_start", "6/1/2027"), "2027-06-01")
        with self.assertRaises(ValidationError):
            self.store.set_fact("availability.earliest_start", "soon")

    def test_records_normalize_and_understand_present(self):
        edu = self.store.add_record("education", {"school": "UW", "start_date": "2025/9", "end_date": "Present"})
        self.assertEqual(self.store.get_record(edu)[1], {"school": "UW", "start_date": "2025-09", "expected": True})
        job = self.store.add_record("experience", {"company": "Globex", "start_date": "Jan, 2024", "end_date": "present"})
        self.assertEqual(self.store.get_record(job)[1], {"company": "Globex", "start_date": "2024-01", "current": True})
        with self.assertRaises(ValidationError):
            self.store.add_record("project", {"name": "X", "start_date": "Fall 2025"})


class TestWriting(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store(with_profile=True, owner=self)   # UW 2025-09 to 2027-05, start 2027-06-01
        self.app = self.store.start_application("Acme", "Engineer")

    def resolve(self, fields):
        return {f["id"]: f for f in Resolver(self.store, self.app, today=TODAY).resolve(fields)["fields"]}

    def test_split_and_formatted_fields(self):
        out = self.resolve([
            {"id": "sm", "label": "Start month", "section": "education", "type": "select", "options": MONTHS},
            {"id": "sy", "label": "Start year", "section": "education", "type": "text"},
            {"id": "gm", "label": "Expected graduation month", "type": "select",
             "options": [f"{i:02d}" for i in range(1, 13)]},
            {"id": "gy", "label": "Graduation year", "type": "select", "options": ["2026", "2027", "2028"]},
            {"id": "ph", "label": "Graduation date", "type": "text", "placeholder": "MM/YYYY"},
            {"id": "lb", "label": "Graduation date (Mon YYYY)", "type": "text"},
            {"id": "nd", "label": "Earliest start date", "type": "date"},
            {"id": "us", "label": "Earliest start date", "type": "text"},
            {"id": "sp", "label": "When can you start?", "type": "text"},
            {"id": "op", "label": "Expected graduation", "type": "select", "options": ["Dec 2026", "May 2027", "Dec 2027"]},
        ])
        got = {k: v.get("value") for k, v in out.items()}
        self.assertEqual(got, {"sm": "September", "sy": "2025", "gm": "05", "gy": "2027", "ph": "05/2027",
                               "lb": "May 2027", "nd": "2027-06-01", "us": "06/01/2027", "sp": "June 1, 2027",
                               "op": "May 2027"})

    def test_label_with_part_word_still_finds_the_date_question(self):
        out = self.resolve([{"id": "m", "label": "Expected graduation date - Month", "type": "select", "options": MONTHS},
                            {"id": "y", "label": "Expected graduation date - Year", "type": "text"}])
        self.assertEqual((out["m"]["question_id"], out["m"]["value"]), ("graduation_date", "May"))
        self.assertEqual(out["y"]["value"], "2027")

    def test_missing_month_is_asked_not_invented(self):
        self.store.set_fact("availability.earliest_start", "2027")
        out = self.resolve([{"id": "s", "label": "Earliest start date (MM/YYYY)", "type": "text", "required": True}])
        self.assertEqual(out["s"]["status"], "needs_user")


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright not installed")
class TestSplitDatesInBrowser(unittest.TestCase):
    def test_fixture(self):
        from playwright.sync_api import sync_playwright
        from jobfill.apply import adapters
        from jobfill.apply.runner import fill_frame
        store = fresh_store(with_profile=True, owner=self)
        app = store.start_application("Acme", "Engineer")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto((Path(__file__).parent / "fixtures" / "dates_like.html").as_uri())
            generic = adapters.get("generic")
            report = fill_frame(generic.frame(page), store, app, generic, overwrite=True, today=TODAY)
            labels = {v["label"] for v in report["fields"].values()}
            self.assertTrue({"Start date Month", "Start date Year", "Expected graduation date Month",
                             "Expected graduation date Year"} <= labels)
            values = page.evaluate("""() => ({sm: document.querySelector('#sm').selectedOptions[0].text,
                sy: document.querySelector('#sy').value, gm: document.querySelector('#gm').selectedOptions[0].text,
                gy: document.querySelector('#gy').selectedOptions[0].text, avail: document.querySelector('#avail').value,
                avail2: document.querySelector('#avail2').value, sig: document.querySelector('#sig').value})""")
            browser.close()
        self.assertEqual(values, {"sm": "September", "sy": "2025", "gm": "05", "gy": "2027", "avail": "06/01/2027",
                                  "avail2": "Jun 2027", "sig": TODAY.isoformat()})


if __name__ == "__main__":
    unittest.main()
