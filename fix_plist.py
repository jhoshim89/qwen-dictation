"""빌드된 .app 의 Info.plist 에 메뉴바 전용 플래그와 권한 문자열을 주입한다.

PyInstaller 는 --windowed 로 일반 GUI 앱을 만들지만, 이 앱은 Dock 아이콘 없는
메뉴바 전용(LSUIElement) 앱이어야 하고 마이크/AppleEvents 권한 설명이 필요하다.
"""
import plistlib
import sys

plist_path = sys.argv[1]

with open(plist_path, "rb") as f:
    pl = plistlib.load(f)

pl["LSUIElement"] = True
pl["CFBundleName"] = "Qwen Dictation"
pl["CFBundleDisplayName"] = "Qwen Dictation"
pl["CFBundleShortVersionString"] = "0.1.0"
pl["CFBundleVersion"] = "0.1.0"
pl["NSMicrophoneUsageDescription"] = "받아쓰기를 위해 마이크로 음성을 녹음합니다."
pl["NSAppleEventsUsageDescription"] = (
    "받아쓴 텍스트를 현재 앱에 붙여넣기 위해 시스템 이벤트를 사용합니다."
)

with open(plist_path, "wb") as f:
    plistlib.dump(pl, f)

print(f"Info.plist patched: {plist_path}")
