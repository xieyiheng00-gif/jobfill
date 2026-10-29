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


# ---- Workday prompt ("selectinput"): a search box with a pop-up menu; only a clicked choice counts,
# and it then shows as a pill while the box stays empty. Menus can be two levels (category -> choice).

PILLS_JS = r"""(id) => {
  const el = document.querySelector(`[data-jobfill-id="${id}"]`);
  const box = el.closest("[data-automation-id^='formField']") || el.closest("[data-automation-id='multiSelectContainer']") || el.parentElement;
  return Array.from(box.querySelectorAll("[data-automation-id='selectedItem']"))
    .map((p) => (p.getAttribute("title") || p.innerText || "").replace(/[×✕]/g, "").replace(/\s+/g, " ").trim()).filter(Boolean);
}"""

# Visible menu entries (not the pills), tagged data-jobfill-opt=<n>. ``branch`` marks a category that
# opens a sub-level (chevron / aria-haspopup); ``marked`` says whether this menu marks categories at all.
MENU_JS = r"""() => {
  const shown = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden";
  let items = Array.from(document.querySelectorAll("[role=option], [data-automation-id=promptOption]"))
    .filter((o) => shown(o) && !o.closest("[data-automation-id='selectedItem'], [data-automation-id='selectedItemList']"));
  items = items.filter((o) => !items.some((p) => p !== o && p.contains(o)));
  document.querySelectorAll("[data-jobfill-opt]").forEach((o) => o.removeAttribute("data-jobfill-opt"));
  return items.map((o, i) => {
    o.setAttribute("data-jobfill-opt", String(i));
    const branch = !!o.querySelector("[data-automation-id*='chevron' i], [data-automation-id*='arrow' i], [class*='chevron' i]")
      || o.getAttribute("aria-haspopup") === "true" || o.hasAttribute("aria-expanded");
    return {text: (o.getAttribute("data-automation-label") || o.innerText || "").replace(/\s+/g, " ").trim(), branch};
  });
}"""

REMOVE_PILL_JS = r"""([id, text]) => {
  const el = document.querySelector(`[data-jobfill-id="${id}"]`);
  const box = el.closest("[data-automation-id^='formField']") || el.closest("[data-automation-id='multiSelectContainer']") || el.parentElement;
  const norm = (s) => (s || "").replace(/[×✕]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
  const pill = Array.from(box.querySelectorAll("[data-automation-id='selectedItem']"))
    .find((p) => norm(p.getAttribute("title") || p.innerText) === norm(text));
  const x = pill && pill.querySelector("[data-automation-id*='delete' i], [data-automation-id*='remove' i], [aria-label*='remove' i], [aria-label*='delete' i], [role=button], button");
  if (x) x.click();
  return !!x;
}"""


def _same(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)


def _pick(items: list[dict], want: str) -> int | None:
    """The menu entry meaning ``want``: exact, then 'Job Boards > LinkedIn'-style suffix, then prefix."""
    w = normalize(want)
    norms = [normalize(i["text"]) for i in items]
    for test in (lambda n: n == w, lambda n: n.endswith(" " + w), lambda n: n.startswith(w + " ")):
        hits = [k for k, n in enumerate(norms) if n and test(n)]
        if hits:
            return hits[0]
    return None


