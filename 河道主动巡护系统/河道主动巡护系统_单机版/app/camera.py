from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from threading import Lock


@dataclass
class CameraState:
    camera_id: str
    location: str
    frames_analyzed: int = 0
    consecutive_floater: int = 0
    last_level: int = 0
    last_confidence: float = 0.0
    last_event_id: int | None = None
    updated_at: str | None = None


class CameraRegistry:
    """保存浏览器摄像头抽帧的短期状态，用于连续检测和事件去重。"""

    def __init__(self, consecutive_required: int = 2) -> None:
        self.consecutive_required = consecutive_required
        self._states: dict[str, CameraState] = {}
        self._lock = Lock()

    def record(self, camera_id: str, location: str, level: int, confidence: float) -> dict:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                state = CameraState(camera_id=camera_id, location=location)
                self._states[camera_id] = state

            state.location = location
            state.frames_analyzed += 1
            state.last_level = level
            state.last_confidence = confidence
            state.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
            state.consecutive_floater = state.consecutive_floater + 1 if level > 0 else 0

            item = asdict(state)
            item["consecutive_required"] = self.consecutive_required
            item["should_trigger"] = (
                level == 3 or state.consecutive_floater >= self.consecutive_required
            )
            return item

    def set_event(self, camera_id: str, event_id: int | None) -> dict:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                state = CameraState(camera_id=camera_id, location="")
                self._states[camera_id] = state
            state.last_event_id = event_id
            return self._serialize(state)

    def get(self, camera_id: str) -> dict:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                state = CameraState(camera_id=camera_id, location="")
            return self._serialize(state)

    def reset(self, camera_id: str) -> dict:
        with self._lock:
            previous = self._states.pop(camera_id, None)
            location = previous.location if previous else ""
            return self._serialize(CameraState(camera_id=camera_id, location=location))

    def _serialize(self, state: CameraState) -> dict:
        item = asdict(state)
        item["consecutive_required"] = self.consecutive_required
        item["should_trigger"] = (
            state.last_level == 3 or state.consecutive_floater >= self.consecutive_required
        )
        return item


camera_registry = CameraRegistry(consecutive_required=2)
