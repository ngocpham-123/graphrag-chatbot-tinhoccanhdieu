def test_library_js_renders_content_text():
    js = open("frontend/library.js", encoding="utf-8").read()
    # "Nội dung" renders the GraphDB text sections, not book part-images.
    assert "section-title" in js
    assert "contentImages" not in js
    assert "content-page" not in js


def test_library_html_bumped_library_js_v11():
    html = open("frontend/library.html", encoding="utf-8").read()
    assert "library.js?v=11" in html
