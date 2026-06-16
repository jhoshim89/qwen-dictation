---
version: alpha
name: Qwen Dictation
description: "Warm Jelly Voice: 말이 자연스럽게 문장이 되도록 돕는 따뜻하고 반응적인 macOS 로컬 받아쓰기 유틸리티."
colors:
  primary: "#E84762"
  action: "#D13652"
  action-hover: "#C92F4C"
  primary-soft: "#FBE5EA"
  highlight: "#FFB3BF"
  recording: "#E86A67"
  ink: "#422E35"
  text: "#4D3A40"
  muted: "#836C74"
  faint: "#A9959A"
  canvas: "#F7F1E9"
  panel: "#FFFDFC"
  subtle: "#F8E9E8"
  line: "#EADDD8"
typography:
  app-title:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1.25
  heading:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 15px
    fontWeight: 700
    lineHeight: 1.35
  body:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.55
  helper:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Pretendard Variable, Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: 11px
    fontWeight: 700
    lineHeight: 1.4
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
rounded:
  control: 12px
  panel: 20px
  pill: 9999px
components:
  settings-panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: 18px
  primary-button:
    backgroundColor: "{colors.action}"
    textColor: "{colors.panel}"
    rounded: "{rounded.control}"
    height: 38px
  status-pill:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    height: 34px
  recording-hud:
    backgroundColor: "{colors.primary}"
    rounded: "{rounded.pill}"
    size: 76px
  voice-mark:
    backgroundColor: "{colors.canvas}"
    rounded: "{rounded.panel}"
    size: 44px
---

# Qwen Dictation Design Guide

## Overview

Qwen Dictation의 브랜드 컨셉은 **Warm Jelly Voice**다. 따뜻한 크림색 바탕,
선명하지만 부담스럽지 않은 코랄, 둥근 캡슐, 절제된 광택을 사용한다.
사용자가 글을 쓰는 흐름을 방해하지 않으면서 음성이 살아 움직이는 느낌을
전달한다.

공식 앱 아이콘과 설정창/메뉴바 voice mark는 모두 `세로 막대 3개` 실루엣을
사용한다.

## Colors

- **Primary (`#E84762`):** 주요 버튼, 선택 상태, focus ring, 브랜드 파형.
- **Action (`#D13652`) / Action hover (`#C92F4C`):** 흰 글자를 AA 대비로 표시하는 주요 버튼.
- **Primary soft (`#FBE5EA`):** 상태 pill, 선택 배경, 핵심 카드 헤더 tint.
- **Highlight (`#FFB3BF`):** 젤리 표면의 작은 내부 하이라이트.
- **Recording (`#E86A67`):** 녹음 중 상태와 파괴적 동작.
- **Ink (`#422E35`) / Text (`#4D3A40`):** 제목과 본문.
- **Muted (`#836C74`) / Faint (`#A9959A`):** 설명과 메타데이터. 읽어야 하는 작은 힌트에는 `muted`를 사용한다.
- **Canvas (`#F7F1E9`) / Panel (`#FFFDFC`) / Line (`#EADDD8`):** 설정창 배경, 카드, 경계선.

넓은 면적에는 크림과 아이보리를 사용한다. 코랄은 행동과 상태를 알려주는
작은 영역에 집중한다.

## Typography

Pretendard Variable을 로컬 번들해 설정창에 사용한다. 네이티브 HUD는 텍스트를
그리지 않으며, 외부 CDN에 의존하지 않는다.

## Layout

기본 간격은 4px 배수다. 설정창은 넓은 화면에서 좌측 설정 패널 묶음과 우측
단어 등록 패널의 2열 구성으로 표시하고, 좁은 화면에서는 1열로 전환한다.
입력창과 본문 카드는 읽기 쉽도록 비교적 평면적으로 유지한다.

## Elevation & Depth

젤리 효과는 앱 아이콘, 주요 버튼, 상태 pill, 핵심 카드 헤더, HUD에만
사용한다. 설정창 canvas에는 매우 약한 warm radial wash를 허용한다.
모든 카드와 입력창에 광택이나 glow를 반복하지 않는다.

## Shapes

카드는 20px radius, 입력창과 버튼은 12px radius, pill과 HUD 캡슐은 완전히
둥근 형태를 사용한다.

## Components

- **App icon:** 공식 젤리 파형 PNG를 크기별로 리샘플링한다.
- **Voice mark:** 설정창과 메뉴바에서 사용하는 평면 파형 실루엣이다.
- **Primary button:** 코랄 그라데이션, 얇은 내부 하이라이트, 작은 그림자를 사용한다.
- **Status pill:** 옅은 핑크 tint와 작은 젤리 점을 사용한다.
- **Settings panel:** 아이보리 카드다. 단축키와 단어 등록 헤더에만 핑크 tint를 허용한다.
- **Recording HUD:** 중앙이 가장 높은 코랄 젤리 막대 3개가 음량에 따라 부드럽게 움직인다.

## Do's and Don'ts

- Do: 로고와 HUD의 캡슐 실루엣을 일관되게 사용한다.
- Do: 일반 텍스트의 WCAG AA 대비 비율 4.5:1 이상을 유지한다.
- Do: 음성 반응은 작고 부드럽게 움직이게 한다.
- Don't: 넓은 면적을 핫핑크로 채우지 않는다.
- Don't: 모든 카드에 유리 효과나 glow를 반복하지 않는다.
- Don't: 외부 CDN에 의존하지 않는다.
