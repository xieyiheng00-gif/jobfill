"""Per-ATS knowledge: how to reach the form, where it lives, and its quirks.

Field reading and filling are generic (forms.py); an adapter only adds what differs between
systems. None of them ever clicks a final submit button on its own: `submit()` runs only from
`jobfill apply submit --confirm`, after the candidate said so.
"""

from __future__ import annotations

import re

from ..text import normalize

CONFIRMATION = re.compile(r"(thank you|thanks) for (applying|your application|your interest)|application (has been |was )?"
                          r"(received|submitted)|we('ve| have) received your application|successfully submitted", re.I)
SUBMIT_WORDS = re.compile(r"^(submit|send|apply|finish|complete)( (my |your )?application| now)?$", re.I)
NEXT_WORDS = re.compile(r"^(next|continue|save and continue|save & continue|next step|proceed|continue to next step)$", re.I)


class Adapter:
    name = "generic"
    ready_selector = "input, select, textarea"
    root_selector: str | None = None
    submit_selector = "button[type=submit], input[type=submit]"

    def open(self, page, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.wait_ready(page)

    def frame(self, page):
        return page.main_frame

    def wait_ready(self, page, timeout: int = 15000) -> None:
        try:
            self.frame(page).wait_for_selector(self.ready_selector, timeout=timeout, state="attached")
        except Exception:
            pass
        page.wait_for_timeout(800)

    def blockers(self, page) -> list[str]:
        """Things only the candidate can do: log in, solve a CAPTCHA."""
        found = []
        fr = self.frame(page)
        if fr.locator("input[type=password]:visible").count():
            found.append("login_required")
        if page.locator("iframe[src*='hcaptcha'], iframe[src*='recaptcha'], iframe[title*='captcha' i]").count():
            visible = page.locator("iframe[src*='hcaptcha']:visible, iframe[src*='recaptcha/api2/bframe']:visible").count()
            if visible:
                found.append("captcha")
        text = fr.locator("body").inner_text(timeout=5000)[:20000]
        if re.search(r"no longer (accepting applications|available|open)|position (has been )?(filled|closed)|"
                     r"job (is )?(closed|expired)", text, re.I):
            found.append("job_closed")
        return found

    def prepare(self, page, store, dry_run: bool = False) -> list[str]:
        """Steps before the form (email gates etc.). Returns blockers. A dry run never types."""
        return self.blockers(page)

    def after_fill(self, frame, field: dict, value) -> None:
        pass

    def custom_fill(self, frame, field: dict, value):
        """Take over a widget this system renders specially; None means use the generic filler."""
        return None

    def after_upload(self, frame) -> None:
        frame.wait_for_timeout(1000)

    def _buttons(self, frame):
        return frame.locator("button:visible, input[type=submit]:visible, input[type=button]:visible, "
                             "a[role=button]:visible")

    def _button_text(self, loc) -> str:
        try:
            return normalize(loc.inner_text(timeout=1000) or loc.get_attribute("value") or "")
        except Exception:
            return normalize(loc.get_attribute("value") or "")

    def next_button(self, frame):
        buttons = self._buttons(frame)
        for i in range(buttons.count()):
            b = buttons.nth(i)
            t = self._button_text(b)
            if NEXT_WORDS.match(t) and not SUBMIT_WORDS.match(t):
                return b
        return None

    def submit_button(self, frame):
        loc = frame.locator(self.submit_selector).filter(visible=True)
        if loc.count():
            return loc.last
        buttons = self._buttons(frame)
        for i in range(buttons.count()):
            if SUBMIT_WORDS.match(self._button_text(buttons.nth(i))):
                return buttons.nth(i)
        return None

    def errors(self, frame) -> list[str]:
        return frame.evaluate(r"""() => Array.from(document.querySelectorAll(
              "[role=alert], .error, .error-message, [class*='error' i]:not(input):not(form), [aria-invalid=true]"))
            .filter(e => e.getClientRects().length && e.textContent.trim())
            .map(e => e.textContent.replace(/\s+/g, ' ').trim()).filter(t => t.length < 200).slice(0, 15)""")

    def confirmed(self, page) -> bool:
        return bool(CONFIRMATION.search(self.frame(page).locator("body").inner_text(timeout=5000)[:20000]))


class Greenhouse(Adapter):
    name = "greenhouse"
    ready_selector = "#first_name, input[name='job_application[first_name]'], #application-form, #application_form"
    root_selector = "#application-form, #application_form, form[action*='applications'], form"
    submit_selector = "#submit_app, button[type=submit]:has-text('Submit'), input[type=submit][value*='Submit']"

    def frame(self, page):
        # Company career sites embed the form in an iframe.
        for fr in page.frames:
            if "greenhouse.io" in fr.url and ("embed/job_app" in fr.url or "/jobs/" in fr.url) and fr != page.main_frame:
                return fr
        return page.main_frame

    def open(self, page, url: str) -> None:
        super().open(page, url)
        fr = self.frame(page)
        if not fr.locator("#first_name, input[name='job_application[first_name]']").count():
            btn = fr.locator("a:has-text('Apply'), button:has-text('Apply')").first
            if btn.count():
                btn.click()
                self.wait_ready(page)


class Lever(Adapter):
    name = "lever"
    ready_selector = "#application-form, form[action*='/apply'], input[name='name']"
    root_selector = "#application-form, form[action*='/apply'], form"
    submit_selector = "#btn-submit, button[type=submit]"

    def after_upload(self, frame) -> None:
        # Lever parses the resume and prefills fields; wait so it cannot overwrite our values later.
        for _ in range(40):
            frame.wait_for_timeout(250)
            busy = frame.locator(".resume-upload-working:visible, .loading-label:visible").count()
            if not busy:
                break
        frame.wait_for_timeout(500)

    def custom_fill(self, frame, field: dict, value):
        if field.get("name") != "location":
            return None
        # Lever's location only counts when a suggestion is picked (it sets a hidden location id);
        # typed text alone is cleared on blur. Type key by key, then click the best suggestion.
        loc = frame.locator(f'[data-jobfill-id="{field["id"]}"]')
        loc.click()
        loc.fill("")
        loc.type(str(value), delay=40)
        options = frame.locator(".dropdown-location:visible")
        for _ in range(20):
            frame.wait_for_timeout(250)
            if options.count():
                break
        if not options.count():
            return False, f"no location suggestion for {value!r}"
        texts = [options.nth(i).inner_text().strip() for i in range(options.count())]
        city = normalize(str(value).split(",")[0])
        best = next((i for i, t in enumerate(texts) if normalize(t).startswith(city)), 0)
        options.nth(best).click()
        frame.wait_for_timeout(300)
        return True, ""


class Ashby(Adapter):
    name = "ashby"
    ready_selector = "#_systemfield_name, .ashby-application-form-field-entry"
    submit_selector = "button.ashby-application-form-submit-button, button:has-text('Submit Application')"

    def open(self, page, url: str) -> None:
        super().open(page, url)
        if not page.locator(".ashby-application-form-field-entry").count():
            # Overview page: switch to the "Application" tab.
            tab = page.locator("a:has-text('Application'), [role=tab]:has-text('Application')").first
            if tab.count():
                tab.click()
                self.wait_ready(page)

    def after_upload(self, frame) -> None:
        frame.wait_for_timeout(1500)


class ICIMS(Adapter):
    name = "icims"
    ready_selector = "input, select, textarea, button"
    submit_selector = "input[type=submit][value*='Submit' i], button:has-text('Submit')"

    def frame(self, page):
        for fr in page.frames:
            if "in_iframe=1" in fr.url or (fr.name == "icims_content_iframe"):
                return fr
        return page.main_frame

    def open(self, page, url: str) -> None:
        super().open(page, url)
        fr = self.frame(page)
        # Job page instead of the login step: follow its "Apply" link.
        if not fr.locator("input:visible").count():
            link = fr.locator("a:has-text('Apply for this job'), a:has-text('Apply'), button:has-text('Apply')").first
            if link.count():
                link.click()
                self.wait_ready(page)

    def prepare(self, page, store, dry_run: bool = False) -> list[str]:
        fr = self.frame(page)
        email = fr.locator("input#email:visible, input[type=email]:visible").first
        others = fr.locator("input:visible:not([type=email]):not([type=checkbox]):not([type=submit]):not([type=hidden])")
        if email.count() and others.count() <= 1 and not fr.locator("input[type=password]:visible").count():
            if dry_run:
                return self.blockers(page) + ["email_gate"]
            # Email gate: iCIMS asks for the email first, then shows the profile form or a login.
            address = store.get_fact("contact.email")
            terms = fr.locator("input[type=checkbox]:visible").first
            if terms.count() and not terms.is_checked():
                # Usually "I accept the privacy/GDPR terms": only with the candidate's standing consent.
                if store.get_fact("consent.privacy_ack") is not True:
                    return self.blockers(page) + ["consent_required"]
                terms.check(force=True)
            if address:
                email.fill(address)
                btn = self.next_button(fr) or fr.locator("#enterEmailSubmitButton, button[type=submit], input[type=submit]").first
                if btn and btn.count():
                    btn.click()
                    page.wait_for_load_state("domcontentloaded")
                    self.wait_ready(page)
        return self.blockers(page)


ADAPTERS = {"greenhouse": Greenhouse(), "lever": Lever(), "icims": ICIMS(), "ashby": Ashby(), "generic": Adapter()}


def get(name: str | None) -> Adapter:
    return ADAPTERS.get(name or "generic", ADAPTERS["generic"])
