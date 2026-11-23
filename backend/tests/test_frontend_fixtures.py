"""The frontend's test fixtures must still be what this backend sends.

They were recorded from the live API (frontend/tests/fixtures). The React
tests run against them, so if a response model changes shape these fail here
first, instead of the frontend tests passing against a backend that no longer
exists.
"""

import json
import pathlib

import pytest

from src.schemas.contract_review import ContractAnswerResponse, ContractReviewResponse
from src.schemas.legal import LegalAnalysisResponse

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir(), reason="frontend fixtures not present")


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", ["contract-review.json", "contract-review-freelance.json"])
def test_contract_review_fixtures_match_the_response_model(name):
    payload = load(name)
    model = ContractReviewResponse(**payload)
    # Re-serialising must not drop anything the frontend reads.
    assert set(payload) <= set(model.model_dump())


def test_the_answer_fixture_matches_the_response_model():
    ContractAnswerResponse(**load("contract-answer.json"))


def test_the_scenario_fixture_matches_the_response_model():
    payload = load("scenario-analysis.json")
    model = LegalAnalysisResponse(**payload)
    assert set(payload) <= set(model.model_dump())


def test_the_document_fixture_is_the_text_the_review_indexes_into():
    review = load("contract-review.json")
    document = load("contract-document.json")
    assert document["contract_id"] == review["contract_id"]
    for finding in review["findings"]:
        span = document["text"][finding["match_start"]:finding["match_end"]]
        assert " ".join(span.split()) == finding["matched_quote"]


def test_the_list_fixture_carries_only_summary_fields():
    items = load("contract-list.json")["items"]
    assert items
    for item in items:
        assert "review" not in item and "document_text" not in item


def test_the_conversation_turn_fixture_matches_the_stream_models():
    from src.schemas.conversation import Source, TurnDone

    events = load("conversation-turn.json")["events"]
    assert [name for name, _ in events][0] == "sources"
    assert [name for name, _ in events][-1] == "done"
    for name, data in events:
        if name == "sources":
            for source in data["sources"]:
                assert set(source) <= set(Source(**source).model_dump())
        if name == "done":
            done = TurnDone(**data)
            assert set(data["answer"]) <= set(done.answer.model_dump())
            # Every cited number points at a section the turn returned.
            numbers = {s.n for s in done.answer.sources}
            assert set(done.answer.cited) <= numbers
