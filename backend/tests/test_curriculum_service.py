import backend.app.services.curriculum_service as cs


def test_grades_returns_10_11_12():
    result = cs.grades()
    numbers = sorted(g["gradeNumber"] for g in result)
    assert numbers == [10, 11, 12]
    for g in result:
        assert g["id"]                      # non-empty opaque id
        assert isinstance(g["label"], str)
