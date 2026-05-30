import json
import logging
import os
import threading
from flask import Flask, jsonify, request, render_template_string

# Suppress flask output logs to keep the console clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

flask_app = Flask(__name__)
app_instance = None  # Global reference to StatusBarApp

# Standard templates folder path
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')

@flask_app.route('/')
def home():
    try:
        html_path = os.path.join(TEMPLATES_DIR, 'dashboard.html')
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
        "model_size": getattr(app_instance, 'selected_model', '0.6b'),
        "stream_interval": getattr(app_instance, 'stream_interval', 1.2),
        "max_time": getattr(app_instance, 'max_time', 30),
    })

@flask_app.route('/api/config', methods=['POST'])
def post_config():
    if not app_instance:
        return jsonify({"error": "App instance not initialized"}), 500
        
    data = request.json
    if not data:
        return jsonify({"error": "Invalid request payload"}), 400

    if 'mode' in data:
        try:
            app_instance.set_mode(data['mode'])
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    if 'language' in data:
        app_instance.current_language = data['language']
        app_instance.sync_menu_state()

    if 'model_size' in data:
        app_instance.selected_model = data['model_size']
        print(f"Model size updated to: {app_instance.selected_model}")

    if 'stream_interval' in data:
        app_instance.stream_interval = max(0.8, float(data['stream_interval']))

    if 'max_time' in data:
        app_instance.max_time = max(1, float(data['max_time']))

    return jsonify({"status": "success", "config": get_config().json})

@flask_app.route('/api/status', methods=['GET'])
def get_status():
    if not app_instance:
        return jsonify({"started": False})
    return jsonify({
        "started": app_instance.started,
        "elapsed_time": getattr(app_instance, 'elapsed_time', 0)
    })

@flask_app.route('/api/dictionary', methods=['GET'])
def get_dictionary():
    dict_path = app_paths.dictionary_path()
    if not os.path.exists(dict_path):
        return jsonify({})
    try:
        with open(dict_path, 'r', encoding='utf-8') as f:
            dictionary = json.load(f)
        return jsonify(dictionary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/api/dictionary', methods=['POST'])
def post_dictionary():
    dict_path = app_paths.dictionary_path()
    data = request.json
    if data is None:
        return jsonify({"error": "Invalid request payload"}), 400
        
    try:
        with open(dict_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def start_server(app):
    global app_instance
    app_instance = app
    
    # Run the flask app in a background daemon thread
    def run():
        flask_app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)
        
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    print("Settings Dashboard background server started on http://127.0.0.1:5001")
