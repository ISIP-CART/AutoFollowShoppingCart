# ESP32 传感器仅日志模式修改说明

## 1. 修改目的

当前 `esp32_at8236_velocity_ble.ino` 会使用左前 ToF、中央超声波和右前 ToF 拒绝运动命令，并在运动过程中触发制动。现阶段要求三路传感器仅用于采样、回传和诊断，不参与任何运动许可或停车决策。

Android 新版将不再根据 `s<cm>` 最小值拦截手动、自动跟随或定向搜索命令。ESP32 同步修改并重新烧录前，固件仍可能返回 `!ERR,sensor_*`，小车仍可能只能后退或只能向单侧转向。

## 2. 必须修改的固件位置

目标文件：`firmware/esp32_at8236_velocity_ble/esp32_at8236_velocity_ble.ino`。

增加统一配置开关，默认关闭传感器运动门控：

```cpp
static const bool RANGE_MOTION_GATING_ENABLED = false;
```

不要只把现有的 `REQUIRE_RANGE_SENSORS_FOR_MOTION` 改成 `false`。该变量只控制“传感器不可用”检查；`centerRiskLatched`、`leftRiskLatched`、`rightRiskLatched` 目前仍会拒绝运动。

在 `motionRangeBlockReason()` 开头统一旁路所有传感器运动判断：

```cpp
const char *motionRangeBlockReason(int left, int right) {
  if (!RANGE_MOTION_GATING_ENABLED) return NULL;

  bool forward = left + right > 0;
  bool turningLeft = right > left;
  bool turningRight = left > right;
  // 保留现有判断，供将来重新启用门控。
  ...
}
```

在运动中持续检查入口也增加显式保护，避免传感器状态调用 `beginBrake()`：

```cpp
void serviceRangeMotionSafety() {
  if (!RANGE_MOTION_GATING_ENABLED) return;
  if (systemState != MANUAL_ACTIVE) return;
  const char *reason = motionRangeBlockReason(logicalLeft, logicalRight);
  if (reason != NULL) beginBrake(reason);
}
```

`handleMotionCommand()` 可以继续调用 `motionRangeBlockReason()`。开关关闭时不得再产生 `sensor_center_unavailable`、`sensor_center_near`、`sensor_left_unavailable`、`sensor_left_near`、`sensor_right_unavailable` 或 `sensor_right_near`。

## 3. 必须保留的传感器功能

- 三路传感器初始化、采样、有效性判断和中值滤波；
- 三个风险锁存的计算，作为诊断信息；
- `serviceLegacyRangeTelemetry()` 及 `s<cm>` 最小有效距离回传；
- `fCART_AT8236:s:` 能力声明和 `s100` 周期配置；
- USB `!D,1` 输出的三路 `RANGE` 诊断；
- 原始距离、状态、年龄、设备状态和风险位输出。

传感器数据继续进入日志，但不得改变目标轮速、系统状态或制动状态。

## 4. 仍须保留的安全逻辑

本次仅关闭传感器运动门控。必须保留 `c0,0` 普通停车、`!S,<seq>` 急停及锁存、BLE 断连停车、心跳超时、运动命令刷新超时、AT8236 未就绪、驱动与速度反馈故障、超速保护、正反转切换制动、协议格式和控制源所有权检查。

关闭传感器门控后没有前向、侧向或后向防撞保证，只能在空旷场地、车轮先悬空且人员可物理断电的条件下测试。

## 5. 固件契约测试调整

更新 `firmware/esp32_at8236_velocity_ble/tests/test_firmware_contract.py`：

- 断言 `RANGE_MOTION_GATING_ENABLED = false`；
- 断言两个运动入口在开关关闭时不会因传感器拒绝或制动；
- 继续断言传感器采样、最小值回传和 USB 诊断位于主循环；
- 继续验证 `:s:`、`s<cm>`、`!D,1` 和三路诊断字段；
- 继续验证普通停车、急停、心跳超时、运动超时和驱动故障处理。

## 6. 烧录后验收

先将四轮悬空并保持可物理断电：

1. 打开 USB 诊断 `!D,1`，确认三路 `RANGE` 数据持续输出。
2. 分别遮挡或断开左、中央、右传感器，确认日志状态变化，但 `c14,14`、`c-5,5`、`c5,-5`、`c-12,-12` 均不返回 `!ERR,sensor_*`。
3. 运动中改变传感器距离，确认不会进入由 `sensor_*_near` 引起的制动。
4. 发送 `c0,0`，确认仍可靠停车。
5. 触发心跳超时、运动刷新超时和 `!S,<seq>`，确认仍可靠停车或锁存。
6. 通过 BLE 确认仍回复 `fCART_AT8236:s:` 并按 `s100` 周期发送 `s<cm>`。

验收后请同步固件 commit、烧录版本标识和测试结果，便于 Android 日志区分旧固件与“传感器仅日志”固件。
