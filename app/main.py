from __future__ import annotations

import io
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, UnidentifiedImageError
from starlette.middleware.sessions import SessionMiddleware

from .camera import camera_registry
from .config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    AUTH_ENABLED,
    CAMERA_AUTOSTART,
    CAMERA_INTERVAL_SECONDS,
    CAMERA_LOCATION,
    CAMERA_SOURCE,
    MOBILE_DIR,
    SESSION_HTTPS_ONLY,
    SESSION_SECRET,
    STATIC_DIR,
    UPLOAD_DIR,
)
from .database import connection, fetch_all, fetch_one, init_db, now_iso
from .inference import detector
from .opencv_camera import opencv_camera, opencv_monitor
from .rules import evaluate_warning
from .schemas import OpenCVCameraStart, StatusUpdate

STATUS_FLOW = {
    "待确认": "已派单",
    "已派单": "处理中",
    "处理中": "已处理",
    "已处理": "复核通过",
    "复核通过": "已关闭",
}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if CAMERA_AUTOSTART:
        try:
            _start_opencv_service(CAMERA_SOURCE, CAMERA_LOCATION, CAMERA_INTERVAL_SECONDS)
        except RuntimeError:
            pass
    yield
    opencv_monitor.stop()
    opencv_camera.stop()


app = FastAPI(
    title="河道漂浮物识别与处置闭环系统",
    version="0.3.0",
    description="YOLO 河道漂浮物图片与摄像头抽帧检测、主动预警与处置闭环接口",
    lifespan=lifespan,
)
PUBLIC_PATHS = {"/login", "/api/auth/login", "/api/auth/logout", "/health", "/api/health"}
AUTH_SESSION_VERSION = 2


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Require a signed session for all application pages, APIs and evidence files."""
    if not AUTH_ENABLED or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if (
        request.session.get("authenticated")
        and request.session.get("auth_session_version") == AUTH_SESSION_VERSION
    ):
        return await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path.startswith("/uploads/"):
        return JSONResponse(status_code=401, content={"detail": "请先登录系统"})
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={target}", status_code=303)


# SessionMiddleware 必须位于鉴权中间件外层，后注册以保证 request.session 已初始化。
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="river_patrol_session",
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
    # 不设置 Max-Age，浏览器关闭后会话 Cookie 自动失效，下次访问需重新登录。
    max_age=None,
)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    if not AUTH_ENABLED or (
        request.session.get("authenticated")
        and request.session.get("auth_session_version") == AUTH_SESSION_VERSION
    ):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/api/auth/login")
async def login(request: Request) -> dict:
    payload = await request.json()
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    if not secrets.compare_digest(username, ADMIN_USERNAME) or not secrets.compare_digest(
        password, ADMIN_PASSWORD
    ):
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["auth_session_version"] = AUTH_SESSION_VERSION
    return {"username": username}


@app.get("/api/auth/me")
def current_user(request: Request) -> dict:
    if not AUTH_ENABLED:
        return {"authenticated": True, "username": "本地访问"}
    authenticated = (
        bool(request.session.get("authenticated"))
        and request.session.get("auth_session_version") == AUTH_SESSION_VERSION
    )
    return {"authenticated": authenticated, "username": request.session.get("username") if authenticated else None}


@app.post("/api/auth/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@app.get("/health")
@app.get("/api/health")
def health(load_model: bool = False) -> dict:
    if load_model:
        try:
            detector.load()
        except RuntimeError:
            pass
    state = detector.state()
    return {
        "status": "ok",
        "database": "ready",
        "model": state.__dict__,
        "opencv_camera": _opencv_service_status(),
    }


@app.post("/predict")
@app.post("/api/detections")
async def create_detection(
    image: UploadFile = File(...),
    location: str = Form(..., min_length=1, max_length=100),
    longitude: float | None = Form(default=None),
    latitude: float | None = Form(default=None),
) -> dict:
    image_path, image_url = await _save_upload(image)
    try:
        current, result = _analyze_saved_image(
            image_path, image_url, location.strip(), longitude, latitude
        )
    except RuntimeError as exc:
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    rule = evaluate_warning(current)
    event = _create_event(current, rule) if rule["create_event"] else None
    return _detection_response(current, result, rule, event)


@app.post("/api/camera/frame")
async def analyze_camera_frame(
    image: UploadFile = File(...),
    camera_id: str = Form(..., min_length=1, max_length=100),
    location: str = Form(..., min_length=1, max_length=100),
    longitude: float | None = Form(default=None),
    latitude: float | None = Form(default=None),
) -> dict:
    """分析浏览器摄像头抽取的一帧，并用连续两帧规则控制事件创建。"""
    image_path, image_url = await _save_upload(image)
    try:
        current, result = _analyze_saved_image(
            image_path, image_url, location.strip(), longitude, latitude
        )
    except RuntimeError as exc:
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _camera_detection_response(current, result, camera_id.strip(), location.strip())


@app.get("/api/camera/status")
def camera_status(camera_id: str = Query(..., min_length=1, max_length=100)) -> dict:
    return camera_registry.get(camera_id.strip())


@app.post("/api/camera/reset")
def reset_camera_status(camera_id: str = Form(..., min_length=1, max_length=100)) -> dict:
    return camera_registry.reset(camera_id.strip())


@app.post("/api/opencv-camera/start")
def start_opencv_camera(payload: OpenCVCameraStart) -> dict:
    try:
        status = _start_opencv_service(payload.source, payload.location, payload.interval_seconds)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return status


@app.post("/api/opencv-camera/stop")
def stop_opencv_camera() -> dict:
    opencv_monitor.stop()
    camera_registry.reset("opencv-primary")
    opencv_camera.stop()
    return _opencv_service_status()


@app.get("/api/opencv-camera/status")
def opencv_camera_status() -> dict:
    return _opencv_service_status()


@app.get("/api/opencv-camera/latest")
def latest_opencv_analysis() -> dict:
    return opencv_monitor.status()


@app.get("/api/opencv-camera/stream")
def opencv_camera_stream() -> StreamingResponse:
    status = opencv_camera.status()
    if not status["running"]:
        raise HTTPException(status_code=409, detail=status["error"] or "OpenCV 摄像头未启动")
    return StreamingResponse(
        opencv_camera.mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.post("/api/opencv-camera/analyze")
def analyze_opencv_camera() -> dict:
    try:
        return _analyze_opencv_snapshot()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/detections")
def list_detections(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return fetch_all("SELECT * FROM detections ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))


@app.get("/api/events")
def list_events(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    if status:
        rows = fetch_all(
            "SELECT * FROM events WHERE status = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = fetch_all("SELECT * FROM events ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,))
    return rows


@app.get("/api/events/{event_id}")
def event_detail(event_id: int) -> dict:
    event = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")
    event["logs"] = fetch_all(
        "SELECT * FROM event_logs WHERE event_id = ? ORDER BY created_at, id", (event_id,)
    )
    event["source_detection"] = fetch_one(
        "SELECT * FROM detections WHERE id = ?", (event["detection_id"],)
    )
    if event["verification_detection_id"]:
        event["verification_detection"] = fetch_one(
            "SELECT * FROM detections WHERE id = ?", (event["verification_detection_id"],)
        )
    else:
        event["verification_detection"] = None
    event["next_status"] = STATUS_FLOW.get(event["status"])
    return event


@app.post("/api/events/{event_id}/verify")
async def verify_event(event_id: int, image: UploadFile = File(...)) -> dict:
    event = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")
    if event["status"] != "已处理":
        raise HTTPException(status_code=409, detail="事件进入“已处理”后才能上传复核图片")

    image_path, image_url = await _save_upload(image)
    try:
        result = detector.predict(image_path)
    except RuntimeError as exc:
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    annotated_image_url = _draw_detections(image_path, result["objects"])

    created_at = now_iso()
    passed = int(result["level"]) == 0
    verification_result = "通过" if passed else "未通过"
    with connection() as db:
        cursor = db.execute(
            """
            INSERT INTO detections
            (location, longitude, latitude, level, level_name, confidence, risk_score,
             image_url, annotated_image_url, objects_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["location"],
                event["longitude"],
                event["latitude"],
                result["level"],
                result["level_name"],
                result["confidence"],
                result["risk_score"],
                image_url,
                annotated_image_url,
                json.dumps(result["objects"], ensure_ascii=False),
                created_at,
            ),
        )
        detection_id = cursor.lastrowid
        db.execute(
            """
            UPDATE events
            SET verification_detection_id = ?, verification_image_url = ?, verification_level = ?,
                verification_name = ?, verification_confidence = ?, verification_result = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                detection_id,
                image_url,
                result["level"],
                result["level_name"],
                result["confidence"],
                verification_result,
                created_at,
                event_id,
            ),
        )
        db.execute(
            """
            INSERT INTO event_logs(event_id, from_status, to_status, note, created_at)
            VALUES (?, '已处理', '已处理', ?, ?)
            """,
            (
                event_id,
                f"模型复核{verification_result}：漂浮物风险由 {event['level']} 级变为 {result['level']} 级",
                created_at,
            ),
        )
    return {
        "event_id": event_id,
        "passed": passed,
        "verification_result": verification_result,
        "floater_detected": result["level"] > 0,
        "floater_level": result["level"],
        "floater_name": result["level_name"],
        "floater_count": int(result.get("object_count", len(result.get("objects", [])))),
        # 兼容旧页面和调用方；新代码应使用 floater_* 字段。
        "garbage_detected": result["level"] > 0,
        "garbage_level": result["level"],
        "garbage_name": result["level_name"],
        "pollution_level": result["level"],
        "pollution_name": result["level_name"],
        "confidence": result["confidence"],
        "image_url": image_url,
        "annotated_image_url": annotated_image_url,
        "message": "复核图片未发现漂浮物，可以继续复核通过并关闭事件"
        if passed
        else "复核图片仍检测到漂浮物，请继续清理后重新复核",
    }


@app.patch("/api/events/{event_id}/status")
def update_event_status(event_id: int, payload: StatusUpdate) -> dict:
    event = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")

    expected = STATUS_FLOW.get(event["status"])
    if payload.status != expected:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态为“{event['status']}”，只能流转到“{expected or '无'}”",
        )
    if payload.status == "已派单" and not payload.handler.strip():
        raise HTTPException(status_code=422, detail="派单时必须填写处理人员")
    if payload.status == "已处理" and not payload.note.strip():
        raise HTTPException(status_code=422, detail="标记已处理时必须填写处理说明")
    if payload.status == "复核通过" and event["verification_result"] != "通过":
        raise HTTPException(status_code=409, detail="请先上传复核图片，且模型判定未发现漂浮物")

    timestamp = now_iso()
    handled_at = timestamp if payload.status == "已处理" else event["handled_at"]
    closed_at = timestamp if payload.status == "已关闭" else event["closed_at"]
    handler = payload.handler.strip() if payload.status == "已派单" else event["handler"]
    processing_note = (
        payload.note.strip() if payload.status == "已处理" else event["processing_note"]
    )
    with connection() as db:
        db.execute(
            """
            UPDATE events
            SET status = ?, updated_at = ?, handled_at = ?, closed_at = ?, handler = ?, processing_note = ?
            WHERE id = ?
            """,
            (payload.status, timestamp, handled_at, closed_at, handler, processing_note, event_id),
        )
        db.execute(
            """
            INSERT INTO event_logs(event_id, from_status, to_status, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, event["status"], payload.status, payload.note.strip(), timestamp),
        )
    return event_detail(event_id)


