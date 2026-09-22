# 河道垃圾分级测试集使用说明

请在 `images/level_0` 至 `images/level_3` 中分别放入 10–20 张经过人工确认的真实图片：

- `level_0`：未发现河道垃圾
- `level_1`：疑似少量河道垃圾
- `level_2`：发现河道垃圾
- `level_3`：大量或明显河道垃圾

同时在 `test_manifest.csv` 填写相对路径、真实等级、图片来源和备注。真实等级必须由人工或明确业务标准给出，不能直接复制模型预测结果。

运行 `python scripts/evaluate_samples.py` 后，将生成 `results.csv`。重点检查：等级准确率、相邻等级混淆、低置信度样本和典型错判原因。
