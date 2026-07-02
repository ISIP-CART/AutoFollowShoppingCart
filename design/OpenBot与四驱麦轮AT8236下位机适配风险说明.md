# OpenBot 原生架构与本项目四驱麦轮 + AT8236 下位机适配风险说明

> 项目：基于 OpenBot 的自主跟随购物车原型  
> 文档目的：梳理当前硬件方案中可能与 OpenBot 原生架构不兼容的点，明确下位机同学需要重点解决的适配任务。  
> 面向对象：下位机 / 电控 / 驱动控制负责人  
> 当前结论：本方案不是不能适配 OpenBot，但不能直接套用 OpenBot 原生 L298N 双路 PWM 驱动逻辑，需要在 ESP32 端增加一层“OpenBot 指令 → 四驱麦轮/AT8236 控制协议”的适配层。

---

## 1. 当前项目硬件路线

当前项目计划采用如下路线：

```text
Android 手机 / OpenBot App
  ↓
ESP32 下位机
  ↓ UART 或 I2C
AT8236 四路编码器电机驱动模块（板载 STM32 协处理器）
  ↓
四驱麦轮底盘
````

其中：

* Android 手机负责视觉感知、目标检测、跟随决策和用户交互；
* ESP32 负责接收上位机运动指令、安全状态判断、通信超时保护、急停处理、指令限幅和协议转换；
* AT8236 驱动板负责四路电机驱动、编码器采集以及底层电机控制；
* 四驱麦轮底盘负责实际运动执行。

该结构与 OpenBot 原生典型结构不同。OpenBot 原生结构更接近：

```text
Android 手机 / OpenBot App
  ↓
Arduino / ESP32
  ↓ PWM + DIR
L298N / 双路电机驱动
  ↓
左右两路电机
```

因此，本项目的主要工作不是简单接线，而是要完成下位机控制架构适配。

---

## 1.1 OpenBot 原生固件通信协议详解（基于 `openbot.ino` 源码分析）

在讨论适配之前，必须先精确理解 OpenBot 原生固件的通信协议和控制逻辑。以下内容均基于 `dev/OpenBot/firmware/openbot/openbot.ino`（1886 行）的源码分析。

### 1.1.1 串口物理参数

```text
波特率：115200
数据位：8
校验位：无（N）
停止位：1
帧格式：文本行，以换行符 \n 结束
```

源码位置：`openbot.ino:898`

```cpp
Serial.begin(115200, SERIAL_8N1);
```

### 1.1.2 上位机→下位机指令格式

OpenBot 使用**单字符指令头 + 参数体 + 换行符**的简单文本协议：

```text
<header><body>\n
```

源码位置：`openbot.ino:560-565, 1504-1519`

```cpp
enum msgParts { HEADER, BODY };
msgParts msgPart = HEADER;
char header;
char endChar = '\n';
const char MAX_MSG_SZ = 60;
char msg_buf[MAX_MSG_SZ] = "";
```

指令解析：先读一个字符作为 `header`，其余字符存入 `msg_buf`，遇到 `\n` 后调用 `parse_msg()` 根据 `header` 分发。

### 1.1.3 核心指令列表（完整）

| 指令头 | 格式 | 功能 | 参数范围 |
|--------|------|------|----------|
| `c` | `c<left>,<right>` | **电机控制** — 这是跟随/遥控的核心指令 | left, right ∈ [-255, 255] |
| `h` | `h<interval_ms>` | **心跳/看门狗** — 超过 interval_ms 未收到任何指令则自动停车 | -1 表示关闭 |
| `f` | `f` | **功能查询** — 返回固件类型和传感器能力 | 无参数 |
| `v` | `v<interval_ms>` | 电压上报间隔设置 | ms |
| `w` | `w<interval_ms>` | 轮速（编码器）上报间隔 | ms |
| `s` | `s<interval_ms>` | 超声波测距上报间隔 | ms |
| `i` | `i<left>,<right>` | 左右指示灯 | 0 或 1 |
| `l` | `l<front>,<back>` | 前后照明灯亮度 | 0-255 |
| `b` | `b<interval_ms>` | 碰撞检测复位间隔 | ms |
| `n` | `n<color>,<state>` | 状态 LED 控制 | color: b/g/y, state: 0/1 |

**关键结论：OpenBot 原生固件不认识 `forward`、`turn`、`mode` 等语义。它只接收 `c<left>,<right>` 中的两个 PWM 占空比值。**

### 1.1.4 `c` 指令解析与电机控制

`c` 指令的解析函数 `process_ctrl_msg()`，源码位置：`openbot.ino:1355-1367`

```cpp
void process_ctrl_msg() {
  char *tmp;
  tmp = strtok(msg_buf, ",:");
  ctrl_left = atoi(tmp);
  tmp = strtok(NULL, ",:");
  ctrl_right = atoi(tmp);
}
```

解析出 `ctrl_left` 和 `ctrl_right` 后，在 `update_vehicle()` 中调用 `update_left_motors()` / `update_right_motors()` 驱动电机。

**左电机控制逻辑**，源码位置：`openbot.ino:1200-1224`

```cpp
void update_left_motors() {
  if (ctrl_left < 0) {
    analogWrite(PIN_PWM_L1, -ctrl_left);  // 反转：L1 输出 PWM
    analogWrite(PIN_PWM_L2, 0);           //       L2 拉低
  } else if (ctrl_left > 0) {
    analogWrite(PIN_PWM_L1, 0);           // 正转：L1 拉低
    analogWrite(PIN_PWM_L2, ctrl_left);   //       L2 输出 PWM
  } else {
    // ctrl_left == 0 → 刹车或滑行
  }
}
```

**关键发现：`ctrl_left > 0` → 前进, `ctrl_left < 0` → 后退。方向由符号控制，速度由绝对值控制。**

### 1.1.5 ESP32 原生 4 电机架构（RTR_520 模式）

OpenBot 的 ESP32 变体（如 `RTR_520`、`RTR_TT2`、`DIY_ESP32`）**本身就支持 4 个编码器电机**，并非只支持双电机。

源码位置：`openbot.ino:398-406`（RTR_520 引脚定义）

```cpp
// 左前电机
const int PIN_PWM_LF1 = 16;
const int PIN_PWM_LF2 = 17;
// 左后电机
const int PIN_PWM_LB1 = 19;
const int PIN_PWM_LB2 = 18;
// 右前电机
const int PIN_PWM_RF1 = 26;
const int PIN_PWM_RF2 = 25;
// 右后电机
const int PIN_PWM_RB1 = 33;
const int PIN_PWM_RB2 = 32;
```

**4 个电机共享 4 路 PWM Channel**，源码位置：`openbot.ino:857-864`

```cpp
ledcAttachPin(PIN_PWM_LF1, CH_PWM_L1);  // 左前电机 A 相 = CH0
ledcAttachPin(PIN_PWM_LB1, CH_PWM_L1);  // 左后电机 A 相 = CH0（并联！）
ledcAttachPin(PIN_PWM_LF2, CH_PWM_L2);  // 左前电机 B 相 = CH1
ledcAttachPin(PIN_PWM_LB2, CH_PWM_L2);  // 左后电机 B 相 = CH1（并联！）
ledcAttachPin(PIN_PWM_RF1, CH_PWM_R1);  // 右前电机 A 相 = CH2
ledcAttachPin(PIN_PWM_RB1, CH_PWM_R1);  // 右后电机 A 相 = CH2（并联！）
ledcAttachPin(PIN_PWM_RF2, CH_PWM_R2);  // 右前电机 B 相 = CH3
ledcAttachPin(PIN_PWM_RB2, CH_PWM_R2);  // 右后电机 B 相 = CH3（并联！）
```

**这意味着 OpenBot 原生 RTR_520 模式已经实现了：左前=左后、右前=右后的四电机并联差速控制。与本项目首版的"差速模式"思路完全一致，只是驱动方式从 PWM 直连变为通过 AT8236 转发。**

### 1.1.6 心跳/看门狗机制

源码位置：`openbot.ino:1002-1006, 1386-1393`

```cpp
// loop() 中：
if ((millis() - heartbeat_time) >= heartbeat_interval) {
    ctrl_left = 0;
    ctrl_right = 0;
}

