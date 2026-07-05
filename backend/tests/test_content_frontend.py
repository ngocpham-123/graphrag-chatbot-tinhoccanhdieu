def test_library_js_renders_content_images():
    js = open("frontend/library.js", encoding="utf-8").read()
    assert "contentImages" in js
    assert "content-page" in js


def test_library_html_bumped_library_js_v10():
    html = open("frontend/library.html", encoding="utf-8").read()
    assert "library.js?v=10" in html
