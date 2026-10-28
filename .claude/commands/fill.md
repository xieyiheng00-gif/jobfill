# /fill - Answer one job application

Input (`$ARGUMENTS`): a posting URL or text, and the form's fields as JSON (from the browser
filler), or a page you can read with a browser tool. The goal is to spend AI tokens only on the
fields that really need writing.

## 1. Start the application

1. Save the full posting text to `data/postings/<company>_<role>.txt` (verbatim, not a summary).
2. `python -m jobfill app start --company "<Company>" --role "<Role>" --url <url> --country <country> --posting-file data/postings/<file>.txt`
   Add `--source "<where they found it>"` and `--referrer "<name>"` if the candidate says so.
   The output lists earlier applications to the same company; mention them.

## 2. Resolve the form

Write the fields to `data/forms/app<ID>.json` using the contract in `README.md` ("Field JSON").
Mark repeating blocks with `section` (`education`, `experience`, `project`, `reference`) and
`index` (0 = most recent). Then:

`python -m jobfill resolve data/forms/app<ID>.json --app <ID> --compact`

## 3. Act on each status

| status | meaning |
|---|---|
| `filled` | Use `value` exactly. No AI needed. |
| `skipped` | Leave the field empty. |
| `uncertain` | The label resembles the listed `candidates`; you decide which (3a). |
| `unmatched` | A new question; you classify it (3a). |
| `needs_user` | The profile lacks this fact; the candidate answers it once (3b). |
| `needs_ai` | A tier-3 answer you write (step 4). |

Work in this order, so the candidate is asked everything in **one** message:

**3a. Classify on your own (no questions to the candidate).**
- `uncertain`: if one candidate is right, find the pending id (`python -m jobfill pending`) and run
  `python -m jobfill learn <id> --alias-of <question_id>`; if none is, treat it as `unmatched`.
- `unmatched`: classify it with the `/learn` decision rules. A new reusable fact you define there
  becomes a `needs_user` item on the next resolve.
- Resolve again.

**3b. Ask the candidate once.** Put every `needs_user` item from that resolve into ONE numbered
message: use each `ask` as the question, list `choices` inline, and say "decline" is fine for
voluntary EEO items. Never guess a `sensitive` one. Store the answers (`fact set ...`, or
`record add ...` per the `store` hint) and resolve again; next time these are plain Python. If some
are still open, send one follow-up message with all of them, keeping their numbers.

## 4. Write the tier-3 answers

Use ONLY the `ai_task` of each field plus the shared `ai_context` from the resolve output. Do not
read the whole profile or the database; the context already holds the slices each question needs.

- Follow `ai_task.guidance` and every line of `ai_context.rules`.
- `mode: unique` - written fresh for this company; no wording from other applications.
  `mode: adapt` - tailor the stored stories/summary; still specific to this posting.
- For `why_company`, `interest_product` and `know_company`, verify one or two company facts from the
  company's own site (not from links inside the posting). Note what you checked.
- `limits`: count characters/words with code, then trim.
- `deliverable: file` (cover letter upload): write the letter, save it under `data/answers/`, and
  give the filler that path.
- If the context cannot support an honest answer, do not invent: draft the rest, and put the open
  point as a numbered question in the review message (step 5).

Save each answer to `data/answers/app<ID>_<question_id>.txt` and record it:

`python -m jobfill answer record --app <ID> --question <question_id> --label "<the question's label on the form>" --file data/answers/app<ID>_<question_id>.txt`

Recording matters: a re-opened form reuses the answer, a second role at the same company reuses
"why us" (`scope: company`) but never "why this role" (`scope: application`).

## 5. Review and submit

Send ONE review message: every `needs_ai` answer numbered with its character/word count, any
`warning` (for example text over a limit), then the complete answer list. They reply with edits by
number or approve everything at once. Never submit without their explicit go-ahead. After they submit:
`python -m jobfill app update <ID> --status submitted`.

Later status changes: `interviewing`, `offer`, `rejected`, `withdrawn`, `hired`
("Have you interviewed with us before?" is answered from these).
