"""Phase 1: the /teacher JSON API knows who is calling when a Bearer token is sent.

No header = legacy mode (old /teacher pages, sample tests) and keeps working unchanged.
    uv run pytest tests/test_teacher_auth.py
"""
import pytest

MONA = {"Authorization": "Bearer demo-token-mona-456"}   # teacher u_mona (demo account)
SARA = {"Authorization": "Bearer demo-token-sara-123"}   # student u_sara (demo account)


@pytest.fixture
def client(monkeypatch, tmp_path):
    pytest.importorskip("langgraph")
    from fastapi.testclient import TestClient

    from rafeeq.platform import service as platform

    monkeypatch.setattr("rafeeq.teacher.lecturer.settings.DATABASE_URL", None)  # in-memory store
    platform.set_store(platform.PlatformStore(tmp_path / "platform"))
    from rafeeq.main import app

    with TestClient(app) as c:
        yield c
    platform.set_store(None)


def test_no_header_keeps_the_legacy_behaviour(client):
    assert client.get("/teacher/profile", params={"teacher_id": "nobody"}).status_code == 404
    assert client.get("/teacher/sessions", params={"teacher_id": "nobody"}).status_code == 200


def test_unknown_token_is_401(client):
    res = client.get("/teacher/sessions", params={"teacher_id": "u_mona"},
                     headers={"Authorization": "Bearer nope"})
    assert res.status_code == 401


def test_a_student_token_is_refused(client):
    res = client.get("/teacher/sessions", params={"teacher_id": "u_sara"}, headers=SARA)
    assert res.status_code == 403


def test_a_teacher_cannot_name_another_teacher(client):
    for path in ("/teacher/sessions", "/teacher/profile"):
        res = client.get(path, params={"teacher_id": "someone-else"}, headers=MONA)
        assert res.status_code == 403, path


def test_a_teacher_can_use_their_own_id(client):
    assert client.get("/teacher/sessions", params={"teacher_id": "u_mona"}, headers=MONA).status_code == 200


def test_profile_put_is_bound_to_the_token(client):
    body = {"teacher_id": "someone-else", "name": "Mona Test"}
    assert client.put("/teacher/profile", json=body, headers=MONA).status_code == 403
    ok = client.put("/teacher/profile", json={**body, "teacher_id": "u_mona"}, headers=MONA)
    assert ok.status_code == 200 and ok.json()["teacher_id"] == "u_mona"


def test_avatar_upload_is_bound_to_the_token(client):
    files = {"image": ("me.png", b"\x89PNG\r\n", "image/png")}
    res = client.post("/teacher/avatar", data={"teacher_id": "someone-else"}, files=files, headers=MONA)
    assert res.status_code == 403


# ------------------------------------------------------------------ asset library API
VIDEO = {"title": "Cell division", "source_url": "https://www.youtube.com/watch?v=abc123",
         "start_sec": 75, "end_sec": 130, "room_id": "r_1"}


def test_assets_always_need_a_teacher_token(client):
    assert client.get("/teacher/assets").status_code == 401
    assert client.post("/teacher/assets", json=VIDEO).status_code == 401
    assert client.get("/teacher/assets", headers=SARA).status_code == 403


def test_save_a_video_moment_and_list_it(client):
    res = client.post("/teacher/assets", json=VIDEO, headers=MONA)
    assert res.status_code == 201
    asset = res.json()
    assert asset["origin"] == "external" and asset["kind"] == "source_video" and asset["file_url"] is None

    listed = client.get("/teacher/assets", params={"room_id": "r_1"}, headers=MONA).json()["assets"]
    assert [a["asset_id"] for a in listed] == [asset["asset_id"]]
    assert client.get(f"/teacher/assets/{asset['asset_id']}", headers=MONA).json()["title"] == "Cell division"


def test_saving_twice_does_not_duplicate(client):
    first = client.post("/teacher/assets", json=VIDEO, headers=MONA).json()
    second = client.post("/teacher/assets", json=VIDEO, headers=MONA).json()
    assert first["asset_id"] == second["asset_id"]
    assert len(client.get("/teacher/assets", headers=MONA).json()["assets"]) == 1


def test_bad_asset_input_is_422(client):
    assert client.post("/teacher/assets", json={**VIDEO, "source_url": "javascript:alert(1)"}, headers=MONA).status_code == 422
    assert client.post("/teacher/assets", json={**VIDEO, "start_sec": 50, "end_sec": 10}, headers=MONA).status_code == 422


def test_missing_asset_or_file_is_404(client):
    assert client.get("/teacher/assets/a_nope", headers=MONA).status_code == 404
    asset = client.post("/teacher/assets", json=VIDEO, headers=MONA).json()
    assert client.get(f"/teacher/assets/{asset['asset_id']}/file", headers=MONA).status_code == 404
