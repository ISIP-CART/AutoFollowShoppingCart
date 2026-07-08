# AutoFollowShoppingCart

基于 OpenBot 架构的室内自主跟随购物车原型项目，目标是在课程周期内完成一个低成本、可演示、可复用的首版闭环系统。

## 项目背景与目标

本项目面向室内超市或模拟超市场景，尝试解决传统购物车需要用户持续手推的问题。我们采用 OpenBot 的核心思路，以 Android 手机作为上位机主脑，负责视觉感知、人物检测、跟随决策和交互；以 Arduino Nano 或 ESP32 作为下位机，负责接收控制命令、驱动电机并执行底层安全保护。

首版目标不是商业化成品，而是一个课程可交付的工程原型。它需要做到：

- 在室内平坦环境中完成单人低速稳定跟随。
- 在目标丢失、急停、通信异常、前方障碍等情况下优先保证安全。
- 在预算和 4 周集中实践周期内完成软硬件集成验证。

## 首版范围

### In Scope

- OpenBot 基础链路跑通
- 手动遥控与底盘联调
- 指定人物检测、目标锁定与自主跟随
- 购物筐或载物平台集成
- 目标丢失后的安全搜寻与停车
- 急停、通信异常停车、基础障碍停车
- 基础测试记录与演示流程整理

### Out of Scope

- 完整 SLAM
- 复杂路径规划
- 高精地图构建
- 自动结账
- 真实超市长期部署
- 云端多车调度

## 系统总体架构

```text
购物者 / 目标人物
        ↓
Android 手机 / OpenBot App
（摄像头感知 + AI 推理 + 跟随决策 + 人机交互）
        ↓
通信接口：USB Serial / Bluetooth
        ↓
微控制器：Arduino Nano / ESP32
（指令解析 + 电机控制 + 超时保护）
        ↓
电机驱动模块
        ↓
移动底盘
        ↓
购物筐 / 载物平台
```

目标丢失策略采用“安全优先的有限重定位”：

- 目标丢失后立即取消前进速度，禁止继续向前跟随。
- 系统进入短时原地低速搜寻状态。
- 若在限定时间内重新锁定目标，则恢复 FOLLOW。
- 若搜寻超时或出现其他异常，则发送 `STOP` 并停车。

## 当前目录结构

```text
AutoFollowShoppingCart/
├─ design/
│  ├─ structure.md
│  ├─ background/
│  ├─ gantt/
│  └─ doc/
│     ├─ 2-9自主跟随机器人平台-深研院-张凯.pptx
│     ├─ 智能系统创新实践学生手册.pdf
│     └─ 项目汇报超市自主跟随购物车.md
├─ dev/
│  └─ OpenBot/        # Team OpenBot fork, tracked as a Git submodule
├─ tools/
│  └─ reid_pc_test/   # PC-side ReID experiments, scripts, docs, and local ignored assets
├─ README.md
└─ AGENTS.md
```

## 计划中的硬件组成

- Android 手机：视觉感知、模型推理、控制界面
- 微控制器：Arduino Nano 或 ESP32
- 移动底盘：双轮差速或兼容 OpenBot 的低成本底盘
- 电机驱动模块
- 电源系统
- 手机固定支架
- 购物筐 / 载物平台
- 急停装置
- 可选障碍传感器：超声波优先

## 软件栈与 OpenBot 关系

- OpenBot：作为总体架构、手机端框架和底盘控制思路来源
- Android Studio：上位机 App 修改、调试和构建
- OpenBot App 工程：复用遥控、模式切换、感知与推理主框架
- MCU 固件：串口通信、电机控制、超时保护、急停
- 轻量级视觉模型：人物检测与短时目标跟踪

本项目的重点不是重写 OpenBot，而是基于 OpenBot 做“购物车场景化集成”和安全策略增强。

当前 OpenBot 工程以 Git submodule 形式放在 `dev/OpenBot`，指向团队组织下的 OpenBot fork。首次克隆本仓库后，可执行：

```bash
git submodule update --init --recursive
```

硬件到位前的软件验证优先从 OpenBot Android 工程开始：使用 Android Studio 打开 `dev/OpenBot/android`，先完成 Gradle Sync、`robot` App 构建安装和手机端摄像头 / 权限验证，再进入跟随逻辑和手机-下位机通信联调。

团队协作、分支、OpenBot 子模块提交流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 当前上位机进度（2026-07-08）

上位机开发已经从文档规划推进到 Android 真机验证阶段，当前主线在 `dev/OpenBot/android`：

- `Human Cart Simulator` 已跑通目标初始化、确认、距离状态、行为动作与 debug 面板。
- 阶段 A 已完成：`Evidence -> BehaviorDecisionResult -> BehaviorAction -> HumanCommand` 最小行为层可运行。
- 阶段 B 已完成首版：Android 端 TFLite ReID 已接入 Human Cart Simulator，`osnet_x0_25` 推理可运行，实机约 30 FPS。
- PC 端 ReID 研究工作区位于 `tools/reid_pc_test/`，已包含 crop 数据整理、bbox gate、chronological replay、sequence replay 等脚本和文档。
- `PersonCropCollector` 与 `PersonSequenceCollector` 已用于采集真实 OpenBot 检测框 crop 与连续时序数据。

当前暴露的核心问题不是“ReID 能否运行”，而是：

```text
如何防止目标离开后误跟干扰者；
如何在目标返回后更快、更安全地重捕获。
```

下一步阶段 C 是在 Android 端新增轻量 `TargetTrackManager + IdentityBeliefAccumulator`，把单帧 ReID 候选升级为“稳定轨迹 + 累计身份信念”，再驱动 `REACQUIRE / FOLLOW_CAUTION / FOLLOW_CONFIDENT`。

注意：`*.tflite`、`*.pth`、`*.onnx`、`tools/reid_pc_test/images/`、`tools/reid_pc_test/outputs/`、`tools/reid_pc_test/weights/` 等本地模型、图片和实验输出默认不进入版本库。

## 4 周阶段目标

1. 第 1 周：跑通 OpenBot 基础链路，完成需求、分工、BOM 和初版 PPT。
2. 第 2 周：完成底盘联调、人物检测与自主跟随初版。
3. 第 3 周：完成购物车化结构、安全停车、参数调优和中期材料。
4. 第 4 周：完成联调、测试记录、最终演示流程、汇报与文档收口。

## 后续待办与风险

### 待办

- 明确三位成员的最终分工
- 产出 BOM、接线图和测试记录模板
- 确认 OpenBot 具体代码仓与硬件兼容路径
- 落实底盘、电源、急停和购物筐结构方案

### 风险

- OpenBot 工程理解不充分导致手机端调试卡住
- 电源与重心设计不合理影响跟随稳定性
- 目标跟随在遮挡和多人干扰场景下不稳定
- 采购周期挤压联调时间
