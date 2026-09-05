import os
import stat

import app_paths


def test_resource_path_points_to_existing_template():
    assert os.path.exists(app_paths.resource_path("templates", "dashboard.html"))


def test_user_files_are_under_user_data_dir():
    base = app_paths.user_data_dir()
    assert app_paths.vocabulary_path().startswith(base)
    assert app_paths.history_path().startswith(base)
    assert app_paths.vocabulary_candidates_path().startswith(base)


def test_user_data_directory_is_private(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda value: str(fake_home) if value == "~" else value,
    )

    path = app_paths.user_data_dir()

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