@app.delete("/api/events/{event_id}", status_code=204)
def delete_event(event_id: int) -> None:
    """删除事件及其状态流转日志，保留原始检测记录作为识别历史。"""
    with connection() as db:
        deleted = db.execute("DELETE FROM events WHERE id = ?", (event_id,)).rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail="事件不存在")


@app.get("/api/dashboard")
def dashboard() -> dict:
    with connection() as db:
        total_today = db.execute(
            "SELECT COUNT(*) AS value FROM detections WHERE date(created_at) = date('now', 'localtime')"
        ).fetchone()["value"]
        active = db.execute(
            "SELECT COUNT(*) AS value FROM events WHERE status != '已关闭'"
        ).fetchone()["value"]
        closed = db.execute(
            "SELECT COUNT(*) AS value FROM events WHERE status = '已关闭'"
        ).fetchone()["value"]
        severe = db.execute(
            "SELECT COUNT(*) AS value FROM detections WHERE level = 3 AND date(created_at) = date('now', 'localtime')"
        ).fetchone()["value"]
        level_rows = db.execute(
            "SELECT level, COUNT(*) AS value FROM detections GROUP BY level ORDER BY level"
        ).fetchall()
    return {
        "stats": {
            "today_detections": total_today,
            "active_events": active,
            "closed_events": closed,
            "severe_today": severe,
        },
        "levels": {str(row["level"]): row["value"] for row in level_rows},
        "recent_detections": list_detections(8),
        "recent_events": list_events(limit=8),
    }


