# 02 OpenBot 平台调研

## 1. 调研目的

本文用于回答以下问题：

1. OpenBot 平台的整体架构和各层能力边界是什么。
2. Android App 提供了哪些可复用功能，人物跟随如何实现。
3. MCU 固件的通信协议、命令格式、传感器支持和安全机制。
4. 硬件兼容范围、车体方案和已知坑点。
5. 本项目复用 OpenBot 的最低可行路径和需要自建的部分。

本文不替代 OpenBot 官方文档，而是服务于本项目的工程决策。

## 2. 总体架构

### 2.1 分层模型

OpenBot 的架构可以从官方 README 和论文摘要归纳为四层：

```
[智能手机] ─── Android App (视觉 + AI + 控制 + 交互 + 数据采集)
     │
     │ USB Serial / BLE
     │
[微控制器] ─── Arduino Nano / ESP32 Firmware (指令解析 + 电机控制 + 传感器采集 + 安全保护)
     │
     │ PWM / GPIO
     │
[车体]   ─── 电机驱动 + 底盘 + 传感器 (超声波/编码器/碰撞/电压)
```

### 2.2 子系统边界

| 层次 | 职责 | 本项目可复用程度 |
| --- | --- | --- |
| Android App | 摄像头采集、模型推理、目标检测/跟踪、模式切换、遥控、数据记录、蓝牙游戏手柄支持 | 高 (可直接用 Robot App，修改跟随逻辑和安全状态机) |
| 通信层 | USB Serial (115200 bps) 或 BLE (ESP32) | 高 (协议格式可直接复用) |
| MCU 固件 | 串口指令解析、PWM 电机控制、编码器转速采集、超声波测距、电池电压监测、指示灯控制、心跳超时停车 | 高 (根据底盘和 MCU 型号修改配置宏) |
| 电机驱动 | L298N / AT8236 等 PWM 驱动模块 | 需根据实际驱动板适配 |
| 底盘 | 差速 / 四驱底盘 | 需根据实际底盘调参 |

## 3. Android App 详解

### 3.1 应用构成

OpenBot Android 工程位于 `android/` 目录，包含两个 App：

- **Robot App** (`android/robot/`)：安装在机器人手机上，承担感知、推理、控制输出。
- **Controller App** (`android/controller/`)：安装在遥控手机上，通过 WiFi 发送控制指令和接收视频流。

本项目首版只需要 Robot App。

### 3.2 构建环境

| 项目 | 要求 |
| --- | --- |
| IDE | Android Studio Electric Eel 2022.1.1 或更新 |
| 编译 SDK | API 33 |
| 目标 SDK | API 32 |
| 最低 API | 21 |
| Gradle 插件 | AGP 7.4.0 |

常见构建问题：

- AGP 版本不兼容：需升级 Android Studio 或降级 Gradle 插件。
- ESP32 板包必须使用 v2.0.17，v3.x.x 不兼容。
- 中国产 Arduino Nano 需要安装 CH340 驱动。

### 3.3 Robot App 功能模块

Robot App 包含以下主界面：

| 界面 | 功能 | 本项目相关性 |
| --- | --- | --- |
| Free Roam | 基础遥控 + 实时传感器数据 (电池/速度/超声波) | 用于底盘联调和手动遥控验证 |
| Data Collection | 数据集采集，支持传感器 + 图像记录 | 可选，如需训练自驾驶策略 |
| Controller Mapping | 蓝牙手柄按键映射验证 | 用于遥控测试 |
| Robot Info | 机器人信息查询和基础指令测试 | 用于下位机联调 |
| Autopilot | 运行自训练驾驶策略模型 | 首版不用，OpenBot 的 CIL-Mobile 策略需自己训练 |
| Object Tracking | 80 类 COCO 物体检测 + 目标跟踪 + 自动跟随 | 核心复用模块 |
| Point Goal Navigation | 基于 ARCore 的相对目标导航 | 首版不用 |
| Model Management | 模型下载、切换和基准测试 | 用于选择人物检测模型 |
| Projects | 运行 OpenBot Playground 项目 | 首版不用 |
| Default | 旧版单屏集成界面 | 仍包含人物跟随和自主导航入口 |

