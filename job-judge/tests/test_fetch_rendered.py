from PIL import Image

import fetch_rendered as fr

DOM = """
<html><head><style>.a{color:red}</style><script>var x = "숨김";</script></head>
<body><h1>채용 &amp; 공고</h1><p>마감일   2026.10.12</p>
<img src="/upload/a.png"><img src='https://cdn.example.com/b.jpg?x=1&amp;y=2'>
<img src="data:image/png;base64,AAAA"><img src="/upload/a.png"></body></html>
"""


def test_visible_text_drops_script_style_and_unescapes():
    text = fr.visible_text(DOM)
    assert "숨김" not in text and "color:red" not in text
    assert "채용 & 공고" in text
    assert "마감일 2026.10.12" in text


def test_image_urls_resolves_relative_skips_data_and_dedupes():
    urls = fr.image_urls(DOM, "https://site.example.com/career/jobs/1")
    assert urls == ["https://site.example.com/upload/a.png", "https://cdn.example.com/b.jpg?x=1&y=2"]


def test_slice_image_resizes_and_cuts(tmp_path):
    source = tmp_path / "tall.png"
    Image.new("RGB", (500, 3000), "white").save(source)
    pieces = fr.slice_image(source, tmp_path / "out")
    # 500x3000 -> 1000x6000, 1500px씩 4조각
    assert len(pieces) == 4
    assert Image.open(pieces[0]).width == fr.SLICE_WIDTH