// 解析 h 指令：
void process_heartbeat_msg() {
  heartbeat_interval = atol(msg_buf);
  heartbeat_time = millis();  // 每次收到任何指令都会刷新
}
```

**关键设计点：**
- 心跳超时阈值由上位机通过 `h<ms>` 指令动态设置
- **不是单独的 heartbeat 消息**：收到**任何**合法指令都会刷新 `heartbeat_time`
- 超时后固件直接将 `ctrl_left` 和 `ctrl_right` 置 0，然后通过 `update_vehicle()` 输出停止

### 1.1.7 Android 端如何生成 `c` 指令

Android 端源码位置：`dev/OpenBot/android/robot/src/main/java/org/openbot/vehicle/Vehicle.java:415-429`

```java
public void sendControl() {
    int left = (int) (getLeftSpeed());   // control.left * speedMultiplier
    int right = (int) (getRightSpeed()); // control.right * speedMultiplier
    sendStringToDevice(String.format(Locale.US, "c%d,%d\n", left, right));
}
```

- `speedMultiplier` = 128（慢速）/ 192（正常）/ 255（快速）
- `control.left` 和 `control.right` 是 [-1.0, 1.0] 的浮点数
- **Android 端不做 forward/turn 语义转换**，直接使用 left/right 值

**"forward/turn" 到 left/right 的转换在 Android 端完成**，通过 `GameController.java:205-215` 的 `convertJoystickToControl()`：

```java
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

公式等价于：`left = forward - turn`, `right = forward + turn`（符号方向取决于坐标系定义）。

### 1.1.8 下位机回传格式

回传同样使用单字符头 + 值的格式：

| 回传头 | 格式 | 含义 |
|--------|------|------|
| `v` | `v12.34` | 电池电压 (V) |
| `w` | `w120,115` | 左右轮速 (rpm) |
| `s` | `s150` | 超声波距离 (cm) |
| `b` | `blf` / `brf` 等 | 碰撞位置 |
| `r` | `r` | 上电就绪信号 |

源码位置：`openbot.ino:903`（就绪信号）、`1653`（电压）、`1676`（轮速）、`1759`（超声波）

---

## 2. 与 OpenBot 原生架构不相容的主要点

### 2.1 驱动板类型不同

OpenBot 原生支持两种驱动模式：

**模式一（Arduino Nano + L298N）**：适用于 `DIY`、`PCB_V1`、`PCB_V2`、`RTR_TT` 等 Nano 变体。Nano 通过 4 路 PWM 直接控制 L298N 双路 H 桥，驱动左右两个电机。

**模式二（ESP32 + 直接 PWM）**：适用于 `RTR_520`、`RTR_TT2`、`DIY_ESP32` 等 ESP32 变体。ESP32 的 4 路 LEDC PWM Channel 通过 GPIO 直连 4 个电机的 A/B 相，实现左前+左后并联、右前+右后并联的差速控制。源码见 `openbot.ino:857-864`。

OpenBot 原生两种模式的共同点是：**MCU 直接输出 PWM 信号给电机驱动电路，不经过中间协议层**。

本项目使用 AT8236 四路编码器电机驱动模块。AT8236 不是简单的"PWM 输入型驱动板"。根据采购资料，该模块是一种带内部控制逻辑的智能电机驱动板（是否板载 STM32 协处理器待与卖家确认，详见 Section 7）。其控制方式为：

```text
ESP32 发送 UART / I2C 指令或 PWM 信号
  ↓
AT8236 内部解析并产生 PWM、读取编码器、控制电机
```

因此：

* ESP32 通过 UART 或 I2C（仅 4 线）向 AT8236 的 STM32 发送目标速度指令；
* STM32 负责底层 PWM 生成、编码器采集和速度闭环控制；
* ESP32 不再直接输出 PWM 给电机；
* OpenBot 原生固件中 `update_left_motors()` / `update_right_motors()` 的 PWM 逻辑**需替换为 AT8236 UART/I2C 通信层**。

---

### 2.2 电机路数：本项目为独立四轮控制 vs 原生为左右并联

OpenBot 原生架构在**控制层面**面向双通道差速驱动：

```text
ctrl_left  → 左侧所有电机
ctrl_right → 右侧所有电机
```

在 ESP32 RTR_520 模式中，固件将 4 个物理电机**硬件并联**为左右两组（左前+左后共用 CH_PWM_L1/L2，右前+右后共用 CH_PWM_R1/R2），因此物理上有 4 个电机但控制上只有 2 个自由度。源码见 `openbot.ino:857-864`。

本项目是四驱底盘 + AT8236 独立四路控制，**ESP32 需要分别控制四个电机的速度**：

```text
M1 → 左前轮
M2 → 右前轮
M3 → 左后轮
M4 → 右后轮
```

因此，ESP32 需要把 OpenBot 上位机输出的 `c<left>,<right>` 运动指令映射成四个独立电机的速度指令。相比 OpenBot 原生的 GPIO 硬件并联方案，本项目需要在 ESP32 软件层实现映射。

即使暂时不使用麦轮的横移能力，也至少需要完成如下映射：

```text
OpenBot 输出：c<left>,<right>
即：ctrl_left  ∈ [-255, 255]
    ctrl_right ∈ [-255, 255]

转换为四轮速度（首版差速模式）：
front_left  = ctrl_left
rear_left   = ctrl_left
front_right = ctrl_right
rear_right  = ctrl_right
```

注意：实际正负号需要根据电机安装方向、轮子方向和 AT8236 接口编号实测确定。本项目的四轮映射需要在**ESP32 固件中软件实现**，而非像 OpenBot 原生那样通过 GPIO 硬件并联自动完成。

---

### 2.3 底盘从普通四驱变成麦轮

