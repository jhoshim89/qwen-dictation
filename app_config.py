# app_config.py
"""사용자 설정을 ~/.qwen-dictation/config.json 에 읽고 쓰는 모듈.

설정은 사용자 데이터 디렉터리에 저장되어 앱(.app) 재시작 후에도 유지된다.
"""
import json
import os

import app_paths
import asr_engines

# max_time=0 은 "자동중단 없음(무제한)" 을 뜻한다.
DEFAULTS = {
    "language": "ko",
    "max_time": 300,
    "input_device": "",
    "hold_key": "ctrl_r",
    "toggle_key": "alt_r",
    "min_volume": 8,
    "asr_engine": asr_engines.DEFAULT_ASR_ENGINE,
    # 받아쓰기 도중 사용자가 키보드로 직접 고쳤을 때의 동작.
    # "continue": 수정 보존하고 세션 유지(다시 말하면 이어서), "stop": 즉시 종료.
    "edit_interrupt_mode": "stop",
    # 홀드 키를 떼면 마지막 글자까지 입력한 뒤 자동으로 Enter 를 보낼지.
    "hold_send_enter": True,
    # 받아쓰기 분야 머리말(자유 문장). 매 변환의 context 앞에 붙어 모델을 그 분야로
    # 편향한다. 예: "수의안과 진료. 안과 질환과 검사 용어 위주". 빈 문자열이면 미사용.
    "domain_context": "",
    # 받아쓰기 표시(HUD) 모드: "pill"(알약·기본) | "pinned"(아이콘 고정) | "cursor"(커서 추적).
    "hud_mode": "pill",
    # B(고정) 모드에서 드래그로 저장된 절대 좌표(AppKit, 좌하단 원점). None이면 기본 우하단.
    "hud_pin_x": None,
    "hud_pin_y": None,
    "max_time_zero_migrated": True,
}


def config_path():
    return os.path.join(app_paths.user_data_dir(), "config.json")


def load_config():
    """저장된 설정을 읽어 DEFAULTS 위에 덮어 반환. 없거나 깨지면 DEFAULTS."""
    cfg = dict(DEFAULTS)
    saved = {}
    try:
        p = config_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k in DEFAULTS:
                    if k in saved:
                        cfg[k] = saved[k]
    except Exception as exc:
        print(f"Config load error: {exc}")
    # Earlier builds used 0 for unlimited by default. Migrate that legacy value
    # once, while preserving a later explicit user choice to return to unlimited.
    if "max_time_zero_migrated" not in saved:
        if cfg.get("max_time") == 0:
            cfg["max_time"] = 300
        cfg["max_time_zero_migrated"] = True
        save_config(cfg)
    cfg["asr_engine"] = asr_engines.normalize_asr_engine(cfg.get("asr_engine"))
    return cfg


def save_config(cfg):
    """DEFAULTS 의 키만 추려서 저장(미지의 키 무시)."""
    try:
        data = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"Config save error: {exc}")
