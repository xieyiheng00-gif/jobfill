# /learn - Teach the question bank new questions

When a form asks something the bank did not recognize, `resolve` puts it in the pending queue.
Each one you classify becomes plain Python next time, for every company. Run this during `/fill`
(inline) or in batches.

`python -m jobfill pending` lists open items with `label`, `field_type`, `options`, how often it was
seen, and fuzzy `candidates`.

## Decision rules (in order)

1. **Rephrasing of a known question** (same meaning, same answer). Confirm with
   `python -m jobfill match "<label>"` and `python -m jobfill question show <id>`, then:
   `python -m jobfill learn <pending_id> --alias-of <question_id>`
   For a family of phrasings with a variable part (a skill, a country, a company), add a regex instead:
   `--pattern "<regex over normalized text>" --priority 4`. Normalized text is lowercase with
   punctuation and apostrophes removed; the company becomes `{company}`; named groups (e.g.
   `(?P<skill>...)`) become arguments of the question's rule. Prefer a plain alias when in doubt.

2. **New reusable fact** - the answer is the same for every company (e.g. "Do you have a CFA
   charter?", "T-shirt size", "Are you willing to work weekends?").
   - Pick the tier: **1** if it essentially never changes (identity, legal, demographic,
     credentials held); **2** if it changes over months (preferences, availability, skills).
   - `python -m jobfill fact define <category.name> --tier <1|2> --type <bool|string|text|number|date|list|enum> --label "..." --prompt "<question to ask the candidate>" [--choices <choice set>] [--review-days N]`
     (`enum` needs an existing choice set from `jobfill/catalog/choices.py`; otherwise use `string`.)
   - `python -m jobfill learn <pending_id> --new-question <snake_case_id> --fact <category.name> --category <category>`
   - Do not ask right away: add the fact's prompt to the single batched question message
     (`/fill` step 3b, `/update` step 3, or one message at the end of a batch run), then
     `python -m jobfill fact set <category.name> "<value>"`.

3. **Must be written per application** - the honest answer depends on the company or role, or a
   stored text pasted into two applications would look templated ("What would you build in your
   first 90 days?", "Which of our values resonates with you?"). This is **tier 3**:
   `python -m jobfill learn <pending_id> --new-question <id> --ai <unique|adapt> --scope <company|application> --context summary,experience,projects,skills --guidance "<one sentence on what a good answer does>"`
   - `unique`: written from facts + posting. `adapt`: tailors stored stories/summary.
   - `scope company`: may be reused when the same company asks again; `application`: never reused.
   - Context keys: `summary, motivations, career_goals, strengths, weaknesses, work_style,
     interests, education, experience, experience_full, projects, projects_full, skills, stories`.
     List only what the answer needs; fewer keys = fewer tokens on every future use.

4. **Noise** (captcha labels, layout text, duplicate hidden inputs):
   `python -m jobfill learn <pending_id> --ignore --reason "<why>"`

When unsure between tier 2 and tier 3, choose tier 3. When unsure whether two questions are the
same, check whether a single stored answer would be truthful for both; if not, they are different.

## Sharing what was learned

`python -m jobfill catalog export-learned --out data/learned_catalog.json` exports only learned
questions, phrasings and fact definitions (no personal values). Another install imports it with
`python -m jobfill catalog import-learned <file>`. Questions that prove common belong in the
built-in bank: add them to `jobfill/catalog/questions.py` with a test case in
`tests/test_matcher.py`.