最终底盘选择麦轮后，系统的信号传递结构本身不需要推翻，仍然可以保持：

```text
OpenBot App → ESP32 → AT8236 → 四个电机
```

但是，麦轮会影响“运动指令到四轮速度”的映射方式。

麦轮底盘理论上支持：

* 前进 / 后退；
* 原地旋转；
* 左右横移；
* 斜向运动；
* 平面全向运动。

而 OpenBot 原生固件的控制接口始终是双通道 PWM 值：

```text
c<ctrl_left>,<ctrl_right>   // 范围 [-255, 255]
```

OpenBot 原生固件本身不理解 v_x / v_y / omega 等运动学概念。所有运动学转换都在 Android 端完成。Android 端最终输出 `Control(left, right)` 两个浮点值，经 `speedMultiplier` 缩放后以 `c<left>,<right>` 格式发送。

对于本项目，麦轮完整控制需要：

```text
v_x：前进速度
v_y：横向速度
omega：旋转角速度
```

这里存在一个接口差异：

```text
OpenBot 原生跟随：2 自由度指令
麦轮完整运动：3 自由度指令
```

因此首版建议：

> 自主跟随模式下，不启用麦轮横移能力，先把麦轮当作普通四驱差速底盘使用。

也就是：

```text
ctrl_left  → 左侧两个麦轮
ctrl_right → 右侧两个麦轮
v_y = 0（无横移，不启用麦轮全向）
```

这样上位机 OpenBot App **完全不需修改**，下位机只需把收到的 `c<left>,<right>` 映射到四个麦轮电机。

后续如果要增加横移能力，例如“购物车自动横向微调到用户正后方”，则需要修改上位机控制逻辑或增加新的控制接口。这个不建议作为首版目标。

---

## 3. 麦轮是否会影响整体信号传递结构？

### 3.1 不影响主链路

麦轮不会改变主信号链路：

```text
手机视觉跟随决策
  ↓
ESP32 下发运动意图
  ↓
AT8236 执行四电机控制
  ↓
麦轮底盘运动
```

所以，从系统架构角度看，麦轮不要求推翻现有设计。

---

### 3.2 会影响底层运动学映射

普通四驱差速底盘可以粗略看作：

```text
左侧两个轮子速度一致
右侧两个轮子速度一致
```

麦轮如果只做前进和转向，也可以采用类似差速映射。

但如果要真正发挥麦轮全向运动能力，则需要完整的麦轮运动学：

```text
front_left_speed
front_right_speed
rear_left_speed
rear_right_speed
=
f(v_x, v_y, omega)
```

不同麦轮安装方向、轮子编号、坐标系定义会导致正负号不同，因此必须通过实测确认。

首版建议采用保守策略：

```text
自主跟随模式：
v_y = 0
只做前进、后退、左转、右转

手动调试模式：
可选支持横移，用于测试麦轮能力，但不作为自主跟随首版必需功能
```

---

## 4. 推荐的控制模式划分

建议下位机固件支持两种控制模式。

---

### 4.1 模式 A：OpenBot 兼容差速模式（首版推荐）

这是首版自主跟随推荐模式。与 OpenBot 原生协议完全兼容，**不需要修改上位机代码**。

输入（来自 OpenBot 原生协议 `c<left>,<right>`）：

```text
ctrl_left  ∈ [-255, 255]  — 上位机生成的左侧 PWM 值
ctrl_right ∈ [-255, 255]  — 上位机生成的右侧 PWM 值
```

注意：OpenBot 原生协议不区分 "forward"/"turn"，上位机已经完成了运动学→双通道 PWM 的转换。正数=前进，负数=后退，绝对值=速度。

输出（ESP32 发给 AT8236 的四轮速度）：

```text
front_left_speed
front_right_speed
rear_left_speed
rear_right_speed
```

映射方式（四轮差速，首版不使用麦轮全向）：

```text
front_left_speed  = ctrl_left
rear_left_speed   = ctrl_left
front_right_speed = ctrl_right
rear_right_speed  = ctrl_right
```

> 说明：OpenBot 原生 RTR_520 模式通过 GPIO 硬件并联实现同侧电机同步（左前=左后，右前=右后）。本项目改为在 ESP32 软件层实现同等映射，两者在运动效果上等价。

优点：

* 与 OpenBot 原生协议 `c<left>,<right>` 完全兼容；
* 上位机 Android App 零修改；
* 自主跟随更稳定、更安全；
* 适合超市低速跟随场景；
* 调试难度最低。

缺点：

* 没有发挥麦轮横移能力；
* 麦轮优势暂时没有充分体现。

适用范围：

* 首版自主跟随；
* 课程演示；
* 低速安全购物车跟随。

---

### 4.2 模式 B：麦轮全向控制模式

这是后续扩展模式，不建议作为首版核心任务。

输入：

```text
v_x
v_y
omega
```

输出：

```text
front_left_speed
front_right_speed
rear_left_speed
rear_right_speed
```

优点：

* 可以实现横移；
* 可以做更灵活的跟随位置调整；
* 更能体现麦轮底盘特点。

缺点：

* OpenBot 原生上位机不直接输出 v_y；
* 需要改上位机 App 或增加额外控制接口；
* 控制复杂度明显提高；
* 在载物购物车场景下，横移可能带来额外安全风险；
* 需要更严格的速度限制和姿态稳定测试。

适用范围：

* 手动调试；
* 后续增强；
* 展示麦轮能力；
* 非首版必需功能。

---

## 5. 推荐的首版总体控制架构

首版建议采用如下结构（基于 OpenBot 实际协议 `c<left>,<right>` + `h<interval>`）：

```text
Android / OpenBot App
  通过 USB Serial / Bluetooth 发送：
  - c<left>,<right>      // left, right ∈ [-255, 255]，正=前进，负=后退
  - h<interval_ms>       // 心跳超时阈值，超过此时间无指令则 ESP32 自动停车
  - f                    // 功能查询
  ↓
ESP32
  1. 解析 OpenBot 原生文本协议（单字符头 + 参数体 + \n）
  2. 执行安全状态机（基于 h 心跳 + 急停 + 通信超时）
  3. 限幅、滤波、斜坡启动
  4. 将 ctrl_left / ctrl_right 映射为四轮目标速度（首版差速模式）
  5. 通过 UART 向 AT8236 发送四路速度指令
  ↓
AT8236 驱动模块（STM32 + AT8236×4）
  1. STM32 通过 UART/I2C 接收四路目标速度（仅 4 线连接）
  2. STM32 内部完成速度闭环 PID + 4 路 PWM 生成
  3. 4 × AT8236 驱动芯片控制四个电机
  4. STM32 采集 4 路编码器，计算实际转速
  5. 可选回传速度 / 编码器 / 状态 / 电压信息给 ESP32
  ↓
四驱麦轮底盘
```

推荐首版数据流（精确对应 OpenBot 原生协议）：

