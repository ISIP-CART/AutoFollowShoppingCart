# ESP32 + AT8236 OpenBot BLE 安全遥控固件

这个目录提供一份独立的 Arduino 固件，用于 `ESP32 WROOM-32E + AT8236 + OpenBot BLE` 的低速安全手动遥控。它不启动 WiFi，不包含网页遥控，不接自动跟随输出，也不替换现有台架测试固件。

## 适用范围

- 上位机只走 OpenBot BLE 手动控制
- 下位机只做左右差速控制和安全停车
- 首版速度上限固定为四轮 `[-40,40]`
- `c0,0` 为普通立即停车
- `!S,<seq>` 为锁存急停，BLE 和 USB 均可触发，只能重启解除

## Arduino IDE 设置

- 开发板：`ESP32 Dev Module`
- 串口监视器波特率：`115200`
- Arduino ESP32 core：使用自带 `BLEDevice / BLEServer / BLE2902`
- 不需要额外第三方 BLE 库

当前仓库环境没有 `arduino-cli`，因此请在 Arduino IDE 中完成最终编译与烧录验证。

## 接线

- `ESP32 GPIO17 / TX1 -> AT8236 RX2`
- `ESP32 GPIO16 / RX1 <- AT8236 TX2`
- `ESP32 GND -> AT8236 GND`

AT8236 初始化参数：

- `$mtype:1#`
- `$mphase:30#`
- `$mline:11#`
- `$wdiameter:80.000#`
- `$deadzone:1600#`
- `$upload:1,1,1#`

## BLE 参数

- 设备名：`OpenBot: CART_AT8236`
- Service：`61653dc3-4021-4d1e-ba83-8b4eec61d613`
- RX：`06386c14-86ea-4d71-811c-48f97c58f8c9`
- TX：`9bf1103b-834c-47cf-b149-c9e4bcf778a7`
- RX 属性：`Write + Write Without Response`
- TX 属性：`Notify + BLE2902`

Android 启用 Notify 后应发送 `f\n`。固件每次都返回功能信息，并在 AT8236
遥测就绪时同时发送 `r\n`；若尚未就绪，则在就绪后补发。这样 Android 重试
`f\n` 时可以恢复丢失的就绪通知。

## 正式协议

所有命令都是逐行 ASCII/UTF-8 文本，使用 `\n` 结尾，忽略 `\r`，单行上限 `60` 字节。支持 BLE 拆包、粘包和同包多行命令。

- `c<left>,<right>\n`
  - 输入范围 `[-255,255]`
  - 实际四轮输出钳制到 `[-40,40]`
  - 首个非零命令获得控制权
  - `c0,0` 立即发零速，不走斜坡
- `h<timeout_ms>\n`
  - 允许范围 `100..3000`
  - 默认 `500`
  - `h` 只证明通信链路仍存活；非零 `c` 还必须每 500 ms 内刷新一次
- `f\n`
  - 返回 `fCART_AT8236:\n`
  - 不触发任何电机动作
- `!S,<seq>\n`
  - BLE 和 USB 均可用
  - `seq` 必须为递增正整数
  - 触发锁存 `EMERGENCY_STOP`
- `!Q\n`
  - 仅 USB 可用
  - 输出当前状态诊断，以及最近合法运动命令的计数、来源、左右值、年龄、target/current
- `!D,0\n` / `!D,1\n`
  - 仅 USB 可用，默认关闭
  - 关闭 / 开启 USB 联调诊断日志
  - BLE 来源会被拒绝；该接口不会通过 BLE Notify 输出高频日志

格式错误、越界或缓冲区溢出不会执行截断内容；如果错误来自当前活动控制源，并且车辆正在运动，固件会立即停车。

## USB 联调诊断

在车轮悬空或无电机测试时，先通过 USB 串口监视器发送 `!D,1`。固件会仅在
USB 输出以 `!D,ms=...` 开头的诊断事件；正常 BLE TX Notify 不会增加高频调试帧。

- `motion_rx`：收到的合法 `c` 命令，包含递增 `seq`、来源和原始左右值。
- `motion_target`：该命令映射后的四轮 target。
- `drive_output`：最多每 `100 ms` 输出一次，包含 current 与实际发给 AT8236 的
  `$spd` 四轮值。
- `immediate_stop`、`state`、`ble_disconnect`、`communication_timeout`、
  `motion_timeout`、`driver_timeout`、`error`：安全停车与异常证据。

示例（字段顺序可能随版本扩展）：

```text
!D,ms=15234,event=motion_rx,seq=17,source=BLE,left=-5,right=5
!D,ms=15234,event=motion_target,seq=17,target=-5,-5,5,5
!D,ms=15274,event=drive_output,seq=17,current=-5,-5,5,5,spd=-5,-5,5,5
```

用 Android 侧的按钮事件、待写入 `c` 命令、BLE 写成功/失败回调时间，与这里的
`ms`、`seq` 和左右值进行关联：Android 已确认写出但 USB 没有 `motion_rx` 时，优先
检查 BLE 链路；ESP32 已记录 `motion_target` 但 `$spd` 或车轮不符合预期时，再检查
AT8236 状态、方向配置和接线。完成测试后发送 `!D,0`，避免 USB 日志影响实时控制。