### 3.4 Object Tracking / 人物跟随 实现细节

这是本项目最重要的复用模块。Object Tracking 界面提供：

- **模型选择**：多个 TFLite 目标检测模型可选。
- **目标类别选择**：80 个 COCO 类别，包括 "person"。
- **置信度阈值**：可调节以过滤误检。
- **推理设备**：CPU / GPU / NNAPI。
- **线程数**：CPU 推理时的并行度。
- **Dynamic Speed** (v0.6.2+)：根据目标框面积动态调节车速，目标越近速度越低。在横屏模式下效果最佳。
- **控制模式**：Controller（蓝牙手柄）、Drive Mode、Speed Mode。

Object Tracking 的工作流程：

1. 手机摄像头持续采集画面。
2. 选定的 TFLite 检测模型输出所有检测到的物体类别与边界框。
3. 用户选择 "person" 作为跟踪目标。
4. 系统锁定画面中置信度最高的人（或满足特定条件的人）。
5. 根据目标边界框在画面中的位置和大小计算控制量：
   - 横向偏差 → 转向量。
   - 目标框大小 → 距离估计 → 线速度。
6. 通过 USB Serial 发送 `c<left>,<right>` 指令给 MCU。

**关键限制**：目前的 Object Tracking 不支持多目标区分和特定人物锁定。它简单地跟踪画面中检测到的 "person" 类别。在多人场景中可能切换到错误的人。这就是本项目需要加入"目标初始化"和"目标锁定"逻辑的原因。

### 3.5 可用模型与性能

OpenBot 预置和可下载的检测模型：

| 模型 | 输入分辨率 | mAP | 典型 CPU FPS (S20FE) | 适用场景 |
| --- | --- | --- | --- | --- |
| MobileNetV1-300 (预置) | 300x300 | 18% | 34 | 默认人物跟随，速度最快但精度最低 |
| MobileNetV3-320 | 320x320 | 16% | 34 | 略差的精度，类似速度 |
| YoloV4-tiny-224 | 224x224 | 22% | 30 | 精度提升，速度尚可 |
| YoloV4-tiny-416 | 416x416 | 29% | 12 | 精度明显提升，速度下降 |
| YoloV5s-320 | 320x320 | 28% | 13 (Mi9) | 精度/速度平衡好 |
| EfficientDet-L0-320 | 320x320 | 26% | 16 | 横屏模式下性能劣化 |

**对本项目的建议**：

- 先使用预置的 MobileNetV1-300 跑通人物检测和基础跟随链路。
- 如果精度不足（频繁误检或漏检），切换到 YoloV5s-320 或 YoloV4-tiny-416。
- 手机性能越好，可用的模型档次越高。仓库现有文档提到的手机实际性能未知，需要实际测试。
- 推理设备建议优先使用 GPU 或 NNAPI（多数现代手机有加速）。

### 3.6 代码结构

```
android/robot/src/main/java/org/openbot/
├── original/DefaultActivity.java   # 旧版主Activity，集成所有功能
├── original/CameraActivity.java    # 摄像头管理基类
├── logging/SensorService.java      # 手机传感器采集
├── server/ServerCommunication.java  # 与训练服务器的通信
├── server/NsdService.java          # 网络服务发现
├── env/
│   ├── Vehicle.java                # 车辆控制接口
│   ├── GameController.java         # 蓝牙手柄接口
│   ├── PhoneController.java        # 手机遥控接口
│   └── AudioPlayer.java            # 音频反馈
└── tflite/
    ├── Autopilot.java              # 自驾驶策略模型
    └── Detector.java               # 目标检测模型
```

本项目可能需要修改的部分：

