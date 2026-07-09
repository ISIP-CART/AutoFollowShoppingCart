# OpenBot 源码分析与上位机架构理解

> 文档目的：记录对 OpenBot 源码的分析和理解，便于后续上位机开发时快速回顾架构和关键代码路径。
> 面向对象：上位机 / Android 端负责人
> 最后更新：2026-07-01

---

## 1. 代码仓库结构

```
dev/OpenBot/                          # Git 子模块，指向团队 fork
├── android/                          # Android 工程根目录
│   ├── robot/                        # ★ 核心 App：运行在手机（机器人）上
│   │   └── src/main/java/org/openbot/
│   │       ├── vehicle/              # 车辆控制：Vehicle.java, Control.java, UsbConnection.java
│   │       ├── tflite/               # AI 推理：Autopilot.java, Navigation.java, Detector.java
│   │       ├── autopilot/            # 自动驾驶 Fragment
│   │       ├── common/               # 通用 UI：ControlsFragment.java
│   │       ├── env/                  # 控制器输入：GameController.java
│   │       └── utils/                # 常量与工具
│   ├── controller/                   # 遥控器 App（安装在另一台手机上）
│   │   └── src/main/java/org/openbot/controller/
│   └── build.gradle
├── firmware/                         # 下位机固件
│   ├── openbot/openbot.ino           # ★ Arduino/ESP32 固件（1886 行）
│   └── README.md                     # 固件使用说明
├── docs/                             # 文档与图片
└── policy/                           # 驾驶策略训练
```

---

## 2. 通信架构全景

```
┌─────────────────────────────────────────────────────────────────┐
│  Android 手机（上位机）                                           │
│  ┌──────────────┐   ┌─────────────────┐   ┌──────────────────┐  │
│  │ 摄像头 → 感知  │ → │ 跟随决策/手动输入 │ → │ Vehicle.setControl│  │
│  │ (Detector/   │   │ (Autopilot/      │   │ (Control.left,    │  │
│  │  Autopilot)  │   │  GameController) │   │  Control.right)   │  │
│  └──────────────┘   └─────────────────┘   └───────┬──────────┘  │
│                                                    │             │
│                                         Vehicle.sendControl()   │
│                                         格式: "c%d,%d\n"        │
│                                         范围: [-255, 255]       │
└────────────────────────────────────────────────┼────────────────┘
                                                 │
                                      USB Serial / Bluetooth
                                                 │
┌────────────────────────────────────────────────┼────────────────┐
│  ESP32（下位机）                                ▼                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ process_ctrl_msg() → ctrl_left, ctrl_right               │   │
│  │ update_left_motors() / update_right_motors()             │   │
│  │   → PWM 输出给电机驱动                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 关键代码路径

| 步骤 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 输入 → Control | `GameController.java:205` | `convertJoystickToControl(xAxis, yAxis)` | 摇杆输入 → left/right |
| 输入 → Control | `Autopilot.java:69` | `recognizeImage(bitmap)` | AI 推理直接输出 Control |
| Control → 串口 | `Vehicle.java:415` | `sendControl()` | 格式化为 `c%d,%d\n` |
| 串口发送 | `UsbConnection.java:201` | `send(msg)` | 字节写入 USB 串口 |
| 串口接收 | `openbot.ino:1504` | `on_serial_rx()` | 固件端接收字符 |
| 指令解析 | `openbot.ino:1532` | `parse_msg()` | 按 header 分发 |
| 控制解析 | `openbot.ino:1355` | `process_ctrl_msg()` | `strtok` 解析 `c<left>,<right>` |
| 电机驱动 | `openbot.ino:1200` | `update_left_motors()` | 根据符号输出 PWM |

---

## 3. OpenBot 原生串口协议详解

### 3.1 物理层

```text
波特率: 115200
数据位: 8
校验:   无 (N)
停止位: 1
帧尾:   \n (0x0A)
```

### 3.2 帧格式

```text
<header><body>\n

示例:
  c128,100\n        → header='c', body="128,100"
  h300\n            → header='h', body="300"
  f\n               → header='f', body=""
