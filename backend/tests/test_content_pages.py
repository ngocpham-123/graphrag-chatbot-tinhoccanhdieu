import json
import os

from backend.app.services import content_pages as cpsvc


def test_content_images_for_returns_existing_files(tmp_path):
    img_dir = tmp_path / "cf"
    img_dir.mkdir()
    (img_dir / "a.jpg").write_bytes(b"x")
    (img_dir / "b.jpg").write_bytes(b"x")
    # "c.jpg" intentionally NOT created on disk
    map_path = tmp_path / "content_pages.json"
    map_path.write_text(json.dumps({"lesson1": ["a.jpg", "c.jpg", "b.jpg"]}), encoding="utf-8")

    urls = cpsvc.content_images_for("lesson1", map_path=str(map_path), img_dir=str(img_dir))
    assert urls == ["/content_figure/a.jpg", "/content_figure/b.jpg"]  # c.jpg dropped, order kept


def test_content_images_for_unknown_lesson(tmp_path):
    map_path = tmp_path / "m.json"
    map_path.write_text(json.dumps({"lesson1": ["a.jpg"]}), encoding="utf-8")
    assert cpsvc.content_images_for("nope", map_path=str(map_path), img_dir=str(tmp_path)) == []


def test_content_images_for_missing_map():
    assert cpsvc.content_images_for("lesson1", map_path="does/not/exist.json", img_dir=".") == []


def test_content_images_for_malformed_shapes_never_raise(tmp_path):
    # top-level JSON array (not a dict)
    p1 = tmp_path / "arr.json"
    p1.write_text(json.dumps(["x"]), encoding="utf-8")
    assert cpsvc.content_images_for("lesson1", map_path=str(p1), img_dir=str(tmp_path)) == []
    # lesson value is not a list
    p2 = tmp_path / "obj.json"
    p2.write_text(json.dumps({"lesson1": "nope"}), encoding="utf-8")
    assert cpsvc.content_images_for("lesson1", map_path=str(p2), img_dir=str(tmp_path)) == []
    # syntactically invalid JSON
    p3 = tmp_path / "bad.json"
    p3.write_text("{not json", encoding="utf-8")
    assert cpsvc.content_images_for("lesson1", map_path=str(p3), img_dir=str(tmp_path)) == []