- `Detector.java`：如果选用 OpenBot 未预置的模型，需要添加模型定义。
- 跟随控制逻辑：OpenBot 的 Object Tracking 的跟随策略比较简单，需要增加目标丢失检测、状态机、安全速度限制。
- `Vehicle.java` 实现：确保控制指令正确发送。
- UI：添加模式切换、安全状态显示。

## 4. MCU 固件详解

### 4.1 支持的 MCU

| MCU | 支持版本 | 通信方式 | 备注 |
| --- | --- | --- | --- |
| Arduino Nano (ATmega328P) | 全功能 | USB Serial | 默认方案，Old Bootloader |
| ESP32 Dev Module | 全功能 + BLE | USB Serial / BLE | 需安装 ESP32 板包 v2.0.17 |
| 其他 MCU | 需满足最低 IO 要求 | 需自适配 | 见下文 |

使用其他 MCU 的最低 IO 要求：

- 1x USB-to-TTL Serial (与手机通信)
- 4x PWM (电机控制)
- 1x Analog Pin (电池电压监测)
- 2x Digital Pin (编码器转速传感器，可选)
- 1x Digital Pin (超声波传感器，可选)
- 2x Digital Pin (指示灯 LED，可选)

### 4.2 硬件配置宏

固件开头需要设置硬件配置 (`openbot.ino`)：

| 宏 | 对应硬件 |
| --- | --- |
| `OPENBOT DIY` | 自建版本，使用 L298N 驱动 |
| `OPENBOT PCB_V1` / `PCB_V2` | 定制 PCB 版本 |
| `OPENBOT RTR_TT` | 成品套件 (TT 电机) |
| `OPENBOT RTR_520` | 成品套件 (520 电机) |
| `OPENBOT RC_CAR` | 改装 RC 卡车 |
| `OPENBOT LITE` | 教育版简化版本 |
| `OPENBOT MTV` | 多地形车辆 |
| `DIY_ESP32` | 自建版 + ESP32 |

### 4.3 可选传感器/功能宏

| 宏 | 功能 | 默认 |
| --- | --- | --- |
| `HAS_VOLTAGE_DIVIDER` | 电池电压分压器 | 取决于配置 |
| `HAS_INDICATORS` | 指示灯 LED | 取决于配置 |
| `HAS_SPEED_SENSORS_FRONT` / `_BACK` | 编码器转速传感器 | 取决于配置 |
| `HAS_SONAR` | 超声波传感器 | 取决于配置 |
| `USE_MEDIAN` | 超声波中值滤波 | 取决于配置 |
| `HAS_BUMPER` | 碰撞传感器 | 取决于配置 |
| `HAS_OLED` | OLED 显示屏 | 取决于配置 |
| `HAS_LEDS_FRONT` / `_BACK` / `_STATUS` | 前后/状态 LED | 取决于配置 |
| `BLUETOOTH` | 蓝牙通信 (仅 ESP32) | 0 (关闭) |
| `NO_PHONE_MODE` | 无手机自主避障模式 | 0 (关闭) |

### 4.4 串口通信协议

波特率：**115200 bps**（默认，可在 App 设置中查看）。

#### 手机 → MCU 指令

| 指令格式 | 含义 | 参数 |
| --- | --- | --- |
| `c<left>,<right>` | 电机控制 | left/right ∈ [-255, 255], 正=前进, 负=后退, 0=停止 |
| `i<left>,<right>` | 指示灯 | left/right ∈ [0,1], 1Hz 闪烁 |
| `l<front>,<back>` | LED 亮度 | front/back ∈ [0,255] |
| `s<time_ms>` | 超声波触发间隔 | 默认 1000ms |
| `w<time_ms>` | 编码器上报间隔 | 默认 1000ms |
| `v<time_ms>` | 电压上报间隔 | 默认 1000ms |
| `h<time_ms>` | 心跳超时 | -1 = 禁用, 超时后自动停车 |
| `b<time_ms>` | 碰撞复位间隔 | 默认 750ms |
| `n<color>,<state>` | 状态 LED | color=b/g/y, state=0/1 |
| `f` | 查询机器人类型和功能 | 返回如 `fRTR_V1:v:i:s:b:wf:wb:lf:lb:ls:` |

