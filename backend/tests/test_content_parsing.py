from backend.app.services import content_parsing as cp


def test_parse_g10_name():
    assert cp.parse_object_name("Tin10.CA.L1.P5.KT1") == {
        "grade": 10, "topic_code": "CA", "lesson_num": 1, "page_num": 5, "part": "KT1"
    }


def test_parse_g11_name():
    assert cp.parse_object_name("SGK.TIN11THUD.CA.L1.P5.MT") == {
        "grade": 11, "topic_code": "CA", "lesson_num": 1, "page_num": 5, "part": "MT"
    }


def test_parse_g12_name():
    assert cp.parse_object_name("Tin12.THUD.P5.A1.MT") == {
        "grade": 12, "topic_code": "A", "lesson_num": 1, "page_num": 5, "part": "MT"
    }


def test_parse_unknown_returns_none():
    assert cp.parse_object_name("random.thing") is None
    assert cp.parse_object_name("") is None


def test_touch_vector_bbox_basic():
    tv = '[{"x":26,"y":154},{"x":555,"y":154},{"x":555,"y":262},{"x":26,"y":262}]'
    assert cp.touch_vector_bbox(tv, 1512, 2118, pad=0) == (26, 154, 555, 262)


def test_touch_vector_bbox_pad_and_clamp():
    tv = '[{"x":0,"y":0},{"x":10,"y":10}]'
    # padded box would be (-6,-6,16,16) -> clamped to 0,0
    assert cp.touch_vector_bbox(tv, 1512, 2118, pad=6) == (0, 0, 16, 16)


def test_touch_vector_bbox_invalid():
    assert cp.touch_vector_bbox("not json", 1512, 2118) is None
    assert cp.touch_vector_bbox('[{"x":5,"y":5},{"x":5,"y":5}]', 1512, 2118, pad=0) is None


def test_crop_filename_ascii_normalizes_diacritics():
    assert cp.crop_filename("Tin10.CA.L1.P5.KĐ") == "Tin10_CA_L1_P5_KD.jpg"
    assert cp.crop_filename("Tin12.THUD.P5.A1.MĐ") == "Tin12_THUD_P5_A1_MD.jpg"
