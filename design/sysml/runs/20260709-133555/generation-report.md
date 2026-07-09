# SysML 生成报告

> 运行时间窗：20260709-133555  
> 范围：仅生成需求图和安全状态机图。  
> 语言：图内文字尽量使用中文，保留 OpenBot、Android、ReID、STOP、LOCAL_SEARCH、TargetTrackManager、IdentityBeliefAccumulator 等既有术语。

## 生成文件

| 文件 | 说明 |
| --- | --- |
| `puml/01_requirements.puml` | 首版需求图，覆盖必做需求、安全约束、验证入口、隐私边界和非首版目标 |
| `puml/02_safety_state_machine.puml` | 安全状态机图，区分可恢复停止、本地搜索、重捕获、阻塞等待、急停保持和 hard STOP |
| `diagram-links.md` | PlantUML server 链接，由脚本生成 |
| `source-manifest.json` | 本次读取和使用的来源清单 |

## 建模边界

- 首版保持 `OpenBot + Android 手机 + MCU/ESP32 + 差速底盘` 主线。
- Android 手机承担视觉感知、AI 推理、跟随决策和交互。
- MCU/ESP32 承担串口解析、底盘驱动适配、通信超时、急停和限速保护。
- ReID 只作为身份置信线索，不作为单帧身份判决器或运动许可。
- 目标丢失或身份不确定时先进入 `motion_stop`，允许短时 `LOCAL_SEARCH / REACQUIRE`，失败或风险升高后进入 hard `STOP`。
- 真实底盘前进接通前，继续优先用 Human Cart Simulator 和诊断日志验证目标返回、遮挡恢复和干扰者抑制。

## 明确排除

完整 SLAM、复杂路径规划、高精地图、云端实时闭环、树莓派主脑、自动结账、真实超市长期部署、商业级多目标 ReID 和麦轮全向自主跟随，均未建模为首版必需能力。

## 校验

已运行并通过：

```powershell
python design\sysml\skills\autofollow-sysml-modeler\scripts\validate_puml.py --puml-dir design\sysml\runs\20260709-133555\puml
python design\sysml\skills\autofollow-sysml-modeler\scripts\plantuml_links.py --puml-dir design\sysml\runs\20260709-133555\puml --output design\sysml\runs\20260709-133555\diagram-links.md
```

结果：

- PUML 结构校验通过。
- `diagram-links.md` 已生成两条 PlantUML editor/render 链接。
- 编码长度：`01_requirements.puml` 为 2792，`02_safety_state_machine.puml` 为 1712。
