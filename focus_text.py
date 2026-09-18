"""받아쓰기를 넣은 입력창의 글자를 읽는다(macOS 손쉬운 사용).

받아쓴 직후 그 입력창의 참조를 잡아 두고, 다음 받아쓰기를 시작할 때 한 번 더 읽어
사용자가 직접 고친 부분을 알아내는 데 쓴다. 상시 감시가 아니라 '우리가 글자를 넣은
그 칸'만 세션당 두 번 읽는다. 읽은 내용은 저장하지 않는다 — 호출한 쪽이 바뀐 단어만
추려 쓰고 원문은 버린다.

앱은 이미 키 입력을 합성하느라 손쉬운 사용 권한을 갖고 있어 추가 권한이 필요 없다.
권한이 없거나 PyObjC 가 없으면 모든 함수가 조용히 None 을 돌려준다(기능만 꺼짐).
"""
import threading

try:  # PyObjC 가 없는 환경(테스트 등)에서도 import 는 성공해야 한다.
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        AXUIElementSetMessagingTimeout,
        AXIsProcessTrusted,
    )
    from AppKit import NSWorkspace
except Exception:  # pragma: no cover - macOS/PyObjC 없는 환경
    AXUIElementCreateApplication = None
    AXUIElementCopyAttributeValue = None
    AXUIElementSetMessagingTimeout = None
    AXIsProcessTrusted = None
    NSWorkspace = None

# 글자를 담을 수 있는 역할. 브라우저 입력창도 이 둘 중 하나로 보인다.
TEXT_ROLES = ("AXTextArea", "AXTextField")
# 한 번에 읽어 올 글자 수 상한. 긴 문서 전체를 메모리에 들고 있지 않기 위한 안전선이다.
MAX_FIELD_CHARS = 20000

# 접근성 호출은 대상 앱이 응답할 때까지 블로킹된다. 받아쓰기 스레드가 붙잡히지 않도록
# 동시에 하나만 들어가게 하고, 응답 없는 앱에서 오래 매달리지 않도록 시간 제한을 둔다.
_LOCK = threading.RLock()
MESSAGING_TIMEOUT_SEC = 1.0


def _set_timeout(element):
    if AXUIElementSetMessagingTimeout is None or element is None:
        return
    try:
        AXUIElementSetMessagingTimeout(element, MESSAGING_TIMEOUT_SEC)
    except Exception:
        pass


def available():
    """이 기능을 쓸 수 있는 환경인지(맥 + PyObjC + 손쉬운 사용 허용)."""
    if AXUIElementCreateApplication is None or AXIsProcessTrusted is None:
        return False
    try:
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def _attr(element, name):
    try:
        err, value = AXUIElementCopyAttributeValue(element, name, None)
    except Exception:
        return None
    return value if err == 0 else None


def _is_text_element(element):
    if element is None:
        return False
    if _attr(element, "AXRole") in TEXT_ROLES:
        return True
    # 일부 앱(Electron 등)은 역할을 AXGroup 으로 내보내면서도 글자 속성은 지원한다.
    return isinstance(_attr(element, "AXValue"), str)


def capture_focused_field():
    """지금 포커스된 입력창의 (참조, 현재 글자) 를 돌려준다. 못 읽으면 (None, None).

    받아쓰기가 끝난 직후에 부른다 — 이때 포커스된 칸이 방금 글자를 넣은 칸이다.
    """
    if not available() or NSWorkspace is None:
        return None, None
    with _LOCK:
        try:
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is None:
                return None, None
            app = AXUIElementCreateApplication(front.processIdentifier())
            _set_timeout(app)
            element = _attr(app, "AXFocusedUIElement")
            _set_timeout(element)
            if not _is_text_element(element):
                return None, None
            return element, read_field(element)
        except Exception:
            return None, None


def read_field(element):
    """잡아 둔 입력창을 다시 읽는다. 사라졌거나 글자가 아니면 None.

    창이 뒤에 있어도 읽힌다 — 참조가 살아 있으면 포커스와 무관하게 값을 준다.
    """
    if element is None or not available():
        return None
    with _LOCK:
        value = _attr(element, "AXValue")
    if not isinstance(value, str):
        return None
    return value[:MAX_FIELD_CHARS]