```text
OpenBot App → 串口:
  "c128,100\n"   // ctrl_left=128, ctrl_right=100（即左轮 50% 前进，右轮 39% 前进）
  "c0,0\n"       // 停车
  "h300\n"       // 设置心跳超时 300ms

ESP32 解析后:
  ctrl_left  = 128  // 来自解析 c<left>,<right>
  ctrl_right = 100

ESP32 差速映射（首版）:
  M1 = front_left  = ctrl_left   // = 128
  M2 = front_right = ctrl_right  // = 100
  M3 = rear_left   = ctrl_left   // = 128
  M4 = rear_right  = ctrl_right  // = 100

ESP32 → AT8236 (UART):
  根据 AT8236 协议将四个速度值编码发送
```

**关键点**：
- OpenBot App 已经完成 "摇杆/跟随策略 → left/right" 的转换，下发的是双通道 PWM 值，不是 forward/turn
- ESP32 的差速映射非常简单：`同侧电机速度相同`（与 OpenBot 原生 GPIO 并联等效）
- 首版 ESP32 不需要做 forward/turn → left/right 转换，那个转换 Android 端已经做了

具体 M1 / M2 / M3 / M4 与实际车轮位置的对应关系，需要下位机同学通过测试确定。

---

## 6. ESP32 端需要新增的适配层

ESP32 不能只照搬 OpenBot 原生 L298N 固件，而应增加如下模块。

---

### 6.1 OpenBot 指令解析层

负责接收来自手机端的运动指令。OpenBot 原生协议已在上方 Section 1.1 详细分析，此处仅总结与下位机适配直接相关的要点。

**已明确事项：**

* 通信方式：USB Serial（优先）或 Bluetooth Serial
* 串口参数：115200 baud, 8N1（源码 `openbot.ino:898`）
* 数据格式：单字符指令头 + 逗号分隔参数 + 换行符 `\n`（源码 `openbot.ino:560-565`）
* 控制指令：`c<ctrl_left>,<ctrl_right>`，值域 [-255, 255]，正=前进，负=后退
* 心跳指令：`h<interval_ms>`，超时后固件自动将 ctrl_left/ctrl_right 置 0
* 功能查询：`f`，固件返回类型和能力列表
* 指令刷新率：由 Android 端 `sendControl()` 调用频率决定，典型值 10-30 Hz

**ESP32 解析层需要做：**

1. 从串口读取字符流，按 `\n` 分行
2. 识别单字符 header（`c`, `h`, `f` 等）
3. 对 `c` 指令：用 `strtok` 按 `,` 分割得到 `ctrl_left` 和 `ctrl_right`（整数值）
4. 对 `h` 指令：解析心跳超时阈值，启动内部看门狗
5. 对 `f` 指令：返回本项目的固件类型和能力列表

**解析输出的内部抽象（供安全状态机和运动学映射层使用）：**

```text
ctrl_left   : int,  ∈ [-255, 255]
ctrl_right  : int,  ∈ [-255, 255]
heartbeat_ms: long, 超时间隔（ms），-1=关闭
new_cmd_rcv : bool, 收到新指令标志（用于刷新心跳计时器）
```

---

### 6.2 安全状态机层

ESP32 端必须独立实现安全状态机，不能只依赖手机端。

建议至少包含：

```text
INIT        初始化
MANUAL      手动模式
FOLLOW      自主跟随模式
STOP        停止
EMERGENCY   急停
COM_TIMEOUT 通信超时
OBSTACLE    障碍停车，可选
ERROR       异常
```

基本原则：

```text
只要进入 STOP / EMERGENCY / COM_TIMEOUT / ERROR，ESP32 必须立即向 AT8236 发送停止指令。
```

---

### 6.3 指令限幅与平滑层

购物车载物后不应突然启动、急转或高速运动。

ESP32 端应实现：

* 最大速度限制；
* 最大转向速度限制；
* 加速度限制；
* 减速度限制；
* 指令死区；
* 速度斜坡；
* 异常值过滤。

示例（基于实际协议值域）：

```text
ctrl_left   ∈ [-255, 255]  // 来自 OpenBot c<left>,<right>
ctrl_right  ∈ [-255, 255]

限制后：
ctrl_left_limited  ∈ [-MAX_SPEED, MAX_SPEED]   // MAX_SPEED 建议 ≤ 128（50% PWM）
ctrl_right_limited ∈ [-MAX_SPEED, MAX_SPEED]
```

建议首版参数保守：

```text
MAX_SPEED = 128    // 最大 50% PWM，购物车载物后不宜高速
加速度缓慢增加      // 每次只允许变化少量值
目标丢失或急停时直接 STOP（ctrl_left=0, ctrl_right=0）
```

---

### 6.4 四驱 / 麦轮运动学映射层

**首版（差速模式，OpenBot 协议直接映射）：**

```text
// 输入：OpenBot 原生 c<left>,<right>
ctrl_left   ∈ [-255, 255]
ctrl_right  ∈ [-255, 255]

// 输出：四个电机的目标速度
front_left_speed  = ctrl_left   // 左前 = 左侧值
rear_left_speed   = ctrl_left   // 左后 = 左侧值
front_right_speed = ctrl_right  // 右前 = 右侧值
rear_right_speed  = ctrl_right  // 右后 = 右侧值
```

这是与 OpenBot 原生 RTR_520 模式 GPIO 并联等效的映射。**不涉及 forward/turn/omega 转换**——那些转换已经在 Android 端完成。

**后续扩展（麦轮全向模式）：**

如果后续要启用麦轮全向运动，需要 ESP32 端实现完整麦轮运动学解算：

```text
front_left_speed  = f1(v_x, v_y, omega)
front_right_speed = f2(v_x, v_y, omega)
rear_left_speed   = f3(v_x, v_y, omega)
rear_right_speed  = f4(v_x, v_y, omega)
```

但首版不建议让自主跟随依赖 v_y。启用麦轮全向需要同时修改上位机协议和 ESP32 映射。

---

### 6.5 AT8236 通信协议层

ESP32 需要实现 AT8236 的 UART 或 I2C 通信协议。

建议优先使用 UART，原因：

* 一对一通信简单；
* 容易用 USB-TTL 调试；
* 不涉及 I2C 上拉电压问题；
* 出问题时更容易抓包和分析。

该层需要完成：

* 初始化 AT8236；
* 设置电机速度；
* 设置电机方向；
* 停止所有电机；
* 可选读取编码器；
* 可选读取当前速度；
* 可选读取错误状态。

示例接口建议：

```cpp
class AT8236Driver {
public:
    bool begin();
    bool setMotorSpeed(int motor_id, int speed);
    bool setAllMotorSpeed(int m1, int m2, int m3, int m4);
    bool stopAll();
    bool brakeAll();
    bool readEncoder(int motor_id, long &count);
    bool readSpeed(int motor_id, int &speed);
};
```

---

## 7. AT8236 板载 STM32 协处理器架构

根据产品参数信息汇总报告和商品页面确认：AT8236 驱动模块由以下核心部件组成：

