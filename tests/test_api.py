import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import app.database as database
import app.main as main_module
from app.main import app, detector


def login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123456"}
    )
    assert response.status_code == 200


def image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "#287b80").save(output, "JPEG")
    return output.getvalue()


def prediction(level: int = 2, confidence: float = 0.88) -> dict:
    return {
        "level": level,
        "level_name": {
            0: "未发现漂浮物",
            1: "少量漂浮物",
            2: "中等数量漂浮物",
            3: "大量漂浮物",
        }[level],
        "confidence": confidence,
        "risk_score": float(level),
        "object_count": 4 if level == 2 else (8 if level == 3 else level),
        "objects": [
            {
                "class_name": "floater",
                "class_name_zh": "漂浮物",
                "confidence": confidence,
                "bbox": [2, 2, 20, 20],
            }
        ]
        * (4 if level == 2 else (8 if level == 3 else level)),
    }


def test_predict_warning_and_full_closed_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "test.db")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(detector, "predict", lambda _: prediction(2, 0.88))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        login(client)
        assert client.get("/mobile/").status_code == 200
        assert client.get("/mobile/manifest.webmanifest").status_code == 200
        original_image = image_bytes()
        response = client.post(
            "/predict",
            data={"location": "测试河段"},
            files={"image": ("river.jpg", original_image, "image/jpeg")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["floater_detected"] is True
        assert payload["floater_level"] == 2
        assert payload["floater_name"] == "中等数量漂浮物"
        assert payload["floater_count"] == 4
        assert payload["warning_level"] == "橙色预警"
        assert payload["image_url"] != payload["annotated_image_url"]
        assert (upload_dir / Path(payload["image_url"]).name).read_bytes() == original_image
        event_id = payload["event_id"]

        transitions = (
            ("已派单", {"handler": "测试人员"}),
            ("处理中", {}),
            ("已处理", {"note": "已完成漂浮物清理"}),
        )
        for status, extra in transitions:
            response = client.patch(
                f"/api/events/{event_id}/status",
                json={"status": status, **extra},
            )
            assert response.status_code == 200

        blocked = client.patch(f"/api/events/{event_id}/status", json={"status": "复核通过"})
        assert blocked.status_code == 409

        monkeypatch.setattr(detector, "predict", lambda _: prediction(2, 0.91))
        failed_verification = client.post(
            f"/api/events/{event_id}/verify",
            files={"image": ("not-clean.jpg", image_bytes(), "image/jpeg")},
        )
        assert failed_verification.status_code == 200
        assert failed_verification.json()["passed"] is False
        still_blocked = client.patch(f"/api/events/{event_id}/status", json={"status": "复核通过"})
        assert still_blocked.status_code == 409

        monkeypatch.setattr(detector, "predict", lambda _: prediction(0, 0.0))
        response = client.post(
            f"/api/events/{event_id}/verify",
            files={"image": ("after.jpg", image_bytes(), "image/jpeg")},
        )
        assert response.status_code == 200
        assert response.json()["passed"] is True

        for status in ("复核通过", "已关闭"):
            response = client.patch(f"/api/events/{event_id}/status", json={"status": status})
            assert response.status_code == 200
        assert response.json()["status"] == "已关闭"
        assert response.json()["handler"] == "测试人员"
        assert response.json()["processing_note"] == "已完成漂浮物清理"

        deleted = client.delete(f"/api/events/{event_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/events/{event_id}").status_code == 404
