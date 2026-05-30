# test_hud_command.py
import os
import sys
import app_paths


def test_hud_command_uses_current_interpreter():
    cmd = app_paths.hud_command(max_time=12)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("hud.py")
    assert "--max_time" in cmd
    assert "12" in cmd


def test_hud_script_exists_at_resource_path():
    assert os.path.exists(app_paths.resource_path("hud.py"))