#### MCU → 手机 上报

| 前缀 | 含义 | 格式 |
| --- | --- | --- |
| `v` | 电池电压 | `v<voltage>` |
| `w` | 编码器转速 | `w<left_rpm>,<right_rpm>` (rpm) |
| `s` | 超声波距离 | `s<distance_cm>` |
| `b` | 碰撞信息 | `b<lf/rf/cf/lb/rb>` 表示触发的碰撞传感器 |

### 4.5 安全相关机制

固件自带的安全功能：

1. **心跳超时停车** (`h<time_ms>`)：如果在指定时间内未收到心跳或任何指令，MCU 自动停车。这是本项目需要的通信超时保护的基础。
2. **超声波紧急停车**：在 `NO_PHONE_MODE` 中，超声波读数低于 `STOP_DISTANCE` (默认 10cm) 时停止。
3. **碰撞检测**：通过碰撞传感器（可选）检测碰撞并上报。
4. **电压监测**：可设置 `VOLTAGE_MIN` 最低驱动电压。

**本项目需要增强的安全功能**：

- 心跳超时机制需要在手机端定时发送心跳（可以是周期性指令本身）。
- 超声波传感器虽然 OpenBot 支持，但仅在上报数据，没有在跟随模式中做主动停车拦截。本项目需要在手机端（决策层）实现基于超声波或视觉的障碍停车逻辑。
- 急停按钮需要接入 MCU 的一个数字引脚，并在固件中增加急停中断处理（OpenBot 原生固件未集成急停按钮）。

### 4.6 依赖库

| 库 | 用途 | 何时需要 |
| --- | --- | --- |
| PinChangeInterrupt | 将普通引脚用作中断（编码器/超声波） | 启用速度传感器或超声波时 |
| Adafruit_SSD1306 + Adafruit_GFX | OLED 显示 | 启用 OLED 时 |

## 5. 车体与硬件

### 5.1 OpenBot 原生车体方案

| 方案 | 成本 | 特点 | 本项目适配性 |
| --- | --- | --- | --- |
| DIY (3D 打印) | ~$50 | 双轮差速，L298N 驱动，3D 打印底盘 | 需要 3D 打印，但设计开源 |
| Lite (教育版) | 更低 | 简化的 DIY 版本 | 太小，负载不足 |
| RTR-TT | $100+ | 成品套件，TT 电机 | 即买即用，但负载有限 |
| RTR-520 | $150+ | 成品套件，520 编码器电机 | 扭矩更大，更适合本项目 |
| RC Truck | 取决于改装件 | 1:16 RC 卡车改装 | 改装工作量大 |
| MTV | 较高 | 四轮差速，户外能力 | 价格高，室内过度 |

### 5.2 本项目底盘适配

本项目已采购的底盘为大号铝合金四驱差速底盘（305 系列，12V 320rpm 编码器电机），与 OpenBot 原生底盘不同。

适配关键点：

1. **电机驱动**：四驱需要支持四路电机或两路并联，需要确认驱动板型号（OpenBot 原生支持的 L298N 是双路的，四驱需 AT8236 等四路驱动或双 L298N）。
2. **编码器**：底盘自带编码器，OpenBot 固件的 `HAS_SPEED_SENSORS_FRONT` 需要适配编码器接线和计数逻辑（`DISK_HOLES` 等参数）。
3. **固件配置**：大概率需要新建一个类似于 `OPENBOT DIY` 的自定义配置。
4. **尺寸和载重**：305 系列底盘尺寸较大，适合加装购物筐，但需要确认电池、电机驱动和控制板的物理安装空间。
5. **电机 PWM 范围**：OpenBot 使用 [-255, 255] 的 PWM 范围控制电机电压比例。12V 电机需要确认驱动板的供电和逻辑电平兼容性。

