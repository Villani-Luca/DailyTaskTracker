def test_create_list_update_folder(client, make_folder):
    make_folder("Work", "#2a78d6")
    personal = make_folder("personal", "#eb6834", description="Errands")

    names = [f["name"] for f in client.get("/api/folders").json()]
    assert names == ["personal", "Work"]  # case-insensitive alphabetical

    response = client.patch(f"/api/folders/{personal['id']}", json={"color": "#1baf7a"})
    assert response.status_code == 200
    assert response.json()["color"] == "#1baf7a"
    assert response.json()["description"] == "Errands"


def test_folder_names_are_unique_ignoring_case(client, make_folder):
    make_folder("Work")
    response = client.post("/api/folders", json={"name": "  WORK ", "color": "#000000"})
    assert response.status_code == 409


def test_folder_color_must_be_hex(client):
    response = client.post("/api/folders", json={"name": "Work", "color": "blue"})
    assert response.status_code == 422


def test_folder_fields_cannot_be_nulled(client, make_folder):
    folder = make_folder()
    response = client.patch(f"/api/folders/{folder['id']}", json={"name": None})
    assert response.status_code == 422


def test_deleting_a_folder_moves_its_tasks_to_the_inbox(client, make_folder, make_task):
    folder = make_folder()
    task = make_task(folder_id=folder["id"])

    assert client.delete(f"/api/folders/{folder['id']}").status_code == 204

    assert client.get(f"/api/folders/{folder['id']}").status_code == 404
    assert client.get(f"/api/tasks/{task['id']}").json()["folder_id"] is None
    assert [t["id"] for t in client.get("/api/tasks", params={"inbox": True}).json()] == [
        task["id"]
    ]
