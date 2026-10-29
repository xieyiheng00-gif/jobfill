"""Writing playbooks for tier-3 answers: the technique a strong answer to each kind of open question uses.

A tier-3 question names its playbook (``ai(..., playbook="star")``). The resolver sends the agent only
the playbooks of the questions on the current form, together with STYLE and CHECKLIST, so the prompt
stays small. Learned questions without one get a default from their category (DEFAULT_BY_CATEGORY).

Each playbook has:

structure  the parts of the answer, in order
length     what a reviewer expects when the form sets no limit (a form limit always wins)
avoid      what makes an answer read as weak, generic or untrue
"""

STYLE = [
    "Answer the question in the first sentence; no warm-up ('Great question', 'I am writing to').",
    "First person, active voice. 'I' for the candidate's own actions, 'we' only for team results.",
    "Specific nouns and real numbers from `candidate` beat adjectives; one strong example beats three thin ones.",
    "Echo one or two key terms from the posting where they are true of the candidate.",
    "Plain prose: no headings, bullets or markdown unless the question asks for a list.",
    "No filler or cliches (passionate, hard-working, team player, fast-paced, results-driven, synergy, "
    "'I believe I would be a great fit').",
    "Tone follows `candidate.writing_style` when set; otherwise confident, warm and concise.",
]

CHECKLIST = [
    "The first sentence answers the exact question asked.",
    "Every claim traces to `candidate`, the posting, or a company source you verified.",
    "The playbook's structure is followed and the length fits the field.",
    "`python -m jobfill answer check` reports no issues; fix them before recording.",
]

