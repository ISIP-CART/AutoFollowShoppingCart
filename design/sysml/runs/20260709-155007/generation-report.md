# SysML 生成报告

> Run：`20260709-155007`

## 生成范围

本次面向第 2 周当前进度，更新 canonical 文档并生成 12 个 PlantUML 文件：

- 默认 8 图：上下文、用例、需求、块定义、内部块、活动、状态机、部署与接口。
- 作业增强 4 图：方案权衡、需求追溯验证、参数约束、WBS/里程碑/甘特图。

## 当前进度覆盖

| 要求 | 覆盖情况 |
| --- | --- |
| 系统功能架构 | `04_block_definition.puml` |
| 逻辑架构 | `05_internal_block.puml`、`06_follow_activity.puml`、`07_safety_state_machine.puml` |
| 物理架构 | `08_deployment_and_interfaces.puml` |
| 方案权衡/约束 | `09_tradeoff_constraints.puml` |
| 需求追溯、验证、确认方法 | `10_traceability_validation.puml` |
| 参数 | `11_param_constraints.puml` |
| WBS、里程碑、甘特图 | `12_wbs_gantt.puml`，已按 2026-07-10 进度同步 |

## 建模边界

- 保持首版架构为 `OpenBot + Android 手机 + ESP32/MCU + 差速底盘`。
- ReID 只作为身份置信辅助，不作为单独 FOLLOW 判决器。
- 目标丢失先 `motion_stop`，再短时 `LOCAL_SEARCH / REACQUIRE`，失败或风险过高后 hard `STOP`。
- 下位机已进入 ESP32 + AT8236 + WiFi 调控实体阶段，但真实底盘自主前进仍需先满足极低速联调准入门槛。
- 麦轮首版按低速差速/保守控制使用，不把横移建模为自主跟随必需能力。
- 诊断日志默认关闭，隐私图片、实验输出和模型权重不纳入版本库。

## 验证结果

已运行 PUML 本地静态校验，所有文件包含 `@startuml` 与 `@enduml`，默认 8 图齐全。
