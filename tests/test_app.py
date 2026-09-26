from tasktracker.config import Settings
from tasktracker.main import create_app


def test_sqlite_file_in_a_missing_folder_is_created(tmp_path):
    db_file = tmp_path / "not" / "there" / "yet" / "tasks.db"
    app = create_app(Settings(database_url=f"sqlite:///{db_file.as_posix()}"))
    app.state.engine.dispose()

    assert db_file.exists()


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "/static/js/app.js" in response.text
