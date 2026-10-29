"""Record kinds: repeating, list-shaped profile data.

Each kind names the fields an entry may have and the ``key`` fields that
identify "the same entry" when an import patch is merged (so re-importing an
updated resume updates entries instead of duplicating them).

Dates may arrive in any common form (``Sep 2025``, ``9/2025``, ``2025/9``, ``09/01/2025``) and are
stored as ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``; an ``end_date`` of "Present" sets ``current`` /
``expected`` instead. Forms get each date in the format and pieces they ask for. ``end_date`` empty plus
``current: true`` (experience) or ``expected: true`` (education) marks
something ongoing. Index 0 of every kind is the most recent entry.
"""

RECORD_KINDS: dict[str, dict] = {
    "education": {
        "tier": 1,
        "key": ["school", "degree"],
        "fields": {
            "school": "Official institution name",
            "degree": "Degree as written on the diploma, e.g. 'Master of Science'",
            "degree_level": "high_school | some_college | associate | bachelor | master | mba | doctorate | professional",
            "field_of_study": "Major / discipline",
            "minor": "Minor, if any",
            "start_date": "YYYY-MM",
            "end_date": "YYYY-MM (graduation or expected graduation)",
            "expected": "true while the degree is still in progress",
            "gpa": "GPA as written, e.g. 3.8 or 9.1/10",
            "gpa_scale": "e.g. 4.0 (assumed 4.0 when the GPA fits)",
            "gpa_4": "Only if the school uses another scale: the 4.0-scale GPA you want forms to show "
                     "(asked once; jobfill never converts scales itself)",
            "location": "City, State/Country",
            "honors": "Honors / distinctions",
            "coursework": "List of relevant courses",
            "thesis": "Thesis title",
        },
    },
    "experience": {
        "tier": 2,
        "key": ["company", "title", "start_date"],
        "fields": {
            "company": "Employer name",
            "title": "Job title exactly as held",
            "employment_type": "full_time | part_time | internship | contract | temporary",
            "location": "City, State/Country",
            "start_date": "YYYY-MM",
            "end_date": "YYYY-MM, empty if current",
            "current": "true if this is a current job",
            "summary": "One factual sentence about the role",
            "highlights": "List of factual achievement bullets (with numbers where real)",
            "skills": "List of tools/skills used",
            "supervisor": "Manager name (only some forms ask)",
            "may_contact": "true if the employer may be contacted",
            "reason_for_leaving": "Short neutral reason",
        },
    },
    "project": {
        "tier": 2,
        "key": ["name"],
        "fields": {
            "name": "Descriptive project name (not the employer name)",
            "role": "Your role on this project (do not upgrade it)",
            "ownership": "sole | lead | contributor",
            "is_coursework": "true for class projects",
            "start_date": "YYYY-MM",
            "end_date": "YYYY-MM",
            "summary": "One-sentence summary",
            "description": "100-150 words: what it does, hardest problem, outcome",
            "highlights": "List of factual bullets",
            "tech": "List of technologies",
            "metrics": "Measured outcomes only, never estimates",
            "url": "Repo or demo link",
        },
    },
    "skill": {
        "tier": 2,
        "key": ["name"],
        "fields": {
            "name": "Skill name, e.g. Python",
            "aliases": "Other names forms use, e.g. ['py']",
            "category": "language | framework | tool | domain | soft",
            "years": "Years of hands-on experience (number); leave empty if unknown",
            "level": "beginner | intermediate | advanced | expert, or none for a skill the candidate lacks",
            "last_used": "YYYY or 'current'",
        },
    },
    "language": {
        "tier": 1,
        "key": ["name"],
        "fields": {
            "name": "Spoken language, e.g. English",
            "proficiency": "native | fluent | professional | conversational | basic",
        },
    },
    "certification": {
        "tier": 2,
        "key": ["name"],
        "fields": {
            "name": "Certification name",
            "issuer": "Issuing body",
            "date": "YYYY-MM",
            "expires": "YYYY-MM or empty",
            "credential_id": "Credential ID",
            "url": "Verification link",
        },
    },
    "award": {
        "tier": 2,
        "key": ["name"],
        "fields": {"name": "Award", "issuer": "Issuer", "date": "YYYY-MM", "description": "One line"},
    },
    "publication": {
        "tier": 2,
        "key": ["title"],
        "fields": {"title": "Title", "venue": "Journal / conference", "date": "YYYY-MM",
                   "authors": "Author list", "url": "Link"},
    },
    "reference": {
        "tier": 2,
        "key": ["name"],
        "fields": {
            "name": "Full name", "title": "Job title", "company": "Organization",
            "email": "Email", "phone": "Phone", "relationship": "e.g. Former manager",
            "years_known": "Number of years",
        },
    },
    "story": {
        # STAR stories: the base material behavioral answers are tailored from.
        "tier": 2,
        "key": ["title"],
        "fields": {
            "title": "Short name for the story",
            "themes": "List from: failure, conflict, leadership, teamwork, pressure, learning, initiative, "
                      "ambiguity, feedback, accomplishment, challenge, data, customer, influence, adaptability, "
                      "mentoring, ethics, creativity",
            "situation": "Context", "task": "What you had to do", "action": "What YOU did",
            "result": "Outcome, with real numbers", "source": "Which job/project it comes from",
        },
    },
}

STORY_THEMES = ["failure", "conflict", "leadership", "teamwork", "pressure", "learning",
                "initiative", "ambiguity", "feedback", "accomplishment", "challenge",
                "data", "customer", "influence", "adaptability", "mentoring", "ethics", "creativity"]
