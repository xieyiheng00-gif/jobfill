"""Plain-Python checks on a written (tier-3) answer before it is recorded.

They catch what a reviewer rejects on sight and what code checks better than a model does: limits,
leftover placeholders, another company's name carried over from an earlier application, near-copies
of an answer written for another company, cliches, and markdown in a plain text field.

Each issue has a level:

fix     the answer must not be submitted like this
review  usually a weakness; fix it unless the question calls for it
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .text import company_key, normalize

CLICHES = [
    "passionate about", "hard working", "hardworking", "team player", "fast paced", "detail oriented",
    "results driven", "go getter", "self starter", "think outside the box", "synergy", "dynamic environment",
    "i believe i would be a great fit", "i would be a great fit", "i am writing to apply", "i am writing to express",
    "to whom it may concern", "great question", "i am thrilled", "delve", "tapestry", "testament to",
    "as an ai", "i hope this finds you", "perfectionist", "i work too hard", "leverage my skills", "cutting edge",
    "world class", "wear many hats", "hit the ground running",
]

# Questions about the company itself: an answer that never names it is usually generic.
COMPANY_QUESTIONS = {"why_company", "interest_product", "know_company", "company_values", "cover_letter_text",
                     "cover_letter_file"}

PLACEHOLDER = re.compile(r"\[[^\]\n]{1,40}\]|\{[^}\n]{1,40}\}|<[A-Za-z][^<>\n]{0,38}>|\b(TODO|TBD|XXX+)\b|"
                         r"lorem ipsum", re.I)
MARKDOWN = re.compile(r"^\s*(#{1,6}\s|[-*•]\s|\d+[.)]\s)|\*\*[^*\n]+\*\*", re.M)
COPY_RATIO = 0.6   # this similar to an answer written for another company reads as reused


def mentions(norm: str, phrase: str) -> bool:
    """Whole-word match on normalized text; a possessive ("Stripe's" -> "stripes") counts."""
    return re.search(rf"(^| ){re.escape(phrase)}s?( |$)", norm) is not None


def check_answer(text: str, *, question_id: str | None = None, company: str | None = None,
                 max_chars: int | None = None, max_words: int | None = None, min_words: int | None = None,
                 other_companies: tuple[str, ...] | list[str] = (), earlier: list[dict] = ()) -> dict:
    """``other_companies``: names that must not appear (other applications, minus the candidate's own
    employers and schools). ``earlier``: answers written for other companies, as {"company", "value"}."""
    issues: list[dict] = []

    def add(level: str, message: str) -> None:
        issues.append({"level": level, "message": message})

    text = text.strip()
    norm = normalize(text)
    chars, words = len(text), len(text.split())

    if max_chars and chars > max_chars:
        add("fix", f"{chars} characters, over the limit of {max_chars}: cut {chars - max_chars}")
    if max_words and words > max_words:
        add("fix", f"{words} words, over the limit of {max_words}: cut {words - max_words}")
    if min_words and words < min_words:
        add("fix", f"{words} words, under the minimum of {min_words}")
    for m in dict.fromkeys(m.group(0) for m in PLACEHOLDER.finditer(text)):
        add("fix", f"placeholder left in the text: {m}")

    current = company_key(company)
    for name in dict.fromkeys(other_companies):
        key = company_key(name)
        if key and key != current and len(key) >= 3 and mentions(norm, key):
            add("fix", f"names {name}, another company you applied to; this answer is for {company or 'this job'}")
    for e in earlier:
        if company_key(e.get("company")) == current or not isinstance(e.get("value"), str):
            continue
        ratio = SequenceMatcher(None, norm, normalize(e["value"])).ratio()
        if ratio >= COPY_RATIO:
            add("fix", f"{round(ratio * 100)}% the same as the answer written for {e['company']}; "
                       "write it for this company")
            break

    if question_id in COMPANY_QUESTIONS and current:
        first = current.split()[0]
        if not (mentions(norm, current) or (len(first) >= 3 and mentions(norm, first))):
            add("review", f"never names {company}; a company-specific answer usually does")
    found = [c for c in CLICHES if mentions(norm, c)]
    if found:
        add("review", "cliches: " + ", ".join(found) + "; replace each with a concrete fact")
    if MARKDOWN.search(text):
        add("review", "markdown (headings, bullets or bold) in a plain text field")

    return {"ok": not any(i["level"] == "fix" for i in issues), "chars": chars, "words": words, "issues": issues}
