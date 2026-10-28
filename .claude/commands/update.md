# /update - Keep the profile current

Use when something changed, or periodically before an application push.

Gather everything you need to ask first, then send the candidate ONE numbered message; never ask
one item per turn. Follow-ups for anything left open are also one batched message.

## Something new happened

| Candidate says | Do |
|---|---|
| "I finished a project / started a job / got a certification" | Ask for every missing detail in one numbered message (for projects: role, ownership, outcome with a real number, tech, and whether it makes a good STAR story), write a patch with that one record, `python -m jobfill import <patch>` dry run, then `--apply`. Offer a STAR story if it is a strong example. |
| "Here's my updated resume" | Save it in `documents/resume/` and run `/setup` Path A. The import is idempotent: unchanged items are skipped, changed ones come back as conflicts, listed with everything else in setup's single questionnaire. |
| "My visa / work authorization changed" | Update `work_auth.*` facts (`us_status`, `requires_sponsorship_now`, `requires_sponsorship_future`, `authorized_countries`, `permit_expiry`). Every work-authorization question recalculates from these. |
| "I moved" / new phone or email | `fact set` the contact/address facts. |
| "I learned <skill>" | `python -m jobfill record list skill`, then `record update <id> --file ...` or `record add skill ...`. |
| "I don't want to answer X automatically anymore" | `python -m jobfill fact unset <key>`; forms will ask again each time. |

## Periodic review (tier 2 goes stale)

1. `python -m jobfill status` lists **Due for review** facts (salary, start date, locations,
   resume path, ...), each with its own review interval.
2. Check `python -m jobfill pending`; classify open items with the `/learn` rules. Note the prompt of
   every new fact you define there.
3. Send ONE numbered message: each stale fact with its current value (`fact get <key>`), asking
   "still right? reply ok or the new value", followed by the prompts of the new facts from step 2.
   - "ok": `python -m jobfill fact confirm <key>` (resets the review clock).
   - New value: `python -m jobfill fact set <key> "<new value>"`.

Every change is kept in history: `python -m jobfill fact history <key>`.