```text
┌──────────────────────────────────────────────┐
│          AT8236 四路编码器电机驱动模块            │
│                                              │
│  ┌─────────┐  ┌──────┐ ┌──────┐ ┌──────┐    │
│  │  STM32  │  │AT8236│ │AT8236│ │AT8236│ ... │
│  │ 协处理器  │→│  ×1  │ │  ×1  │ │  ×1  │    │
│  │(协议处理) │  └──────┘ └──────┘ └──────┘    │
│  └────┬────┘       ↓        ↓        ↓       │
│       │       M1电机  M2电机  M3电机  M4电机   │
│       │       +AB相编码器回传                   │
│       │                                       │
│  对外接口：UART / I2C / Type-C USB Serial       │
│  仅需 4 根线即可与主控通信                       │
│  兼容：ESP32, STM32, Arduino, 树莓派, Jetson    │
└──────────────────────────────────────────────┘
```

**已确认的硬件架构：**

| 参数 | 详情 | 来源 |
|------|------|------|
| 板载协议处理器 | **STM32** | 产品对比表明确标注 |
| 电机驱动芯片 | AT8236 × 4（每路电机一个独立驱动芯片） | 产品对比表 |
| 通讯方式 | **UART（串口）或 IIC**，二选一 | 产品特性第3条 |
| 备选通讯 | Type-C USB 串口，便于与树莓派等直连 | 产品特性第8条 |
| 主控引脚占用 | **仅 4 个**（VCC/GND + 2根通信线） | 产品对比表 |
| 编码器 | 板载 PH2.0-6pin 编码器接口 × 4 | 产品对比表 |
| 保护功能 | 防反接、过流、过热、IO 隔离 | 产品特性第2/6/11条 |
| 电压检测 | 内置 ADC 可读电源电压 | 产品特性第10条 |
| 兼容主控 | ESP32 / STM32 / 树莓派 / Jetson / Arduino / MSPM0 | 产品特性第4条 |

**系统控制链路：**

```text
ESP32（项目主下位机）
  │  通过 UART 或 I2C（仅 4 线）发送目标速度/状态指令
  ↓
AT8236 板载 STM32（协议处理器）
  │  解析主控指令 → 控制 4 路 AT8236 驱动芯片
  │  采集 4 路编码器 → 计算转速 → 可选回传给 ESP32
  ↓
4 路 520 编码器电机
```

**对 ESP32 固件的影响：**

1. **GPIO 占用极低**：仅需 4 个引脚（VCC/GND/UART-TX/UART-RX 或 VCC/GND/I2C-SDA/I2C-SCL），相比原生 PWM 方案节省大量引脚
2. **必须实现 AT8236 的 UART 或 I2C 通信协议**：ESP32 向 STM32 发送"目标速度"指令，由 STM32 内部完成 PWM 生成和编码器闭环
3. **不需要在 ESP32 端处理编码器中断**：编码器采集由 STM32 完成，ESP32 只需按需查询
4. **如果板载 PID 参数可调**：可通过协议修改速度闭环参数，优化跟随响应
### 7.2 需要优先确认的协议细节

虽然硬件架构已确认（STM32 + UART/I2C），但以下协议细节仍需向卖家确认或通过测试验证：

* AT8236 UART 默认波特率、数据帧格式、校验方式
* I2C 从机地址、寄存器表或命令表（若选 I2C 模式）
* 速度指令的单位和值域范围
* STOP 与 BRAKE 指令的区别
* 编码器数据的回传格式和查询方式
* 板载 PID 参数是否可通过协议调整
* Type-C USB 串口模式如何切换（若需直连电脑调试）

因此，下位机同学需要优先拿到：

```text
1. AT8236 通信协议文档
2. ESP32 控制 AT8236 的示例代码
3. Arduino 控制 AT8236 的示例代码
4. UART 波特率、数据帧格式、校验方式
5. I2C 地址、寄存器表或命令表
6. 四路电机速度控制示例
7. 四路编码器读取示例
8. 停止 / 刹车 / 清零编码器示例
```

如果卖家无法提供协议或示例代码，该驱动板的软件集成风险会明显升高。

---

## 8. 需要向卖家确认的问题清单

采购涉及 4 个商品，以下按商品分类列出需确认的问题，便于分别向对应商家提问。

采购商品列表：

| 编号 | 商品 | 店铺/品牌 | 链接 |
|------|------|-----------|------|
| P1  | **大号铝合金四驱底盘（双层 305 系列）12V 320rpm 编码器电机** | 酷点机器人（淘宝） | 见 `design/采购.md` |
| P2  | **乐鑫 ESP32 开发板 WROOM-32E（拓展盘 + 主板已焊排针）** | HUA（淘宝） | 见 `design/采购.md` |
| P3  | **12V 锂电池组 9600mAh + 12V 充电器（2A）** | 亚博智能（天猫） | 见 `design/采购.md` |
| P4  | **四路编码器电机驱动模块 AT8236（+ 铜柱 + 数据线 + 电源线）** | 亚博智能（天猫） | 见 `design/采购.md` |

---

### 8.1 向 P4 卖家（亚博智能 AT8236 驱动板）确认

#### 通信协议与示例代码

| 序号 | 问题 | 对应商品 |
|------|------|----------|
| Q1 | UART 默认波特率是多少？（115200 / 9600 / 其他？） | P4 |
| Q2 | UART 指令帧格式是什么？（固定长度 / 变长 + 校验和 / 文本协议？） | P4 |
| Q3 | I2C 从机地址是多少？若使用 I2C 模式，上拉电压是几伏？ESP32 3.3V 是否兼容？ | P4 |
| Q4 | 模块默认通讯模式是 UART 还是 I2C？如何切换两种模式？ | P4 |
| Q5 | Type-C USB 串口模式如何使用？是否需要跳线或配置切换？能否直接通过 Type-C 连接电脑调试？ | P4 |
| Q6 | 是否有 ESP32 控制 AT8236 的示例代码？（Arduino IDE 或 PlatformIO 均可） | P4 |
| Q7 | 是否有 Arduino 控制 AT8236 的示例代码？ | P4 |
| Q8 | 能否提供完整的通信协议文档（UART/I2C 寄存器表或命令表）？ | P4 |

#### 电机控制

| 序号 | 问题 | 对应商品 |
|------|------|----------|
| Q9 | 是否支持四路电机**独立**速度控制？（即四个电机可以设置不同速度） | P4 |
| Q10 | 速度指令的值域范围是多少？单位是什么？（PWM 占空比/转速 rpm/内部比例值？） | P4 |
| Q11 | 是否支持闭环速度控制？板载 PID 参数是否可以通过协议读写调整？ | P4 |
| Q12 | 是否支持单个电机方向反转？（即通过指令反转，而非改接线） | P4 |
| Q13 | STOP 指令是滑行停止（coast）还是刹车停止（brake）？是否两种都支持？ | P4 |
| Q14 | 是否支持紧急刹车（立即制动）？与普通停止有何区别？ | P4 |

#### 编码器

