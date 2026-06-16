from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent


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
