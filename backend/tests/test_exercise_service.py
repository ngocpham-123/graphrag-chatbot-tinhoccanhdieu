import rdflib

from backend.app.services import exercise_service as es
from backend.app.services import curriculum_service as cs


def _rows(ttl: str, query: str):
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return list(g.query(query))


def test_get_exercise_known_id():
    ex = es.get_exercise("l1_ex2")
    assert ex["id"] == "l1_ex2"
    assert ex["lessonId"] == "lesson1"
    assert ex["text"]                       # the question text
    assert ex["type"] in es.ASSESSMENT_LOCALNAMES


def test_get_exercise_unknown_raises_notfound():
    import pytest
    with pytest.raises(cs.NotFoundError):
        es.get_exercise("nosuchexercise")


def test_extract_exercises_from_assessment_rows():
    ttl = """
    @prefix ex: <http://example.org/tinhoc10-cd#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    ex:l1_ex1 a ex:Exercise ; rdfs:label "Bài 1 - Bài tập 1" ; ex:hasRawText "Nêu ví dụ minh hoạ." .
    """
    q = """PREFIX ex: <http://example.org/tinhoc10-cd#>
           PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
           SELECT ?item ?kind ?title ?text WHERE {
             ?item a ?kind ; ex:hasRawText ?text . OPTIONAL { ?item rdfs:label ?title } }"""
    rows = _rows(ttl, q)
    sparql = "SELECT ?item ?kind ?text WHERE { ?item a ex:Exercise ; ex:hasRawText ?text }"
    out = es.extract_exercises_from_rows(sparql, rows)
    assert len(out) == 1
    assert out[0]["id"] == "l1_ex1"
    assert out[0]["type"] == "Exercise"
    assert "ví dụ" in out[0]["text"]


def test_extract_exercises_ignores_non_assessment_query():
    ttl = """
    @prefix ex: <http://example.org/tinhoc10-cd#> .
    ex:p1 a ex:Paragraph ; ex:hasRawText "đoạn văn" .
    """
    q = """PREFIX ex: <http://example.org/tinhoc10-cd#>
           SELECT ?item ?kind ?text WHERE { ?item a ?kind ; ex:hasRawText ?text }"""
    rows = _rows(ttl, q)
    sparql = "SELECT ?p ?text WHERE { ?p ex:mentionsConcept ?c ; ex:hasRawText ?text }"
    assert es.extract_exercises_from_rows(sparql, rows) == []


def test_parse_grade_json_plain():
    d = es._parse_grade_json('{"verdict":"correct","feedback":"Tốt","modelAnswer":"Đáp án"}')
    assert d == {"verdict": "correct", "feedback": "Tốt", "modelAnswer": "Đáp án"}


def test_parse_grade_json_fenced_and_bad_verdict():
    raw = '```json\n{"verdict":"perfect","feedback":"x","modelAnswer":"y"}\n```'
    d = es._parse_grade_json(raw)
    assert d["verdict"] == "partial"          # unknown verdict normalized
    assert d["feedback"] == "x"


def test_parse_grade_json_garbage_falls_back():
    d = es._parse_grade_json("not json at all")
    assert d["verdict"] == "partial"
    assert isinstance(d["feedback"], str)
    assert d["modelAnswer"] == ""


def test_grade_correct_answer_not_incorrect():
    # l1_ex2: "đầu vào và đầu ra của một bài toán xử lí thông tin"
    res = es.grade_exercise(
        "l1_ex2",
        "Đầu vào là dữ liệu, đầu ra là thông tin hữu ích.",
    )
    assert res["verdict"] in {"correct", "partial", "incorrect"}
    assert res["verdict"] != "incorrect"
    assert res["feedback"] and res["modelAnswer"]


def test_grade_irrelevant_answer_not_correct():
    res = es.grade_exercise("l1_ex2", "Hôm nay trời mưa.")
    assert res["verdict"] != "correct"
