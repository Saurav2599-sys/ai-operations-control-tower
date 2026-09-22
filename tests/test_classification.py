"""Tests for app/classification.py against a fake OpenAI client -- no real
API key or network call needed. The fake mimics just enough of the
`openai` SDK's response shape (choices[0].message.tool_calls[0].function
.arguments as a JSON string) for classify_order() to parse.
"""

import json
from types import SimpleNamespace

import pytest

from app.classification import ClassificationError, classify_order


def _fake_response(args: dict):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(args)))
                    ]
                )
            )
        ]
    )


class FakeClient:
    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exception:
            raise self._exception
        return self._response


def test_classify_order_parses_valid_response():
    client = FakeClient(
        response=_fake_response(
            {
                "required_skills": ["plumbing", "hvac"],
                "suggested_priority": "high",
                "confidence": 0.85,
                "reasoning": "Mentions a leaking pipe and a broken AC unit.",
            }
        )
    )
    result = classify_order("Fix the leaking pipe, and the AC is broken too", client=client)
    assert result.suggested_skills == frozenset({"plumbing", "hvac"})
    assert result.suggested_priority == "high"
    assert result.confidence == 0.85
    assert len(client.calls) == 1
    # Forces the tool call rather than leaving it to the model's discretion.
    assert client.calls[0]["tool_choice"]["function"]["name"] == "extract_order_requirements"


def test_classify_order_drops_skills_outside_the_known_pool():
    """Defense in depth: even with an enum-constrained schema, a
    hallucinated skill shouldn't silently pass through -- it would make
    the order unassignable to any real employee without anyone noticing
    why."""
    client = FakeClient(
        response=_fake_response(
            {
                "required_skills": ["plumbing", "time_travel"],
                "suggested_priority": "normal",
                "confidence": 0.7,
                "reasoning": "...",
            }
        )
    )
    result = classify_order("some description", client=client)
    assert result.suggested_skills == frozenset({"plumbing"})


def test_classify_order_falls_back_to_normal_priority_on_invalid_value():
    client = FakeClient(
        response=_fake_response(
            {
                "required_skills": [],
                "suggested_priority": "asap",  # not one of the allowed enum values
                "confidence": 0.5,
                "reasoning": "...",
            }
        )
    )
    result = classify_order("some description", client=client)
    assert result.suggested_priority == "normal"


def test_classify_order_clamps_out_of_range_confidence():
    client = FakeClient(
        response=_fake_response(
            {
                "required_skills": [],
                "suggested_priority": "low",
                "confidence": 1.5,
                "reasoning": "...",
            }
        )
    )
    result = classify_order("some description", client=client)
    assert result.confidence == 1.0


def test_classify_order_treats_majority_of_pool_as_untrustworthy():
    """A repeatable failure mode surfaced by a real eval run (see the
    README's "Phase 3 eval results"): the model sometimes returns most of
    the entire skill pool at once instead of the 1-2 skills that actually
    apply, at high reported confidence. Real orders never need more than
    a couple of skills, so "most of the pool at once" is treated as
    untrustworthy rather than a genuine multi-skill extraction --
    confidence is clamped to 0 so it can never auto-fill required_skills,
    even though the raw (suspect) suggestion is still returned for a
    human to see."""
    client = FakeClient(
        response=_fake_response(
            {
                "required_skills": [
                    "carpentry", "electrical", "general_repair", "hvac",
                    "inspection", "painting", "plumbing", "welding",
                ],
                "suggested_priority": "high",
                "confidence": 0.9,
                "reasoning": "...",
            }
        )
    )
    result = classify_order("some description", client=client)
    assert len(result.suggested_skills) == 8  # untouched, still visible
    assert result.confidence == 0.0


def test_classify_order_allows_a_few_skills_at_normal_confidence():
    """The majority-of-pool guard shouldn't punish a legitimately
    multi-skill order -- e.g. the eval set's HVAC-filter-replacement case
    genuinely needs both hvac and inspection. Two skills, well under half
    of an 8-skill pool, keeps its reported confidence untouched."""
    client = FakeClient(
        response=_fake_response(
            {
                "required_skills": ["hvac", "inspection"],
                "suggested_priority": "normal",
                "confidence": 0.85,
                "reasoning": "...",
            }
        )
    )
    result = classify_order("some description", client=client)
    assert result.suggested_skills == frozenset({"hvac", "inspection"})
    assert result.confidence == 0.85


def test_classify_order_raises_on_client_exception():
    client = FakeClient(exception=RuntimeError("network down"))
    with pytest.raises(ClassificationError):
        classify_order("some description", client=client)


def test_classify_order_raises_on_malformed_response():
    client = FakeClient(response=SimpleNamespace(choices=[]))
    with pytest.raises(ClassificationError):
        classify_order("some description", client=client)


def test_classify_order_rejects_empty_description_without_calling_the_client():
    client = FakeClient()
    with pytest.raises(ClassificationError):
        classify_order("   ", client=client)
    assert client.calls == []
