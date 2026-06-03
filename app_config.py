# app_config.py
"""사용자 설정을 ~/.qwen-dictation/config.json 에 읽고 쓰는 모듈.

설정은 사용자 데이터 디렉터리에 저장되어 앱(.app) 재시작 후에도 유지된다.
"""
import json
import os

import app_paths

# max_time=0 은 "자동중단 없음(무제한)" 을 뜻한다.
DEFAULTS = {
    "language": "ko",
    "max_time": 300,
    "input_device": "MATA STUDIO C10",
    "hold_key": "cmd_r",
    "toggle_key": "alt_r",
    "min_volume": 35,
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
    return cfg


def save_config(cfg):
    """DEFAULTS 의 키만 추려서 저장(미지의 키 무시)."""
    try:
        data = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"Config save error: {exc}")
