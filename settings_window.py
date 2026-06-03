"""In-process native settings window hosting the local settings web UI.

Renders the Flask settings page (http://127.0.0.1:5001) inside a standalone
native macOS window using a WKWebView in an NSWindow, instead of opening the
user's default web browser. Built with PyObjC so it coexists with the rumps
NSApplication run loop (no separate main loop, unlike pywebview).

Defensive: all AppKit/WebKit usage is guarded. If those frameworks are
unavailable or any step fails, ``open_settings`` falls back to opening the URL
in the default web browser so settings always open somehow. Importing this
module must NOT build any window and must NOT crash.
"""

import threading

_DEFAULT_URL = "http://127.0.0.1:5001"

_settings_singleton = None
_settings_lock = threading.Lock()

try:
    import AppKit
    import Foundation
    import WebKit
    _WEBKIT_OK = True
except Exception as _e:  # pragma: no cover - depends on platform/frameworks
    _WEBKIT_OK = False
    _WEBKIT_ERR = str(_e)


# Window geometry
_WIN_WIDTH = 900.0
_WIN_HEIGHT = 760.0
_WIN_MIN_WIDTH = 720.0
_WIN_MIN_HEIGHT = 620.0


def _fallback(url, reason=""):
    """Open the URL in the default web browser as a last resort."""
    try:
        import webbrowser
        if reason:
            print(f"[settings_window] falling back to browser ({reason})")
        webbrowser.open(url)
    except Exception as exc:  # pragma: no cover
        print(f"[settings_window] browser fallback failed: {exc}")


class SettingsWindow:
    """Owns the NSWindow + WKWebView. All methods must run on the main thread."""

    def __init__(self):
        self._build()

    def _build(self):
        rect = Foundation.NSMakeRect(0, 0, _WIN_WIDTH, _WIN_HEIGHT)
        style = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskResizable
        )
        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        win.setTitle_("Qwen Dictation 설정")
        win.setMinSize_(Foundation.NSMakeSize(_WIN_MIN_WIDTH, _WIN_MIN_HEIGHT))
        # Closing the window should just hide it; the app keeps running in the
        # menu bar. releasedWhenClosed=False keeps the Python reference valid so
        # we can re-show the same window later.
        win.setReleasedWhenClosed_(False)
        win.center()

        content = win.contentView()
        webview = WebKit.WKWebView.alloc().initWithFrame_(content.bounds())
        webview.setAutoresizingMask_(
            AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
        )
        content.addSubview_(webview)

        self._window = win
        self._webview = webview

    def _load(self, url):
        ns_url = Foundation.NSURL.URLWithString_(url)
        request = Foundation.NSURLRequest.requestWithURL_(ns_url)
        self._webview.loadRequest_(request)

    def show(self, url=_DEFAULT_URL):
        self._load(url)
        # LSUIElement apps have no dock icon; activate so the window comes front.
        try:
            AppKit.NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass
        self._window.makeKeyAndOrderFront_(None)


def open_settings(url=_DEFAULT_URL):
    """Open the settings window (lazy singleton); fall back to browser on error.

    Builds and shows the window on the main thread. Safe to call repeatedly.
    """
    if not _WEBKIT_OK:
        _fallback(url, "WebKit/AppKit unavailable")
        return

    def _do():
        global _settings_singleton
        try:
            with _settings_lock:
                if _settings_singleton is None:
                    _settings_singleton = SettingsWindow()
            _settings_singleton.show(url)
        except Exception as exc:
            _fallback(url, f"window error: {exc}")

    try:
        if AppKit.NSThread.isMainThread():
            _do()
        else:
            # Marshal onto the main thread for AppKit safety.
            Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
    except Exception as exc:
        _fallback(url, f"dispatch error: {exc}")
