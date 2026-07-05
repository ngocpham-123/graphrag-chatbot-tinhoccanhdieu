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
    # figures, tables, concepts, and assessments are all populated
    assert isinstance(d["figures"], list)
    assert isinstance(d["tables"], list)
    for key in ("concepts", "assessments"):
        assert isinstance(d[key], list)


def test_lesson_detail_unknown_raises_notfound():
    import pytest
    with pytest.raises(cs.NotFoundError):
        cs.lesson_detail("nosuchlesson")


def test_lesson_detail_figures_lesson1():
    d = cs.lesson_detail("lesson1")
    assert d["figures"]                                  # lesson 1 has figures/diagrams
    f = d["figures"][0]
    assert set(f) == {"id", "caption", "type", "imageUrl", "concept"}
    assert f["imageUrl"] is None or f["imageUrl"].startswith("/figures/")
    # the data/info/knowledge pyramid diagram belongs to lesson 1
    assert any("Tháp" in (x["caption"] or "") for x in d["figures"])


def test_lesson_detail_tables_lesson2():
    d = cs.lesson_detail("lesson2")
    captions = [t["caption"] for t in d["tables"]]
    assert any("đơn vị lưu trữ" in (c or "").lower() for c in captions)


def test_lesson_detail_concepts_lesson1():
    d = cs.lesson_detail("lesson1")
    labels = [c["label"] for c in d["concepts"]]
    assert "Thông tin" in labels
    assert "Dữ liệu" in labels
    for c in d["concepts"]:
        assert set(c) == {"id", "label", "definition"}


def test_lesson_detail_concepts_topic_fallback_surfaces_unplaced():
    # "Biểu diễn thông tin" (conceptBieuDienThongTin) is a topicAcs concept that
    # is linked to no lesson. The topic-concept fallback must surface it on a
    # lesson of that topic even though it is not directly linked to the lesson.
    d = cs.lesson_detail("topicAcs_lesson1")
    labels = [c["label"] for c in d["concepts"]]
    assert "Biểu diễn thông tin" in labels


def test_lesson_detail_assessments_lesson1():
    d = cs.lesson_detail("lesson1")
    assert d["assessments"]                       # lesson 1 has exercises/activities
    item = d["assessments"][0]
    assert set(item) == {"id", "type", "title", "text"}
    assert any(a["text"] for a in d["assessments"])
