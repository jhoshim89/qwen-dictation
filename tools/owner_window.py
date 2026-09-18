"""내 소유의 작은 창을 띄우고 잠시 뒤 글자를 바꾼다(포커스는 뺏지 않는다)."""
import AppKit, Foundation, objc

BEFORE = "강막 궤양 소견입니다"
AFTER = "각막 궤양 소견입니다"

app = AppKit.NSApplication.sharedApplication()
# 액세서리 정책: Dock/메뉴바를 차지하지 않고 다른 앱의 포커스를 가져가지 않는다.
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

rect = Foundation.NSMakeRect(40, 40, 360, 90)
win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
    rect, AppKit.NSWindowStyleMaskTitled, AppKit.NSBackingStoreBuffered, False)
win.setTitle_("AXHoldTest")
tv = AppKit.NSTextView.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, 360, 90))
tv.setString_(BEFORE)
win.setContentView_(tv)
win.orderFrontRegardless()   # 보이게만 한다 — key 창으로 만들지 않는다

def change(_timer):
    tv.setString_(AFTER)
    print("owner: 글자 바꿈", flush=True)

def quit_(_timer):
    AppKit.NSApp.terminate_(None)

print("owner: 준비됨", flush=True)
Foundation.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(6.0, False, change)
Foundation.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(14.0, False, quit_)
app.run()
