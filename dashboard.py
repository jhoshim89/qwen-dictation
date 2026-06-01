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