## 6. 通信方式对比

| 方式 | 优点 | 缺点 | 本项目首版建议 |
| --- | --- | --- | --- |
| USB Serial | 稳定、低延迟、不需要额外硬件、即插即用、默认波特率 115200 | 需要 OTG 线连接手机和 MCU | **首版优先** |
| BLE (ESP32) | 无线、部署灵活 | 需 ESP32、调试复杂、抗干扰性不如有线 | 备选，后续可考虑 |

## 7. 控制方式

OpenBot 支持多种控制方式：

| 方式 | 实现 | 本项目适用性 |
| --- | --- | --- |
| 蓝牙游戏手柄 | PS4 / Xbox 等手柄通过蓝牙连接手机 | 首版手动遥控测试阶段使用 |
| Controller App | 另一台手机安装 Controller App 通过 WiFi 遥控 | 可选，用于分体操控展示 |
| Python / Node.js | 通过 WiFi + WebRTC/RTSP 在电脑端遥控 | 可选，调试便利 |
| 自主跟随 (Object Tracking) | App 内置的目标检测 + 自动控制 | **核心复用** |
| Autopilot (CIL-Mobile) | 自训练的端到端驾驶策略 | 首版不用，需要大量训练数据和 GPU |

## 8. 本项目复用方案与自建部分

### 8.1 直接复用

| 模块 | 复用内容 | 注意事项 |
| --- | --- | --- |
| Android App | Robot App 完整工程 | 需在 Android Studio 中打开 `dev/OpenBot/android` 进行编译 |
| Object Tracking 界面 | 人物检测 + 基础跟随逻辑 | 需要增加目标锁定、目标丢失检测、安全状态机 |
| 串口通信 | USB Serial 通信链路，baud 115200 | 需确认手机 OTG 兼容性 |
| MCU 固件 | `openbot.ino` 基础框架 | 需根据实际底盘创建新的硬件配置宏 |
| Free Roam | 遥控测试界面 | 用于底盘联调和手动遥控演示 |
| Robot Info | 指令测试和传感器状态查看 | 用于通信链路调试 |

### 8.2 需要修改

| 模块 | 修改内容 | 优先级 |
| --- | --- | --- |
| 目标锁定 | 增加"初始化目标"逻辑：用户站在指定位置 → 系统锁定该人 → 进入 FOLLOW | 高 |
| 目标丢失检测 | 连续 N 帧未检测到目标 → 进入 LOST | 高 |
| 安全状态机 | 增加 FOLLOW / LOST / SEARCH / STOP / OBSTACLE / EMERGENCY 状态管理 | 高 |
| 跟随控制策略 | 目标丢失后立即取消线速度；搜索阶段仅允许原地低速左右扫描 | 高 |
| 超声波障碍停车 | 在手机端利用超声波读数实现障碍减速/停车 | 高 |
| MCU 固件配置 | 创建适配本项目四驱底盘的硬件配置 | 高 |
| 急停按钮处理 | 在 MCU 固件中增加急停中断和停车逻辑 | 高 |
| 通信超时保护 | 确认并测试心跳超时参数 | 高 |
| 购物车 UI | 简化界面，突出模式切换、跟随状态、安全状态 | 中 |
| 参数调整界面 | 方便调跟随时速度、距离、转向灵敏度 | 中 |

### 8.3 首版不需要

| 模块 | 原因 |
| --- | --- |
| Autopilot (CIL-Mobile) | 需要大量数据采集、GPU 训练和复杂调参 |
| Point Goal Navigation | 需要 ARCore，首版不需要 |
| Playground / Projects | 课程原型不需要拖拽编程 |
| Web Server Controller | 不需要远程操控 |
| Driving Policy Training | 4 周周期内来不及 |

## 9. 已知风险与降级方案

