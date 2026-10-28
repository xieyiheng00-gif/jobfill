"""`jobfill apply ...`: start an application from a URL and fill its form with plain Python."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .. import report as results
from ..db import ROOT
from ..resolver import Resolver
from . import adapters, browser
from .detect import Detection, detect
from .forms import extract, fill, is_empty, to_resolver_field

MAX_PASSES = 4   # re-read the form after filling: answers can reveal follow-up questions


class ApplyError(Exception):
    def __init__(self, message: str, code: int = 2, **extra):
        super().__init__(message)
        self.payload = {"error": message, **extra}
        self.code = code


def state_dir(data_dir: Path, app_id: int) -> Path:
    d = data_dir / "apply" / f"app{app_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(data_dir: Path, app_id: int) -> dict:
    p = state_dir(data_dir, app_id) / "state.json"
    if not p.exists():
        raise ApplyError(f"application {app_id} was not started with `jobfill apply start`")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(data_dir: Path, app_id: int, state: dict) -> None:
    (state_dir(data_dir, app_id) / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


NEXT_STEP = {
    "python": "Run `python -m jobfill apply fill --app {id}`.",
    "ai": "Fill it in the built-in browser following /apply step 3 (answers still come from `jobfill resolve`).",
    "follow": "Open the listing, find the employer's own apply link, and run `apply start` on it.",
    "agent_check": "Open the page in the built-in browser: if it is not a job posting, report the error; "
                   "otherwise rerun `apply start` with the real apply link, or with --ats custom.",
    "unsupported": "Not supported yet; tell the candidate to apply manually.",
}


# --------------------------------------------------------------------------- start

def start(store, data_dir: Path, url: str, *, company=None, role=None, source=None, referrer=None,
          ats=None, network=True) -> dict:
    d: Detection = detect(url, network=network)
    if ats:   # the agent looked at the page and decided
        d.ats = ats
        d.kind = "job"
        # "generic": a portal that needs an account, filled in the jobfill window so the login carries over
        d.handler = "python" if ats in adapters.ADAPTERS else "ai"
        d.apply_url = d.apply_url or url
    if d.kind == "not_job":
        raise ApplyError(f"Not a job posting: {d.reason}", code=3, detection=d.to_dict())
    out = {"detection": d.to_dict(), "handler": d.handler}
    if d.handler in ("unsupported", "follow", "agent_check"):
        out["next"] = NEXT_STEP[d.handler]
        return out
    company = company or d.company
    if not company:
        raise ApplyError("Could not tell the company name; pass --company.", detection=d.to_dict())
    posting_file = None
    app_id = store.start_application(company, role or d.role, url=url, ats=d.ats, source=source, referrer=referrer,
                                     posting=d.posting,
                                     country=None)
    if d.posting:
        posting_file = state_dir(data_dir, app_id) / "posting.txt"
        posting_file.write_text(d.posting, encoding="utf-8")
    save_state(data_dir, app_id, {"url": url, "apply_url": d.apply_url or url, "ats": d.ats, "handler": d.handler,
                                  "filled_once": False, "tag": f"jobfill-app-{app_id}"})
    prior = store.same_company_apps(company, exclude_id=app_id)
    out.update({"app_id": app_id, "company": company, "role": role or d.role, "location": d.location,
                "posting_file": str(posting_file) if posting_file else None,
                "previous_applications_to_company": [{"id": a["id"], "role": a["role"], "status": a["status"]}
                                                     for a in prior],
                "next": NEXT_STEP[d.handler].format(id=app_id)})
    return out


# --------------------------------------------------------------------------- fill

def fill_frame(frame, store, app_id: int, adapter, *, overwrite: bool, files: bool = True,
               today: date | None = None, dry_run: bool = False) -> dict:
    """Fill everything the database can answer on the current page. Works on any Playwright frame.

    ``dry_run`` reads and resolves the form without typing anything (a preview).
    """
    report: dict = {"fields": {}, "passes": 0}
    ai_context: dict | None = None
    seen: set[str] = set()
    for _ in range(MAX_PASSES):
        fields = extract(frame, adapter.root_selector)
        new = [f for f in fields if f["id"] not in seen]
        if not new:
            break
        report["passes"] += 1
        seen.update(f["id"] for f in fields)
        by_id = {f["id"]: f for f in new}
        result = Resolver(store, app_id, today=today, log=not dry_run).resolve([to_resolver_field(f) for f in new])
        if result.get("ai_context"):
            ai_context = result["ai_context"]
        # Upload files first: some systems (Lever) parse the resume and prefill other fields.
        for r in sorted(result["fields"], key=lambda r: by_id[r["id"]]["kind"] != "file"):
            f = by_id[r["id"]]
            entry = {k: v for k, v in r.items() if k not in ("raw", "source", "match")}
            entry["kind"] = f["kind"]
            if r["status"] == "filled":
                if dry_run:
                    entry["fill"] = "would fill"
                elif f["kind"] == "file" and not files:
                    entry["fill"] = "skipped (--no-files)"
                elif not overwrite and not is_empty(f):
                    entry["fill"] = "kept (already has a value)"
                else:
                    ok, note = fill(frame, f, r["value"], root=ROOT, after=adapter.after_fill,
                                    custom=adapter.custom_fill)
                    entry["fill"] = "ok" if ok else f"failed: {note}"
                    if ok and f["kind"] == "file":
                        adapter.after_upload(frame)
                if not dry_run:
                    store.set_answer_fill(app_id, _key(store, f), entry["fill"])
            report["fields"][r["id"]] = entry
        if dry_run:
            break   # nothing typed, so no follow-up questions can appear
    # Verify: anything we "filled" that is still empty did not take.
    final = {f["id"]: f for f in extract(frame, adapter.root_selector, read_options=False)}
    for fid, entry in report["fields"].items():
        if entry.get("fill") == "ok" and fid in final and is_empty(final[fid]) and entry["kind"] != "checkbox":
            entry["fill"] = "failed: value did not stick"
            if not dry_run:
                store.set_answer_fill(app_id, _key(store, final[fid]), entry["fill"])
    if ai_context:
        report["ai_context"] = ai_context
    return report


def _key(store, f: dict) -> str:
    return store.answer_key(f["label"], f.get("section"), f.get("index"))


def summarize(report: dict, app_id: int) -> dict:
    fields = report["fields"]
    pick = lambda status: [v | {"field": k} for k, v in fields.items() if v["status"] == status]
    out = {
        "app_id": app_id,
        "blockers": report.get("blockers", []),
        "counts": {s: len(pick(s)) for s in ("filled", "needs_ai", "needs_user", "uncertain", "unmatched", "skipped")},
        "fill_failed": [{"field": k, "label": v["label"], "value": v.get("value"), "why": v["fill"]}
                        for k, v in fields.items() if str(v.get("fill", "")).startswith("failed")],
        "needs_user": [{"field": v["field"], "label": v["label"], "ask": v.get("ask"), "fact": v.get("fact"),
                        "choices": v.get("choices"), "store": v.get("store"), "sensitive": v.get("sensitive")}
                       for v in pick("needs_user")],
        "uncertain": [{"field": v["field"], "label": v["label"], "candidates": v.get("candidates")} for v in pick("uncertain")],
        "unmatched": [{"field": v["field"], "label": v["label"]} for v in pick("unmatched")],
        "needs_ai": [{"field": v["field"], **v["ai_task"]} for v in pick("needs_ai")],
    }
    if out["needs_ai"] and report.get("ai_context"):
        out["ai_context"] = report["ai_context"]
    if "login_required" in out["blockers"]:
        out["next"] = (f"This site needs an account. Ask the candidate to run `python -m jobfill login --app {app_id}` "
                       "in their own terminal (it creates or signs in to the account), then run `apply fill` again. "
                       "Never run login yourself.")
    return {k: v for k, v in out.items() if v not in ([], None)}


def open_page(ctx, state: dict, adapter):
    page, fresh = browser.find_page(ctx, state["tag"], state["apply_url"])
    if fresh:
        adapter.open(page, state["apply_url"])
        page.evaluate("(t) => { window.name = t; }", state["tag"])
    page.bring_to_front()
    return page, fresh


def fill_command(store, data_dir: Path, app_id: int, *, overwrite=False, headless=False, files=True,
                 dry_run=False) -> dict:
    state = load_state(data_dir, app_id)
    if state["handler"] != "python":
        raise ApplyError(f"application {app_id} is handled by the agent ({state['handler']}), not the Python filler")
    adapter = adapters.get(state["ats"])
    with browser.session(data_dir, headless) as ctx:
        page, fresh = open_page(ctx, state, adapter)
        blockers = adapter.prepare(page, store, dry_run=dry_run)
        if {"login_required", "job_closed", "email_gate", "consent_required"} & set(blockers):
            report = {"fields": {}, "blockers": blockers}
        else:
            report = fill_frame(adapter.frame(page), store, app_id, adapter,
                                overwrite=overwrite or not state.get("filled_once"), files=files, dry_run=dry_run)
            report["blockers"] = blockers
            state["filled_once"] = state.get("filled_once") or not dry_run
        state["page_url"] = page.url
    save_state(data_dir, app_id, state)
    (state_dir(data_dir, app_id) / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                                             encoding="utf-8")
    out = summarize(report, app_id)
    if not dry_run:
        out["record"] = results.write(store, data_dir, app_id)["markdown"]
    return out


def set_command(store, data_dir: Path, app_id: int, field_id: str, value, *, headless=False) -> dict:
    state = load_state(data_dir, app_id)
    adapter = adapters.get(state["ats"])
    with browser.session(data_dir, headless) as ctx:
        page, _ = open_page(ctx, state, adapter)
        frame = adapter.frame(page)
        fields = {f["id"]: f for f in extract(frame, adapter.root_selector, read_options=False)}
        f = fields.get(field_id) or fields.get("g-" + field_id)
        if f is None:
            raise ApplyError(f"field {field_id} is not on the page (the page may have reloaded; run `apply fill` again)")
        ok, note = fill(frame, f, value, root=ROOT, after=adapter.after_fill, custom=adapter.custom_fill)
    if ok:
        store.record_answer(app_id, _key(store, f), f["label"], value, source="user", status="filled", fill="ok",
                            section=f.get("section"), idx=f.get("index"))
        results.write(store, data_dir, app_id)
    return {"field": field_id, "label": f["label"], "ok": ok, "note": note or None}


def next_command(data_dir: Path, app_id: int, *, headless=False) -> dict:
    state = load_state(data_dir, app_id)
    adapter = adapters.get(state["ats"])
    with browser.session(data_dir, headless) as ctx:
        page, _ = open_page(ctx, state, adapter)
        frame = adapter.frame(page)
        btn = adapter.next_button(frame)
        if btn is None:
            raise ApplyError("No Next/Continue button on this page (the next button may be the final submit).")
        label = btn.inner_text(timeout=2000) if btn.count() else ""
        btn.click()
        page.wait_for_load_state("domcontentloaded")
        adapter.wait_ready(page)
        errors = adapter.errors(adapter.frame(page))
        state["page_url"] = page.url
    save_state(data_dir, app_id, state)
    return {"clicked": label.strip(), "page_url": state["page_url"], "errors": errors,
            "next": f"Run `python -m jobfill apply fill --app {app_id}` for this step."}


def submit_command(store, data_dir: Path, app_id: int, *, confirm: bool, headless=False) -> dict:
    if not confirm:
        raise ApplyError("Refusing to submit without --confirm. Only pass it after the candidate explicitly "
                         "approved submitting this application.")
    state = load_state(data_dir, app_id)
    adapter = adapters.get(state["ats"])
    with browser.session(data_dir, headless) as ctx:
        page, _ = open_page(ctx, state, adapter)
        frame = adapter.frame(page)
        btn = adapter.submit_button(frame)
        if btn is None:
            raise ApplyError("No submit button found on this page.")
        btn.click()
        page.wait_for_timeout(5000)
        blockers = adapter.blockers(page)
        done = adapter.confirmed(page)
        errors = [] if done else adapter.errors(adapter.frame(page))
        state["page_url"] = page.url
    save_state(data_dir, app_id, state)
    if done:
        store.update_application(app_id, status="submitted")
    record = results.write(store, data_dir, app_id)["markdown"]
    return {"submitted": done, "record": record, "blockers": blockers, "errors": errors, "page_url": state["page_url"],
            "next": None if done else ("Solve the CAPTCHA in the browser window, then run submit again."
                                       if "captcha" in blockers else
                                       "Not confirmed. Check the window for errors, fix them, and try again.")}
