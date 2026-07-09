# 图目录 / Diagram Catalog

## Default Diagrams

Generate these when the user does not specify a custom selection:

| File | Diagram | Purpose |
| --- | --- | --- |
| `01_context.puml` | System context | Actors, environment, shopping cart system boundary, and external constraints. |
| `02_use_cases.puml` | Use cases | Teacher/demo, target user, team operator, safety and test workflows. |
| `03_requirements.puml` | Requirements | First-version requirements and non-goals as SysML-style requirements. |
| `04_block_definition.puml` | Block definition | Android, perception, behavior, MCU, driver, chassis, basket, and safety blocks. |
| `05_internal_block.puml` | Internal block | Main internal ports, command paths, feedback, and safety signals. |
| `06_follow_activity.puml` | Follow activity | Target selection, follow loop, lost/search/reacquire, obstacle and STOP behavior. |
| `07_safety_state_machine.puml` | Safety state machine | Manual, follow, local search, safety stop, estop, timeout, and recovery states. |
| `08_deployment_and_interfaces.puml` | Deployment and interfaces | Android phone, ESP32/MCU, AT8236 driver, motors, power, and serial interfaces. |

## Optional Diagrams

Use these when requested:

| Suggested File | Diagram | When to use |
| --- | --- | --- |
| `09_sequence_follow_loop.puml` | Sequence | Explain frame-by-frame Android to MCU command flow. |
| `10_test_validation.puml` | Test validation | Map acceptance tests to requirements and evidence. |
| `11_fault_safety.puml` | Fault tree / safety | Show obstacle, lost target, communication timeout, and estop safety paths. |
| `12_param_constraints.puml` | Constraint / value types | Show speed limits, timeout windows, confidence gates, and distance states. |

## Selection Rules

- "默认" or no selection means all 8 default diagrams.
- "只画需求图和状态机图" means `03_requirements.puml` and `07_safety_state_machine.puml`.
- "部署图" means `08_deployment_and_interfaces.puml`.
- "接口图" can mean `05_internal_block.puml` or `08_deployment_and_interfaces.puml`; choose both unless the user narrows it.
- "新增" means create a new numbered file after the selected/default diagrams.

## Language Rules

- Diagram titles, labels, requirements, states, notes, and relationship text should be Chinese by default.
- Keep English only for stable technical names: `OpenBot`, `Android`, `ReID`, `STOP`, `LOCAL_SEARCH`, `TargetTrackManager`, and file names.
- Prefer Chinese filenames only if the user asks; otherwise keep numbered ASCII filenames for tooling stability.
