"""jobfill: a tiered answer database for job application forms.

Plain Python answers the questions it knows (tier 1 static facts, tier 2
evolving facts and records). Only tier-3 questions ("why this company?") and
genuinely new questions go to an AI agent, with a compact context.
"""

__version__ = "0.1.0"
