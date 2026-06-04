# HUD 표시 모드 설계 (받아쓰기 인디케이터)

작성일: 2026-06-04
대상 파일: `hud_overlay.py`, `whisper-dictation.py`, `app_config.py`, `dashboard.py`, `templates/dashboard.html`

## 목표

받아쓰기 중 화면에 뜨는 표시(HUD)를 사용자가 셋 중 하나로 고를 수 있게 한다.
현재는 화면 하단 중앙에 "알약 + 듣는 중 글자"가 강제로 뜨고, 커서가 있는
모니터로 자동으로 따라 옮겨간다. 이를 유지하되, 글자 없는 작은 아이콘 모드와
고정/커서추적 모드를 추가한다.

## 모드 (대시보드에서 선택)

세 모드 모두 같은 음성 반응 막대(`jelly_bar_heights`)를 재사용한다. 조용하면
짧고 말하면 자란다 — 기존 동작 유지.

### A. 알약 (`pill`) — 기본값
- 현재 동작 그대로. 하단 중앙에 알약(92×40) + "듣는 중"/"변환 중" 글자 + 막대.
- 커서가 있는 모니터로 자동 이동(현재 `_reposition_for_pointer_screen` 유지).
- 기본값이므로 설정을 바꾸지 않은 기존 사용자는 변화 없음.

### B. 아이콘 고정 (`pinned`)
- 글자 없는 원형 아이콘(지름 36). 막대만 가운데 그린다.
- 사용자가 드래그해 원하는 자리에 놓으면 그 절대 좌표를 저장한다.
- **한 모니터의 그 자리에 고정. 커서를 다른 모니터로 옮겨도 따라가지 않는다**
  (`_reposition_for_pointer_screen` 미적용).
- 저장된 좌표가 어느 화면에도 들어가지 않으면(모니터 분리 등) 주 모니터
  오른쪽 아래 기본 자리로 스냅.

### C. 커서 추적 (`cursor`)
- 글자 없는 원형 아이콘(지름 36). 막대만 가운데 그린다.
- 매 틱(0.15s)마다 커서 위치를 읽어 커서 우하단으로 살짝 떨어진 곳에 따라붙는다.
  모니터 경계를 자유롭게 넘는다(의도된 동작, 애플 받아쓰기 스타일).

## 시각 사양 (아이콘 모드 B·C)

- 패널/뷰 크기: 36×36, 원형(코너 반경 = 18).
- 배경/테두리/막대 색은 기존 팔레트 재사용(`BG_RGBA`, `BORDER_RGBA`, `JELLY_*`).
- 막대 3개를 원 가운데 정렬. 기존 `jelly_bar_heights(level)` 그대로 사용하되
  36px 원 안에 맞도록 폭/간격만 소폭 조정(막대폭 3.5, 간격 2.5, 중앙정렬).
- "변환 중" 상태: 아이콘 모드는 글자가 없으므로 아이콘을 그대로 두되 살짝
  흐리게(전체 알파 낮춤) 표시해 "처리 중"임을 구분. 알약 모드는 기존처럼 글자.

## 데이터 / 설정

`app_config.py`의 `DEFAULTS`에 키 추가:

```python
"hud_mode": "pill",       # "pill" | "pinned" | "cursor"
"hud_pin_x": None,        # B 모드에서 드래그로 저장된 절대 X (AppKit 좌표, 좌하단 원점)
"hud_pin_y": None,        # B 모드에서 드래그로 저장된 절대 Y
```

- `hud_pin_x/y`가 `None`이면 B 모드 첫 진입 시 주 모니터 오른쪽 아래 기본 자리.
- 알 수 없는 `hud_mode` 값은 `"pill"`로 폴백.

저장/반영 경로는 기존 `domain_context`/`edit_interrupt_mode` 흐름을 그대로 따른다:
1. `whisper-dictation.py` `current_config()`에 세 키 추가.
2. `whisper-dictation.py` `_apply_saved_config()`에서 읽어 `self.hud_mode` 등으로 보관,
   `hud_overlay`에 전달.
3. `dashboard.py` GET `/api/config`에 세 키 노출.
4. `dashboard.py` POST `/api/config`의 `apply()`에서 `hud_mode` 검증·저장.
   드래그 좌표(`hud_pin_x/y`)는 대시보드가 아니라 앱이 드래그 종료 시 직접 저장.

