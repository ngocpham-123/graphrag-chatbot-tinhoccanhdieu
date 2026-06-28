"""Router tests use a minimal app that mounts ONLY the curriculum router,
so the heavy chat-startup (OpenAI + Chroma) is not triggered."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import curriculum

app = FastAPI()
app.include_router(curriculum.router)
client = TestClient(app)


def test_get_grades_200():
    resp = client.get("/api/curriculum/grades")
    assert resp.status_code == 200
    nums = sorted(g["gradeNumber"] for g in resp.json())
    assert nums == [10, 11, 12]


def test_get_topics_200():
    resp = client.get("/api/curriculum/grades/grade10/topics")
    assert resp.status_code == 200
    assert any(t["id"] == "topicA" for t in resp.json())


def test_get_lessons_200():
    resp = client.get("/api/curriculum/topics/topicA/lessons")
    assert resp.status_code == 200
    assert any(l["id"] == "lesson1" for l in resp.json())


def test_get_lesson_detail_200():
    resp = client.get("/api/curriculum/lessons/lesson1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "lesson1"
    assert len(body["sections"]) == 6


def test_get_lesson_detail_unknown_404():
    resp = client.get("/api/curriculum/lessons/nosuchlesson")
    assert resp.status_code == 404