```

### 3.3 指令全集

| Header | 格式 | 方向 | 功能 | 值域 |
|--------|------|------|------|------|
| `c` | `c<left>,<right>` | 上位机→下位机 | **电机控制** | left,right ∈ [-255,255] |
| `h` | `h<ms>` | 上位机→下位机 | 心跳超时设置 | ms 或 -1(关闭) |
| `f` | `f` | 上位机→下位机 | 查询固件能力 | 无参数 |
| `v` | `v<ms>` | 上位机→下位机 | 电压上报间隔 | ms |
| `w` | `w<ms>` | 上位机→下位机 | 轮速上报间隔 | ms |
| `s` | `s<ms>` | 上位机→下位机 | 超声波上报间隔 | ms |
| `i` | `i<left>,<right>` | 上位机→下位机 | 指示灯 | 0/1 |
| `l` | `l<front>,<back>` | 上位机→下位机 | 照明灯 | 0-255 |
| `v` | `v<voltage>` | 下位机→上位机 | 电池电压回传 | 浮点 |
| `w` | `w<rpm_l>,<rpm_r>` | 下位机→上位机 | 轮速回传 | 整数 |
| `s` | `s<cm>` | 下位机→上位机 | 超声波距离回传 | 整数 |
| `r` | `r` | 下位机→上位机 | 就绪信号 | 无 |

### 3.4 `c` 指令的语义

**关键理解：`c` 指令的两个参数是双通道 PWM 占空比值，不是 forward/turn。**

```text
c<ctrl_left>,<ctrl_right>

ctrl_left  > 0  → 左侧电机正转（前进）
ctrl_left  < 0  → 左侧电机反转（后退）
ctrl_left == 0  → 左侧电机停止

ctrl_right > 0  → 右侧电机正转（前进）
ctrl_right < 0  → 右侧电机反转（后退）
ctrl_right == 0 → 右侧电机停止

绝对值 = PWM 占空比 = 速度
```

### 3.5 心跳/看门狗机制

```cpp
// openbot.ino:1002-1006
if ((millis() - heartbeat_time) >= heartbeat_interval) {
    ctrl_left = 0;
    ctrl_right = 0;
}
```

- `heartbeat_interval` 由上位机通过 `h<ms>` 设置
- `heartbeat_time` 在**收到任何合法指令**时刷新（不只是单独的 heartbeat 消息）
- 超时后固件自动将 ctrl_left 和 ctrl_right 置 0，输出停止信号

---

## 4. 下位机硬件架构（本项目 vs OpenBot 原生）

OpenBot 原生 RTR_520 使用 ESP32 直接 PWM → 4 电机（GPIO 硬件并联为左右两组）。
本项目使用 AT8236 驱动模块，其内部架构为：

```text
ESP32（本项目下位机）
  │  UART 或 I2C（仅 4 根线：VCC/GND/TX/RX 或 VCC/GND/SDA/SCL）
  ↓
AT8236 板载 STM32 协处理器
  │  解析主控指令 → 4 路速度闭环 PID → PWM 控制
  │  采集 4 路 AB 相编码器 → 计算实际转速
  ↓
AT8236 驱动芯片 ×4 → 四个 520 编码器电机
```

**与上位机无关**：上位机只发送 `c<left>,<right>`，不关心后端的 AT8236 通信细节。

---

## 5. Android 端发送控制指令的完整链路

### 4.1 Control 数据类

```java
// Control.java
public class Control {
    private final float left;   // [-1.0, 1.0]
    private final float right;  // [-1.0, 1.0]
}
```

### 4.2 Vehicle 类——发送控制

```java
// Vehicle.java:415-429
public void sendControl() {
    int left = (int) (getLeftSpeed());   // control.left * speedMultiplier
    int right = (int) (getRightSpeed()); // control.right * speedMultiplier
    sendStringToDevice(String.format(Locale.US, "c%d,%d\n", left, right));
}
```

- `speedMultiplier` = 128（慢速）/ 192（正常）/ 255（快速）
- 每次 `setControl()` 都会立即调用 `sendControl()`

### 4.3 三种输入模式 → Control

**Joystick 模式（手动遥控）：**

```java
// GameController.java:205-215
public Control convertJoystickToControl(float xAxis, float yAxis) {
    float left = -yAxis;
    float right = -yAxis;
    if (left >= 0) left += xAxis;
    else left -= xAxis;
    if (right >= 0) right -= xAxis;
    else right += xAxis;
    return new Control(left, right);
}
```

等价公式：`left ≈ forward - turn`, `right ≈ forward + turn`

**AI 推理模式（Autopilot）：**

```java
// Autopilot.java:69-96
public Control recognizeImage(final Bitmap bitmap, final int indicator) {
    // TFLite 模型推理 → 直接输出 [left, right]
    return new Control(predicted_ctrl[0][0], predicted_ctrl[0][1]);
}
```

**控制器 App 模式（远程遥控）：**

```java
// ControlsFragment.java:256-263
case Constants.CMD_DRIVE:
    JSONObject driveValue = event.getJSONObject("driveCmd");
    vehicle.setControl(
        new Control(
            Float.parseFloat(driveValue.getString("l")),
            Float.parseFloat(driveValue.getString("r"))));
