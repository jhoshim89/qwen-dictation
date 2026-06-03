# 받아쓰기 도중 수동 편집 처리 모드 (edit_interrupt_mode)

## 배경

라이브 받아쓰기는 0.8초마다 `type_diff`로 "직전에 내가 타이핑한 글자 = 입력창 글자"
라고 가정하고 새 받아쓴 내용으로 덮어쓴다. 따라서 사용자가 말하는 도중 키보드로
직접 글자를 고치면, 다음 갱신 틱이 사용자의 수정을 백스페이스로 지우고 자기 글자로
덮어버린다. 즉 현재는 "수동 편집 보존"이 불가능하다.

## 목표

사용자가 받아쓰기 중 다른 키를 입력했을 때의 동작을 **설정으로 선택**할 수 있게 한다.

- `stop` (①): 다른 키를 누르면 그 받아쓰기 세션을 멈추고 현재 글자를 그대로 확정.
  다시 받아쓰려면 단축키를 한 번 더.
- `continue` (②, 기본값): 다른 키를 누르면 받아쓰기가 "지금 입력창 상태가 새 출발점"
  이라고 받아들여 사용자의 수정을 건드리지 않는다. 이후 다시 말하면 커서 위치에서
  이어서 타이핑한다.

비목표: 마우스 클릭으로 커서를 옮기는 경우는 감지하지 않는다(키 입력만 감지).

## 설정

`~/.qwen-dictation/config.json`에 키 `edit_interrupt_mode` 추가. 값은 `"continue"` 또는
`"stop"`, 기본 `"continue"`. 대시보드 라이브 설정에서 즉시 변경. `app_config.DEFAULTS`,
`StatusBarApp.current_config`/`_apply_saved_config`, 대시보드 `get/post_config`에 반영.

## 동작 설계

### 수동 키 입력 감지 (`MultiHotkeyListener`)

`on_key_press`에서 활성 세션(`active_trigger is not None`) 중 다음 조건을 모두 만족하면
"수동 편집"으로 본다:

- 누른 키가 hold/toggle 단축키 구성요소가 아님.
- 모디파이어 단독(Shift/Ctrl/Alt/Cmd/fn)이 아니고 Enter도 아님
  (Enter는 기존 토글 종료 동작을 그대로 유지).
- **자기 타이핑이 아님**: 스트리밍 루프가 `type_diff`로 글자를 칠 때 발생하는 합성
  키 이벤트를 사용자 입력으로 오인하면 안 된다. `Recorder.self_type_guard_until`
  타임스탬프를 두고, 타이핑 중과 직후 0.2초는 들어오는 키를 합성으로 간주해 무시.

감지되면 모드에 따라:

- `stop`: `self._end(active_trigger, finalize=False)` — 마지막 틱 없이 세션 종료
  (사용자 수정 글자를 다시 건드리지 않음).
- `continue`: `recorder.rebaseline()` 호출.

### 재기준화 (`Recorder.rebaseline`)

스레드 경합을 피하려고 리스너 스레드는 플래그만 세운다(`rebaseline_pending = True`).
스트리밍 스레드의 `_stream_tick`이 틱 시작에서 플래그를 보면 `audio_lock` 아래
`window_start = len(audio_frames)`, `committed_text = ""`, `last_typed = ""`로 리셋한다.
이렇게 하면 다음 발화는 빈 기준에서 시작해 `type_diff`가 백스페이스 없이 커서 위치에
새 글자만 덧붙인다 — 사용자의 수정과 이전 글자를 보존.

### 자기 타이핑 가드

`_stream_tick`에서 `_type` 호출을 감싼다:

```
self.self_type_guard_until = time.time() + 30.0   # 타이핑 동안 넉넉히
try:
    self.last_typed = self._type(self.last_typed, target)
finally:
    self.self_type_guard_until = time.time() + 0.2  # 늦게 도착하는 합성 이벤트 커버
```

## 알려진 한계 (의도된 범위 밖)

- 마우스 커서 이동은 감지하지 않는다.
- 자기 타이핑 가드 윈도(약 0.2초) 동안의 진짜 사용자 입력은 무시될 수 있다. 틱은
  0.8초 간격이라 데드존은 작다.
- `continue` 재기준화 후 `dictation_history`에는 마지막 편집 이후의 텍스트만 남는다.

## 테스트

- `test_app_config`: 기본값 `edit_interrupt_mode == "continue"` 와 저장/로드 왕복.
- `test_multi_hotkey`: 활성 세션 중 일반 키 입력이 (a) stop 모드에서 `_end(finalize=False)`
  호출, (b) continue 모드에서 `recorder.rebaseline` 호출, (c) 자기 타이핑 가드 중에는
  무시, (d) 단축키 구성요소/Enter는 수동 편집으로 처리하지 않음.
- `test_streaming`: `rebaseline()`이 플래그를 세우고, 플래그 소비가 상태를 리셋함.
