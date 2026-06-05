import importlib.util
import sys

import pytest


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only crash path")
def test_listener_mask_excludes_system_defined():
    # Caps Lock(한/영) 전환 시 pynput 이 NSSystemDefined(시스템 정의) 이벤트를
    # NSEvent.eventWithCGEvent_ 로 변환하는데, 그 변환이 백그라운드 탭 스레드에서
    # TSM 입력소스 전환을 호출하면 macOS 가 메인 디스패치 큐를 강제(assert)해 앱이
    # EXC_BREAKPOINT(SIGTRAP)로 즉사한다(크래시 리포트 2건으로 확인). 그 이벤트
    # 종류를 리스너 mask 에서 빼 변환 경로 자체를 없앤다. 이 앱은 미디어 키를
    # 단축키로 쓰지 않으므로 기능 손실이 없다.
    wd = _load()
    from pynput.keyboard._darwin import CGEventMaskBit, NSSystemDefined

    bit = CGEventMaskBit(NSSystemDefined)
    # 원본 pynput 리스너에는 그 비트가 있다(충돌 원인).
    assert wd.keyboard.Listener._EVENTS & bit
    # 우리 안전 리스너에는 없다(가드 적용됨).
    assert not (wd.SafeKeyboardListener._EVENTS & bit)
    # 일반 키 입력(KeyDown/Up)·수정자(FlagsChanged) 감지는 그대로여야 한다.
    from pynput.keyboard._darwin import (
        kCGEventKeyDown,
        kCGEventKeyUp,
        kCGEventFlagsChanged,
    )
    for ev in (kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged):
        assert wd.SafeKeyboardListener._EVENTS & CGEventMaskBit(ev)
