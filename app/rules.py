from __future__ import annotations

from typing import Any

from .config import CONFIDENCE_THRESHOLD

RULES = {
    0: {
        "threshold": 0.0,
        "warning": "不预警",
        "advice": "未发现漂浮物，正常归档并保持定期巡查。",
    },
    1: {
        "threshold": CONFIDENCE_THRESHOLD,
        "warning": "黄色预警",
        "advice": "发现少量漂浮物，建议人工复核并安排巡查或清理。",
    },
    2: {
        "threshold": CONFIDENCE_THRESHOLD,
        "warning": "橙色预警",
        "advice": "发现 4 至 7 个漂浮物，通知河道管理人员安排现场清理并记录位置和数量。",
    },
    3: {
        "threshold": CONFIDENCE_THRESHOLD,
        "warning": "红色预警",
        "advice": "发现 8 个及以上漂浮物，立即派单清理，防止继续聚集或向下游扩散。",
    },
}


def evaluate_warning(current: dict[str, Any]) -> dict[str, Any]:
    """按单张图片中漂浮物数量对应的等级生成预警，不使用时序规则。"""
    level = int(current["level"])
    confidence = float(current["confidence"])
    rule = RULES[level]

    if level == 0:
        return _result(False, rule["warning"], "未发现漂浮物", rule["advice"], rule["threshold"])

    if confidence >= rule["threshold"]:
        return _result(
            True,
            rule["warning"],
            f"{current['level_name']}，检测到 {int(current.get('object_count', 0))} 个漂浮物",
            rule["advice"],
            rule["threshold"],
        )

    return _result(
        False,
        "低置信度记录",
        f"漂浮物检测置信度未达到 {rule['threshold']:.0%}",
        "结果已归档，建议人工检查后再决定是否处置。",
        rule["threshold"],
    )


def _result(
    create_event: bool,
    warning: str,
    reason: str,
    advice: str,
    threshold: float,
) -> dict[str, Any]:
    return {
        "create_event": create_event,
        "warning": warning,
        "reason": reason,
        "advice": advice,
        "confidence_threshold": threshold,
    }
