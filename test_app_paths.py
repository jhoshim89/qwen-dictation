# test_app_paths.py
import os
import app_paths


def test_resource_path_points_to_existing_template():
    p = app_paths.resource_path("templates", "dashboard.html")
    assert p.endswith(os.path.join("templates", "dashboard.html"))
    assert os.path.exists(p), f"template not found at {p}"


def test_user_data_dir_is_writable_and_created():
    d = app_paths.user_data_dir()
    assert os.path.isdir(d)
    probe = os.path.join(d, ".write_probe")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)


def test_dictionary_path_is_under_user_data_dir():
    assert app_paths.dictionary_path().startswith(app_paths.user_data_dir())


def test_hud_command_includes_hud_script():
    cmd = app_paths.hud_command(max_time=30)
    assert any("hud" in part for part in cmd)
    assert "30" in cmd
