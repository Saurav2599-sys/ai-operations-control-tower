"""Phase 3: LLM-based classification of free-text order descriptions into
the structured fields Phase 1/2 already understand (required_skills,
priority) -- but only as a *suggestion* that fills in what's missing,
never as something that overrides what a human already specified. See
"A note on Phase 3's design choices" in the README for why.

Forces the tool call via `tool_choice` rather than hoping the model
decides to use it -- the same lesson learned the hard way building the
Autonomous Workflow Broker project: a system prompt that says "you must
call this tool" is a request the model is free to ignore; `tool_choice`
pinned to the one tool isn't.
"""

import json
import os
from dataclasses import dataclass

from app.constants import SKILL_POOL

DEFAULT_MODEL = os.getenv("OPENAI_CLASSIFICATION_MODEL", "gpt-4o-mini")

_TOOL_NAME = "extract_order_requirements"

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": _TOOL_NAME,
            "description": (
                "Extract the skills required to fulfill a work order, and a "
                "suggested priority, from its free-text description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "required_skills": {
                        "type": "array",
                        "items": {"type": "string", "enum": SKILL_POOL},
                        "description": (
                            "Skills genuinely needed for this job, chosen only "
                            "from the allowed list. Empty array if none apply "
                            "or the description is too vague to tell."
                        ),
                    },
                    "suggested_priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": (
                            "How urgent this reads as, based on the description "
                            "alone (e.g. safety hazards, complete outages -> "
                            "urgent/high; cosmetic or routine -> low/normal)."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0.0-1.0 confidence in required_skills specifically.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "One sentence explaining the extraction.",
                    },
                },
                "required": [
                    "required_skills",
                    "suggested_priority",
                    "confidence",
                    "reasoning",
                ],
            },
        },
    }
]


@dataclass
class ClassificationResult:
    suggested_skills: frozenset[str]
    suggested_priority: str
    confidence: float
    reasoning: str


class ClassificationError(RuntimeError):
    """Raised when the LLM call fails or returns something unusable.
    Callers are expected to catch this and degrade gracefully -- Phase 3
    is an enrichment layer order ingestion doesn't depend on, not a hard
    dependency. See submit_order() in app/api.py."""


def _get_client():
    # Imported lazily so importing this module doesn't require the
    # `openai` package (or an API key) unless classify_order() is
    # actually called -- tests inject a fake client instead.
    from openai import OpenAI

    return OpenAI()


def classify_order(
    description: str, client=None, model: str = DEFAULT_MODEL
) -> ClassificationResult:
    """Extract required_skills + a suggested_priority from free text.

    Raises ClassificationError on any failure (network, malformed
    response, empty description) rather than returning a fake "confident
    nothing found" result -- a caller silently treating a failed call the
    same as "the model looked and found nothing" would be a worse bug
    than a loud, catchable one.
    """
    if not description or not description.strip():
        raise ClassificationError("empty description")

    try:
        # Client construction belongs inside this try too -- OpenAI() raises
        # immediately (not lazily, on first call) when OPENAI_API_KEY is
        # missing or blank. That's still "the enrichment failed" from a
        # caller's perspective, not a different category of error -- a
        # missing key shouldn't 500 an order submission any more than a
        # network blip should.
        client = client or _get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract structured requirements from operations "
                        "work orders. Be conservative: an empty skills list "
                        "and low confidence is better than guessing."
                    ),
                },
                {"role": "user", "content": description},
            ],
            tools=_TOOLS,
            tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
        )
    except Exception as exc:
        # openai's client raises several distinct exception types
        # (APIError, RateLimitError, APIConnectionError, ...); any of
        # them means "the enrichment failed," which callers handle
        # uniformly by catching ClassificationError.
        raise ClassificationError(f"LLM call failed: {exc}") from exc

    try:
        tool_call = response.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
    except (IndexError, AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise ClassificationError(f"unusable response: {exc}") from exc

    # Defense in depth: an enum-constrained schema is a strong hint, not a
    # hard guarantee. Silently drop anything outside the known skill pool
    # rather than trust it -- a hallucinated skill would make an order
    # unassignable to every real employee without anyone noticing why.
    raw_skills = args.get("required_skills") or []
    skills = frozenset(s for s in raw_skills if s in SKILL_POOL)

    priority = args.get("suggested_priority")
    if priority not in ("low", "normal", "high", "urgent"):
        priority = "normal"

    try:
        confidence = float(args.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    # Defense in depth, round 2: a real work order essentially never needs
    # more than a couple of skills (the eval set's worst case is 2, out of
    # scripts/eval_classification.py's 18 hand-labeled cases). Measured
    # against real runs (see the README's "Phase 3 eval results"), the
    # model has a repeatable failure mode where it returns a majority of
    # the entire pool at once, at high reported confidence -- not because
    # the order is genuinely that complex, but as a schema/parsing quirk.
    # That's not a case to filter values out of (every value is a real
    # pool member) -- it's a case to stop trusting confidence for. Clamp
    # it to 0 so this can never clear CLASSIFICATION_CONFIDENCE_THRESHOLD
    # and silently overwrite required_skills; the raw suggestion is still
    # returned untouched below, visible via ai_suggested_skills for a
    # human to actually look at.
    if len(skills) > len(SKILL_POOL) // 2:
        confidence = 0.0

    reasoning = str(args.get("reasoning") or "")

    return ClassificationResult(
        suggested_skills=skills,
        suggested_priority=priority,
        confidence=confidence,
        reasoning=reasoning,
    )