| 风险 | 详细说明 | 降级方案 |
| --- | --- | --- |
| App 编译失败 | AGP 版本不兼容、依赖下载失败、手机 API 版本过低 | 1) 先尝试预编译 APK 安装；2) 记录完整的构建环境配置；3) 降级到 maven central 可用的依赖版本 |
| USB Serial 连接失败 | OTG 线不兼容、手机不支持 USB Host、驱动问题 | 1) 准备多根 OTG 线和适配器；2) 测试手机的 USB Host 能力；3) 考虑 ESP32 + BLE 备选 |
| 默认人物检测模型精度不足 | MobileNetV1-300 mAP 仅 18%，可能频繁漏检或误检 | 1) 切换到 YoloV5s-320 或 YoloV4-tiny-416；2) 降低相机分辨率提高帧率；3) 限定受控光照和背景环境 |
| 自主跟随不稳定 | 目标丢失频繁、蛇形摆动、速度振荡 | 1) 只做直线和简单转弯演示；2) 降低速度；3) 增加检测帧数容错 (连续 N 帧丢失才判定) |
| MCU 固件与底盘不匹配 | 四驱底盘需要自定义 PWM 和编码器配置 | 1) 先以最简配置跑通基本电机驱动；2) 逐步增加编码器和超声波功能 |
| 电源问题 | 供电不足导致手机掉电或 MCU 重启 | 1) 手机和 MCU 使用独立电源；2) 确保电池输出电流满足四驱满载需求 |
| 超声波受振动干扰 | OpenBot 官方文档明确指出超声波对振动敏感 | 1) 增加硅胶减震垫；2) 采用中值滤波 (`USE_MEDIAN`)；3) 如果不可靠，降低对超声波的依赖，改用视觉辅助 |

## 10. 参考资料来源

| 资料 | URL | 获取内容 |
| --- | --- | --- |
| OpenBot 官网 | https://www.openbot.org/ | 项目定位和使用说明 |
| OpenBot GitHub 主页 | https://github.com/ob-f/OpenBot | 架构概述、快速入门 |
| OpenBot Android README | https://github.com/ob-f/OpenBot/blob/master/android/README.md | App 构建步骤和故障排除 |
| OpenBot Robot App README | https://github.com/ob-f/OpenBot/blob/master/android/robot/README.md | App 功能、模型列表、基准测试、代码结构 |
| OpenBot Firmware README | https://github.com/ob-f/OpenBot/blob/master/firmware/README.md | 通信协议、硬件配置宏、传感器支持、测试步骤 |
| OpenBot Body README | https://github.com/ob-f/OpenBot/blob/master/body/README.md | 车体方案概览 |
| OpenBot Controller README | https://github.com/ob-f/OpenBot/blob/master/controller/README.md | 控制方式汇总 |
| OpenBot Policy README | https://github.com/ob-f/OpenBot/blob/master/policy/README.md | 自驾驶策略训练流程 (首版不用) |
| OpenBot Playground README | https://github.com/ob-f/OpenBot/blob/master/open-code/README.md | 积木编程平台 (首版不用) |
| OpenBot Releases | https://github.com/ob-f/OpenBot/releases | 版本历史和重要变更 |
| OpenBot 论文 | https://arxiv.org/abs/2008.10631 | 学术背景和系统验证 |
| 仓库 dev/OpenBot submodule | 本仓库 `dev/OpenBot/` | 团队 fork 的实际代码 |

## 11. 下步建议

1. 在 Android Studio 中打开 `dev/OpenBot/android`，完成 Robot App 的首编和手机安装验证。
2. 确认手机 USB Host / OTG 能力，准备串口通信测试。
3. 根据实际采购的底盘和驱动板，在固件 `openbot.ino` 中新建硬件配置。
4. 先以 MobileNetV1-300 跑通人物检测 → 目标锁定 → 基础跟随链路。
5. 在跟随闭环跑通后，再根据实际模型精度决定是否切换更强的检测模型。
6. 安全功能（急停、通信超时、障碍停车、目标丢失处理）在跟随链路确认后再逐一叠加。
