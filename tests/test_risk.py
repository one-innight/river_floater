import pytest

from app.inference import assess_risk
from app.rules import evaluate_warning


def obj(name: str, confidence: float, area: float = 0.01):
    return {"class_name": name, "confidence": confidence, "area_ratio": area}


def test_empty_is_no_floater():
    result = assess_risk([])
    assert result["level"] == 0
    assert result["level_name"] == "未发现漂浮物"


@pytest.mark.parametrize(("count", "level"), [(1, 1), (3, 1), (4, 2), (7, 2), (8, 3)])
def test_floater_count_controls_warning_level(count, level):
    assert assess_risk([obj("floater", 0.2) for _ in range(count)])["level"] == level


def test_medium_floater_count_creates_orange_warning():
    current = {"level": 2, "level_name": "中等数量漂浮物", "confidence": 0.80, "object_count": 3}
    result = evaluate_warning(current)
    assert result["create_event"] is True
    assert result["warning"] == "橙色预警"


def test_result_below_threshold_is_archived_without_event():
    current = {"level": 2, "level_name": "中等数量漂浮物", "confidence": 0.14, "object_count": 3}
    result = evaluate_warning(current)
    assert result["create_event"] is False
    assert result["warning"] == "低置信度记录"


@pytest.mark.parametrize(
    ("level", "name", "threshold", "warning"),
    [
        (1, "少量漂浮物", 0.3, "黄色预警"),
        (2, "中等数量漂浮物", 0.3, "橙色预警"),
        (3, "大量漂浮物", 0.3, "红色预警"),
    ],
)
def test_each_level_creates_event_at_exact_threshold(level, name, threshold, warning):
    result = evaluate_warning(
        {"level": level, "level_name": name, "confidence": threshold, "object_count": level}
    )
    assert result["create_event"] is True
    assert result["warning"] == warning
