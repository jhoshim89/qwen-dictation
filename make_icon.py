# make_icon.py
"""앱 아이콘(.icns)과 메뉴바 템플릿 PNG를 코드로 생성한다.

실행: ./venv/bin/python make_icon.py
산출물: assets/AppIcon.icns, assets/menubar.png
필요 도구: PIL(설치됨), iconutil/sips(macOS 기본)
"""
import math
import os
import shutil
import subprocess

from PIL import Image, ImageDraw

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(ASSETS, exist_ok=True)


def _rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_app_icon(size):
    """앱 아이콘 한 장(size x size)을 그려서 RGBA 이미지 반환."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 짙은 남색 둥근 사각 바탕(그라데이션 흉내: 두 겹)
    margin = int(size * 0.06)
    _rounded(d, (margin, margin, size - margin, size - margin),
             radius=int(size * 0.22), fill=(11, 15, 25, 255))      # #0b0f19
    _rounded(d, (margin, margin, size - margin, int(size * 0.62)),
             radius=int(size * 0.22), fill=(49, 46, 129, 90))      # 위쪽 보라 하이라이트

    # 마이크 본체(둥근 캡슐)
    cx = size * 0.5
    mic_w = size * 0.20
    mic_top = size * 0.24
    mic_bot = size * 0.56
    _rounded(d, (cx - mic_w / 2, mic_top, cx + mic_w / 2, mic_bot),
             radius=int(mic_w / 2), fill=(243, 244, 246, 255))     # #f3f4f6

    # 마이크 받침(아치 + 스탠드)
    arc_box = (cx - mic_w * 0.95, mic_top + mic_w * 0.2,
               cx + mic_w * 0.95, mic_bot + mic_w * 0.6)
    d.arc(arc_box, start=20, end=160, fill=(165, 180, 252, 255),
          width=max(2, int(size * 0.022)))                          # #a5b4fc
    stand_top = mic_bot + mic_w * 0.6
    d.line((cx, stand_top, cx, stand_top + size * 0.08),
           fill=(165, 180, 252, 255), width=max(2, int(size * 0.022)))
    d.line((cx - size * 0.07, stand_top + size * 0.08,
            cx + size * 0.07, stand_top + size * 0.08),
           fill=(165, 180, 252, 255), width=max(2, int(size * 0.022)))

    # 음파(좌우 초록 곡선 두 줄) — 받아쓰기 '소리' 상징
    for i, r in enumerate((0.16, 0.24)):
        col = (34, 197, 94, 255) if i == 0 else (34, 197, 94, 160)  # #22c55e
        for sign in (-1, 1):
            bx = cx + sign * (mic_w * 0.5 + size * r)
            box = (bx - size * r, size * 0.30, bx + size * r, size * 0.50)
            start, end = (300, 60) if sign > 0 else (120, 240)
            d.arc(box, start=start, end=end, fill=col,
                  width=max(2, int(size * 0.020)))
    return img


def draw_menubar(size=44):
    """메뉴바용 흑백 template 이미지(투명 배경에 검은 마이크 실루엣)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size * 0.5
    mic_w = size * 0.34
    _rounded(d, (cx - mic_w / 2, size * 0.18, cx + mic_w / 2, size * 0.60),
             radius=int(mic_w / 2), fill=(0, 0, 0, 255))
    d.arc((cx - mic_w * 0.95, size * 0.30, cx + mic_w * 0.95, size * 0.72),
          start=20, end=160, fill=(0, 0, 0, 255), width=max(2, int(size * 0.06)))
    d.line((cx, size * 0.72, cx, size * 0.84), fill=(0, 0, 0, 255),
           width=max(2, int(size * 0.06)))
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