def _start_opencv_service(source: str, location: str, interval_seconds: float) -> dict:
    opencv_monitor.stop()
    camera_registry.reset("opencv-primary")
    opencv_camera.start(source, location)
    opencv_monitor.start(_analyze_opencv_snapshot, interval_seconds)
    return _opencv_service_status()


def _opencv_service_status() -> dict:
    return {
        "capture": opencv_camera.status(),
        "monitor": opencv_monitor.status(),
    }


def _analyze_opencv_snapshot() -> dict:
    status = opencv_camera.status()
    if not status["running"]:
        raise RuntimeError(status["error"] or "OpenCV 摄像头未启动")
    image_path: Path | None = None
    try:
        image_path, image_url = _save_image_bytes(opencv_camera.snapshot())
        current, result = _analyze_saved_image(
            image_path, image_url, status["location"], None, None
        )
    except Exception:
        if image_path is not None:
            image_path.unlink(missing_ok=True)
        raise
    return _camera_detection_response(current, result, "opencv-primary", status["location"])


def _analyze_saved_image(
    image_path: Path,
    image_url: str,
    location: str,
    longitude: float | None,
    latitude: float | None,
) -> tuple[dict, dict]:
    result = detector.predict(image_path)
    annotated_image_url = _draw_detections(image_path, result["objects"])
    created_at = now_iso()
    with connection() as db:
        cursor = db.execute(
            """
            INSERT INTO detections
            (location, longitude, latitude, level, level_name, confidence, risk_score,
             image_url, annotated_image_url, objects_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                location,
                longitude,
                latitude,
                result["level"],
                result["level_name"],
                result["confidence"],
                result["risk_score"],
                image_url,
                annotated_image_url,
                json.dumps(result["objects"], ensure_ascii=False),
                created_at,
            ),
        )
        detection_id = cursor.lastrowid
    current = fetch_one("SELECT * FROM detections WHERE id = ?", (detection_id,))
    # object_count 是推理阶段的派生字段，不在 detections 表中单独存储；
    # 事件标题和预警文案仍需使用它。
    current["object_count"] = int(result.get("object_count", len(result.get("objects", []))))
    return current, result


def _detection_response(current: dict, result: dict, rule: dict, event: dict | None) -> dict:
    return {
        "floater_detected": current["level"] > 0,
        "floater_level": current["level"],
        "floater_name": current["level_name"],
        "floater_count": len(current.get("objects", [])),
        # 以下 garbage_* 字段仅用于兼容旧页面和调用方。
        "garbage_detected": current["level"] > 0,
        "garbage_level": current["level"],
        "garbage_name": current["level_name"],
        "garbage_count": int(current.get("object_count", len(current.get("objects", [])))),
        # 保留原字段，避免旧页面或调用方立即失效。
        "pollution_level": current["level"],
        "pollution_name": current["level_name"],
        "confidence": current["confidence"],
        "timestamp": current["created_at"].replace("T", " ")[:19],
        "location": current["location"],
        "image_url": current["image_url"],
        "annotated_image_url": current["annotated_image_url"],
        "frame_width": int(result.get("image_width", 0)),
        "frame_height": int(result.get("image_height", 0)),
        "objects": current.get("objects", []),
        "warning_level": rule["warning"],
        "advice": rule["advice"],
        "event_id": event["id"] if event else None,
        "event_no": event["event_no"] if event else None,
        "detection": current,
        "rule": rule,
        "event": event,
    }


def _camera_detection_response(
    current: dict,
    result: dict,
    camera_id: str,
    location: str,
) -> dict:
    camera_state = camera_registry.record(
        camera_id, location, int(current["level"]), float(current["confidence"])
    )
    rule = evaluate_warning(current)
    event = None
    event_action = "none"

    if current["level"] > 0 and not camera_state["should_trigger"]:
        event_action = "monitoring"
    elif rule["create_event"] and camera_state["should_trigger"]:
        event = _find_open_event(location)
        if event:
            event_action = "reused"
        else:
            event = _create_event(current, rule)
            event_action = "created"
        camera_state = camera_registry.set_event(camera_id, event["id"])

    payload = _detection_response(current, result, rule, event)
    payload.update(
        {
            "camera_id": camera_id,
            "camera_state": camera_state,
            "event_action": event_action,
            "monitoring_message": _camera_message(current, camera_state, event_action, event),
        }
    )
    return payload


def _find_open_event(location: str) -> dict | None:
    return fetch_one(
        """
        SELECT * FROM events
        WHERE location = ? AND status != '已关闭'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (location,),
    )


