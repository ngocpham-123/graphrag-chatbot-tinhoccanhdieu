def test_index_includes_exercise_js():
    html = open("frontend/index.html", encoding="utf-8").read()
    assert "/static/exercise.js" in html


def test_library_includes_exercise_js():
    html = open("frontend/library.html", encoding="utf-8").read()
    assert "/static/exercise.js" in html


def test_exercise_js_exists_and_exposes_mount():
    js = open("frontend/exercise.js", encoding="utf-8").read()
    assert "mountExerciseRunner" in js
    assert "/api/exercises/grade" in js
