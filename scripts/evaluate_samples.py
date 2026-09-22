"""批量评估人工标注的 0~3 级河道垃圾测试图片。"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.inference import detector  # noqa: E402

EVALUATION_DIR = PROJECT_ROOT / "evaluation"
MANIFEST_PATH = EVALUATION_DIR / "test_manifest.csv"
RESULT_PATH = EVALUATION_DIR / "results.csv"


def main() -> None:
    with MANIFEST_PATH.open("r", encoding="utf-8-sig", newline="") as source:
        samples = list(csv.DictReader(source))
    if not samples:
        raise SystemExit("test_manifest.csv 还没有样本，请先填写人工标注图片。")

    results: list[dict[str, str | int | float]] = []
    confusion: Counter[tuple[int, int]] = Counter()
    for index, sample in enumerate(samples, start=1):
        relative_path = sample["image_path"].strip()
        expected_level = int(sample["expected_level"])
        if expected_level not in range(4):
            raise ValueError(f"第 {index} 行 expected_level 必须是 0~3")
        image_path = EVALUATION_DIR / relative_path
        if not image_path.is_file():
            raise FileNotFoundError(f"第 {index} 行图片不存在：{image_path}")

        prediction = detector.predict(image_path)
        predicted_level = int(prediction["level"])
        confusion[(expected_level, predicted_level)] += 1
        results.append(
            {
                "image_path": relative_path,
                "expected_level": expected_level,
                "predicted_level": predicted_level,
                "predicted_name": prediction["level_name"],
                "confidence": prediction["confidence"],
                "risk_score": prediction["risk_score"],
                "correct": "是" if predicted_level == expected_level else "否",
                "detected_objects": ";".join(
                    f"{item['class_name']}:{item['confidence']:.3f}"
                    for item in prediction["objects"]
                ),
                "source": sample.get("source", ""),
                "notes": sample.get("notes", ""),
            }
        )

    with RESULT_PATH.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    correct = sum(item["correct"] == "是" for item in results)
    print(f"评估完成：{correct}/{len(results)}，准确率 {correct / len(results):.1%}")
    for expected in range(4):
        distribution = ", ".join(
            f"预测{predicted}级={confusion[(expected, predicted)]}" for predicted in range(4)
        )
        print(f"真实{expected}级：{distribution}")
    print(f"结果已保存：{RESULT_PATH}")


if __name__ == "__main__":
    main()