def _camera_message(
    current: dict, camera_state: dict, event_action: str, event: dict | None
) -> str:
    if current["level"] == 0:
        return "本次抽帧未发现漂浮物，连续计数已清零"
    if event_action == "monitoring":
        return (
            f"已连续发现漂浮物 {camera_state['consecutive_floater']}/"
            f"{camera_state['consecutive_required']} 帧，继续观察"
        )
    if event_action == "created":
        return f"已创建预警事件 {event['event_no']}"
    if event_action == "reused":
        return f"同河段已有未关闭事件 {event['event_no']}，本次不重复创建"
    return "本次抽帧结果已归档"


async def _save_upload(upload: UploadFile) -> tuple[Path, str]:
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="上传图片为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片不能超过 15 MB")
    return _save_image_bytes(content)


def _save_image_bytes(content: bytes) -> tuple[Path, str]:
    try:
        with Image.open(io.BytesIO(content)) as source:
            image_format = source.format
            source.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="文件不是有效图片") from exc

    extensions = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    if image_format not in extensions:
        raise HTTPException(status_code=400, detail="仅支持 JPG、PNG 或 WEBP 图片")
    filename = f"{uuid4().hex}{extensions[image_format]}"
    path = UPLOAD_DIR / filename
    path.write_bytes(content)
    return path, f"/uploads/{filename}"


