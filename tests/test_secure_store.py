import json
import os
import stat

import secure_store
import temporary_audio


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_atomic_json_is_private_and_replaces_complete_value(tmp_path):
    path = tmp_path / "state.json"
    secure_store.atomic_write_json(path, {"value": "one"})
    secure_store.atomic_write_json(path, {"value": "two"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": "two"}
    assert _mode(path) == 0o600
    assert not list(tmp_path.glob(".state.json.*"))


def test_private_append_tightens_existing_permissions(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("first\n", encoding="utf-8")
    os.chmod(path, 0o644)

    secure_store.append_private_text(path, "second\n")

    assert path.read_text(encoding="utf-8") == "first\nsecond\n"
    assert _mode(path) == 0o600


def test_temporary_wav_is_private_and_removed_even_on_error():
    seen = None
    try:
        with temporary_audio.temporary_wav() as path:
            seen = path
            assert os.path.exists(path)
            assert _mode(path) == 0o600
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert seen is not None
    assert not os.path.exists(seen)
