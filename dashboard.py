import json
import logging
import os
import threading
from flask import Flask, jsonify, request, render_template_string

import app_paths
import vocabulary

# Suppress flask output logs to keep the console clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

flask_app = Flask(__name__)
app_instance = None  # Global reference to StatusBarApp

@flask_app.route('/')
def home():
    try:
        html_path = app_paths.resource_path('templates', 'dashboard.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return render_template_string(content)
    except Exception as e:
        return f"Error loading dashboard: {e}", 500

@flask_app.route('/api/config', methods=['GET'])
def get_config():
    if not app_instance:
        return jsonify({"error": "App instance not initialized"}), 500

    return jsonify({
        "mode": app_instance.mode,
        "language": app_instance.current_language or "ko",
        "languages": app_instance.languages,
        "k_double_cmd": getattr(app_instance, 'k_double_cmd', False),
        "model_size": getattr(app_instance, 'selected_model', '1.7b'),
        "stream_interval": getattr(app_instance, 'stream_interval', 1.2),
        "max_time": getattr(app_instance, 'max_time', 30),
        "hotkey_mode": getattr(app_instance, 'hotkey_mode', 'multi'),
        "hold_key": getattr(app_instance, 'hold_key', 'alt_r'),
        "toggle_key": getattr(app_instance, 'toggle_key', 'cmd_r'),
    })

@flask_app.route('/api/config', methods=['POST'])
def post_config():
    if not app_instance:
        return jsonify({"error": "App instance not initialized"}), 500

    data = request.json
    if not data:
        return jsonify({"error": "Invalid request payload"}), 400

    hotkey_changed = any(k in data for k in ("hotkey_mode", "hold_key", "toggle_key"))

    def apply():
        if 'mode' in data:
            app_instance.set_mode(data['mode'])
        if 'language' in data:
            app_instance.current_language = data['language']
            app_instance.sync_menu_state()
        if 'model_size' in data:
            app_instance.selected_model = data['model_size']
            print(f"Model size updated to: {app_instance.selected_model}")
        if 'stream_interval' in data:
            app_instance.stream_interval = max(0.8, float(data['stream_interval']))
        if 'max_time' in data:
            app_instance.max_time = max(0, float(data['max_time']))
        if hotkey_changed:
            mode = data.get("hotkey_mode", getattr(app_instance, "hotkey_mode", "multi"))
            hold = data.get("hold_key", getattr(app_instance, "hold_key", "alt_r"))
            toggle = data.get("toggle_key", getattr(app_instance, "toggle_key", "cmd_r"))
            valid_keys = ("alt_r", "cmd_r", "ctrl_r", "shift_r")
            if mode not in ("multi", "single", "double"):
                raise ValueError("unknown hotkey mode")
            if mode == "multi" and (hold == toggle or hold not in valid_keys or toggle not in valid_keys):
                raise ValueError("hold/toggle keys must differ and be valid")
            app_instance.hotkey_mode = mode
            app_instance.hold_key = hold
            app_instance.toggle_key = toggle
        if hasattr(app_instance, "save_settings"):
            app_instance.save_settings()
        if hotkey_changed and hasattr(app_instance, "apply_hotkey_config"):
            app_instance.apply_hotkey_config()

    try:
        if hasattr(app_instance, "dispatch_to_main"):
            app_instance.dispatch_to_main(apply, wait=True)
        else:
            apply()
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"status": "success", "config": get_config().json})

@flask_app.route('/api/status', methods=['GET'])
def get_status():
    if not app_instance:
        return jsonify({"started": False})
    return jsonify({
        "started": app_instance.started,
        "elapsed_time": getattr(app_instance, 'elapsed_time', 0)
    })

