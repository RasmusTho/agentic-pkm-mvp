def test_root_ok(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_create_and_list_items(client):
    r = client.post("/items", params={"name": "foo"})
    assert r.status_code == 200
    created = r.json()
    assert created["name"] == "foo"

    r2 = client.get("/items")
    assert r2.status_code == 200
    names = [i["name"] for i in r2.json()]
    assert "foo" in names
def test_duplicate_name_returns_409(client):
    r1 = client.post("/items", params={"name": "dup"})
    assert r1.status_code == 200
    r2 = client.post("/items", params={"name": "dup"})
    assert r2.status_code == 409
    assert r2.json()["detail"].lower().startswith("item already exists")