def _draw_detections(image_path: Path, objects: list[dict]) -> str:
    """另存检测框图片，保留未修改的原始上传证据。"""
    colors = {
        "litter": "#f2b85b",
        "trash": "#f2b85b",
        "garbage": "#f2b85b",
        "waste": "#f2b85b",
        "floatingdebris": "#f2b85b",
    }
    annotated_path = image_path.with_name(f"{image_path.stem}_detected.jpg")
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        line_width = max(2, round(min(image.size) / 240))
        for item in objects:
            class_key = str(item["class_name"]).strip().lower().replace(" ", "_")
            color = colors.get(class_key, "#f2b85b")
            box = tuple(item["bbox"])
            draw.rectangle(box, outline=color, width=line_width)
            label = f"{item['class_name']} {item['confidence']:.0%}"
            text_box = draw.textbbox((box[0], box[1]), label)
            text_height = text_box[3] - text_box[1] + 6
            top = max(0, box[1] - text_height)
            draw.rectangle(
                (box[0], top, box[0] + text_box[2] - text_box[0] + 8, box[1]), fill=color
            )
            draw.text((box[0] + 4, top + 2), label, fill="#071316")
        image.save(annotated_path, "JPEG", quality=92, optimize=True)
    return f"/uploads/{annotated_path.name}"


def _create_event(detection: dict, rule: dict) -> dict:
    """MVP 阶段每次达到阈值的单图识别都创建一条独立事件。"""
    timestamp = now_iso()
    floater_count = int(detection.get("object_count", len(detection.get("objects", []))))
    title = f"{detection['location']} · {detection['level_name']}，检测到 {floater_count} 个漂浮物"
    with connection() as db:
        cursor = db.execute(
            """
            INSERT INTO events
            (location, longitude, latitude, level, level_name, warning, title, advice, status,
             confidence, image_url, detection_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '待确认', ?, ?, ?, ?, ?)
            """,
            (
                detection["location"],
                detection["longitude"],
                detection["latitude"],
                detection["level"],
                detection["level_name"],
                rule["warning"],
                title,
                rule["advice"],
                detection["confidence"],
                detection["image_url"],
                detection["id"],
                timestamp,
                timestamp,
            ),
        )
        event_id = cursor.lastrowid
        event_no = f"RIVER-{timestamp[:10].replace('-', '')}-{event_id:04d}"
        db.execute("UPDATE events SET event_no = ? WHERE id = ?", (event_no, event_id))
        db.execute(
            "INSERT INTO event_logs(event_id, from_status, to_status, note, created_at) VALUES (?, NULL, '待确认', ?, ?)",
            (event_id, rule["reason"], timestamp),
        )
    return fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/mobile", StaticFiles(directory=MOBILE_DIR, html=True), name="mobile")
