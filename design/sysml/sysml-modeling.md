# 自主跟随购物车 SysML 建模说明

> 更新时间窗口：20260709-155007  
> 本次图集范围：面向第 2 周周二要求，补齐系统功能架构、逻辑架构、物理架构、方案权衡、需求追溯、验证确认方法、关键参数、WBS、里程碑与甘特图。  
> 建模边界：首版课程可交付原型，保持 `OpenBot + Android 手机 + MCU/ESP32 + 差速底盘` 主线；不把 SLAM、服务器、树莓派主脑、复杂路径规划、自动结账或真实超市长期部署建模为首版必需能力。

## 1. 周二要求对应交付

根据课堂图片，周二任务是“系统设计详细方案确定：软硬件，明确技术路线”，具体包括：

| 周二要求 | 本次交付物 |
| --- | --- |
| 系统功能架构、逻辑架构、物理架构 | `04_block_definition.puml`、`05_internal_block.puml`、`08_deployment_and_interfaces.puml` |
| SysML 建模 | `design/sysml/sysml-modeling.md` 与本次 run 下的 `.puml` 图 |
| 方案权衡与约束条件 | 本文第 4 节与 `09_tradeoff_constraints.puml` |
| 需求追溯、验证及确认方法 | 本文第 5 节与 `10_traceability_validation.puml` |
| 参数 | 本文第 6 节与 `11_param_constraints.puml` |
| WBS、阶段性里程碑、甘特图迭代更新 | 本文第 7 节与 `12_wbs_gantt.puml` |

本次生成目录：

- `design/sysml/runs/20260709-155007/puml/`
- `design/sysml/runs/20260709-155007/diagram-links.md`
- `design/sysml/runs/20260709-155007/generation-report.md`
- `design/sysml/runs/20260709-155007/source-manifest.json`

## 2. 建模事实来源

本次建模依据当前仓库文档和实现记录，优先级遵循 `AGENTS.md`：

| 来源 | 用途 |
| --- | --- |
| `AGENTS.md` | 首版验收口径、架构硬约束、目标丢失策略、隐私边界 |
| `README.md` | 项目定位、当前上位机进度、目录与 4 周目标 |
| `design/structure.md` | 需求、用例、WBS、里程碑、甘特图和测试计划 |
| `design/自主跟随购物车上位机软件开发计划.md` | 上位机功能/逻辑架构、ReID、状态机、行为仲裁 |
| `design/上位机软件开发 Phase 2——修正跟随距离控制计划书.md` | 初始化距离标定、图像伺服、Distance State 参数 |
| `design/障碍处理计划书.md` | 左/中/右可通行空间与跟随式局部避障 |
| `design/OpenBot与四驱麦轮AT8236下位机适配风险说明.md` | OpenBot 协议、ESP32、AT8236、四轮差速映射与安全保护 |
| `design/工程决策与实现策略记录.md` | 方案演化、成本/周期/采购/安全约束、方案 C 收敛 |
| `dev/OpenBot/android/cartfollow-devlog.md` | Human Cart Simulator、状态机、ReID、track/belief 与诊断日志当前实现 |
| `design/doc/产品参数信息汇总报告.md`、`design/采购.md` | 底盘、电机、ESP32、AT8236、电池等参数 |

本次未读取或写入 `tools/reid_pc_test/images*/`、`tools/reid_pc_test/outputs/`、`tools/reid_pc_test/weights/`。

## 3. 系统架构口径

### 3.1 功能架构

首版功能分为 6 个功能组：

| 功能组 | 主要功能 | 首版状态 |
| --- | --- | --- |
| 人机交互 | 启动、手动遥控、目标确认、重拍/取消、状态提示、日志开关 | 必做 |
| 感知与身份 | 人物检测、目标初始化、目标记忆、ReID 辅助、track/bbox gate | 必做，ReID 已在 Android 侧跑通 |
| 距离与风险 | 初始化距离标定、图像伺服、Distance State、左/中/右可通行空间 | 距离已实现，避障为下一阶段 |
| 行为决策 | FollowStateMachine、SafetyFusion、ActionArbitrator、目标丢失搜索 | 必做 |
| 控制执行 | `Control(left,right)`、Human Cart Simulator 提示、后续 VehicleControlAdapter | Simulator 已跑通，真实底盘控制未接通 |
| 底盘安全 | ESP32 协议解析、AT8236 驱动、限速、急停、通信超时停车 | 下位机联调重点 |

