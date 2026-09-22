from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from .config import CONFIDENCE_THRESHOLD, IMAGE_SIZE, MODEL_PATH

CLASS_ZH = {
    "floater": "漂浮物",
    "float": "漂浮物",
    "floating_debris": "漂浮物",
}

FLOATER_CLASS_KEYWORDS = (
    "floater",
    "float",
    "floating_debris",
)

LEVEL_NAMES = {
    0: "未发现漂浮物",
    1: "少量漂浮物",
    2: "中等数量漂浮物",
    3: "大量漂浮物",
}


@dataclass
class ModelState:
    loaded: bool
    available: bool
    message: str
    model_path: str
    classes: list[str]


class RiverDetector:
    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        self.model_path = model_path
        self._model: Any = None
        self._error: str | None = None
        self._lock = Lock()

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            if not self.model_path.exists():
                self._error = f"未找到模型：{self.model_path}"
                raise RuntimeError(self._error)
            try:
                from ultralytics import YOLO

                self._model = YOLO(str(self.model_path))
                self._error = None
            except Exception as exc:  # 将环境错误转成对前端友好的说明
                self._error = f"模型加载失败：{exc}"
                raise RuntimeError(self._error) from exc

    def state(self) -> ModelState:
        names: list[str] = []
        if self._model is not None:
            raw_names = self._model.names
            names = list(raw_names.values()) if isinstance(raw_names, dict) else list(raw_names)
        return ModelState(
            loaded=self._model is not None,
            available=self.model_path.exists() and self._error is None,
            message=self._error
            or ("模型已就绪" if self._model is not None else "模型将在首次识别时加载"),
            model_path=str(self.model_path),
            classes=names,
        )

    def predict(self, image_path: Path) -> dict[str, Any]:
        self.load()
        with self._lock:
            result = self._model.predict(
                source=str(image_path),
                conf=CONFIDENCE_THRESHOLD,
                imgsz=IMAGE_SIZE,
                verbose=False,
            )[0]

        height, width = result.orig_shape
        objects: list[dict[str, Any]] = []
        names = result.names
        for box in result.boxes:
            class_id = int(box.cls.item())
            class_name = str(names[class_id])
            class_key = class_name.strip().lower().replace(" ", "_")
            if not any(keyword in class_key for keyword in FLOATER_CLASS_KEYWORDS):
                continue
            xyxy = [round(float(value), 2) for value in box.xyxy[0].tolist()]
            x1, y1, x2, y2 = xyxy
            area_ratio = max(0.0, (x2 - x1) * (y2 - y1) / (width * height))
            objects.append(
                {
                    "class_id": class_id,
                    "class_name": class_name,
                    "class_name_zh": CLASS_ZH.get(class_key, "漂浮物"),
                    "confidence": round(float(box.conf.item()), 4),
                    "bbox": xyxy,
                    "area_ratio": round(area_ratio, 5),
                }
            )

        assessment = assess_risk(objects)
        return {**assessment, "objects": objects, "image_width": width, "image_height": height}


def assess_risk(objects: list[dict[str, Any]]) -> dict[str, Any]:
    """仅按检测到的漂浮物数量生成 0~3 级预警等级。

    检测置信度仅用于 YOLO 的检测框过滤，不再参与污染程度分级：
    1~3 个为低等级，4~7 个为中等级，8 个及以上为高等级。
    """
    if not objects:
        return {
            "level": 0,
            "level_name": LEVEL_NAMES[0],
            "confidence": 0.0,
            "max_detection_confidence": 0.0,
            "risk_score": 0.0,
            "object_count": 0,
            "total_area_ratio": 0.0,
        }

    object_count = len(objects)
    max_confidence = max(float(item["confidence"]) for item in objects)
    total_area_ratio = min(sum(float(item.get("area_ratio", 0)) for item in objects), 1.0)
    score = float(object_count)

    if object_count >= 8:
        level = 3
    elif object_count >= 4:
        level = 2
    else:
        level = 1
    return {
        "level": level,
        "level_name": LEVEL_NAMES[level],
        "confidence": round(max_confidence, 4),
        "max_detection_confidence": round(max_confidence, 4),
        "risk_score": round(score, 4),
        "object_count": object_count,
        "total_area_ratio": round(total_area_ratio, 5),
    }


detector = RiverDetector()