@flask_app.route('/api/selftest', methods=['POST'])
def selftest():
    """엔진 자가검증: 마이크로 N초 녹음 → Qwen 변환 → 텍스트 반환.
    앱 프로세스(마이크 권한 보유)에서 도니, 원격(SSH)에서 스피커로 소리를 내며
    이 엔드포인트를 호출하면 단축키/타이핑 없이 '스피커→마이크→변환' 전 구간을 검증할 수 있다.
    localhost(127.0.0.1) 전용. peak/rms 로 실제 소리가 잡혔는지도 함께 확인한다."""
    if not app_instance or not getattr(app_instance, 'recorder', None):
        return jsonify({"ok": False, "error": "app/recorder not ready"}), 503
    try:
        import tempfile
        import numpy as np
        import pyaudio
        import soundfile as sf
        seconds = float((request.json or {}).get("seconds", 5)) if request.is_json else 5.0
        seconds = max(1.0, min(15.0, seconds))
        pa = pyaudio.PyAudio()
        dev = pa.get_default_input_device_info().get("name")
        st = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        frames = []
        for _ in range(int(16000 / 1024 * seconds)):
            frames.append(st.read(1024, exception_on_overflow=False))
        st.stop_stream(); st.close(); pa.terminate()
        raw = b"".join(frames)
        a = np.frombuffer(raw, dtype=np.int16)
        peak = int(np.max(np.abs(a.astype(np.int32)))) if a.size else 0
        rms = int(np.sqrt(np.mean(a.astype(np.float64) ** 2))) if a.size else 0
        path = tempfile.gettempdir() + "/qwen_selftest.wav"
        sf.write(path, a.astype(np.float32) / 32768.0, 16000)
        text = app_instance.recorder.transcriber.transcribe_file(
            path, language=app_instance.current_language, model_size=app_instance.selected_model)
        return jsonify({"ok": True, "device": dev, "seconds": seconds,
                        "peak": peak, "rms": rms, "text": text,
                        "language": app_instance.current_language,
                        "model": app_instance.selected_model})
    except Exception as e:
        return jsonify({"ok": False, "error": repr(e)}), 500

@flask_app.route('/api/dictate_test', methods=['POST'])
def dictate_test():
    """단축키와 동일한 받아쓰기 한 사이클을 localhost 에서 트리거한다(물리 키 없이).
    start_app → N초 녹음·스트리밍 타이핑(포커스된 앱에 type_diff) → stop_app.
    원격(SSH)에서 스피커로 소리를 내며 호출하면, 마이크→변환→실제 타이핑까지 전 구간을
    포커스된 입력창(예: 크롬 textarea)에서 검증할 수 있다. localhost 전용."""
    if not app_instance or not getattr(app_instance, 'recorder', None):
        return jsonify({"ok": False, "error": "app/recorder not ready"}), 503
    try:
        import time
        seconds = float((request.json or {}).get("seconds", 6)) if request.is_json else 6.0
        seconds = max(2.0, min(15.0, seconds))
        app_instance.dispatch_to_main(app_instance.start_app, None, wait=True)
        time.sleep(seconds)
        app_instance.dispatch_to_main(app_instance.stop_app, None, wait=True)
        time.sleep(1.2)  # 정지 후 마지막 스트리밍 tick 이 타이핑을 끝내도록
        rec = app_instance.recorder
        typed = (getattr(rec, 'committed_text', '') or '') + (getattr(rec, 'last_typed', '') or '')
        return jsonify({"ok": True, "seconds": seconds,
                        "committed": getattr(rec, 'committed_text', ''),
                        "last_typed": getattr(rec, 'last_typed', '')})
    except Exception as e:
        return jsonify({"ok": False, "error": repr(e)}), 500

@flask_app.route('/api/vocabulary', methods=['GET'])
def get_vocabulary():
    return jsonify(vocabulary.load_vocabulary())

@flask_app.route('/api/vocabulary', methods=['POST'])
def post_vocabulary():
    data = request.json
    if not isinstance(data, list):
        return jsonify({"error": "expected a list of words"}), 400
    cleaned = vocabulary.save_vocabulary(data)
    return jsonify(cleaned)

def start_server(app):
    global app_instance
    app_instance = app

    # Run the flask app in a background daemon thread
    def run():
        flask_app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    print("Settings Dashboard background server started on http://127.0.0.1:5001")