### 3.2 逻辑架构

逻辑链路保持：

```text
Perception Evidence
  -> TargetTrackManager / IdentityBeliefAccumulator
  -> DistanceState / TraversabilityEvidence / SystemSafetyEvidence
  -> FollowStateMachine
  -> ActionArbitrator
  -> ControlGenerator
  -> Human Cart Simulator 或 VehicleControlAdapter
```

ReID 是身份置信度辅助，不是单独身份判决器；身份不确定时优先 `motion_stop / REACQUIRE_HOLD`，不允许继续前进。

### 3.3 物理架构

首版物理链路为：

```text
Android 手机
  -> USB Serial / Bluetooth
  -> ESP32
  -> UART 或 I2C
  -> AT8236 四路编码器电机驱动板
  -> 4 个 520 编码器电机
  -> 四驱麦轮/差速底盘
  -> 模块化购物筐或载物平台
```

麦轮首版按差速使用：`ctrl_left -> 左侧两轮`，`ctrl_right -> 右侧两轮`，横移不作为首版自主跟随必需功能。

## 4. 方案权衡与约束

| 维度 | 方案 A：大型底盘 | 方案 B：牵引式 | 方案 C：竞赛底盘 + 模块化购物筐 |
| --- | --- | --- | --- |
| 采购可得性 | 低到中 | 中 | 高 |
| 成本 | 高 | 中 | 中低 |
| 控制风险 | 中高 | 高 | 中 |
| 结构风险 | 中 | 高 | 中 |
| 周期匹配 | 低 | 低 | 高 |
| 展示效果 | 最像真实购物车 | 有新意但不稳定 | 缩比原型清晰可展示 |
| 当前结论 | 暂不采用 | 暂不采用 | 当前主线 |

关键约束：

- 4 周集中实践，优先闭环演示而非商业级完整能力。
- 预算原则上每人不超过 2500 元，核心平台尽量控制在 1500-3000 元。
- Android 手机作为上位机主脑，不默认引入树莓派、服务器或云端实时控制。
- 真实底盘前进尚未接通，进入极低速底盘联调前需先通过 Human Cart Simulator 的诊断复测。
- 结构载重首版按“购物筐 + 1-3 kg 物品”验证，更高载重以后续实测为准。
- 目标丢失、身份不确定、障碍风险、急停和通信异常均优先保证安全。

## 5. 需求追溯、验证与确认方法

| 需求 | 来源 | 验证方法 | 确认方法 | 证据 |
| --- | --- | --- | --- | --- |
| 手动遥控 | FR-01 / REQ-01 | 前进、后退、左转、右转、停止各 3 次 | 教师/组员现场观察 | 视频、测试表 |
| 目标确认与重识别启动 | FR-10~FR-13 | 采集、确认、重拍、取消、确认后重识别 | 操作流程复现 | 截图、录屏、状态日志 |
| 低速自主跟随 | FR-03 | 直线、转弯、停下场景 | 完整演示 | 视频、测试记录 |
| 目标丢失安全搜索 | FR-05 | 遮挡或离开画面，检查 motion_stop、LOCAL_SEARCH、STOP | 安全状态检查 | `cartfollow_diagnostics`、视频 |
| 急停与通信异常停车 | NFR-02 | 急停按钮、断开通信 | 停车响应观察 | 视频计时、固件日志 |
| 距离控制 | NFR-04 / Phase 2 | 初始化 1 m 左右 setpoint，观察 `TOO_FAR / OK / TOO_CLOSE / UNKNOWN` | 跟随距离测量 | debug 面板、测试表 |
| 障碍处理 | FR-06 | 静态障碍、行人横穿、左/中/右空间评分 | 不碰撞、不抢行 | 视频、风险日志 |
| 购物筐固定 | FR-04 / NFR-08 | 空载、1 kg、3 kg，直行、转弯、急停 | 无明显滑移、松动、倾覆 | 结构照片、测试表 |
| 隐私边界 | NFR-09 | 日志开关关闭时不生成 session/crop/gallery | 本地目录检查 | 存储目录截图 |

## 6. 关键参数

