from backend.app.models.schemas import ChatResponse
from backend.app.services import chatgpt_service as cgs


def test_chatresponse_has_exercises_field():
    r = ChatResponse(
        reply="x", conversation_id="c1",
        exercises=[{"id": "l1_ex1", "type": "Exercise", "title": None, "text": "q"}],
    )
    assert r.exercises[0]["id"] == "l1_ex1"


def test_assessment_fewshot_selects_item_iri():
    # The assessment example must project ?item so the chat layer can extract ids.
    prompt = cgs.SPARQL_GENERATION_PROMPT
    assert "?item" in prompt
    # the assessment SELECT line must include ?item alongside ?text
    assert "SELECT ?item" in prompt or "?item ?kind" in prompt