## 컴포넌트별 책임

### `hud_overlay.py`
- `_OverlayView`에 `compact` 플래그 추가. `compact=True`면 원형 배경 + 가운데
  막대만 그리고 라벨 생략. `compact=False`면 현재 알약 그리기 유지.
- `DictationOverlay`에 모드 상태와 진입점 추가:
  - `set_mode(mode, pin_xy)` — 모드 전환 시 패널 크기(92×40 ↔ 36×36)·모양·
    마우스 이벤트 수신 여부·위치 정책을 한 번에 재구성.
  - 위치 정책:
    - `pill`: 기존 하단 중앙 + 커서 모니터 추적.
    - `pinned`: 저장 좌표(없으면 기본 우하단). 커서 추적 안 함.
    - `cursor`: 매 틱 커서 위치로 재배치.
  - 마우스 이벤트: `pinned`만 `setIgnoresMouseEvents_(False)` + 드래그로 이동
    가능(`setMovableByWindowBackground_(True)`). `pill`/`cursor`는 기존처럼
    `True`로 두어 클릭을 가로채지 않음.
  - 드래그로 창이 움직이면 `NSWindowDelegate.windowDidMove_`에서 새 원점을
    콜백으로 앱에 알려 config에 저장.
  - `reposition_to_cursor()` — C 모드에서 매 틱 호출. 커서 좌표 + 오프셋.
  - `clamp_to_visible(x, y)` — 저장 좌표가 어느 화면에도 없으면 기본 우하단 반환.
    (순수 함수에 가깝게 빼서 단위 테스트 대상으로 삼는다.)

### `whisper-dictation.py`
- `_apply_saved_config()`에서 `hud_mode`, `hud_pin_x/y`를 읽어 보관하고
  `overlay.set_mode(...)` 호출(메인 스레드).
- `_tick_overlay()`:
  - 모드가 `cursor`면 매 틱 `overlay.reposition_to_cursor()`.
  - 상태 표시는 모드에 따라: 알약은 "듣는 중"/"변환 중" 글자, 아이콘은 흐림 토글.
- 드래그 저장 콜백: overlay가 새 좌표를 알려오면 `self.hud_pin_x/y` 갱신 후
  `save_settings()`.

### `dashboard.py` + `templates/dashboard.html`
- "음성 인식" 패널에 `<select id="hud-mode" onchange="updateConfig()">` 추가.
  옵션 3개: 알약(기본)/아이콘 고정/아이콘 커서 따라가기.
- `fetchConfig()`에 `hud-mode` 값 세팅, `updateConfig()`에 `hud_mode` 전송.
- 드래그 좌표는 대시보드 UI에 노출하지 않는다(앱이 자동 저장).

## 동작 흐름 (요약)

1. 사용자가 대시보드에서 모드 선택 → POST `/api/config` → 앱이 `set_mode` 적용.
2. 받아쓰기 시작 → `_tick_overlay`가 0.15초마다 레벨 갱신·표시.
   - cursor 모드면 매 틱 커서로 위치 이동.
3. (B 모드) 사용자가 아이콘을 드래그 → `windowDidMove_` → 좌표 config 저장.
4. 받아쓰기 종료 → 기존처럼 `hide()`.

## 에러 처리

- 모든 AppKit 호출은 기존처럼 try/except로 감싸 실패 시 경고만 출력하고
  녹음·변환은 계속된다(기존 견고성 계약 유지).
- 잘못된 `hud_mode`/좌표는 안전한 기본값으로 폴백.

## 테스트

- 단위(pytest): `jelly_bar_heights` 회귀, `clamp_to_visible`(화면 밖 좌표 → 기본
  우하단), `hud_mode` 폴백, config 라운드트립(저장→로드).
- 수동(e2e): 멀티 모니터에서 A(따라옴)/B(고정·드래그·재시작 후 위치 유지)/
  C(커서 추적) 실제 확인. AppKit 드로잉은 자동 검증 불가하므로 육안 확인.

## 범위 밖 (안 건드림)

- 음성 인식·타이핑·녹음·단축키 로직.
- 아이콘 크기 사용자 설정(36 고정. 추후 필요하면 코드 상수로 조정).
- 색/테마 변경, 알약↔아이콘 외 새로운 모양.
- 서브프로세스 HUD, 리뷰 카드 재도입(금지 항목).