## 安全换向保护

固件会记住最近一次非零四轮目标。新的非零目标只要要求任一轮改变正负号，就会立即向 AT8236 下发四轮零速并进入 `REVERSAL_BLOCKED`；反向目标不会缓存，也不会在后台自动重放。

解除步骤：先松开方向键，使上位机发送 `c0,0`；随后持续零命令等待 `1000 ms`；任何新的非零 `c` 都会保持四轮零速并重新开始等待。等待完成后必须重新按下所需方向，才会从零速软启动。同方向的连续更新不会触发此保护。

`!Q`（USB）会输出 `reversal_blocked`、`reversal_neutral_age_ms` 与 `last_nonzero_target`；开启 `!D,1` 后，USB 日志还会记录 `reversal_block`、`reversal_neutral`、`reversal_reject` 和 `reversal_rearmed`。BLE 断连、运动保鲜超时、AT8236 遥测中断和锁存急停仍优先按原有规则停车。

本版本尚未把 `$MSPD` 字段假定为四轮实际速度。收到单轮标定日志、确认字段顺序、符号、单位与刷新周期前，不会启用自动过零换向。

## 控制权规则

- 控制源只有 `OWNER_NONE / OWNER_BLE / OWNER_USB`
- 首个非零 `c` 命令获得控制权
- 其他来源的非零 `c` 被拒绝
- 任意来源的 `c0,0` 都可立即停车并释放控制权
- 任意来源的 `!S` 都应停车；本固件允许 BLE 和 USB 触发锁存急停
- BLE 断连、通信超时或运动命令超过 500 ms 未刷新后，先停车清零，再释放控制权
- 超时释放后，必须收到新的非零命令才能重新运动

## 状态机

- `BOOT_STOP`
  - 上电后的默认状态
  - 未收到有效 AT8236 状态帧前，不允许进入可运动状态
- `READY_STOP`
  - 驱动已就绪，输出保持零
- `MANUAL_ACTIVE`
  - 当前由 BLE 或 USB 持有控制权并输出低速运动
- `REVERSAL_BLOCKED`
  - 任一轮被要求直接反转时进入，保持四轮零输出
  - 仅在收到 `c0,0` 后连续等待 `1000 ms` 才回到可接受新方向的停止状态
- `COM_TIMEOUT`
  - 控制命令超时或 BLE 断连后进入，输出保持零
- `EMERGENCY_STOP`
  - BLE 或 USB 锁存急停，需重启解除
- `DRIVER_ERROR`
  - AT8236 状态帧异常锁存，需重启解除

## AT8236 遥测与故障判定

固件启用 `$upload:1,1,1#`，校验以下状态帧的头部、结尾、字段数量和数字格式：

- `$MSPD`
- `$MTEP`
- `$MAll`

判定规则：

- 上电后 `1500 ms` 内未收到有效状态帧，保持 `BOOT_STOP`
- 运动期间若 `1000 ms` 内未收到有效状态帧，进入锁存 `DRIVER_ERROR`

## 轮位与方向

- `M3 = 左前`
- `M4 = 右前`
- `M1 = 左后`
- `M2 = 右后`

前进方向符号：

- `M1 = +1`
- `M2 = -1`
- `M3 = -1`
- `M4 = +1`

## 烧录步骤

1. 用 Arduino IDE 打开 `firmware/esp32_at8236_openbot_ble/` 草图目录。
2. 选择 `ESP32 Dev Module` 和正确串口。
3. 编译并烧录。
4. 打开串口监视器，确认看到启动信息。
5. 等待 BLE 广播 `OpenBot: CART_AT8236`。
6. 连接后用 `f\n`、`h500\n`、`c0,0\n` 做无电机安全确认。

## 建议测试顺序

1. 无电机测试：确认广播名、UUID、`f` 回包、分包与多行解析、`!D` 的 USB 权限和
   `!Q` 扩展字段，异常输入保持停车。
2. 车轮悬空测试：先由 USB 发送 `!D,1`，再由 Android BLE 依次验证
   `c14,14`、`c0,0`、`c-5,5`、`c5,-5`、`c-12,-12`；每条 BLE 命令都应有对应的
   `motion_rx`、target/current 与 `$spd` 演变记录。
3. 安全测试：BLE 断开、停止发命令、ESP32 重启、AT8236 状态帧中断时都应及时停车。
4. 控制权测试：BLE 与 USB 互不抢占非零控制，但任一来源都能发送 `c0,0` 停车。
5. 落地测试：空载开阔场地、旁边有人可随时物理断电。

## 已知边界

- 本固件不开放麦轮横移、自动跟随、里程计、传感器上传或 WiFi 遥控
- 没有接入物理急停引脚，真实测试必须保留人工断电手段
- `EMERGENCY_STOP` 和 `DRIVER_ERROR` 设计为锁存，BLE 重连不会自动解除
- BLE 急停属于软件安全层，不能替代后续物理急停按钮或人工断电
- USB 诊断默认关闭；开启后只用于悬空或受控联调，完成后应关闭
