"""/snap reading rules: never return sample text as if it were read from the photo."""
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from rafeeq.copilot import clients
from rafeeq.snap.reader import NotAnImage, ReaderUnavailable, read_snap

SPEC = yaml.safe_load((Path(__file__).resolve().parent.parent / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))


def png_bytes() -> bytes:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = np.full((120, 240, 3), 255, np.uint8)
    cv2.putText(img, "2x+3=11", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RAFEEQ_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    clients.disconnect("read_image")
    yield
    clients.disconnect("read_image")


def test_not_an_image_is_rejected():
    pytest.importorskip("cv2")
    with pytest.raises(NotAnImage):
        read_snap(b"definitely not a picture")


def test_no_reader_configured_is_an_error_not_a_sample():
    with pytest.raises(ReaderUnavailable):
        read_snap(png_bytes())


def test_connected_reader_result_matches_the_contract(tmp_path):
    clients.connect("read_image", lambda data: {"type": "student_work", "language": "en",
                                                "text": "2x+3=11", "confidence": 0.9})
    result = read_snap(png_bytes())
    schema = {"$ref": "#/components/schemas/SnapResult", "components": SPEC["components"]}
    assert not list(Draft202012Validator(schema).iter_errors(result))
    assert result["text"] == "2x+3=11"
    assert (tmp_path / "snaps" / f"{result['file_id']}.jpg").exists()


def test_odd_reader_output_is_normalised():
    clients.connect("read_image", lambda data: {"type": "selfie", "language": "fr", "confidence": "high"})
    result = read_snap(png_bytes())
    assert result["type"] == "other" and result["language"] == "ar" and 0 <= result["confidence"] <= 1
