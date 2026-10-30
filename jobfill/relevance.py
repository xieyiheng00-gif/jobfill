"""Which parts of the candidate's real background a posting is about, chosen in plain Python.

"Why us?", "Why this role?", "What do you know about our product?" and "Why are you leaving?" should be
written from the experience that matters to this job, not from the whole profile. This matches the stored
skills, experience, projects and stories against the saved posting (or, without one, the role title):

  matched_skills  stored skills (and tools listed on jobs or projects) the posting names, most experienced first
  evidence        the jobs, projects and stories that use them most, each with what matched and its best lines
  angles          up to three (posting line -> evidence) pairs: one example answer is written per angle
  company_lines   posting sentences about the company itself (product, mission, customers)

Nothing is invented here: every item is a stored record or a line of the posting.
"""

from __future__ import annotations

import re
from datetime import date

from .derive import is_current, lacks_skill
from .text import content_tokens, normalize, phrase_in

COMPANY_WORDS = re.compile(r"\b(mission|vision|product|products|platform|customers?|clients?|users?|we build|we are|"
                           r"our team|founded|million|billion|world|industry|leader|helps?|enable|serve)\b", re.I)
MAX_EVIDENCE = 4
MAX_ANGLES = 3


def _lines(posting: str) -> list[str]:
    """The posting as sentences and bullet lines of a readable length."""
    parts = re.split(r"[\n\r]+|(?<=[.!?])\s+|\s[•·▪●]\s", posting or "")
    out = []
    for p in parts:
        p = re.sub(r"^[\s•·▪●*\-–—]+", "", p).strip()
        if 4 <= len(p.split()) <= 45 and p not in out:
            out.append(p)
    return out


def _skill_names(r: dict) -> list[str]:
    return [r["name"], *(r.get("aliases") or [])]


def _span(r: dict) -> str:
    start, end = r.get("start_date") or "", r.get("end_date") or ""
    return f"{start} - {end or 'present'}" if start else ""


def _describe(kind: str, r: dict) -> tuple[str, str, list[str], list[str]]:
    """(what it is, all its text, its listed skills, its detail lines) for a stored record."""
    if kind == "experience":
        what = f"{r.get('title')}, {r.get('company')}" + (f" ({_span(r)})" if _span(r) else "")
        detail = [r.get("summary", ""), *(r.get("highlights") or [])]
        listed = r.get("skills") or []
    elif kind == "project":
        what = f"Project: {r.get('name')}" + (" (coursework)" if r.get("is_coursework") else "")
        detail = [r.get("summary", ""), r.get("description", ""), *(r.get("highlights") or []),
                  *(r.get("metrics") or [])]
        listed = r.get("tech") or []
    else:   # story
        what = f"Story: {r.get('title')}" + (f" ({r['source']})" if r.get("source") else "")
        detail = [r.get(k, "") for k in ("situation", "action", "result")]
        listed = []
    detail = [d for d in detail if d]
    return what, " ".join([what, *detail, *listed]), listed, detail


def match(store, app: dict | None, today: date | None = None) -> dict:
    """Python's pick of what to write about for this application (see the module docstring)."""
    today = today or date.today()
    posting = (app or {}).get("posting") or ""
    role = (app or {}).get("role") or ""
    company = (app or {}).get("company") or ""
    target = normalize(f"{role}\n{posting}")
    words = content_tokens(target)

    skills = sorted((r for r in store.records("skill") if not lacks_skill(r)), key=lambda r: -(r.get("years") or 0))
    records = [(kind, r, *_describe(kind, r)) for kind in ("experience", "project", "story") for r in store.records(kind)]
    # The candidate's vocabulary: skill records (with aliases), then tools listed on a job or project.
    vocab: dict[str, tuple[str, list[str], int | None]] = {}
    for r in skills:
        vocab.setdefault(normalize(r["name"]), (r["name"], _skill_names(r), r.get("years")))
    for _, _, _, _, listed, _ in records:
        for t in listed:
            vocab.setdefault(normalize(t), (t, [t], None))
    matched = [v for v in vocab.values() if any(phrase_in(normalize(n), target) for n in v[1])]
    matched_names = [name for name, _, _ in matched]

    scored = []
    for kind, r, what, text, listed, detail in records:
        ntext = normalize(text)
        uses = [name for name, names, _ in matched if any(phrase_in(normalize(n), ntext) for n in names)]
        overlap = len((content_tokens(ntext) & words) - {normalize(company)})
        score = 3 * len(uses) + min(overlap, 8) * 0.5
        if kind == "experience" and is_current(r, today):
            score += 0.5
        if score <= 0:
            continue
        # Its lines that carry the match first: these are what an example answer quotes from.
        best = sorted(detail, key=lambda d: -sum(phrase_in(normalize(u), normalize(d)) for u in uses))[:2]
        scored.append((score, {"kind": kind, "what": what, "matched": uses, "lines": best}))
    scored.sort(key=lambda x: -x[0])
    evidence = [e for _, e in scored[:MAX_EVIDENCE]]

    lines = _lines(posting)
    angles, used = [], set()
    for e in evidence:
        terms = {normalize(u) for u in e["matched"]} | (content_tokens(normalize(" ".join(e["lines"]))) & words)
        ranked = sorted((l for l in lines if l not in used),
                        key=lambda l: -sum(phrase_in(t, normalize(l)) for t in terms))
        hook = ranked[0] if ranked and any(phrase_in(t, normalize(ranked[0])) for t in terms) else None
        if hook:
            used.add(hook)
        angles.append({"posting": hook or (f"The {role} role" if role else None), "evidence": e["what"],
                       "skills": e["matched"]})
        if len(angles) == MAX_ANGLES:
            break

    out = {"matched_skills": [name + (f" ({years}y)" if years else "") for name, _, years in matched],
           "evidence": evidence, "angles": angles}
    co = normalize(company)
    company_lines = [l for l in lines if COMPANY_WORDS.search(l) or (co and phrase_in(co, normalize(l)))][:5]
    if company_lines:
        out["company_lines"] = company_lines
    if not posting:
        out["note"] = (f"No posting is saved for this application, so this was matched on the role title only. "
                       f"Save the job description (`python -m jobfill app update --id {(app or {}).get('id', '<id>')} "
                       "--posting-file <file>`) and ask again for answers tied to it.")
    if not matched_names and not evidence:
        out["note"] = (out.get("note", "") + " Nothing stored matches this job yet: ask the candidate which "
                       "experience they want to talk about instead of writing a generic answer.").strip()
    return out
