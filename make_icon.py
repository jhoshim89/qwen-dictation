# make_icon.py
"""라즈베리 젤리 브랜드 기반 앱 아이콘과 메뉴바 템플릿 PNG를 생성한다.

실행: ./venv/bin/python make_icon.py
입력: assets/AppIcon-source.png
산출물: assets/AppIcon.icns, assets/menubar.png
필요 도구: PIL(설치됨), iconutil/sips(macOS 기본)
"""
import os
import shutil
import subprocess

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
APP_ICON_SOURCE = os.path.join(ASSETS, "AppIcon-source.png")
os.makedirs(ASSETS, exist_ok=True)


def draw_app_icon(size):
    """선택한 젤리 시안을 아이콘셋 크기로 고품질 리샘플링한다."""
    with Image.open(APP_ICON_SOURCE) as source:
        return source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def draw_menubar(size=44):
    """메뉴바용 흑백 template 이미지(HUD와 같은 세 줄 파형)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    black = (0, 0, 0, 255)
    radius = max(1, int(size * .045))
    for left, top, right, bottom in (
        (.28, .35, .37, .65),
        (.455, .22, .545, .78),
        (.63, .35, .72, .65),
    ):
        d.rounded_rectangle(
            (size * left, size * top, size * right, size * bottom),
            radius=radius,
            fill=black,
        )
    return img


def build_icns():
    iconset = os.path.join(ASSETS, "AppIcon.iconset")
    if os.path.exists(iconset):
        shutil.rmtree(iconset)
    os.makedirs(iconset)
    specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
             (256, 1), (256, 2), (512, 1), (512, 2)]
    for base, scale in specs:
        px = base * scale
        img = draw_app_icon(px)
        name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
        img.save(os.path.join(iconset, name))
    icns = os.path.join(ASSETS, "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    shutil.rmtree(iconset)
    return icns


def main():
    icns = build_icns()
    mb = draw_menubar(44)
    mb.save(os.path.join(ASSETS, "menubar.png"))
    print("ICON_OK", icns, os.path.join(ASSETS, "menubar.png"))


if __name__ == "__main__":
    main()
