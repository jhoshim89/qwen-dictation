"""다른 프로세스에서 그 창의 입력칸 참조를 붙잡아 두고, 글자가 바뀐 뒤 다시 읽는다."""
import sys, time
from ApplicationServices import AXUIElementCreateApplication, AXUIElementCopyAttributeValue
pid = int(sys.argv[1]); app = AXUIElementCreateApplication(pid)
def attr(el, n):
    e, v = AXUIElementCopyAttributeValue(el, n, None)
    return v if e == 0 else None
def find(el, d=0):
    if el is None or d > 10: return None
    if attr(el, "AXRole") == "AXTextArea": return el
    for c in (attr(el, "AXChildren") or []):
        f = find(c, d+1)
        if f is not None: return f
    return None
wins = attr(app, "AXWindows") or []
target = next((w for w in wins if attr(w, "AXTitle") == "AXHoldTest"), None)
field = find(target)
print("입력칸 찾음:", field is not None)
if field is None: sys.exit(1)
print("1) 잡아둘 때 읽은 값 :", repr(attr(field, "AXValue")))
time.sleep(9)   # 이 사이에 소유 프로세스가 글자를 바꾼다
print("2) 바뀐 뒤 같은 참조 :", repr(attr(field, "AXValue")))
