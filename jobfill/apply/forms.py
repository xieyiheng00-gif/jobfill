"""Read form fields from a page and type answers into them (Playwright, no AI)."""

from __future__ import annotations

import re
from pathlib import Path

from ..text import normalize

EXTRACT_JS = (Path(__file__).with_name("extract.js")).read_text(encoding="utf-8")

# Visible options of an open dropdown: the listbox the input controls, else any visible listbox.
OPTIONS_JS = r"""(id) => {
  const el = document.querySelector(`[data-jobfill-id="${id}"]`);
  const shown = (n) => n && n.getClientRects().length > 0 && getComputedStyle(n).visibility !== "hidden";
  let boxes = [];
  for (const attr of ["aria-controls", "aria-owns"]) {
    const ref = el && el.getAttribute(attr);
    if (ref && document.getElementById(ref)) boxes.push(document.getElementById(ref));
  }
  if (!boxes.length) boxes = Array.from(document.querySelectorAll("[role=listbox]")).filter(shown);
  const opts = [];
  for (const b of boxes) for (const o of b.querySelectorAll("[role=option]")) if (shown(o)) opts.push(o.textContent.replace(/\s+/g, " ").trim());
  if (!opts.length) for (const o of document.querySelectorAll("[role=option]")) if (shown(o)) opts.push(o.textContent.replace(/\s+/g, " ").trim());
  return opts;
}"""

NOT_AN_OPTION = re.compile(r"^(no options?|no results?( found)?|loading\.*|type to search|start typing|searching\.*|"
                           r"no matches( found)?)$", re.I)

INPUT_TYPES = {"text": "text", "email": "email", "tel": "tel", "url": "url", "number": "number", "date": "date",
               "search": "text", "month": "text", "password": "password"}


def sel(field_id: str) -> str:
    return f'[data-jobfill-id="{field_id.removeprefix("g-")}"]'


def extract(frame, root_selector: str | None = None, read_options: bool = True) -> list[dict]:
    fields = frame.evaluate(EXTRACT_JS, root_selector)
    fields = [f for f in fields if f.get("type") != "password"]
    if read_options:
        for f in fields:
            if f["kind"] == "combobox" and not f.get("options"):
                f["options"] = combobox_options(frame, f["id"])
    return fields


def combobox_options(frame, field_id: str) -> list[str]:
    loc = frame.locator(sel(field_id))
    try:
        loc.click(timeout=3000)
        frame.wait_for_timeout(350)
        opts = frame.evaluate(OPTIONS_JS, field_id)
        if not opts:
            loc.press("ArrowDown")
            frame.wait_for_timeout(350)
            opts = frame.evaluate(OPTIONS_JS, field_id)
        loc.press("Escape")
    except Exception:
        return []
    out = []
    for o in opts:
        if o and not NOT_AN_OPTION.match(o) and o not in out:
            out.append(o)
    return out


def to_resolver_field(f: dict) -> dict:
    kind = f["kind"]
    if kind == "input":
        rtype = INPUT_TYPES.get(f["type"], "text")
    elif kind == "select":
        rtype = "multiselect" if f.get("multiple") else "select"
    elif kind == "combobox":
        rtype = "select" if f.get("options") else "text"
    elif kind == "buttons":
        rtype = "radio"   # toggle-button group behaves like a radio group
    else:
        rtype = kind  # textarea, radio, checkbox, file
    out = {"id": f["id"], "label": f["label"], "type": rtype, "required": bool(f.get("required"))}
    if f.get("options") and kind != "input":
        out["options"] = f["options"]
    for k in ("max_chars", "section", "index"):
        if f.get(k) is not None:
            out[k] = f[k]
    if rtype == "date":
        out["format"] = "YYYY-MM-DD"
    return out


def is_empty(f: dict) -> bool:
    v = f.get("value")
    return v in (None, "", [], False)


def _best_option(texts: list[str], wanted: str) -> int | None:
    w = normalize(wanted)
    norms = [normalize(t) for t in texts]
    for i, n in enumerate(norms):
        if n == w:
            return i
    for i, n in enumerate(norms):
        if n.startswith(w) or w.startswith(n):
            return i
    words = [x for x in w.split() if len(x) > 1]
    if words:
        for i, n in enumerate(norms):
            if all(x in n.split() for x in words):
                return i
        for i, n in enumerate(norms):
            if words[0] in n.split():
                return i
    return None


