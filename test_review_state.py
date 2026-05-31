import importlib.util


def _load():
    spec = importlib.util.spec_from_file_location("wd", "whisper-dictation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeApp:
    """StatusBarApp 의 리뷰 관련 부분만 흉내내기 위해, 실제 메서드를 빌려 쓴다."""
    pass


def _make_app(wd):
    # rumps.App 를 인스턴스화하지 않고 리뷰 메서드만 가진 객체에 바인딩.
    app = FakeApp()
    app.pending_review_text = None
    app.review_active = False
    # 실제 함수를 언바운드로 빌려 FakeApp 에 붙인다.
    app.request_review = wd.StatusBarApp.request_review.__get__(app, FakeApp)
    app.resolve_review = wd.StatusBarApp.resolve_review.__get__(app, FakeApp)
    return app


def test_request_review_stores_text(monkeypatch):
    wd = _load()
    app = _make_app(wd)
    app.request_review("hello world")
    assert app.review_active is True
    assert app.pending_review_text == "hello world"


def test_resolve_send_calls_paste_with_submit(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.request_review("보낼 글")
    app.resolve_review("send")
    assert calls == [("보낼 글", True)]
    assert app.review_active is False
    assert app.pending_review_text is None


def test_resolve_insert_calls_paste_without_submit(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.request_review("고칠 글")
    app.resolve_review("insert")
    assert calls == [("고칠 글", False)]
    assert app.review_active is False


def test_resolve_cancel_does_not_paste(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.request_review("버릴 글")
    app.resolve_review("cancel")
    assert calls == []
    assert app.review_active is False
    assert app.pending_review_text is None


def test_resolve_when_not_active_is_noop(monkeypatch):
    wd = _load()
    calls = []
    monkeypatch.setattr(wd, "paste_text", lambda text, submit=False: calls.append((text, submit)))
    app = _make_app(wd)
    app.review_active = False
    app.pending_review_text = None
    app.resolve_review("send")
    assert calls == []
