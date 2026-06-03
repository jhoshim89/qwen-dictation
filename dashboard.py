import json
import logging
import os
import threading
from flask import Flask, jsonify, request, render_template_string, send_from_directory

import app_paths
import dictation_history
import hotkeys
import vocabulary

# Suppress flask output logs to keep the console clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

flask_app = Flask(__name__)
app_instance = None  # Global reference to StatusBarApp


def list_input_devices():
    """Return available microphone names for the settings dashboard."""
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            return [
                pa.get_device_info_by_index(index).get("name", "")
                for index in range(pa.get_device_count())
                if int(pa.get_device_info_by_index(index).get("maxInputChannels", 0)) > 0
            ]
        finally:
            pa.terminate()
    except Exception as exc:
        print(f"Input device list error: {exc}")
        return []


@flask_app.route('/')
def home():
    try:
        html_path = app_paths.resource_path('templates', 'dashboard.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return render_template_string(content)
    except Exception as e:
        return f"Error loading dashboard: {e}", 500

@flask_app.route('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(app_paths.resource_path('assets'), filename)

@flask_app.route('/api/config', methods=['GET'])
def get_config():
    if not app_instance:
        return jsonify({"error": "App instance not initialized"}), 500

    return jsonify({
        "language": app_instance.current_language or "ko",
        "languages": app_instance.languages,
        "max_time": getattr(app_instance, 'max_time', 300),
        "input_device": getattr(app_instance, 'input_device', ''),
        "input_devices": list_input_devices(),
        "hold_key": getattr(app_instance, 'hold_key', 'cmd_r'),
        "toggle_key": getattr(app_instance, 'toggle_key', 'alt_r'),
        "min_volume": getattr(app_instance, 'min_volume', 35),
        "edit_interrupt_mode": getattr(app_instance, 'edit_interrupt_mode', 'continue'),
    })

@flask_app.route('/api/config', methods=['POST'])
def post_config():
    if not app_instance:
        return jsonify({"error": "App instance not initialized"}), 500

    data = request.json
    if not data:
        return jsonify({"error": "Invalid request payload"}), 400

    hotkey_changed = any(k in data for k in ("hold_key", "toggle_key"))

    def apply():
        if 'language' in data:
            app_instance.current_language = data['language']
            app_instance.sync_menu_state()
        if 'max_time' in data:
            app_instance.max_time = max(0, float(data['max_time']))
        if 'input_device' in data:
            app_instance.input_device = str(data['input_device'] or "")
        if 'min_volume' in data:
            app_instance.min_volume = max(1, min(100, int(float(data['min_volume']))))
            if getattr(app_instance, "recorder", None) is not None:
                app_instance.recorder.transcriber.min_volume = app_instance.min_volume
        if 'edit_interrupt_mode' in data:
            mode = str(data['edit_interrupt_mode'])
            app_instance.edit_interrupt_mode = mode if mode in ("continue", "stop") else "continue"
        if hotkey_changed:
            hold = data.get("hold_key", getattr(app_instance, "hold_key", "cmd_r"))
            toggle = data.get("toggle_key", getattr(app_instance, "toggle_key", "alt_r"))
            ok, error = hotkeys.validate_hotkey_pair(hold, toggle)
            if not ok:
                raise ValueError(error)
            app_instance.hold_key = hotkeys.normalize_hotkey(hold)
            app_instance.toggle_key = hotkeys.normalize_hotkey(toggle)
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
        preferred = getattr(app_instance, "input_device", "")
        selected = next(
            (
                pa.get_device_info_by_index(index)
                for index in range(pa.get_device_count())
                if pa.get_device_info_by_index(index).get("name") == preferred
                and int(pa.get_device_info_by_index(index).get("maxInputChannels", 0)) > 0
            ),
            None,
        )
        dev = selected or pa.get_default_input_device_info()
        st = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True,
                     input_device_index=dev.get("index"), frames_per_buffer=1024)
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
            path, language=app_instance.current_language)
        return jsonify({"ok": True, "device": dev.get("name"), "seconds": seconds,
                        "peak": peak, "rms": rms, "text": text,
                        "language": app_instance.current_language,
                        "model": "Qwen3-ASR 1.7B"})
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


@flask_app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(dictation_history.load_history())


@flask_app.route('/api/history/<history_id>/correction', methods=['POST'])
def post_history_correction(history_id):
    corrected_text = (request.json or {}).get("corrected_text", "")
    try:
        return jsonify({"candidates": dictation_history.record_correction(history_id, corrected_text)})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@flask_app.route('/api/vocabulary/candidates', methods=['GET'])
def get_vocabulary_candidates():
    return jsonify(dictation_history.list_candidates())


@flask_app.route('/api/vocabulary/candidates/accept', methods=['POST'])
def accept_vocabulary_candidate():
    try:
        words = dictation_history.accept_candidate((request.json or {}).get("term"))
        return jsonify({"vocabulary": words, "candidates": dictation_history.list_candidates()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@flask_app.route('/api/vocabulary/candidates/dismiss', methods=['POST'])
def dismiss_vocabulary_candidate():
    try:
        dictation_history.dismiss_candidate((request.json or {}).get("term"))
        return jsonify(dictation_history.list_candidates())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@flask_app.route('/api/vocabulary/candidates/reset-dismissed', methods=['POST'])
def reset_dismissed_vocabulary_candidates():
    dictation_history.reset_dismissed()
    return jsonify(dictation_history.list_candidates())

def start_server(app):
    global app_instance
    app_instance = app

    # Run the flask app in a background daemon thread
    def run():
        flask_app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    print("Settings Dashboard background server started on http://127.0.0.1:5001")
