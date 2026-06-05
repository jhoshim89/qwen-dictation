# 대시보드 좌우 균형 레이아웃 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`).

**Goal:** 대시보드 좌우 두 열의 높이를 맞추되, 단어 입력칸은 작게 유지하고 빈 칸이 안 생기게 한다.

**Architecture:** 4개 패널을 2+2로 재배치한다 — 좌열: 받아쓰기 표시 + 단어 등록, 우열: 단축키 + 음성 인식. 동일 너비 2열에 `align-items:stretch`. 단어 등록의 textarea가 `min-height`(180)로 좌열 높이를 정하고, 우열의 음성 인식 패널이 `flex:1`로 남는 높이를 채워 두 열 끝선이 일치한다. main을 화면 높이에 묶지 않아(자연 높이) 입력칸이 화면 크기에 따라 거대해지지 않는다.

**Tech Stack:** Flask 템플릿(HTML) + CSS. 코드 로직 변경 없음.

**검증 완료:** 브라우저에서 DOM을 실제로 재배치한 프로토타입으로 측정함 — 좌우 끝선 일치(둘 다 900), 입력칸 180px, 음성 인식 아래 빈 칸 0, 고급 설정 아래 빈 칸 없음, main 높이 852(화면 1189에 안 묶임).

대상 파일: `templates/dashboard.html` (단일 파일)

---

## Task 1: 본문을 2열(.col)로 재배치

**Files:**
- Modify: `templates/dashboard.html` (`<main>` 본문 구조)

기존 구조:
```
<main>
  <div class="stack"> [받아쓰기 표시] [단축키] [음성 인식] </div>
  <section class="panel main-panel"> [단어 등록 …] </section>
</main>
```
새 구조(좌: 받아쓰기 표시 + 단어 등록 / 우: 단축키 + 음성 인식):
```
<main>
  <div class="col">
    [받아쓰기 표시 section]      ← 기존 #hud-panel 그대로
    [단어 등록 section.main-panel] ← 기존 것 그대로, 이 위치로 이동
  </div>
  <div class="col">
    [단축키 section.panel.tint]   ← 기존 그대로
    [음성 인식 section.recognition-panel] ← 기존 그대로
  </div>
</main>
```

- [ ] **Step 1: `<main>` 여는 태그~ 단어 등록 섹션까지 재구성**

`<main>\n<div class="stack">` 를 `<main>\n<div class="col">` 로 바꾸고, `음성 인식` 섹션(`<section class="panel recognition-panel">…</section>`)을 좌열에서 빼낸다. `</div>`(stack 닫힘) 위치를 `받아쓰기 표시` 섹션 다음으로 옮기고, 그 자리에 `단어 등록`(main-panel) 섹션을 넣는다. 그다음 우열 `<div class="col">` 를 열어 `단축키` + `음성 인식` 섹션을 넣고 닫는다.

결과 골격(섹션 내부 마크업은 기존 것 그대로 이동):
```html
<main>
<div class="col">
<section class="panel" id="hud-panel">…받아쓰기 표시 (기존 그대로)…</section>
<section class="panel main-panel">…단어 등록 tabs + view-vocab + view-history (기존 그대로)…</section>
</div>
<div class="col">
<section class="panel tint">…단축키 (기존 그대로)…</section>
<section class="panel recognition-panel">…음성 인식 (기존 그대로)…</section>
</div>
</main>
```

- [ ] **Step 2: 문법/렌더 확인**

Run: `./venv/bin/pytest test_dashboard_paths.py -q`
Expected: PASS (`/` 라우트 200, 자산 라우트 정상)

---

## Task 2: 2열 균형 CSS

**Files:**
- Modify: `templates/dashboard.html` (`<style>`)

- [ ] **Step 1: main 2열 + 동일 너비 + stretch**

`main{…}` 규칙에서 `grid-template-columns` 를 `1fr 1fr` 로, `align-items` 를 `stretch` 로 둔다. 높이 묶음(`height`/`min-height:calc(100vh …)`)은 두지 않는다(자연 높이). 즉:
```css
main{display:grid;grid-template-columns:1fr 1fr;align-items:stretch;gap:14px;max-width:1060px;margin:0 auto;padding:14px 24px 20px}
```

- [ ] **Step 2: .col + 패널 채움 규칙 추가**

`<style>` 안(미디어쿼리 앞)에 추가:
```css
.col{display:flex;flex-direction:column;gap:14px;min-height:0}
.main-panel{flex:1;min-height:0}
.recognition-panel{flex:1;min-height:0}
#vocab-list{flex:1;min-height:180px;height:auto}
```
- `.main-panel`(단어 등록)이 좌열에서 자라고, 그 안 `#vocab-list` textarea 가 `flex:1;min-height:180` 으로 좌열 높이를 결정(약 180px 유지).
- `.recognition-panel`(음성 인식)이 우열에서 `flex:1` 로 남는 높이를 채워 우열 끝선을 좌열에 맞춘다.

- [ ] **Step 3: 옛 .stack / #vocab-list 충돌 규칙 정리**

기존 `.stack{…}` 규칙들과 `#vocab-list{flex:none;height:180px}` 는 더 이상 안 쓰거나 충돌하므로 제거/갱신한다(위 Step 2 의 `#vocab-list` 규칙이 최종이 되도록). `.stack` 셀렉터가 남아도 HTML 에서 안 쓰면 무해하나, 혼동을 줄이려 `#vocab-list{flex:none;height:180px}` 한 줄은 Step 2 규칙으로 대체한다.

- [ ] **Step 4: 브라우저 실측 (작성자가 Claude in Chrome 으로 직접)**

`http://127.0.0.1:5001` 새로고침 후 측정:
  - 좌열 bottom == 우열 bottom (±5px) — 끝선 일치
  - `#vocab-list` 높이 ≈ 180px — 입력칸 작음
  - 음성 인식 패널 아래 빈 칸 ≈ 0
  - 고급 설정 펼쳤을 때 페이지 스크롤로 닿음(작은 창)
Expected: 위 4개 모두 충족(프로토타입에서 확인된 값과 일치).

- [ ] **Step 5: 전체 라우트 회귀 + 커밋**

```bash
./venv/bin/pytest -q
git add templates/dashboard.html
git commit -m "feat: balanced two-column dashboard (rebalanced panels, matched heights)"
```

---

## Self-Review

- 스펙 커버리지: 좌우 끝선 일치(Task2 stretch+flex), 입력칸 작게 유지(min-height:180 driver), 빈 칸 없음(음성인식 flex-fill, 고급설정 자연 바닥), 화면-높이 비묶음(main 높이 미지정) — 모두 태스크에 매핑.
- 플레이스홀더: 없음(이동은 기존 섹션 verbatim, CSS 는 실제 값 명시).
- 일관성: `.col` / `flex:1` / `min-height:180` 명칭·값 일관. 프로토타입 측정값(900/180/0/17)과 동일 접근.
