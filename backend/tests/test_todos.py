"""The to-do list: CRUD, persistence, duplicates, ownership and validation."""


def test_create_list_edit_complete_delete(user_client):
    c, _ = user_client
    r = c.post("/api/todos", json={"title": "  Finish   chapter 3 ", "notes": " before Friday ", "due_date": "2030-01-05"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["title"] == "Finish chapter 3" and task["notes"] == "before Friday" and task["completed"] is False

    tid = task["id"]
    assert [t["id"] for t in c.get("/api/todos").json()] == [tid], "persisted across requests"

    edited = c.patch(f"/api/todos/{tid}", json={"title": "Finish chapter 4", "due_date": None}).json()
    assert edited["title"] == "Finish chapter 4" and edited["due_date"] is None and edited["notes"] == "before Friday"

    done = c.patch(f"/api/todos/{tid}", json={"completed": True}).json()
    assert done["completed"] is True and done["completed_at"]
    undone = c.patch(f"/api/todos/{tid}", json={"completed": False}).json()
    assert undone["completed"] is False and undone["completed_at"] is None

    assert c.delete(f"/api/todos/{tid}").status_code == 204
    assert c.get("/api/todos").json() == []


def test_duplicate_open_tasks_are_refused_but_finished_ones_can_repeat(user_client):
    c, _ = user_client
    first = c.post("/api/todos", json={"title": "Return the library book"}).json()
    assert c.post("/api/todos", json={"title": "return  the LIBRARY book"}).status_code == 409

    c.patch(f"/api/todos/{first['id']}", json={"completed": True})
    second = c.post("/api/todos", json={"title": "Return the library book"})
    assert second.status_code == 201, "a finished task doesn't block doing it again"

    assert c.patch(f"/api/todos/{first['id']}", json={"completed": False}).status_code == 409, "reopening would duplicate"
    other = c.post("/api/todos", json={"title": "Something else"}).json()
    assert c.patch(f"/api/todos/{other['id']}", json={"title": "Return the library book"}).status_code == 409


def test_validation(user_client):
    c, _ = user_client
    assert c.post("/api/todos", json={"title": "   "}).status_code == 422
    assert c.post("/api/todos", json={"title": "x" * 201}).status_code == 422
    assert c.post("/api/todos", json={"title": "ok", "notes": "n" * 1001}).status_code == 422
    assert c.post("/api/todos", json={"title": "ok", "due_date": "not-a-date"}).status_code == 422
    tid = c.post("/api/todos", json={"title": "valid"}).json()["id"]
    assert c.patch(f"/api/todos/{tid}", json={"title": None}).status_code == 422


def test_clear_completed_keeps_open_tasks(user_client):
    c, _ = user_client
    keep = c.post("/api/todos", json={"title": "keep me"}).json()
    gone = c.post("/api/todos", json={"title": "finished"}).json()
    c.patch(f"/api/todos/{gone['id']}", json={"completed": True})
    assert c.delete("/api/todos/completed").status_code == 204
    assert [t["id"] for t in c.get("/api/todos").json()] == [keep["id"]]


def test_ownership_and_auth(user_client, other_client, client):
    c, _ = user_client
    o, _ = other_client
    tid = c.post("/api/todos", json={"title": "private"}).json()["id"]
    assert o.get("/api/todos").json() == []
    assert o.patch(f"/api/todos/{tid}", json={"completed": True}).status_code == 404
    assert o.delete(f"/api/todos/{tid}").status_code == 404
    assert client.get("/api/todos").status_code == 401
    assert client.post("/api/todos", json={"title": "x"}).status_code == 401
