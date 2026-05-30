#!/bin/bash
# A wrapper script to launch the Qwen3-ASR dictation app cleanly.

# Get the directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Activate the virtual environment
if [ ! -d "./venv" ]; then
    echo "Virtual environment not found! Please make sure dependencies are installed."
    exit 1
fi

source ./venv/bin/activate

# Execute the python dictation app, forwarding all arguments
exec python3 whisper-dictation.py "$@"