```

### 4.4 USB 通信类

```java
// UsbConnection.java:201-209
public void send(String msg) {
    if (isOpen() && !isBusy()) {
        busy = true;
        serialDevice.write(msg.getBytes(UTF_8));
        busy = false;
    }
}
```

---

## 5. 下位机固件（openbot.ino）关键代码段

### 5.1 支持的硬件平台

| 宏定义 | MCU | 说明 |
|--------|-----|------|
| `DIY` | Arduino Nano | 无 PCB 自建版 |
| `PCB_V1/V2` | Arduino Nano | 有 PCB 版 |
| `RTR_TT` | Arduino Nano | TT 电机 Ready-to-Run |
| `RTR_TT2` | ESP32 | TT 电机 ESP32 版 |
| `RTR_520` | **ESP32** | **520 编码器电机，4 轮** |
| `MTV` | ESP32 | 多地形车 |
| `DIY_ESP32` | ESP32 | 无 PCB 自建版 |

### 5.2 RTR_520 模式的引脚和电机架构

```cpp
// 电机控制引脚（4 电机 × 2 相 = 8 GPIO）
PIN_PWM_LF1 = 16, PIN_PWM_LF2 = 17  // 左前电机
PIN_PWM_LB1 = 19, PIN_PWM_LB2 = 18  // 左后电机
PIN_PWM_RF1 = 26, PIN_PWM_RF2 = 25  // 右前电机
PIN_PWM_RB1 = 33, PIN_PWM_RB2 = 32  // 右后电机

// 4 路 PWM Channel（同侧并联）
CH_PWM_L1 = 0  → LF1 + LB1（左侧两电机 A 相）
CH_PWM_L2 = 1  → LF2 + LB2（左侧两电机 B 相）
CH_PWM_R1 = 2  → RF1 + RB1（右侧两电机 A 相）
CH_PWM_R2 = 3  → RF2 + RB2（右侧两电机 B 相）