| 参数 | 当前口径 | 说明 |
| --- | --- | --- |
| 跟随速度 | 0.3-0.8 m/s | 首版低速；真实底盘需再限速标定 |
| 跟随距离 | 1.0-2.0 m 可调 | 首版用初始化距离标定 + 图像伺服 |
| 急停响应 | 不超过 0.5 s | 视频计时验证 |
| 通信超时 | 300-500 ms 初值 | ESP32 看门狗与 OpenBot `h<interval_ms>` 对齐 |
| 搜索超时 | 约 5 s | Human Cart Simulator 当前 `SEARCH_TIMEOUT_MS=5000` |
| 丢失判定 | 连续约 10 帧未匹配 | 当前 `FOLLOW_LOST_M=10` |
| 重识别稳定帧 | 约 8 帧 | 当前 `REACQUIRE_MATCH_N=8` |
| 距离远阈值 | `heightScale < 0.85` | 判定 `TOO_FAR` |
| 距离近阈值 | `heightScale > 1.15` | 判定 `TOO_CLOSE` |
| 载重目标 | 购物筐 + 1-3 kg | 首版稳定演示口径 |
| 电机 | 12 V 520 编码器电机，减速比 30，空载 320 rpm | 来自产品参数汇总 |
| 驱动 | AT8236 四路编码器电机驱动 | UART/I2C 协议待实物确认 |

## 7. WBS、里程碑与甘特图

### 7.1 WBS 摘要

| WBS | 工作包 | 负责人建议 | 主要交付 |
| --- | --- | --- | --- |
| 1 | 项目管理与建模 | 成员 C 主，A/B 配合 | 需求、WBS、甘特图、SysML 12 图、周报 |
| 2 | Android 上位机 | 成员 A 主 | Human Cart Simulator、ReID、状态机、诊断日志、track/bbox gate |
| 3 | ESP32 / AT8236 下位机 | 成员 B 主 | ESP32 固件、AT8236 适配、WiFi 调控、轮向标定、通信超时 |
| 4 | 结构与物资 | 成员 C 主，B 配合 | 手机支架、线束、电池固定、购物筐 / 载物平台 |
| 5 | 联调与安全 | A/B/C | 上位机复测、真实底盘低速准入、目标丢失、障碍、急停 |
| 6 | 测试与交付 | 成员 C 主 | diagnostics 复盘、测试记录、演示视频、PPT/报告 |

### 7.2 里程碑

| 里程碑 | 时间 | 验收标准 |
| --- | --- | --- |
| M1 需求与基础方案收口 | 第 1 周末 | 需求、WBS、BOM、OpenBot / 下位机方案分析和第 1 周阶段材料完成 |
| M2 上位机策略闭环完成 | 第 2 周末 | Human Cart Simulator、Android ReID、诊断日志和 track / bbox gate 形成可复盘闭环 |
| M3 真实底盘联调准入 | 第 3 周中前 | ESP32 / AT8236、轮向标定、通信超时停车、结构固定和上位机复测达到极低速联调门槛 |
| M4 购物车化与安全闭环 | 第 3 周末 | 购物筐 / 载物平台、目标丢失搜索、急停、通信异常停车和基础障碍停车完成 |
| M5 最终演示闭环 | 第 4 周末 | 完整演示、测试记录、视频、PPT、报告收口 |

### 7.3 甘特图口径

```text
任务                      第1周  第2周  第3周  第4周
需求/方案/SysML            ███    ██
Human Cart Simulator        █      ███
ReID/track/bbox gate               ███    █
ESP32/AT8236 实体调试        █      ███    █
结构固定与载物平台                 ██     ███    █
通信超时/急停/安全保护              ██     ███    █
真实底盘极低速联调                        ██     ██
测试记录/视频/PPT            █      █      ██     ███
```

## 8. 开放问题

1. AT8236 的 UART/I2C 具体协议、速度值域、STOP/刹车语义仍需实物资料确认。
2. ESP32 与 AT8236 的逻辑电平、共地、供电拓扑和急停接线需实测确认。
3. 购物筐固定件尺寸、磁吸规格和机械限位形式需结合底盘孔位实测。
4. 新版 APK 仍需用 `cartfollow_diagnostics` 复测目标返回、遮挡恢复和干扰者抑制。
5. 真实底盘前进控制接通前，需要确认 `candidate_switch_penalty`、`belief_high_bbox_failed`、非目标转绿和 `hard_stop_count` 没有恶化。
