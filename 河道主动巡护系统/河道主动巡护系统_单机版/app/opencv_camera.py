from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Iterator
from threading import Event, Lock, Thread
from time import sleep
from typing import Any

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")


class OpenCVCamera:
    """单路后端视频源，支持 USB 设备编号、视频文件和 RTSP/HTTP 地址。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._capture = None
        self._thread: Thread | None = None
        self._running = False
        self._latest_jpeg: bytes | None = None
        self._source = ""
        self._location = ""
        self._error: str | None = None
        self._frames_read = 0

    def start(self, source: str, location: str) -> dict:
        self.stop()
        normalized = source.strip() or "0"
        capture = self._open_capture(normalized)
        if capture is None:
            raise RuntimeError(f"无法打开视频源：{self._safe_source(normalized)}")

        with self._lock:
            self._capture = capture
            self._source = normalized
            self._location = location.strip()
            self._error = None
            self._latest_jpeg = None
            self._frames_read = 0
            self._running = True
            self._thread = Thread(target=self._read_loop, name="opencv-camera", daemon=True)
            thread = self._thread
        thread.start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._running = False
            capture = self._capture
            thread = self._thread
            self._capture = None
            self._thread = None
        if capture is not None:
            capture.release()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "source": self._safe_source(self._source),
                "location": self._location,
                "frame_ready": self._latest_jpeg is not None,
                "frames_read": self._frames_read,
                "error": self._error,
            }

    def snapshot(self) -> bytes:
        with self._lock:
            frame = self._latest_jpeg
            error = self._error
            running = self._running
        if frame is None:
            message = error or ("摄像头尚未产生画面" if running else "OpenCV 摄像头未启动")
            raise RuntimeError(message)
        return frame

    def mjpeg(self) -> Iterator[bytes]:
        previous: bytes | None = None
        while True:
            with self._lock:
                running = self._running
                frame = self._latest_jpeg
            if not running:
                break
            if frame is not None and frame is not previous:
                previous = frame
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            sleep(0.04)

    def _read_loop(self) -> None:
        import cv2

        failures = 0
        with self._lock:
            initial_source = self._source
        is_video_file = not initial_source.isdigit() and not self._is_remote(initial_source)
        fps = float(self._capture.get(cv2.CAP_PROP_FPS) or 0) if self._capture is not None else 0
        file_frame_delay = 1.0 / min(max(fps, 1.0), 60.0) if is_video_file else 0.0
        while True:
            with self._lock:
                running = self._running
                capture = self._capture
            if not running or capture is None:
                break
            ok, frame = capture.read()
            if not ok:
                failures += 1
                if failures >= 20:
                    with self._lock:
                        source = self._source
                        still_running = self._running
                        self._error = (
                            "RTSP 视频流中断，正在自动重连"
                            if self._is_remote(source)
                            else "视频源连续读取失败或视频文件已结束"
                        )
                    if still_running and self._is_remote(source):
                        capture.release()
                        sleep(2)
                        replacement = self._open_capture(source)
                        with self._lock:
                            if not self._running:
                                if replacement is not None:
                                    replacement.release()
                                break
                            if replacement is not None:
                                self._capture = replacement
                                self._error = None
                                capture = replacement
                                failures = 0
                        continue
                    with self._lock:
                        self._running = False
                    break
                sleep(0.1)
                continue
            failures = 0
            encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not encoded:
                continue
            with self._lock:
                self._latest_jpeg = jpeg.tobytes()
                self._frames_read += 1
            if file_frame_delay:
                sleep(file_frame_delay)

        with self._lock:
            capture = self._capture
            self._capture = None
            self._thread = None
            self._running = False
        if capture is not None:
            capture.release()

    @staticmethod
    def _open_capture(source: str):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("当前环境没有安装 OpenCV，请安装 opencv-python") from exc

        capture_source: int | str = int(source) if source.isdigit() else source
        if isinstance(capture_source, int) and sys.platform == "win32":
            capture = cv2.VideoCapture(capture_source, cv2.CAP_DSHOW)
        elif OpenCVCamera._is_remote(source):
            capture = cv2.VideoCapture(capture_source, cv2.CAP_FFMPEG)
        else:
            capture = cv2.VideoCapture(capture_source)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            return None
        return capture

    @staticmethod
    def _is_remote(source: str) -> bool:
        return source.lower().startswith(("rtsp://", "rtsps://", "http://", "https://"))

    @staticmethod
    def _safe_source(source: str) -> str:
        return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", source)


opencv_camera = OpenCVCamera()


class OpenCVDetectionMonitor:
    """独立于网页运行的定时推理线程，保证 RTSP 无人值守巡护。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._stop_event: Event | None = None
        self._thread: Thread | None = None
        self._running = False
        self._interval_seconds = 8.0
        self._analyses = 0
        self._latest_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self, analyze: Callable[[], dict[str, Any]], interval_seconds: float) -> dict:
        self.stop()
        stop_event = Event()
        interval = max(2.0, float(interval_seconds))
        with self._lock:
            self._stop_event = stop_event
            self._running = True
            self._interval_seconds = interval
            self._analyses = 0
            self._latest_result = None
            self._last_error = None
            self._thread = Thread(
                target=self._loop,
                args=(stop_event, analyze, interval),
                name="opencv-detection-monitor",
                daemon=True,
            )
            thread = self._thread
        thread.start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            stop_event = self._stop_event
            thread = self._thread
            self._running = False
            self._stop_event = None
            self._thread = None
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "interval_seconds": self._interval_seconds,
                "analyses": self._analyses,
                "latest_result": self._latest_result,
                "last_error": self._last_error,
            }

    def _loop(
        self,
        stop_event: Event,
        analyze: Callable[[], dict[str, Any]],
        interval_seconds: float,
    ) -> None:
        if stop_event.wait(1.0):
            return
        while not stop_event.is_set():
            try:
                result = analyze()
                with self._lock:
                    self._analyses += 1
                    self._latest_result = result
                    self._last_error = None
            except Exception as exc:  # 保持监控线程存活，等待视频流重连或模型恢复
                with self._lock:
                    self._last_error = str(exc)
            if stop_event.wait(interval_seconds):
                break
        with self._lock:
            if self._stop_event is stop_event:
                self._running = False


opencv_monitor = OpenCVDetectionMonitor()
