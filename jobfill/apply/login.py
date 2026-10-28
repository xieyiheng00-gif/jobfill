"""Create or sign in to a job-portal account in the jobfill browser window.

Started only by ``jobfill login``, which the candidate runs in their own terminal: the agent never types
passwords or verification codes. Uses the login email and the per-company derived password
(``accounts.py``); an optional mail connector (``mail.py``) reads the verification code or link.

Works on generic sign-in / sign-up / verification forms and on Workday (data-automation-id fields,
click_filter overlays, the hidden "beecatcher" honeypot that must never be filled).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .. import accounts

# Finds the auth controls on the page and tags them data-jobfill-auth=email|pw1|pw2|code|boxN|terms|
# submit|create|signin. Honeypots (hidden, tabindex=-1, "beecatcher") are never tagged.
ANALYZE_JS = r"""() => {
  const shown = (e) => { if (!e || !e.getClientRects().length) return false;
    const st = getComputedStyle(e); return st.visibility !== "hidden" && st.display !== "none"; };
  const trap = (e) => /beecatcher|honeypot|captcha/i.test(`${e.name} ${e.id} ${e.getAttribute("data-automation-id") || ""} ${e.className}`)
    || e.tabIndex < 0 || e.getAttribute("aria-hidden") === "true";
  document.querySelectorAll("[data-jobfill-auth]").forEach((e) => e.removeAttribute("data-jobfill-auth"));
  const about = (e) => { const l = (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.closest("label");
    return `${l ? l.innerText : ""} ${e.getAttribute("aria-label") || ""} ${e.placeholder || ""} ${e.name || ""} ${e.id || ""} ` +
           `${e.getAttribute("autocomplete") || ""} ${e.getAttribute("data-automation-id") || ""}`; };
  const txt = (e) => (e.innerText || e.value || e.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();
  const inputs = Array.from(document.querySelectorAll("input")).filter((e) => shown(e) && !trap(e));
  const pws = inputs.filter((e) => e.type === "password");
  const scope = pws.length ? (pws[0].closest("form") || pws[0].closest("[data-automation-id=signInContent]") || document.body) : document.body;
  const email = inputs.find((e) => e.type !== "password" && scope.contains(e) &&
                                  (e.type === "email" || /e-?mail|user ?name|login id|\bemail\b/i.test(about(e))));
  const code = inputs.find((e) => e.type !== "password" && e !== email &&
                                 (e.autocomplete === "one-time-code" || /\b(code|otp|passcode|verification|pin)\b/i.test(about(e))));
  const boxes = code ? [] : inputs.filter((e) => e.maxLength === 1 && /^(text|tel|number)$/.test(e.type));
  const terms = Array.from(scope.querySelectorAll("input[type=checkbox]")).find((e) => !trap(e) &&
    /agree|terms|accept|consent|privacy|acknowledge/i.test(about(e) + " " + ((e.closest("label, div, fieldset") || {}).innerText || "")));
  const clickables = Array.from(document.querySelectorAll("button, a, input[type=submit], [role=button], [data-automation-id=click_filter]"))
    .filter((e) => shown(e) && !/^utility/.test(e.getAttribute("data-automation-id") || ""));
  const SUBMIT = /^(sign in|log ?in|create account|register|sign up|continue|submit|next|verify|confirm|verify (email|account))$/i;
  let submit = null;
  if (pws.length || code || boxes.length) {
    const area = pws.length ? scope : ((code || boxes[0]).closest("form") || document.body);
    submit = clickables.find((e) => area.contains(e) && SUBMIT.test(txt(e)) && e.getAttribute("data-automation-id") !== "click_filter")
          || Array.from(area.querySelectorAll("button[type=submit], input[type=submit]")).find(shown) || null;
    // Workday lays a click_filter element over its submit buttons: click that.
    const filter = submit && submit.parentElement && submit.parentElement.querySelector("[data-automation-id=click_filter]");
    if (filter && shown(filter)) submit = filter;
  }
  const besideSubmit = (e) => e === submit || (submit && submit.parentElement && submit.parentElement.contains(e));
  const create = clickables.find((e) => !besideSubmit(e) && /^(create (an )?account|sign up|register|create profile|new user\??|join now)$/i.test(txt(e)));
  const signin = clickables.find((e) => !besideSubmit(e) && /^(sign in|log ?in|sign in instead|already have an account\??( sign in)?)$/i.test(txt(e)));
  const mark = (e, k) => e && e.setAttribute("data-jobfill-auth", k);
  mark(email, "email"); mark(pws[0], "pw1"); mark(pws[1], "pw2"); mark(code, "code"); mark(terms, "terms");
  mark(submit, "submit"); mark(create, "create"); mark(signin, "signin");
  boxes.forEach((b, i) => b.setAttribute("data-jobfill-auth", "box" + i));
  const body = document.body.innerText;
  const errors = Array.from(document.querySelectorAll("[role=alert], [data-automation-id=errorMessage], .error, .error-message, [class*='error' i]"))
    .filter(shown).map(txt).filter(Boolean).join(" | ").slice(0, 600);
  return { passwords: pws.length, email: !!email, email_value: email ? email.value : "", code: !!code, boxes: boxes.length,
    terms: !!terms, terms_checked: !!(terms && terms.checked), submit: !!submit, create: !!create, signin: !!signin, errors,
    verify_prompt: /verify your (email|account)|check your (email|inbox)|(we('ve| have)|has been) sent (you )?(an? )?(email|verification|code|link)|confirm your email|enter the (code|verification code)/i.test(body),
    captcha: !!Array.from(document.querySelectorAll("iframe[src*='captcha'], iframe[title*='captcha' i], .g-recaptcha, .h-captcha")).find(shown),
    url: location.href };
}"""

EXISTS = re.compile(r"already (exists|registered|in use|associated|taken)|account (with this|for this) email|"
                    r"email (address )?is already", re.I)
BAD_LOGIN = re.compile(r"(incorrect|invalid|wrong|doesn.t match|not recognized).{0,40}(password|credentials|email|sign.?in)|"
                       r"(password|credentials).{0,30}(incorrect|invalid|wrong)|couldn.t sign you in|sign.?in failed|"
                       r"account (is )?locked", re.I)
RULES = re.compile(r"password (must|should|does not meet|doesn.t meet)|password requirements not met", re.I)


@dataclass
class Outcome:
    status: str    # signed_in | needs_verification | captcha | consent_required | failed | no_login_form
    message: str
    account: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["account"]:
            d["account"] = {k: d["account"][k] for k in ("host", "email", "status", "version")}
        return d


def _auth(frame, key: str):
    return frame.locator(f'[data-jobfill-auth="{key}"]').first


def _click(page, frame, key: str, wait_ms: int) -> None:
    _auth(frame, key).click(timeout=5000, force=True)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(wait_ms)


def _fill_email(frame, s: dict, email: str) -> None:
    if s["email"] and s["email_value"].strip().lower() != email.lower():
        loc = _auth(frame, "email")
        if loc.is_editable():
            loc.fill(email)


def login_flow(page, frame, store, data_dir, host: str, company: str, *, mail=None, max_steps: int = 10,
               wait_ms: int = 3000) -> Outcome:
    """Drive whatever auth page is showing until signed in, or until only the candidate can continue."""
    email = accounts.login_email(store)
    if not email:
        return Outcome("failed", "No login email: set `account.login_email` (or your contact email) first.")
    password, acct = accounts.password_for(store, data_dir, host, company)
    since = datetime.now(timezone.utc)
    went_to_create = created = signed_in_once = verified = False
    for _ in range(max_steps):
        s = frame.evaluate(ANALYZE_JS)
        acct = store.account(host)
        if s["captcha"]:
            return Outcome("captcha", "A CAPTCHA is showing. Solve it in the jobfill window, then run login again.", acct)
        errors = s["errors"]
        if created and EXISTS.search(errors):
            # Account made earlier (by jobfill or by hand): sign in instead.
            store.upsert_account(host, acct["company_key"], email, "created")
            created = False
            if s["signin"]:
                _click(page, frame, "signin", wait_ms)
                continue
        if signed_in_once and BAD_LOGIN.search(errors):
            store.set_account_status(host, "failed")
            return Outcome("failed", f"The site rejected the sign-in for {email}. If you made this account yourself, "
                                     "reset its password with the site's 'Forgot password' and set it to "
                                     "`jobfill account password --show` (run it yourself), or create the account again "
                                     "with another email.", store.account(host))
        if RULES.search(errors):
            return Outcome("failed", f"The site did not accept the generated password: {errors[:200]}", acct)

        if s["code"] or s["boxes"]:
            found = mail.wait_for_verification(since, [host], company) if mail else None
            if not found or not found.get("code"):
                return Outcome("needs_verification",
                               f"The site sent a verification code to {email}. Type it into the jobfill window, or set "
                               "up the mail connector in data/secret.env so jobfill can read it.", acct)
            if s["code"]:
                _auth(frame, "code").fill(found["code"])
            else:
                for i, digit in enumerate(found["code"][: s["boxes"]]):
                    _auth(frame, f"box{i}").fill(digit)
            verified = True
            if s["submit"]:
                _click(page, frame, "submit", wait_ms)
            else:
                page.wait_for_timeout(wait_ms)
            store.set_account_status(host, "verified")
            continue

        if s["passwords"] >= 2:   # create-account form
            if created:
                return Outcome("failed", f"Account creation did not go through: {errors[:200] or 'no message'}", acct)
            if s["terms"] and not s["terms_checked"]:
                if store.get_fact("consent.account_terms") is not True:
                    return Outcome("consent_required", "Creating this account requires accepting the site's terms. "
                                   "Tick the box in the window yourself, or allow it for all portals "
                                   "(`consent.account_terms`), then run login again.", acct)
                _auth(frame, "terms").check(force=True)
            _fill_email(frame, s, email)
            _auth(frame, "pw1").fill(password)
            _auth(frame, "pw2").fill(password)
            created = True
            store.upsert_account(host, acct["company_key"], email, "created")
            _click(page, frame, "submit", wait_ms)
            continue

        if s["passwords"] == 1:   # sign-in form
            if acct["status"] == "pending" and not went_to_create and not created and s["create"]:
                went_to_create = True   # no account yet: make one
                _click(page, frame, "create", wait_ms)
                continue
            if signed_in_once:
                return Outcome("failed", f"Sign-in did not complete: {errors[:200] or 'the sign-in form is still showing'}.",
                               acct)
            _fill_email(frame, s, email)
            _auth(frame, "pw1").fill(password)
            signed_in_once = True
            _click(page, frame, "submit", wait_ms)
            continue

        if s["verify_prompt"] and not verified:
            found = mail.wait_for_verification(since, [host], company) if mail else None
            if found and found.get("link"):
                page.goto(found["link"], wait_until="domcontentloaded")   # extract() only returns portal-domain links
                page.wait_for_timeout(wait_ms)
                verified = True
                store.set_account_status(host, "verified")
                continue
            return Outcome("needs_verification",
                           f"{company} sent a verification email to {email}. Open its link in the jobfill window (or set up "
                           "the mail connector), then run login again.", acct)

        if signed_in_once or created or verified:
            store.set_account_status(host, "active")
            return Outcome("signed_in", f"Signed in to {host} as {email}.", store.account(host))
        return Outcome("no_login_form", "There is no sign-in or create-account form on this page "
                                        "(you may already be signed in).", acct)
    return Outcome("failed", "Stopped after several steps without signing in; finish in the window.", store.account(host))
