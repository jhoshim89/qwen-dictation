from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]


def test_logo_mark_uses_three_vertical_bars_only():
    svg = ElementTree.parse(ROOT / "assets" / "logo-mark.svg").getroot()
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    foreground = [
        rect
        for rect in svg.findall("svg:rect", namespace)
        if rect.attrib.get("fill", "").lower() == "#e84762"
    ]

    assert len(foreground) == 3
    assert all(float(rect.attrib["height"]) > float(rect.attrib["width"]) for rect in foreground)

    left = min(float(rect.attrib["x"]) for rect in foreground)
    right = max(float(rect.attrib["x"]) + float(rect.attrib["width"]) for rect in foreground)
    assert (left + right) / 2 == 48.0


def test_docs_landing_uses_warm_jelly_tokens():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8").lower()

    for token in ("#422e35", "#836c74", "#eaddd8", "#f7f1e9", "#e84762", "#d13652"):
        assert token in html

    assert "#c3215a" not in html
    assert "#811d4a" not in html
    assert "pretendard" in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert 'class="hero-preview" src="social-preview.png?v=20260701-single-icons"' in html


def test_hud_text_pill_exception_is_documented():
    design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "텍스트 상태 pill을 의도적 예외로 허용" in design
    assert "text-bearing HUD pill" in readme
    assert "Release readiness diagnosis matrix" in readme


def test_docs_hud_preview_keeps_current_pill_label_and_legibility():
    svg = (ROOT / "docs" / "hud-current-preview.svg").read_text(encoding="utf-8")

    assert "현재 코드 기준: 104 x 44, alpha 0.62, 하단 offset 24" in svg
    assert 'width="104" height="44" rx="22"' in svg
    assert 'fill="#5a5658" fill-opacity=".78"' in svg
    assert "filter=" not in svg
    assert 'transform="translate(428 362)"' in svg