| 序号 | 问题 | 对应商品 |
|------|------|----------|
| Q15 | 是否能通过协议读取四路编码器的实时计数值？ | P4 |
| Q16 | 是否能通过协议读取四路电机的实时转速（而非仅计数值）？ | P4 |
| Q17 | 编码器计数方向是否可通过协议配置？（用于匹配电机接线方向） | P4 |
| Q18 | 编码器接口的线序定义是什么？是否与 P1 底盘的 520 编码器电机线序匹配？（P1 电机线序见产品参数汇总报告 Section 2.4.3） | P4 + P1 |

#### 电气与安全

| 序号 | 问题 | 对应商品 |
|------|------|----------|
| Q19 | 电机供电电压范围是多少？是否支持 12V 锂电池直供？ | P4 + P3 |
| Q20 | 逻辑电平是 3.3V 还是 5V？与 ESP32 的 3.3V UART/I2C 直连是否安全？ | P4 + P2 |
| Q21 | 每路电机连续电流和峰值电流各是多少？四个 520 编码器电机（堵转电流各 3.5A）同时启动是否有过流风险？ | P4 + P1 |
| Q22 | 是否有过流保护、欠压保护、过热保护？保护触发后如何恢复？ | P4 |
| Q23 | AT8236 驱动板本身是否需要独立的逻辑供电？还是通过电机供电取电？ | P4 + P3 |

---

### 8.2 向 P1 卖家（酷点机器人 底盘）确认

| 序号 | 问题 | 对应商品 |
|------|------|----------|
| Q24 | 底盘的**实际最大承载能力**是多少？（标称未明确，需确认负重上限，本项目需承载购物筐 + 1-3kg 物品） | P1 |
| Q25 | 已确认：本项目采购版本为 **减速比 30** 的 520 编码器电机，对应 **空载 320rpm**、**减速后编码器线数 330**。后续仍需实测确认固件中的 `TICKS_PER_REV` 最终标定值。 | P1 |
| Q26 | 四驱底盘是否默认配置了麦克纳姆轮？还是需单独选购？已购买的双层铝合金四驱套餐包含什么轮组？ | P1 |
| Q27 | 底盘底板上的安装孔距/孔位图纸是否可以提供？便于设计购物筐固定支架的安装位置 | P1 |
| Q28 | 编码器电机接口端子型号是 PH2.0 还是 XH254？与 P4 AT8236 驱动板的 PH2.0-6pin 接口是否直接兼容？ | P1 + P4 |
| Q29 | 提供 7 种模式控制源代码中，是否包含**串口命令模式**的资料？（可用于与 ESP32 的通信调试） | P1 |

---

### 8.3 向 P2 卖家（HUA ESP32 开发板）确认

| 序号 | 问题 | 对应商品 |
|------|------|----------|
| Q30 | VIN 外接供电的精确电压范围是多少？（页面写"5-12V"和"最大 5.5V"存在矛盾，需确认） | P2 |
| Q31 | 拓展盘的 GVS 接口默认跳线输出是 5V 还是 3.3V？切换跳线位置在哪里？ | P2 |
| Q32 | 主板是否板载自动下载电路（无需手动按 Boot 键即可烧录）？ | P2 |
| Q33 | CH340 驱动是否需要手动安装？Windows/Mac/Linux 兼容性如何？ | P2 |

---

### 8.4 向 P3 卖家（亚博智能 电池）确认

| 序号 | 问题 | 对应商品 |
|------|------|----------|
| Q34 | 12V 锂电池组 9600mAh 的**最大持续放电电流**是多少？能否同时驱动 4 个 520 电机（堵转电流各 3.5A，合计最高约 14A）？ | P3 + P1 |
| Q35 | 电池是否内置保护板（过充/过放/短路保护）？放电截止电压是多少？ | P3 |
| Q36 | 电池的输出接口类型是什么？（DC 头 / XT30 / XT60 / 裸线？）是否需要额外购买转接线？ | P3 |
| Q37 | 充电器是否带充满自停功能？充满指示灯状态是什么？ | P3 |

---

### 8.5 跨商品综合确认

| 序号 | 问题 | 涉及商品 |
|------|------|----------|
| Q38 | AT8236 驱动板 → 520 编码器电机的接线：两端接口分别是 PH2.0-6pin（P4 板载）和 PH2.0/XH254-6pin（P1 电机），线序是否需要转换？卖家是否提供配套转接线？ | P4 + P1 |
| Q39 | 12V 电池 → AT8236 驱动板供电 → ESP32 供电：推荐的供电拓扑是什么？ESP32 是通过 AT8236 板载的 5V/3.3V 输出取电，还是通过独立的 DC-DC 降压模块从电池取电？ | P3 + P4 + P2 |
| Q40 | 若 AT8236 驱动板支持**同时**通过 UART 通信控制 4 路电机 + 读取 4 路编码器，其通信带宽（波特率）是否足够支持 10-30Hz 的控制刷新率？ | P4 |

---

## 9. 电气连接注意事项

### 9.1 必须共地

ESP32 与 AT8236 通信时，必须确保：

```text
ESP32 GND
AT8236 GND
电池负极
```

三者参考地一致。

否则 UART / I2C 通信可能不稳定，甚至误动作。

---

### 9.2 注意逻辑电平

ESP32 是 3.3V 逻辑。

需要确认 AT8236 通信接口是否兼容 3.3V。

如果 AT8236 UART TX 输出 5V，ESP32 RX 可能存在风险，需要电平转换或分压。

如果使用 I2C，需要确认上拉电阻连接到 3.3V 还是 5V。若上拉到 5V，不建议直接连接 ESP32。

---

### 9.3 电机供电与逻辑供电分开考虑

四个 520 编码器电机启动电流较大，不建议简单从 ESP32 供电链路取电。

建议结构：

```text
12V 电池
  ├─ AT8236 电机供电
  └─ DC-DC 降压
       └─ ESP32 / 其他逻辑模块
```

需要注意：

* 电机供电线要足够粗；
* 电池放电能力要足够；
* 建议加入保险丝或总开关；
* 急停最好能切断电机驱动使能或电机供电；
* 逻辑电源和电机电源布线尽量减少干扰。

---

## 10. 下位机需要实现的核心功能

### 10.1 最小可运行功能

下位机同学至少需要完成：

```text
1. ESP32 能接收 OpenBot 上位机运动指令
2. ESP32 能通过 UART / I2C 控制 AT8236
3. 能让四个电机前进、后退、停止
4. 能实现左转、右转
5. 能实现立即 STOP
6. 能实现通信超时停车
7. 能限制最大速度
8. 能记录基本调试日志
```

---

### 10.2 推荐增强功能

在最小功能完成后，建议继续实现：

```text
1. 编码器速度读取
2. 四轮速度闭环状态反馈
3. 电机方向配置表
4. 麦轮横移手动测试
5. 电池电压监测
6. 急停按钮硬件接入
7. 障碍传感器触发停车
8. 运行状态 LED 或蜂鸣器提示
```

---

## 11. 建议的 ESP32 固件结构