PLAYBOOKS = {
    "why_company": {
        "structure": "Hook: one specific, verifiable thing about the company (product, technical choice, mission "
                     "line, recent launch) -> why it matters to the candidate, tied to a real project or experience "
                     "-> what they would contribute or build there.",
        "length": "80-150 words",
        "avoid": "Praise any company could get ('industry leader', 'great culture'); perks or pay as the reason; "
                 "restating the posting back to them.",
    },
    "why_role": {
        "structure": "The role's core responsibility (from the posting) in the candidate's words -> one or two real "
                     "experiences that prepared them for exactly that -> what they want to learn or own in it.",
        "length": "80-150 words",
        "avoid": "Generic career talk; walking through every requirement; reasons that fit any job.",
    },
    "fit": {
        "structure": "The two or three posting requirements the candidate meets best -> for each: the claim, one "
                     "concrete proof (project, number, outcome) and why it matters here -> one closing line of fit.",
        "length": "120-200 words",
        "avoid": "Traits with no proof; repeating the resume line by line; raising gaps nobody asked about.",
    },
    "about_you": {
        "structure": "Present: who they are now (role or studies, focus) -> Past: the one or two experiences that best "
                     "prove they can do this job, with a real number -> Future: what they want next and why this "
                     "role is that step.",
        "length": "80-150 words",
        "avoid": "A life story in date order; personal details not in `candidate`; a list of adjectives.",
    },
    "cover_letter": {
        "structure": "Opening: the role, and one specific reason for this company -> one or two paragraphs, each "
                     "proving a key requirement with a real example -> close: what they would bring, and interest "
                     "in a conversation.",
        "length": "250-400 words in three or four short paragraphs",
        "avoid": "'I am writing to apply for'; retelling the resume; flattery; placeholders.",
    },
    "star": {
        "structure": "Situation and Task in one or two sentences (the stakes, the candidate's responsibility) -> "
                     "Action is most of the answer: the candidate's own decisions and steps, with their reasoning "
                     "-> Result: the real number or concrete outcome -> one line on what they learned or now do "
                     "differently.",
        "length": "150-250 words (roughly 10% situation, 10% task, 60% action, 20% result)",
        "avoid": "'We' hiding what the candidate did; a story with no result; blaming others; a hypothetical "
                 "instead of a real stored story.",
    },
    "project": {
        "structure": "What it is and who it was for -> the hardest problem or key decision, with the trade-off "
                     "considered -> what the candidate personally built or decided -> the result (number, users, "
                     "adoption) -> why it is relevant to this role.",
        "length": "120-200 words",
        "avoid": "A tech-stack list with no purpose; claiming the lead on team work; results that are not stored.",
    },
    "learning": {
        "structure": "Gap: what they learned and why they needed it -> Method: how they learned it (source, practice, "
                     "how fast) -> Proof: where they applied it and what changed -> Next: how it carries into this "
                     "role.",
        "length": "100-180 words",
        "avoid": "'I am a fast learner' with no example; a textbook explanation of the topic; something unrelated "
                 "to the role unless the question invites it.",
    },
    "strengths": {
        "structure": "Two or three strengths this posting needs -> each with one real example and its result -> how "
                     "it would show up in this role.",
        "length": "80-150 words",
        "avoid": "Generic traits without proof; more than three strengths.",
    },
    "weakness": {
        "structure": "A real, specific growth area that is not core to this role -> one brief moment where it showed "
                     "-> the concrete steps taken since -> evidence of progress.",
        "length": "60-120 words",
        "avoid": "Humblebrags ('perfectionist', 'I work too hard'); a weakness that disqualifies them for the role; "
                 "no sign of progress.",
    },
    "goals": {
        "structure": "Near term: what they want to master or deliver in this role -> longer term: the direction it "
                     "builds toward -> why this company is the right place for that path.",
        "length": "60-120 words",
        "avoid": "Titles at other companies; goals that suggest leaving soon; vague 'grow as a person'.",
    },
    "plan": {
        "structure": "Learn: the people, systems, users and the team's priorities -> Contribute: a first modest, "
                     "concrete win tied to the posting's responsibilities -> Own: an area they would take on by the "
                     "end. Be humble about what cannot be known from outside.",
        "length": "100-180 words",
        "avoid": "Promising big changes; criticizing how things are done now; generic onboarding talk.",
    },
    "values": {
        "structure": "The value or motivation in plain words -> one concrete moment from `candidate` where it showed "
                     "(what they did) -> how it connects to this company's stated values or work.",
        "length": "80-150 words",
        "avoid": "Abstract statements with no moment behind them; claiming an identity, background or "
                 "demographic trait that `candidate` does not state.",
    },
    "explain": {
        "structure": "A one-sentence plain definition -> an everyday analogy -> why it matters to the listener -> "
                     "optionally, where the candidate used it.",
        "length": "80-150 words",
        "avoid": "Unexplained jargon; condescension; a lecture longer than the field.",
    },
    "opinion": {
        "structure": "A clear pick or position -> why, from the candidate's own use of it -> one honest limit or "
                     "trade-off -> what it means for work like this role's.",
        "length": "80-150 words",
        "avoid": "Hype; naming tools or methods the candidate has not used. For AI use: concrete tasks, how the "
                 "output is checked, and where they choose not to use it.",
    },
    "process": {
        "structure": "The principle behind the approach -> the steps in order (understand, break down, try, verify) "
                     "-> a real example where it worked, with the result.",
        "length": "100-180 words",
        "avoid": "Abstract steps with no example; a process the candidate's stored work does not show.",
    },
    "candid": {
        "structure": "One or two factual sentences of context, without apology -> what they did or learned in that "
                     "time, if true -> forward focus: why this role is the next step.",
        "length": "40-100 words",
        "avoid": "Criticizing a past employer, manager or team; personal or medical details; any reason the "
                 "candidate did not give (ask them instead).",
    },
    "distinctive": {
        "structure": "The single most distinctive true thing (an unusual mix of skills, a rare experience, a result "
                     "with a number) -> one concrete situation that shows it -> why it matters to this employer.",
        "length": "60-120 words",
        "avoid": "Claims every candidate makes ('hard-working', 'curious').",
    },
    "short": {
        "structure": "Draft three versions, count characters with code, and keep the one that names the "
                     "candidate's real work and this employer's problem.",
        "length": "the field's limit, else one sentence of 15-30 words",
        "avoid": "Adjectives only; a slogan with no fact in it.",
    },
    "light": {
        "structure": "One or two genuine interests from `candidate`, each with a specific detail (what, how long, a "
                     "small achievement) -> optionally one line on how it shows in their work.",
        "length": "30-80 words",
        "avoid": "Invented hobbies; forced links to the job.",
    },
    "ask": {
        "structure": "One thoughtful question about the team's work, priorities or how success is measured, "
                     "informed by the posting.",
        "length": "one or two sentences",
        "avoid": "Questions the posting already answers; pay or perks.",
    },
    "direct": {
        "structure": "Answer directly in the first sentence -> support it with one concrete piece of evidence from "
                     "`candidate` -> connect it to this role in one sentence.",
        "length": "60-150 words",
        "avoid": "Padding; restating the question; claims the data cannot support.",
    },
}

DEFAULT_BY_CATEGORY = {"behavioral": "star", "motivation": "why_role"}
DEFAULT_PLAYBOOK = "direct"


def playbook_for(ai: dict, category: str | None) -> str:
    """The playbook a tier-3 answer spec uses: its own, else the default for its category."""
    name = ai.get("playbook")
    if name in PLAYBOOKS:
        return name
    if ai.get("deliverable") == "file":
        return "cover_letter"
    return DEFAULT_BY_CATEGORY.get(category or "", DEFAULT_PLAYBOOK)
