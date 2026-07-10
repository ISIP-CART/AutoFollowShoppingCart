# WBS 图说明

当前 WBS 图文件位于：

- `design/WBS/WBS.png`

本版 WBS 按 2026-07-10 当前项目状态更新，强调六条并行主线：

1. 项目管理与建模
2. Android 上位机
3. ESP32 / AT8236 下位机
4. 结构与物资
5. 联调与安全
6. 测试与交付

图中状态含义：

- 绿色：已完成
- 蓝色：进行中
- 橙色：待验证
- 灰色：待开始

## 生成方式

WBS 图由以下脚本生成：

```powershell
python design\WBS\generate_wbs.py
```

如果后续需要继续调整 WBS 工作包、任务状态或文字，请优先修改 `generate_wbs.py` 后重新生成，不要只手动修改 PNG。