// 编码器引脚（4 路独立）
PIN_SPEED_LF = 21, PIN_SPEED_RF = 35
PIN_SPEED_LB = 23, PIN_SPEED_RB = 36
```

### 5.3 电机控制逻辑

```cpp
// openbot.ino:1200-1224
void update_left_motors() {
  if (ctrl_left < 0) {
    analogWrite(PIN_PWM_L1, -ctrl_left);  // L1 输出 PWM（反转）
    analogWrite(PIN_PWM_L2, 0);           // L2 拉低
  } else if (ctrl_left > 0) {
    analogWrite(PIN_PWM_L1, 0);           // L1 拉低
    analogWrite(PIN_PWM_L2, ctrl_left);   // L2 输出 PWM（正转）
  } else {
    // ctrl_left == 0 → coast_mode ? 滑行 : 刹车
  }
}
```

### 5.4 轮速计算

```cpp
// openbot.ino:1660-1677
void send_wheel_reading(long duration) {
  float rpm_factor = 60.0 * 1000.0 / duration / TICKS_PER_REV;
  rpm_left = (counter_lf + counter_lb + counter_lm) * rpm_factor;
  rpm_right = (counter_rf + counter_rb + counter_rm) * rpm_factor;
  // 清零计数器...
}
```

- RTR_520 的 `TICKS_PER_REV = 209`（530rpm 电机，减速比 19，每转 11 ticks）
- 左右轮速 = 同侧所有编码器计数之和 × rpm_factor

---

## 6. 对本项目上位机开发的启示

### 6.1 首版不需要修改 Android 端

因为：
- OpenBot 原生协议 `c<left>,<right>` 已经是项目需要的接口
- Android 端已有完整的 Control → 串口发送链路
- 跟随决策层（Autopilot / 自定义）只需要输出 `Control(left, right)`

### 6.2 上位机开发重点工作

1. **人物检测与目标锁定**：在现有 Detector 基础上实现目标用户识别
2. **确认式目标初始化**：新增“候选目标采集 -> 用户确认 -> 重识别启动 -> 倒计时进入 FOLLOW”的两阶段初始化流程
3. **ReID 增强目标记忆**：在 `bbox + 运动连续性 + 颜色特征` 基础上，预留或接入 ReID embedding，用于多人干扰抑制和目标重识别
4. **跟随控制策略**：基于检测框位置输出 `Control(left, right)`
   - 目标在画面中心 → `Control(forward, forward)`
   - 目标偏左 → `Control(forward, forward - turn_delta)`
   - 目标偏右 → `Control(forward - turn_delta, forward)`
5. **目标记忆与状态机实现**：至少覆盖 `IDLE / CAPTURE_TARGET / LOCKED_PENDING_CONFIRM / CONFIRMED_ARMED / REACQUIRE_TARGET / READY_TO_FOLLOW / FOLLOW / LOST / SEARCH / STOP`
6. **目标丢失处理**：
   - 连续 N 帧未检测到 → 输出 `Control(0, 0)` 取消前进
   - 启动搜索计时 → 输出 `Control(0, ±search_speed)` 原地扫描
   - 超时 → 输出 `Control(0, 0)` 停车
7. **Human Cart Simulator**：在硬件未联调完成前实时显示“前进 / 左转 / 右转 / 停止 / 搜索”等人类可执行提示，以手持手机方式完成近似闭环测试
8. **模式切换 UI**：手动 / 跟随 / 停止切换，以及候选目标确认 / 重拍 / 取消交互

### 6.3 与下位机的接口

上位机只需发送：
- `c<left>,<right>` — 运动控制（已有实现）
- `h<interval_ms>` — 心跳超时设置

不需要关心：
- AT8236 通信协议
- 麦轮运动学映射
- 电机方向配置
- 编码器读取

---

## 7. 相关文件索引

| 文件 | 用途 |
|------|------|
| `dev/OpenBot/firmware/openbot/openbot.ino` | 固件源码（1886行） |
| `dev/OpenBot/firmware/README.md` | 固件通信协议文档 |
| `dev/OpenBot/android/robot/.../Vehicle.java` | Android 端车辆控制 |
| `dev/OpenBot/android/robot/.../Control.java` | 控制值数据类 |
| `dev/OpenBot/android/robot/.../UsbConnection.java` | USB 串口通信 |
| `dev/OpenBot/android/robot/.../GameController.java` | 摇杆→Control 转换 |
| `dev/OpenBot/android/robot/.../Autopilot.java` | AI 自动驾驶 |
| `dev/OpenBot/android/controller/.../DualDriveSeekBar.kt` | 控制器 App UI |
| `design/OpenBot与四驱麦轮AT8236下位机适配风险说明.md` | 下位机适配风险分析 |
| `design/structure.md` | 系统设计主文档 |
| `design/自主跟随购物车上位机软件开发计划.md` | 上位机目标初始化、ReID、Human Cart Simulator 与无底盘调试计划 |
| `design/工程决策与实现策略记录.md` | 工程决策记录 |

---

## 8. 2026-07-09 上位机实现状态补充

本文件前文主要记录 OpenBot 源码结构与上位机接入点。当前工程进展已经从“预留或接入 ReID embedding”推进到 Android 真机策略验证阶段：

- Human Cart Simulator 已成为当前上位机闭环验证入口，真实底盘前进控制仍未接通；
- Android 端已完成 `osnet_x0_25_market1501.tflite` ReID 推理，且 ReID crop 已修正为 upright 输入；
- `TargetTrackManager + IdentityBeliefAccumulator` 已接入 trackId、lockedTrackId、targetBelief、suspectedTrack；
- 最新策略补入 locked track ghost memory、suspected track 滞回、loose/default/strict bbox gate、恢复后 relock 和非 locked 空间支持门控；
- Human Cart Simulator 新增“记录日志”开关，默认关闭，关闭时不创建 `cartfollow_diagnostics` session，也不写 CSV/JSON/crop/gallery/event。

因此，当前上位机代码仍复用 OpenBot 原有 Android 主脑和控制链路，但本轮验证重点是身份、轨迹、bbox gate 与状态恢复策略，而不是改造底盘控制路径。进入真实底盘前进联调前，需要先用新版 diagnostics 证明 `candidate_switch_penalty` 和 `belief_high_bbox_failed` 下降，且非目标转绿与 hard stop 不增加。
