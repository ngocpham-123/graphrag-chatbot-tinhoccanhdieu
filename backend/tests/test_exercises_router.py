"""Router tests mount only the exercises router (no chat startup), and mock the
grading service so they do not call OpenAI."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import exercises
from backend.app.services import curriculum_service as cs

app = FastAPI()
app.include_router(exercises.router)
client = TestClient(app)


def test_grade_200_shape():
    fake = {"verdict": "partial", "feedback": "Cần bổ sung.", "modelAnswer": "Đáp án mẫu."}
    with patch("backend.app.routers.exercises.es.grade_exercise", return_value=fake):
        resp = client.post("/api/exercises/grade",
                           json={"exerciseId": "l1_ex2", "userAnswer": "abc"})
    assert resp.status_code == 200
    assert set(resp.json()) == {"verdict", "feedback", "modelAnswer"}


def test_grade_empty_answer_400():
    resp = client.post("/api/exercises/grade",
                       json={"exerciseId": "l1_ex2", "userAnswer": "   "})
    assert resp.status_code == 400


def test_grade_unknown_id_404():
    with patch("backend.app.routers.exercises.es.grade_exercise",
               side_effect=cs.NotFoundError("nope")):
        resp = client.post("/api/exercises/grade",
                           json={"exerciseId": "nope", "userAnswer": "abc"})
    assert resp.status_code == 404


def test_grade_graphdb_error_503():
    with patch("backend.app.routers.exercises.es.grade_exercise",
               side_effect=cs.CurriculumError("db down")):
        resp = client.post("/api/exercises/grade",
                           json={"exerciseId": "l1_ex2", "userAnswer": "abc"})
    assert resp.status_code == 503
