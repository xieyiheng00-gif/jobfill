# /apply <job URL> - Fill a job application

`$ARGUMENTS` is the job posting URL. Plain Python decides the application system and fills every
field the database can answer; you spend tokens only on what is left. Never submit without the
candidate's explicit go-ahead in chat.

If `$ARGUMENTS` is empty, ask for the job URL and stop.

## Step 1: Detect the system (no AI, no browser)

`python -m jobfill apply start "<url>"` (add `--source "<where they found it>"` and
`--referrer "<name>"` if the candidate mentioned them). Act on the result:

| Result | Do |
|---|---|
| exit code 3, `"error": "Not a job posting: ..."` | Reply with that error in one line and stop. |
| `handler: "unsupported"` (Workday) | Reply: "This job uses Workday, which needs an account login; jobfill does not support it yet. Please apply manually: <url>". Stop. |
| `handler: "follow"` (LinkedIn, Indeed, ...) | Open the URL in the built-in browser, find the employer's own apply link (not Easy Apply), and run `apply start` again with that link. If there is none (Easy Apply only), say so and stop. |
| `handler: "agent_check"` | The HTML alone could not tell. Open it in the built-in browser and read the text (`get_page_text`). Not a job posting: reply with the error and stop. A job: look at where "Apply" leads or which iframe holds the form; rerun `apply start` with that apply URL, or with `--ats custom --company "<Company>" --role "<Role>"` for a company portal. |
| `handler: "python"` (Greenhouse, Lever, iCIMS, Ashby) | Step 2. |
| `handler: "ai"` (Amazon, TikTok, Google, other portals and ATSs) | Step 3. |

The output includes `app_id`, company, role, and earlier applications to the same company
(mention those). The posting text is saved for tier-3 answers.

## Step 2: Python filler (Greenhouse, Lever, iCIMS, Ashby)

1. `python -m jobfill apply fill --app <ID>` opens a visible Chromium window (it stays open between
   commands), fills the form from the database, re-reads it for follow-up questions, and prints what
   is left:
   - `blockers: ["login_required"]` - iCIMS wants an account. Tell the candidate to sign in or create
     the account in that window themselves (never type a password), then rerun `apply fill`.
   - `blockers: ["consent_required"]` - the page wants terms/privacy accepted before continuing and the
     candidate has no standing `consent.privacy_ack`. Ask them; if they agree, they tick it in the window
     (or set the fact for the future), then rerun `apply fill`.
   - `blockers: ["job_closed"]` - tell the candidate the posting is closed; stop.
   - `uncertain` / `unmatched` - classify with the `/learn` rules (no questions to the candidate).
     Exception: agreements, policies and consents (arbitration, AI-use policies, AI notetakers or
     recordings, terms, background-check authorizations) are the candidate's decision. Put them in the
     batched question message with the exact wording; only if they want a standing answer, define a
     `consent.*` fact and learn the question onto it.
   - `needs_user` - collect them (plus prompts of facts you just defined) into ONE numbered message;
     store the answers (`fact set`, `record add`).
   - `needs_ai` - write each answer from its task and the shared `ai_context` exactly as in `/fill`
     step 4, save it to `data/answers/app<ID>_<question_id>.txt`, and record it:
     `python -m jobfill answer record --app <ID> --question <question_id> --label "<the question's label on the form>" --file data/answers/app<ID>_<question_id>.txt`
   - `fill_failed` - usually a custom widget. Retry with
     `python -m jobfill apply set --app <ID> --field <field> --value "<value>"` (`--json` for lists),
     or ask the candidate to fix it in the window.
2. Run `python -m jobfill apply fill --app <ID>` again. Stored facts and recorded answers now fill
   the remaining fields; values already in the form are kept (`--overwrite` replaces them).
   One-off questions not worth learning: `apply set` with the answer.
3. Multi-page forms (iCIMS): when a page is done, `python -m jobfill apply next --app <ID>` clicks
   Next/Continue (it never clicks a final submit), then `apply fill` again for the new page.
4. Review, in ONE message: every written answer (numbered, with character/word count), any
   `fill_failed` you could not fix, and a reminder that the window shows the whole filled form.
   Ask them to check the window, then to say "submit" or list changes.
5. Only after an explicit "submit" (or equivalent) from the candidate:
   `python -m jobfill apply submit --app <ID> --confirm`. A CAPTCHA (`blockers: ["captcha"]`) is for
   the candidate to solve in the window; then run submit again. When `submitted` is true the
   application status becomes `submitted`. If they prefer, they click Submit themselves; then run
   `python -m jobfill app update <ID> --status submitted`.

## Step 3: Agent fills in the built-in browser (company portals, other systems)

Plain Python still answers the questions; you drive the page.

1. `navigate` to the URL in the built-in browser (`mcp__Claude_Browser__*`). Click Apply. Sign-in or
   account creation pages are for the candidate: ask them to do it in the browser pane, then continue.
2. For each form page:
   - Read only the controls: `read_page` with `filter: "interactive"`. Avoid screenshots unless the
     page is unreadable.
   - Write `data/forms/app<ID>_p<N>.json` in the field JSON format from `README.md` (label, type,
     options, required, `section`/`index` for repeated education/experience blocks, max length).
     Use the field's `ref` as its `id`.
   - `python -m jobfill resolve data/forms/app<ID>_p<N>.json --app <ID> --compact`, then handle
     statuses exactly as in Step 2 (classify, one batched question message, written answers recorded
     with `answer record`), and resolve again.
   - Enter every `filled` value with `form_input` (by ref) or `computer` clicks for custom dropdowns.
   - File uploads: if the browser cannot attach the file, ask the candidate to attach the resume
     (path: `python -m jobfill fact get documents.resume_path`) in the browser pane.
   - Click Next / Continue to move on. Never click the final submit button on your own.
3. Review and submit as in Step 2.4-2.5: one review message, explicit go-ahead, then click Submit (or
   the candidate does), then `python -m jobfill app update <ID> --status submitted`.

## Step 4: The result record

Every question on the form is saved for the application as it is handled: the question, the
answer, who answered it (the profile via plain Python, the AI, or the candidate), and whether
jobfill typed it in. `apply fill`, `apply set`, `answer record`, `apply submit` and
`app update --status` keep `data/applications/app<ID>_<company>_<role>.md` (and `.json`) current.

When the application is done (submitted, or abandoned with `app update <ID> --status withdrawn`):
- End with one line linking that Markdown file and its result line, e.g. "31 of 36 answered
  questions came from your profile with no AI (86%); 3 written by AI; 2 by you."
- `python -m jobfill app report <ID>` rewrites it on demand (`--print` shows it);
  `python -m jobfill app stats` shows the totals across all applications.

## Rules

- Answers come from `jobfill resolve` / `apply fill`; never type facts from memory or from the
  documents directly. Missing facts are asked once and stored.
- Never type passwords, never solve CAPTCHAs, never accept terms the candidate has not agreed to
  (`consent.*` facts record their standing choices).
- When finished: `python -m jobfill apply close` closes the jobfill browser window (it otherwise
  stays open for the next application, keeping any logins).