def _menu(frame, before: list[dict] | None = None, wait_ms: int = 4000) -> list[dict]:
    """Menu entries once they appear (or change from ``before``, e.g. after search or drill-down)."""
    items: list[dict] = []
    for _ in range(max(1, wait_ms // 200)):
        frame.wait_for_timeout(200)
        items = frame.evaluate(MENU_JS)
        if items and items != before:
            break
    return items


BACK = "[data-automation-id*='back' i]:visible, [aria-label*='back' i]:visible"


def _to_top(frame, items: list[dict]) -> list[dict]:
    """Workday reopens the menu at the level last shown: step back up to the top level."""
    for _ in range(3):
        back = frame.locator(BACK).first
        if not back.count():
            break
        back.click()
        items = _menu(frame, before=items, wait_ms=1500)
    return items


def fill_selectinput(frame, field: dict, value) -> tuple[bool, str]:
    loc = frame.locator(f'[data-jobfill-id="{field["id"]}"]')
    pills = lambda: frame.evaluate(PILLS_JS, field["id"])
    for want in (value if isinstance(value, list) else [value]):
        want = str(want)
        if any(_same(p, want) for p in pills()):
            continue   # already chosen
        start = pills()

        # 1. Search: Workday searches every level once Enter is pressed.
        loc.click()
        loc.fill("")
        loc.type(want, delay=20)
        loc.press("Enter")
        found = _menu(frame)
        k = _pick(found, want)
        if k is not None:
            frame.locator(f'[data-jobfill-opt="{k}"]').click()
            frame.wait_for_timeout(500)
            if any(_same(p, want) for p in pills()):
                continue

        # 2. Browse: open each category and look inside (Job Boards -> LinkedIn).
        loc.press("Escape")
        loc.fill("")
        seen: list[str] = []
        loc.click()
        top = _to_top(frame, _menu(frame))
        marked = any(i["branch"] for i in top)
        done = False
        for entry in top:
            seen.append(entry["text"])
            if marked and not entry["branch"] and not _same(entry["text"], want):
                continue   # a plain choice, not a category: clicking it would select it
            if frame.evaluate(MENU_JS) != top:   # back to the top level for every category
                _to_top(frame, frame.evaluate(MENU_JS))
                if frame.evaluate(MENU_JS) != top:
                    loc.press("Escape")
                    loc.click()
                    _to_top(frame, _menu(frame))
            now = frame.evaluate(MENU_JS)
            k = next((n for n, i in enumerate(now) if i["text"] == entry["text"]), None)
            if k is None:
                continue
            frame.locator(f'[data-jobfill-opt="{k}"]').click()
            frame.wait_for_timeout(500)
            added = [p for p in pills() if p not in start]
            if any(_same(p, want) for p in added):
                done = True
                break
            for p in added:   # it was a plain choice after all (menu without category marks): undo it
                frame.evaluate(REMOVE_PILL_JS, [field["id"], p])
                frame.wait_for_timeout(300)
            if added:
                continue
            sub = _menu(frame, before=now, wait_ms=2000)
            if sub == now:
                continue
            seen += [f"{entry['text']} > {i['text']}" for i in sub if i["text"] != entry["text"]]
            k = _pick(sub, want)
            if k is not None:
                frame.locator(f'[data-jobfill-opt="{k}"]').click()
                frame.wait_for_timeout(500)
                done = any(_same(p, want) for p in pills())
                break
        if not done:
            loc.press("Escape")
            return False, f"no menu choice matches {want!r}; it offers: {seen[:40]}"
    return True, ""


class Workday(Adapter):
    """Workday: each company is its own tenant with its own account. Apply -> Apply Manually ->
    Sign in with email, then a multi-page form ("Save and Continue")."""
    name = "workday"
    ready_selector = ("[data-automation-id=signInContent], [data-automation-id=applyFlowPage], "
                      "[data-automation-id=adventureButton], input")
    submit_selector = "[data-automation-id=bottom-navigation-next-button]:has-text('Submit')"

    def open(self, page, url: str) -> None:
        super().open(page, url)
        # Each step's button renders only after the previous click has loaded; a step that never shows up
        # (already signed in, or a tenant without that choice) is skipped.
        for step in ("adventureButton", "applyManually", "SignInWithEmailButton"):
            button = page.locator(f"[data-automation-id={step}]:visible").first
            try:
                button.wait_for(state="visible", timeout=10000)
            except Exception:
                continue
            button.click()
        page.wait_for_timeout(1500)
        self.wait_ready(page)

    def custom_fill(self, frame, field: dict, value):
        if field.get("kind") == "selectinput":
            return fill_selectinput(frame, field, value)
        return None

    def next_button(self, frame):
        nxt = frame.locator("[data-automation-id=bottom-navigation-next-button]:visible").first
        if nxt.count() and not SUBMIT_WORDS.match(self._button_text(nxt)):
            return nxt
        return super().next_button(frame)


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


ADAPTERS = {"greenhouse": Greenhouse(), "lever": Lever(), "icims": ICIMS(), "ashby": Ashby(), "workday": Workday(),
            "generic": Adapter()}


def get(name: str | None) -> Adapter:
    return ADAPTERS.get(name or "generic", ADAPTERS["generic"])