def _fill_combobox(frame, loc, field_id: str, value) -> tuple[bool, str]:
    for v in (value if isinstance(value, list) else [value]):
        v = str(v)
        loc.click(timeout=5000)
        try:
            loc.fill("")
        except Exception:
            pass
        loc.type(v[:60], delay=15)
        texts: list[str] = []
        for _ in range(16):  # up to ~4s for async (search-as-you-type) dropdowns
            frame.wait_for_timeout(250)
            texts = [t for t in frame.evaluate(OPTIONS_JS, field_id) if not NOT_AN_OPTION.match(t)]
            if texts:
                break
        i = _best_option(texts, v)
        if i is None:
            loc.press("Escape")
            return False, f"no dropdown option matches {v!r}" + (f" (saw {texts[:5]})" if texts else "")
        opt = frame.locator("[role=option]:visible").filter(has_text=texts[i]).first
        try:
            opt.click(timeout=3000)
        except Exception:
            loc.press("Enter")
        frame.wait_for_timeout(150)
    return True, ""


def _click_choice(frame, ref: str) -> bool:
    loc = frame.locator(f'[data-jobfill-id="{ref}"]')
    try:
        loc.check(timeout=3000, force=True)
    except Exception:
        pass
    if loc.is_checked():
        return True
    # Custom-styled inputs: click the label the user would click.
    frame.evaluate("""(ref) => { const e = document.querySelector(`[data-jobfill-id="${ref}"]`);
        const l = (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.closest('label');
        (l || e).click(); }""", ref)
    return loc.is_checked()


def fill(frame, f: dict, value, *, root: Path, after=None, custom=None) -> tuple[bool, str]:
    """Put ``value`` (as returned by the resolver) into field ``f``.

    ``custom(frame, field, value)`` lets an adapter take over a widget it knows; it returns
    ``(ok, note)``, or None to use the generic handling.
    """
    kind = f["kind"]
    loc = frame.locator(sel(f["id"]))
    try:
        if custom is not None:
            handled = custom(frame, f, value)
            if handled is not None:
                return handled
        if kind == "file":
            path = Path(str(value))
            if not path.is_absolute():
                path = root / path
            if not path.exists():
                return False, f"file not found: {path}"
            loc.set_input_files(str(path))
        elif kind == "select":
            values = value if isinstance(value, list) else [value]
            loc.select_option(label=[str(v) for v in values] if f.get("multiple") else str(values[0]), timeout=5000)
        elif kind == "buttons":
            refs = dict((label, ref) for label, ref in f["option_refs"])
            if str(value) not in refs:
                return False, f"no option {value!r}"
            button = frame.locator(f'[data-jobfill-id="{refs[str(value)]}"]')
            if button.get_attribute("aria-pressed") != "true":
                button.click(timeout=5000)
            if button.get_attribute("aria-pressed") != "true":
                return False, f"could not press {value!r}"
        elif kind in ("radio", "checkbox") and f.get("option_refs"):
            wanted = value if isinstance(value, list) else [value]
            refs = dict((label, ref) for label, ref in f["option_refs"])
            missing = [w for w in wanted if w not in refs]
            if missing:
                return False, f"no option {missing}"
            for w in wanted:
                if not _click_choice(frame, refs[w]):
                    return False, f"could not select {w!r}"
        elif kind == "checkbox":
            on = value is True or str(value).strip().lower() in ("yes", "true", "1")
            if on != loc.is_checked():
                if not _click_choice(frame, f["id"]) and on:
                    return False, "could not tick the box"
        elif kind == "combobox":
            ok, note = _fill_combobox(frame, loc, f["id"], value)
            if not ok:
                return ok, note
        else:
            loc.fill(str(value), timeout=5000)
            loc.dispatch_event("blur")
        if after:
            after(frame, f, value)
        return True, ""
    except Exception as e:
        return False, str(e).splitlines()[0][:200]
