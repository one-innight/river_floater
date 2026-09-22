import io
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.database as database
import app.main as main_module
from app.camera import CameraRegistry
from app.main import app, detector
from app.opencv_camera import OpenCVCamera


def login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123456"}
    )
    assert response.status_code == 200


def image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 48), "#355b58").save(output, "JPEG")
    return output.getvalue()


def prediction(level: int, confidence: float) -> dict:
    names = {
        0: "未发现漂浮物",
        1: "少量漂浮物",
        2: "中等数量漂浮物",
        3: "大量漂浮物",
    }
    objects = (
        []
        if level == 0
        else [
            {
                "class_name": "floater",
                "class_name_zh": "漂浮物",
                "confidence": confidence,
                "bbox": [3, 3, 30, 30],
                "area_ratio": 0.2,
            }
        ]
    )
    return {
        "level": level,
        "level_name": names[level],
        "confidence": confidence,
        "risk_score": float(level),
        "object_count": len(objects),
        "total_area_ratio": 0.2 if objects else 0.0,
        "image_width": 64,
        "image_height": 48,
        "objects": objects,
    }


def test_camera_registry_requires_two_consecutive_frames():
    registry = CameraRegistry(consecutive_required=2)
    first = registry.record("camera-1", "河段 A", 2, 0.4)
    second = registry.record("camera-1", "河段 A", 2, 0.5)
    clean = registry.record("camera-1", "河段 A", 0, 0.0)

    assert first["should_trigger"] is False
    assert second["should_trigger"] is True
    assert clean["consecutive_floater"] == 0


def test_camera_frame_creates_once_then_reuses_open_event(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "camera.db")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(detector, "predict", lambda _: prediction(2, 0.5))
    camera_id = f"test-{uuid4()}"

    with TestClient(app) as client:
        login(client)

        def post_frame():
            return client.post(
                "/api/camera/frame",
                data={"camera_id": camera_id, "location": "视频测试河段"},
                files={"image": ("frame.jpg", image_bytes(), "image/jpeg")},
            )

        first = post_frame()
        second = post_frame()
        third = post_frame()

        assert first.status_code == 200
        assert first.json()["event_action"] == "monitoring"
        assert first.json()["event_id"] is None
        assert second.json()["event_action"] == "created"
        assert second.json()["event_id"] is not None
        assert third.json()["event_action"] == "reused"
        assert third.json()["event_id"] == second.json()["event_id"]
        assert len(client.get("/api/events").json()) == 1

        monkeypatch.setattr(detector, "predict", lambda _: prediction(0, 0.0))
        clean = post_frame().json()
        assert clean["camera_state"]["consecutive_floater"] == 0


def test_opencv_status_masks_rtsp_password():
    safe = OpenCVCamera._safe_source("rtsp://admin:secret@192.168.1.8:554/stream")
    assert "secret" not in safe
    assert "***" in safe


def test_opencv_analyze_rejects_when_camera_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "stopped.db")
    with TestClient(app) as client:
        login(client)
        response = client.post("/api/opencv-camera/analyze")
        assert response.status_code == 503


def test_opencv_video_file_runs_backend_monitor(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    video_path = tmp_path / "river-test.avi"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (96, 64))
    if not writer.isOpened():
        pytest.skip("当前 OpenCV 构建不能创建 MJPG 测试视频")
    for index in range(40):
        frame = np.full((64, 96, 3), (30 + index, 80, 70), dtype=np.uint8)
        writer.write(frame)
    writer.release()

    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "opencv.db")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(detector, "predict", lambda _: prediction(3, 0.8))

    with TestClient(app) as client:
        login(client)
        started = client.post(
            "/api/opencv-camera/start",
            json={"source": str(video_path), "location": "RTSP 测试河段", "interval_seconds": 2},
        )
        assert started.status_code == 200

        latest = None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            latest = client.get("/api/opencv-camera/latest").json()
            if latest["latest_result"]:
                break
            time.sleep(0.1)

        assert latest and latest["latest_result"]
        assert latest["latest_result"]["event_action"] == "created"
        assert latest["latest_result"]["garbage_level"] == 3
        stopped = client.post("/api/opencv-camera/stop")
        assert stopped.status_code == 200
