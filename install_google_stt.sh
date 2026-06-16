#!/bin/bash
# Optional Google Speech-to-Text runtime.
set -e
cd "$(dirname "$0")"

./venv/bin/python -m pip install 'google-cloud-speech>=2.40,<3'

cat <<'MSG'
Google Speech-to-Text package installed.

Before selecting Google in Qwen Dictation, configure Application Default Credentials:

  gcloud auth application-default login

or set GOOGLE_APPLICATION_CREDENTIALS to a Speech-enabled service account JSON.
MSG
