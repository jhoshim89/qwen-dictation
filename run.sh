#!/bin/bash
# A wrapper script to launch the Qwen3-ASR dictation app cleanly.
set -eu

# Get the directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Use the virtual environment interpreter directly so a broken/partial
# activate script cannot silently fall back to the system python3.
if [ ! -x "./venv/bin/python3" ]; then
    echo "Virtual environment not found! Please make sure dependencies are installed."
    exit 1
fi

# Execute the python dictation app, forwarding all arguments
exec ./venv/bin/python3 whisper-dictation.py "$@"
