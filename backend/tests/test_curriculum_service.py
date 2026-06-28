import backend.app.services.curriculum_service as cs


def test_grades_returns_10_11_12():
    result = cs.grades()
    numbers = sorted(g["gradeNumber"] for g in result)
    assert numbers == [10, 11, 12]
    for g in result:
        assert g["id"]                      # non-empty opaque id
        assert isinstance(g["label"], str)


def test_topics_for_grade10_includes_topicA_with_6_lessons():
    topics = cs.topics_for_grade("grade10")
    by_id = {t["id"]: t for t in topics}
    assert "topicA" in by_id
    assert by_id["topicA"]["lessonCount"] == 6
    assert by_id["topicA"]["title"]            # has a title


def test_topics_for_grade_invalid_id_raises_notfound():
    import pytest
    with pytest.raises(cs.NotFoundError):
        cs.topics_for_grade("bad-id")          # hyphen is invalid


def test_lessons_for_topicA_has_lesson1():
    lessons = cs.lessons_for_topic("topicA")
    by_id = {l["id"]: l for l in lessons}
    assert "lesson1" in by_id
    assert by_id["lesson1"]["lessonNumber"] == 1
    assert len(lessons) == 6


def test_lesson_detail_core_lesson1():
    d = cs.lesson_detail("lesson1")
    assert d["id"] == "lesson1"
    assert d["lessonNumber"] == 1
    assert d["title"]
    # objectives + summary come from NoteBox / SummaryBox
    assert d["objectives"] and isinstance(d["objectives"][0], str)
    assert d["summary"]
    # lesson 1 has exactly 6 sections, each with a title
    assert len(d["sections"]) == 6
    assert all(s["title"] for s in d["sections"])
    # section 1 has at least one paragraph
    first = sorted(d["sections"], key=lambda s: (s["order"] is None, s["order"]))[0]
    assert first["paragraphs"]
    assert first["paragraphs"][0]["text"]
    # keys filled by later tasks exist as lists/None already
    for key in ("figures", "tables", "concepts", "assessments"):
        assert d[key] == []


def test_lesson_detail_unknown_raises_notfound():
    import pytest
    with pytest.raises(cs.NotFoundError):
        cs.lesson_detail("nosuchlesson")
