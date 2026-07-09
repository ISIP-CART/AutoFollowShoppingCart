# 甘特图说明

当前完整甘特图文件位于：

- `design/gantt/autofollowshoppingcart-day-gantt.xlsx`
- `design/gantt/autofollowshoppingcart-day-gantt-preview.png`

本版甘特图在原有日级排期基础上，按 2026-07-10 当前进度更新了任务名称、关键路径和里程碑节点。重点体现：上位机 Human Cart Simulator / ReID / 诊断日志 / track-bbox gate 已进入可复盘闭环，下位机 ESP32 + AT8236 + WiFi 控制已进入实体调试，真实底盘联调仍需先满足低速安全门槛。

## 颜色含义

- 蓝色：普通计划任务
- 橙色：关键路径任务
- 红色节点：里程碑节点，即“不完成则后续无法开展”的关键卡点
- 浅灰底：每周后两天的节奏参考

## 当前里程碑

- `M1` 需求与基础方案收口
  对应第 7 天前完成需求、WBS、BOM、OpenBot / 下位机方案分析和第 1 周阶段材料。

- `M2` 上位机策略闭环完成
  对应 Human Cart Simulator、Android ReID、诊断日志和 track / bbox gate 策略形成可复盘闭环。

- `M3` 真实底盘联调准入
  对应 ESP32 / AT8236、轮向标定、通信超时停车、结构固定和上位机复测达到极低速真实底盘联调门槛。

- `M4` 最终展示闭环完成
  对应最终彩排、参数冻结、材料收口和现场预案确认完成。

## 生成方式

甘特图由以下脚本生成：

- `design/gantt/gantt_builder.mjs`

如果后续需要继续调整任务排期、关键路径或里程碑颜色，请优先修改脚本后重新生成，而不是只手动改预览图。
