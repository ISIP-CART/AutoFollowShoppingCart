# 自主跟随购物车 SysML 建模说明

> 更新时间窗：20260709-133555  
> 本次图集范围：仅生成需求图和安全状态机图。  
> 建模边界：首版课程可交付原型，保持 `OpenBot + Android 手机 + MCU/ESP32 + 差速底盘` 主线；不把 SLAM、服务器、树莓派主脑、复杂路径规划、自动结账或真实超市长期部署建模为首版必需能力。

## 1. 建模目标

本文件是 `design/sysml/` 下的 canonical SysML 风格建模文档。本次更新只面向两个核心问题：

1. 首版系统必须满足哪些需求，哪些能力只是后续扩展。
2. 目标丢失、身份不确定、距离不可信、障碍、急停和通信异常时，系统如何从可恢复的 `motion_stop / LOCAL_SEARCH / REACQUIRE` 过渡到 hard `STOP`。

本次生成文件位于：

- `design/sysml/runs/20260709-133555/puml/01_requirements.puml`
- `design/sysml/runs/20260709-133555/puml/02_safety_state_machine.puml`
- `design/sysml/runs/20260709-133555/diagram-links.md`

## 2. 事实来源

建模依据来自当前仓库文档和实现记录：

- `AGENTS.md`：首版验收口径、架构硬约束、目标丢失策略、文档优先级和隐私边界。
- `README.md`：项目范围、OpenBot 子仓库定位、当前上位机进度。
- `design/structure.md`：需求、场景、功能/非功能指标、测试计划和风险边界。
- `design/doc/项目汇报超市自主跟随购物车.md`：课程汇报定位、OpenBot 架构、成本约束和核心功能。
- `design/自主跟随购物车上位机软件开发计划.md`：Android 上位机行为决策层、ReID 角色、距离控制、局部可通行空间、`motion_stop` 与 hard `STOP` 的边界。
- `design/上位机软件开发 Phase 2——修正跟随距离控制计划书.md`：初始化距离标定、图像伺服和 Distance State 口径。
- `design/障碍处理计划书.md`：左 / 中 / 右可通行空间、低速局部避障和阻塞等待边界。
- `design/OpenBot与四驱麦轮AT8236下位机适配风险说明.md`：OpenBot `c(left,right)`、ESP32/AT8236、心跳、急停和差速首版边界。
- `dev/OpenBot/android/cartfollow-devlog.md`：Human Cart Simulator、FollowStateMachine、ActionArbitrator、TargetTrackManager、IdentityBeliefAccumulator、诊断日志开关和当前验证状态。
- `tools/reid_pc_test/README.md`：PC ReID 工作区是研究与诊断资产，不是首版实时运行依赖。
- `firmware/esp32_at8236_m1_test/esp32_at8236_m1_test.ino`：ESP32/AT8236 bring-up、host tank control、emergency stop、command timeout、soft-start 与底盘测试接口。

## 3. 首版需求摘要

### 3.1 必须满足的核心需求

| ID | 需求 | 建模含义 |
| --- | --- | --- |
| REQ-01 | OpenBot 基础链路跑通 | Android/OpenBot App 与下位机/底盘通信、控制、调试链路成立 |
| REQ-02 | 手机端可手动遥控底盘 | 自动跟随前先验证方向、制动、通信和急停 |
| REQ-03 | 单目标检测、确认与锁定 | 未确认目标不得启动车辆 |
| REQ-04 | 低速自主跟随 | 室内平坦环境中保持安全距离 |
| REQ-05 | 集成购物筐或载物平台 | 首版按课程原型和 1-3 kg 轻载演示口径处理 |
| REQ-06 | 目标丢失后先取消前进，再短时原地搜索 | `motion_stop` 不是 hard `STOP`，仍允许有限重捕获 |
| REQ-07 | 搜索超时、急停、障碍或通信异常进入 hard STOP | 安全异常和恢复失败必须兜底停车 |
| REQ-08 | ReID 只作为身份置信度辅助 | 不允许单帧 ReID 高分直接授权前进 |
| REQ-09 | 距离状态控制 | 初始化距离标定 + 图像伺服输出 `TOO_FAR / OK / TOO_CLOSE / UNKNOWN` |
| REQ-10 | 局部安全与障碍处理 | 左 / 中 / 右可通行判断，风险不明则低速谨慎或等待 |
| REQ-11 | Human Cart Simulator 支撑无底盘验证 | 当前真实底盘前进控制尚未接通，需先在 simulator 复测策略 |
| REQ-12 | 诊断日志默认关闭 | 未打开“记录日志”时不创建 session、CSV、crop、gallery 或 event |
| REQ-13 | 隐私与研究资产边界 | 私人图片、实验输出和模型权重默认不提交 |

### 3.2 非首版目标

完整 SLAM、复杂路径规划、高精地图、自动结账、云端调度、服务器实时闭环、树莓派主脑、真实超市长期部署、商业级多目标 ReID 和麦轮全向自主跟随，均不进入首版必需需求。

## 4. 安全状态机口径

安全状态机区分“仍可恢复的停止”和“兜底终态停车”：

- `motion_stop`：线速度清零，禁止继续前进；系统仍可观察、原地低速搜索或等待重捕获。
- `LOCAL_SEARCH`：目标丢失后的短时低速原地扫描，不允许继续前向位移。
- `REACQUIRE`：疑似目标重新出现后，融合 track、bbox gate、ReID belief、距离和风险，多帧稳定后恢复。
- `BLOCKED_WAIT`：障碍或局部可通行空间不足时停止等待，不主动抢行。
- hard `STOP`：搜索失败、急停、通信异常、障碍风险过高、程序异常或人工取消后的安全停车状态。

当前 Android 侧已经实现 Human Cart Simulator、阶段 A 行为层、阶段 B TFLite ReID 首版接入，以及阶段 C `TargetTrackManager + IdentityBeliefAccumulator` 的 track/bbox gate 修正。最新状态包括 locked ghost memory、suspected track 滞回、loose/default/strict gate、恢复后 relock、非 locked 空间支持门控和诊断日志开关。下一步仍应先安装新版 APK，用诊断日志验证目标返回、遮挡恢复和干扰者抑制，再讨论极低速真实底盘联调。

## 5. 生成产物

本次 run 目录：`design/sysml/runs/20260709-133555/`

| 文件 | 说明 |
| --- | --- |
| `puml/01_requirements.puml` | SysML 风格需求图，中文标签为主 |
| `puml/02_safety_state_machine.puml` | 安全状态机图，中文状态名为主 |
| `diagram-links.md` | PlantUML editor/render 链接 |
| `generation-report.md` | 生成范围、来源和校验结果 |
| `source-manifest.json` | 本次读取的主要来源清单 |

## 6. 开放问题

1. AT8236 的最终 UART/I2C 协议、轮序、正负方向和速度闭环仍需实物测试确认。
2. 急停按钮的 NC 硬切断、GPIO 上报和接线方案仍需采购与联调验证。
3. 超声波/ToF 是否进入首版硬件兜底仍需实测噪声和安装位置。
4. 新版 APK 需要用 `cartfollow_diagnostics` 复测目标返回、遮挡恢复和干扰者抑制。
5. 真实底盘极低速联调前，需要确认 `candidate_switch_penalty`、`belief_high_bbox_failed`、`recovered_rate`、`hard_stop_count` 和非目标转绿指标没有恶化。
