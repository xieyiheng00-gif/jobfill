"""Where the candidate is in a multi-page application, so jobfill follows them instead of undoing their work.

The candidate shares the window with jobfill: they may answer questions themselves, click Next before
jobfill does, or go Back to check an earlier page. jobfill keeps the pages of each application in the
order they were reached (``state["pages"]``) and, before it fills, sets a field, clicks Next or
submits, places the page shown in the window:

current  the furthest page reached: work on it
new      a page not seen before: the candidate (or jobfill's Next) moved on; fill it, keeping their answers
earlier  a page before the furthest one: the candidate went back to check something; jobfill pauses
         until they return to the furthest page or move on

A page is known by its step title (the current step of a progress bar, when the system shows one) and
by the labels of its questions. Follow-up questions that appear on a page do not make it another page.
"""

from __future__ import annotations

from ..text import normalize
from .forms import extract

SAME_PAGE = 0.6      # share of the smaller page's question labels two readings must have in common
SETTLE_TRIES = 5     # a page still loading after a click shows no questions yet: wait up to this many seconds

STEP_JS = r"""(selector) => {
  for (const e of document.querySelectorAll(selector)) {
    if (e.getClientRects().length) return (e.innerText || e.textContent || "").replace(/\s+/g, " ").trim();
  }
  return "";
}"""


def read(page, adapter) -> dict:
    """The page in the window: its step title, question labels and address."""
    frame = adapter.frame(page)
    title = ""
    if adapter.step_selector:
        try:
            title = frame.evaluate(STEP_JS, adapter.step_selector)[:120]
        except Exception:
            title = ""
    fields = extract(frame, adapter.root_selector, read_options=False)
    labels = sorted({n for f in fields if (n := normalize(f["label"]))})
    return {"title": title, "labels": labels, "url": page.url.split("#")[0]}


def blank(info: dict) -> bool:
    return not info["title"] and not info["labels"]


def settle(page, adapter) -> dict:
    """Read the page, giving one that is still loading (no questions, no title yet) a few seconds."""
    info = read(page, adapter)
    for _ in range(SETTLE_TRIES):
        if not blank(info):
            break
        page.wait_for_timeout(1000)
        info = read(page, adapter)
    return info


def same(a: dict, b: dict) -> bool:
    if a.get("title") and b.get("title"):
        return a["title"] == b["title"]
    la, lb = set(a.get("labels") or ()), set(b.get("labels") or ())
    if la and lb:
        return len(la & lb) / min(len(la), len(lb)) >= SAME_PAGE
    return not la and not lb and a.get("url") == b.get("url")


def locate(pages: list[dict], info: dict) -> tuple[str, int]:
    """("current" | "new" | "earlier", index of the page in ``pages``)."""
    if not pages:
        return "new", 0
    hits = [i for i, p in enumerate(pages) if same(p, info)]
    if not hits:
        return "new", len(pages)
    i = hits[-1]   # two similar pages: the later one, so a look-alike never reads as going back
    return ("current" if i == len(pages) - 1 else "earlier"), i


def remember(pages: list[dict], where: str, index: int, info: dict) -> None:
    if where == "new":
        pages.append(info)
        return
    p = pages[index]
    p["labels"] = sorted(set(p["labels"]) | set(info["labels"]))   # follow-up questions join the page
    p["title"] = p["title"] or info["title"]
    p["url"] = info["url"]


def position(pages: list[dict], index: int) -> dict:
    out = {"n": index + 1, "of": max(len(pages), index + 1)}
    if index < len(pages) and pages[index].get("title"):
        out["title"] = pages[index]["title"]
    return out
