"""Map a form label to a question in the bank: exact alias, then regex pattern, then fuzzy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import normalize, similarity

ACCEPT = 0.86      # fuzzy score needed to answer without asking anyone
UNCERTAIN = 0.62   # below this the label is treated as unknown
MARGIN = 0.04      # winner must beat the runner-up (a different question) by this much
STRONG = 3         # patterns at or above this priority run before fuzzy matching

TEXTUAL_TYPES = {"text", "textarea", "string", "input"}
CHOICE_TYPES = {"select", "radio", "checkbox", "multiselect", "combobox"}


@dataclass
class Match:
    status: str                      # exact | pattern | fuzzy | uncertain | none
    question_id: str | None = None
    score: float = 0.0
    params: dict = field(default_factory=dict)
    normalized: str = ""
    candidates: list = field(default_factory=list)   # [(question_id, score)]

    @property
    def matched(self) -> bool:
        return self.status in ("exact", "pattern", "fuzzy")


class Matcher:
    def __init__(self, questions: dict[str, dict], aliases: list[dict]):
        self.questions = questions
        self.exact: dict[str, list[str]] = {}
        self.fuzzy: list[tuple[str, str]] = []
        self.patterns: list[tuple[int, re.Pattern, str]] = []
        for a in aliases:
            if a["question_id"] not in questions:
                continue
            if a["is_pattern"]:
                self.patterns.append((a["priority"], re.compile(a["normalized"]), a["question_id"]))
            else:
                self.exact.setdefault(a["normalized"], []).append(a["question_id"])
                self.fuzzy.append((a["normalized"], a["question_id"]))
        self.patterns.sort(key=lambda p: -p[0])

    @classmethod
    def from_store(cls, store) -> "Matcher":
        return cls(store.questions(), store.aliases())

    # ------------------------------------------------------------------ filters
    def _kind_ok(self, q: dict, field_type: str | None) -> bool:
        ft = (field_type or "text").lower()
        kinds = q.get("kinds")
        if ft == "file":
            return bool(kinds) and "file" in kinds
        if kinds and "file" in kinds and "text" not in kinds:
            return False
        if kinds and ("text" in kinds or "textarea" in kinds):
            # Essay questions never answer a dropdown/checkbox/date/number field.
            return ft in TEXTUAL_TYPES
        return True

    def _guards_ok(self, q: dict, norm: str) -> bool:
        if q["require"] and not any(w in norm for w in q["require"]):
            return False
        return not any(w in norm for w in q["exclude"])

    def _by_section(self, qids: list[str], section: str | None) -> list[str]:
        """Prefer questions of the field's section; unsectioned fields prefer unsectioned questions."""
        if section:
            same = [q for q in qids if self.questions[q]["section"] == section]
            return same or [q for q in qids if self.questions[q]["section"] is None]
        return [q for q in qids if self.questions[q]["section"] is None or self.questions[q]["global_ok"]]

    # ------------------------------------------------------------------ main entry
    def match(self, label: str, *, section: str | None = None, field_type: str | None = None,
              company: str | None = None, role: str | None = None) -> Match:
        norm = normalize(label, company=company, role=role)
        if not norm:
            return Match("none", normalized=norm)

        # 1. exact alias
        hits = [q for q in self.exact.get(norm, []) if self._kind_ok(self.questions[q], field_type)]
        if hits:
            chosen = self._by_section(hits, section)
            if len(set(chosen)) == 1:
                return Match("exact", chosen[0], 1.0, normalized=norm)
            if not chosen:   # only sectioned questions use this alias, field has no section
                return Match("uncertain", normalized=norm, candidates=[(q, 1.0) for q in sorted(set(hits))])
            return Match("uncertain", normalized=norm, candidates=[(q, 1.0) for q in sorted(set(chosen))])

        # 2. specific regex patterns (priority >= STRONG) before fuzzy; catch-alls after it.
        hit = self._pattern(norm, label, section, field_type, strong=True)
        if hit:
            return hit

        # 3. fuzzy similarity over aliases
        scores: dict[str, float] = {}
        for alias, qid in self.fuzzy:
            q = self.questions[qid]
            if not self._kind_ok(q, field_type) or not self._guards_ok(q, norm):
                continue
            s = similarity(norm, alias)
            if s > scores.get(qid, 0.0):
                scores[qid] = s
        allowed = set(self._by_section(list(scores), section)) or set(scores)
        ranked = sorted(((qid, s) for qid, s in scores.items() if qid in allowed), key=lambda x: -x[1])
        top = [(qid, round(s, 3)) for qid, s in ranked[:3] if s >= UNCERTAIN]
        if ranked and ranked[0][1] >= ACCEPT:
            runner = ranked[1][1] if len(ranked) > 1 else 0.0
            if ranked[0][1] - runner >= MARGIN:
                return Match("fuzzy", ranked[0][0], round(ranked[0][1], 3), normalized=norm, candidates=top)
        hit = self._pattern(norm, label, section, field_type, strong=False)
        if hit:
            return hit
        if top:
            return Match("uncertain", normalized=norm, candidates=top)
        return Match("none", normalized=norm)

    def _pattern(self, norm: str, label: str, section, field_type, strong: bool) -> Match | None:
        for priority, rx, qid in self.patterns:
            if (priority >= STRONG) != strong:
                continue
            q = self.questions[qid]
            if not self._kind_ok(q, field_type) or not self._guards_ok(q, norm):
                continue
            if section and q["section"] not in (None, section):
                continue
            m = rx.search(norm)
            if m:
                params = {k: _original_case(v.strip(), label) for k, v in m.groupdict().items() if v and v.strip()}
                return Match("pattern", qid, 0.95, params=params, normalized=norm)
        return None


def _original_case(value: str, label: str) -> str:
    """Recover 'Rust' / 'C++' from the raw label for a param captured from normalized text."""
    if "{" in value:
        return value
    words = [re.escape(w) for w in value.split()]
    m = re.search(r"(?<![A-Za-z0-9])" + r"[^A-Za-z0-9+#]+".join(words) + r"(?![A-Za-z0-9])", label, re.IGNORECASE)
    return m.group(0) if m else value
