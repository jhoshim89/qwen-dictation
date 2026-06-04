# 홀드 키 떼면 자동 엔터 — 설계

## 목적

홀드 키(기본 오른쪽 Cmd)로 받아쓰기를 한 뒤 키에서 손을 떼면, 받아쓴
마지막 글자까지 모두 입력된 다음 자동으로 Enter 키가 눌리도록 한다.
채팅·검색창에서 "말하고 손 떼면 바로 전송"되는 흐름을 만든다.

설정에서 켜고 끌 수 있으며, 기본값은 켜짐.

## 동작 규칙

- **적용 대상**: 홀드 트리거를 키에서 떼서 정상 종료될 때만.
- **순서(잘림 방지)**: 손을 뗌 → 스트리밍 루프가 마지막 음성을 한 번 더
  받아써서 글자를 마저 타이핑(`finalize_on_stop`) → 그 직후 Enter 전송.
  마지막 단어가 잘리지 않는다. 손 뗌과 Enter 사이에 약 1초 이내(스트림 틱
  1회) 지연이 있다.
- **Enter를 보내지 않는 경우**:
  - 토글 키로 멈출 때
  - 받아쓰는 도중 키보드로 직접 손대서 멈출 때(`finalize=False`)
  - 자동 종료(최대 시간) 타이머로 멈출 때
  - 메뉴의 Stop Recording으로 멈출 때
  - 설정이 꺼져 있을 때

## 설정

- 새 설정 키: `hold_send_enter` (bool), 기본값 `True`.
- 저장/로드 경로는 기존 `edit_interrupt_mode`와 동일
  (`app_config.DEFAULTS` → `StatusBarApp` 속성 → `current_config()` →
  `dashboard.py` GET/POST → `templates/dashboard.html`).
- 대시보드 "고급 설정"에서 "받아쓰기 도중 손대면" 항목 바로 아래에
  켬/끔 항목으로 노출.

## 구현 위치

1. **`app_config.py`**: `DEFAULTS`에 `"hold_send_enter": True` 추가.
   새 불리언이라 마이그레이션 불필요(기존 설정 파일엔 키가 없으면 기본값
   사용).

2. **`whisper-dictation.py`**
   - `StatusBarApp._apply_saved_config`: `self.hold_send_enter =
     bool(cfg.get("hold_send_enter", True))`.
   - `StatusBarApp.current_config`: `hold_send_enter` 포함.
   - `Recorder.__init__` / `Recorder.start`: `self.send_enter_on_stop =
     False`로 초기화/리셋.
   - `Recorder.stop(finalize=True, send_enter=False)`:
     `self.send_enter_on_stop = bool(send_enter and finalize)`.
   - `Recorder._stream_loop` 끝, `finalize_on_stop` 처리 및
     `add_history` 직후: `self.send_enter_on_stop`이면 Enter를
     press/release. 합성 키가 수동 편집으로 오인되지 않도록 짧은 가드
     시각(`self_type_guard_until`)을 세우고, 키 이벤트 flush를 위해
     아주 짧은 sleep 후 전송.
   - `StatusBarApp.stop_app(_, finalize=True, send_enter=False)`:
     `self.recorder.stop(finalize=finalize, send_enter=send_enter)`.
   - `MultiHotkeyListener._end(trigger, finalize=True)`: trigger가
     `"hold"`이고 `finalize`이며 `app.hold_send_enter`일 때만
     `send_enter=True`로 `dispatch_app(..., stop_app, None, finalize,
     send_enter)` 호출. (`dispatch_app`은 `*args`를 그대로 전달.)

3. **`dashboard.py`**: GET 응답에 `hold_send_enter` 포함, POST 처리에
   `hold_send_enter`(불리언)를 받아 `app_instance`에 반영 후 저장.

4. **`templates/dashboard.html`**: "고급 설정"에 켬/끔 컨트롤 추가,
   `fetchConfig`에서 값 채우기, `updateConfig`에서 값 전송.

## 테스트

- `MultiHotkeyListener` 단위 테스트: 홀드 떼서 종료 시 `stop_app`이
  `send_enter=True`로 호출되는지; 토글 종료·수동 편집 종료·설정 꺼짐일
  때 `send_enter=False`인지.
- `Recorder.stop` → `_stream_loop` 종료 경로에서
  `send_enter_on_stop`이 set일 때 Enter press/release가 호출되는지
  (키보드 컨트롤러 목으로 검증).
- `app_config` 로드/저장 라운드트립에 `hold_send_enter` 포함 확인.

## 비목표 (YAGNI)

- 토글 키용 자동 엔터 옵션은 만들지 않는다(요청 범위 밖).
- Enter 외 다른 키(Tab 등) 전송 옵션은 만들지 않는다.
- 지연 시간 사용자 조절 옵션은 만들지 않는다.
