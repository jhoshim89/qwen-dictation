import os

import app_paths


def test_resource_path_points_to_existing_template():
    assert os.path.exists(app_paths.resource_path("templates", "dashboard.html"))


def test_user_files_are_under_user_data_dir():
    base = app_paths.user_data_dir()
    assert app_paths.vocabulary_path().startswith(base)
    assert app_paths.history_path().startswith(base)
    assert app_paths.vocabulary_candidates_path().startswith(base)