建议下位机代码分为以下模块：

```text
firmware/
├─ main.cpp
├─ openbot_protocol.h / .cpp
│  └─ 解析手机端 OpenBot 指令
├─ at8236_driver.h / .cpp
│  └─ 封装 AT8236 UART / I2C 协议
├─ kinematics.h / .cpp
│  └─ ctrl_left/ctrl_right 到四轮速度映射（首版差速模式）
├─ safety_manager.h / .cpp
│  └─ 急停、超时、限幅、状态机
├─ config.h
│  └─ 轮子方向、接口编号、速度上限、PID 参数等配置
└─ debug_log.h / .cpp
   └─ 串口调试输出
```

这样可以避免所有逻辑堆在一个文件里，后续也方便调试和替换驱动板。

---

## 12. 轮子编号与方向配置

由于麦轮和四个电机方向容易混乱，必须建立轮子编号表。

建议统一记录：

| 车轮位置   | AT8236 电机接口 | 正转时车辆运动效果 | 是否需要反向 |
| ------ | ----------- | --------- | ------ |
| 左前轮 FL | M?          | 待测试       | 待测试    |
| 右前轮 FR | M?          | 待测试       | 待测试    |
| 左后轮 RL | M?          | 待测试       | 待测试    |
| 右后轮 RR | M?          | 待测试       | 待测试    |

建议在 `config.h` 中写成：

```cpp
#define MOTOR_FL 1
#define MOTOR_FR 2
#define MOTOR_RL 3
#define MOTOR_RR 4

#define DIR_FL 1
#define DIR_FR -1
#define DIR_RL 1
#define DIR_RR -1
```

具体正负号必须实测，不要凭直觉写死。

---

## 13. 推荐调试步骤

不要一开始就直接让整车带购物筐跑。建议按以下顺序调试。

---

### 阶段 1：资料确认

目标：

```text
确认 AT8236 协议、接线、电压、电流、示例代码。
```

完成标准：

```text
能看懂如何让某一路电机转动、停止、读取编码器。
```

---

### 阶段 2：单板通信测试

目标：

```text
ESP32 通过 UART / I2C 成功控制 AT8236。
```

测试内容：

```text
1. AT8236 初始化
2. M1 单独转动
3. M1 停止
4. M1 改变方向
5. 读取 M1 编码器
```

---

### 阶段 3：四电机悬空测试

将底盘架空，四轮离地。

测试内容：

```text
1. 四个轮子分别单独转动
2. 四个轮子分别停止
3. 记录 M1/M2/M3/M4 对应实际轮子
4. 确认每个轮子的正方向
5. 测试 stopAll()
6. 测试 brakeAll()
```

---

### 阶段 4：差速模式测试

仍然架空测试：

```text
forward > 0, turn = 0
```

期望：

```text
四个轮子都产生前进方向运动
```

测试：

```text
forward = 正值
forward = 负值
turn = 正值
turn = 负值
forward + turn
forward - turn
```

---

### 阶段 5：低速落地测试

不装购物筐，低速落地测试：

```text
1. 低速前进
2. 低速后退
3. 原地左转
4. 原地右转
5. 低速弧线运动
6. 急停
7. 通信断开停车
```

---

### 阶段 6：麦轮横移测试，可选

仅在差速模式稳定后测试。

测试：

```text
v_y > 0
v_y < 0
v_x + v_y
v_y + omega
```

注意：

```text
横移不建议作为自主跟随首版功能，只建议作为手动演示或后续扩展。
```

---

### 阶段 7：带购物筐低速测试

装上购物筐，但先不放重物。

测试：

```text
1. 低速前进
2. 转向
3. 停止
4. 急停
5. 通信超时停车
```

---

### 阶段 8：带 1~3 kg 负载测试

逐步增加负载，不要一次加满。

记录：

```text
1. 起步是否打滑
2. 转向是否明显偏移
3. 急停时购物筐是否滑动
4. 电机是否明显发热
5. 驱动板是否过热
6. 电池电压是否明显下降
```

---

## 14. 与上位机同学的接口边界

由于上位机同学主要负责 Android / OpenBot App，不应让上位机承担 AT8236 细节。

**首版接口策略：完全兼容 OpenBot 原生协议，不自定义新协议。**

上位机只发送 OpenBot 原生指令（无需修改）：

```text
c<left>,<right>      // 电机控制，left/right ∈ [-255, 255]
h<interval_ms>       // 心跳超时
f                    // 功能查询
```

下位机负责：

```text
1. 解析 OpenBot 原生协议（c/h/f 指令）
2. ctrl_left/ctrl_right → 四轮速度映射（首版差速模式）
3. AT8236 通信协议
4. 电机方向修正
5. 编码器处理
6. 通信超时停车（基于 h 心跳或独立看门狗）
7. 急停
8. 限速和平滑
```

也就是说，上位机不需要知道：

```text
1. AT8236 怎么通信
2. 四个电机怎么编号
3. 麦轮具体公式
4. 哪个轮子需要反向
5. 编码器如何读取
```

这部分应封装在 ESP32 下位机内部。

---

## 15. 推荐上下位机接口格式

### 15.1 首版策略：直接使用 OpenBot 原生协议

**首版强烈建议直接使用 OpenBot 原生协议，不设计新协议。**

理由：
- OpenBot 原生协议已明确定义（见 Section 1.1），两端均有成熟实现
- Android 端 `Vehicle.java:sendControl()` 已发送 `c<left>,<right>\n` 格式
- 下位机 `openbot.ino:1355-1367` 已实现 `c` 指令解析
- 使用原生协议意味着**上位机代码零修改**，只需 ESP32 固件兼容

原生协议格式：

```text
上位机 → ESP32：
  c128,100              // 控制指令（以 \n 结尾）
  h300                  // 心跳超时 300ms
  f                     // 功能查询

ESP32 → 上位机（可选回传）：
  v12.10                // 电池电压
  w120,115              // 左右轮速 rpm
  s150                  // 超声波距离 cm
  r                     // 上电就绪
```

### 15.2 如果未来需要扩展协议（非首版任务）

以下是一个自定义扩展协议的**设计思路参考**，不推荐在首版使用。仅当后续需要传递 OpenBot 原生协议不支持的语义（如横移速度 v_y、明确的状态模式切换）时才考虑。

**注意：使用此格式需要修改 Android 端 `Vehicle.java` 和 `Control.java`，是较大的变更。**

示例：

```text
CMD,FOLLOW,0.30,0.10    // 模式=跟随, forward因子, turn因子
CMD,MANUAL,0.20,-0.20
CMD,STOP,0,0
CMD,EMERGENCY,0,0
```

下位机回传状态示例：

```text
STAT,FOLLOW,OK,12.1V,NO_ERROR
STAT,STOP,COM_TIMEOUT,12.0V,NO_CMD
STAT,EMERGENCY,ESTOP,12.1V,LOCKED
```

**此自定义协议的风险：**
- 需要额外开发 Android 端协议层
- 破坏了与 OpenBot 生态的兼容性
- 增加了联调复杂度和出错概率
- 在 4 周课程周期内不推荐引入

