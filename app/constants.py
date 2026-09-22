"""Shared vocabulary used across order ingestion, employee matching
(Phase 2), and AI classification (Phase 3). One list so all three layers
agree on what a "skill" is -- an LLM extracting something outside this
list is a bug to catch (see app/classification.py's post-filtering), not
a new skill to silently accept.
"""

SKILL_POOL = [
    "electrical",
    "plumbing",
    "hvac",
    "carpentry",
    "welding",
    "painting",
    "general_repair",
    "inspection",
]