### 15.3 首版回传建议

如果时间紧，状态回传可以先简化，但至少建议支持：

```text
OK
STOP
ERROR
COM_TIMEOUT
EMERGENCY
```

回传格式可沿用 OpenBot 原生风格（单字符头 + 值），例如：

```text
xOK          // 状态正常
xSTOP        // 已停车
xTIMEOUT     // 通信超时
xESTOP       // 急停激活
```

---

## 16. 急停与安全策略要求

自主跟随购物车必须优先保证安全。

建议安全优先级如下：

```text
急停按钮 > 通信超时 > 目标丢失停车 > 障碍停车 > 普通跟随指令
```

ESP32 侧必须实现：

```text
1. 如果急停触发，立即 stopAll 或 brakeAll
2. 如果超过指定时间未收到上位机指令，立即停车
3. 如果收到 STOP 指令，立即停车
4. 如果指令异常或超出范围，拒绝执行并停车
5. 如果 AT8236 通信失败，进入 ERROR 并停车
```

建议加入通信看门狗：

```cpp
if (millis() - last_command_time > COMMAND_TIMEOUT_MS) {
    stopAllMotors();
    state = COM_TIMEOUT;
}
```

建议初始参数：

```text
COMMAND_TIMEOUT_MS = 300 ~ 500 ms
```

具体值根据上位机指令刷新率调整。

---

## 17. 当前方案的主要风险评估

| 风险点           | 风险等级 | 说明                     | 建议             |
| ------------- | ---- | ---------------------- | -------------- |
| AT8236 协议细节未确认 | 高    | 已确认 STM32 + UART/I2C 架构，但具体帧格式、波特率、寄存器表尚需确认 | 向卖家索要协议文档与示例代码 |
| OpenBot 固件不能直接复用 | 高    | 原生 PWM 逻辑（`update_left/right_motors()`）需替换为 AT8236 UART/I2C 通信层 | ESP32 编写适配层    |
| 麦轮运动学复杂        | 中    | 完整全向控制比差速复杂            | 首版禁用横移         |
| 电机方向混乱         | 中    | 四轮方向容易接反               | 建立轮子编号表        |
| I2C 电平风险       | 中    | ESP32 是 3.3V，I2C 上拉可能到 5V | 首版优先 UART      |
| 急停不可靠          | 高    | 移动购物车必须安全              | ESP32 独立急停 GPIO    |
| 电机电流不足         | 中    | 四个 520 电机堵转电流各 3.5A    | 已确认 AT8236 有过流保护 |
| 编码器数据可用性       | 低    | STM32 已采集编码器，ESP32 按需读取 | 优先确认编码器查询协议 |
| 板载 PID 不可调      | 中    | 若 STM32 固件 PID 固定，速度响应可能不理想 | 确认协议是否支持 PID 参数读写 |

---

## 18. 当前推荐技术路线

综合项目周期、OpenBot 架构和硬件现实，建议采用：

```text
OpenBot 原生上位机逻辑零修改（保持 c<left>,<right> + h<interval> 协议）
ESP32 作为协议解析 + 安全控制 + AT8236 通信核心
AT8236 作为四路电机执行板
麦轮首版按差速四驱使用（ctrl_left→左侧两轮, ctrl_right→右侧两轮）
横移能力作为后续扩展
```

具体路线：

```text
1. 上位机（Android）发送 c<left>,<right>（值域 [-255, 255]）+ h<interval_ms> 心跳
2. ESP32 解析原生文本协议（单字符头 + 参数 + \n）
3. ESP32 执行限速、平滑、安全状态机
4. ESP32 将 ctrl_left/ctrl_right 复制为四轮目标速度（左前=左后=ctrl_left, 右前=右后=ctrl_right）
5. ESP32 通过 UART（或 PWM）发送给 AT8236
6. AT8236 控制四个编码器电机
7. ESP32 基于 h 心跳监控通信超时，急停独立触发
8. 任意异常立即停车（ctrl_left=0, ctrl_right=0）
```

---

## 19. 交付物要求

下位机同学最终建议交付以下内容：

```text
1. ESP32 固件源码
2. AT8236 驱动封装代码
3. OpenBot 指令解析代码
4. 四轮速度映射代码
5. 急停与通信超时停车代码
6. 电机编号与方向配置表
7. 接线图
8. 调试记录
9. 风险与问题记录
10. 可复现实验步骤
```

建议至少形成以下测试记录：

```text
1. 单电机控制测试
2. 四电机方向测试
3. 差速运动测试
4. 急停测试
5. 通信超时停车测试
6. 带购物筐低速测试
7. 带负载低速测试
```

---

## 20. 最终结论

本项目的硬件方案与 OpenBot 原生 L298N 双路 PWM 驱动方案存在明显差异，但并非不可兼容。

核心差异是：

```text
OpenBot 原生（ESP32 RTR_520 模式）：
上位机 → ESP32 → 4路PWM直连 → 4个电机（左前=左后, 右前=右后，硬件并联）
              → 4路编码器直连 → ESP32 直接中断计数
              → h 心跳超时自动停车

本项目（基于 OpenBot 原生协议，上位机零修改）：
上位机 → ESP32 → 解析 c<left>,<right> + h<interval>（协议完全复用）
              → ctrl_left/ctrl_right → 四轮差速映射（ESP32 软件层）
              → UART/I2C（仅4线）→ AT8236 STM32 协处理器
              → AT8236 ×4 驱动芯片 → 四个电机 → 麦轮底盘
              → 编码器采集由 STM32 完成，ESP32 按需查询
```

**架构优势：**
- ESP32 仅需 4 个引脚（vs 原生 8 PWM + 4 编码器 = 12 GPIO）
- 编码器闭环控制和 PWM 生成由 STM32 完成，ESP32 负担减轻
- 上位机 Android App 零修改

因此，下位机工作的关键不是"设计新协议"，而是**理解并复用 OpenBot 原生协议**，在此基础上实现 AT8236 驱动适配。

```text
OpenBot 原生协议解析（c/h/f 指令，零修改）
+
ESP32 安全控制（心跳超时、急停、限幅）
+
AT8236 通信适配（UART/I2C 或 PWM，取决于实物）
+
四驱麦轮速度映射（首版差速模式：ctrl_left→左侧两轮, ctrl_right→右侧两轮）
```

首版建议不要追求完整麦轮全向自主跟随，而是先采用 OpenBot 兼容差速模式，把麦轮底盘作为普通四驱差速平台使用，优先实现：

```text
能前进（ctrl_left>0, ctrl_right>0）
能转向（ctrl_left≠ctrl_right）
能停止（c0,0）
能急停（ESP32 独立硬件急停）
通信断开能停车（h 心跳超时或独立看门狗）
目标丢失后不会继续前进（上位机发 c0,0，ESP32 执行）
```

在此基础上，再考虑横移、全向控制和更复杂的麦轮跟随策略。
