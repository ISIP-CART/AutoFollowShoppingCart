---
name: autofollow-sysml-modeler
description: Generate and maintain Chinese SysML-style modeling artifacts for the AutoFollowShoppingCart OpenBot project. Use when updating design/sysml/sysml-modeling.md, creating PlantUML .puml diagrams, selecting diagram types, generating PlantUML server links, or checking project-specific SysML safety boundaries.
---

# AutoFollow SysML Modeler

## Core Workflow

Use this skill to update the SysML modeling artifacts for the OpenBot-based autonomous following shopping cart project. Default to Chinese for all human-facing content.

1. Read project facts from `AGENTS.md`, `README.md`, `design/**/*.md`, `design/doc` course/report materials, `dev/OpenBot/android/cartfollow-devlog.md`, relevant `firmware/` docs, and `tools/reid_pc_test/README.md`.
2. Do not read private or heavy artifact folders: `.git/`, build outputs, `tools/reid_pc_test/images*/`, `tools/reid_pc_test/outputs/`, or `tools/reid_pc_test/weights/`.
3. Update `design/sysml/sysml-modeling.md` as the canonical modeling document.
4. Create a timestamped run folder under `design/sysml/runs/<YYYYMMDD-HHMMSS>/`.
5. Write selected `.puml` files under `puml/`, then run the bundled validation/link scripts with an available Python runtime.
6. Write `generation-report.md`, `source-manifest.json`, and `diagram-links.md`.

Never run Git operations from this skill. Do not commit, pull, merge, push, checkout, reset, clean, or stage files.

## Project Boundaries

Keep the first-version architecture anchored to `OpenBot + Android 手机 + MCU/ESP32 + 差速底盘`.
Android 手机是上位机，承担视觉感知、AI 推理、跟随决策和交互。
MCU 解析串口命令、驱动电机并执行安全保护。

Do not silently expand the first version into SLAM, cloud dispatch, Raspberry Pi control, automatic checkout, or real-supermarket deployment. If a source conflicts with the architecture boundary, record the conflict in `sysml-modeling.md` instead of overwriting the boundary.

Use newer project documents for implementation status only when they do not conflict with `AGENTS.md` and `design/structure.md`.

## Diagram Selection

If the user does not specify diagrams, generate the default set listed in `references/diagram-catalog.md`.
If the user names diagram types, generate only those diagrams.
If the user asks to add a new diagram, create it with a clear numbered filename after the default set.
Ask for confirmation only when the user explicitly requests confirmation or when the requested diagram scope is contradictory.

## PlantUML Rules

Use simple, renderable PlantUML with SysML-like stereotypes such as `<<block>>`, `<<requirement>>`, `<<interfaceBlock>>`, `<<constraint>>`, and `<<valueType>>`.
Each PUML file must start with `@startuml` and end with `@enduml`.

Language rules:

- Use Chinese for titles, actors, blocks, requirements, states, transitions, notes, and relationship labels.
- Keep English only for unavoidable protocol/API/model names, file names, class names, and established terms such as `OpenBot`, `Android`, `ReID`, `STOP`, `LOCAL_SEARCH`, `TargetTrackManager`, and `IdentityBeliefAccumulator`.
- If a source document is English, translate its meaning into concise Chinese labels instead of copying English sentences into the diagram.

Avoid fragile syntax that commonly causes PlantUML server `400 Bad Request`:

- Do not put raw protocol examples like `c<left,right>` in labels. Use `c(left,right)` or `c&lt;left,right&gt;`.
- Do not use complex HTML-like labels unless necessary.
- Prefer quoted labels and simple aliases.
- Do not set local or platform-specific fonts with `skinparam defaultFontName`; public PlantUML servers may not have those fonts.
- Avoid optional layout tuning such as `skinparam linetype ortho` unless a diagram fails to read without it.
- Keep diagram URLs reasonably short; split crowded diagrams if the encoded link becomes too long.

For maximum render reliability, prefer `rectangle`, `node`, `component`, `actor`, `usecase`, and `state` blocks. Requirements can be expressed as `rectangle "REQ-001\n中文需求" as R1 <<requirement>>` instead of class boxes when PlantUML class syntax is uncertain.

When unsure about syntax, consult `design/sysml/PlantUML_Language_Reference_Guide_en.pdf` or `references/plantuml-safe-patterns.md` before writing the PUML.

## Bundled Scripts

Run scripts from the repository with an available Python runtime. Prefer conda if the user has one, but do not hard-code a conda installation path or environment name in generated instructions.

Conda example:

```powershell
conda run -n <env> python design\sysml\skills\autofollow-sysml-modeler\scripts\validate_puml.py --puml-dir design\sysml\runs\<timestamp>\puml
conda run -n <env> python design\sysml\skills\autofollow-sysml-modeler\scripts\plantuml_links.py --puml-dir design\sysml\runs\<timestamp>\puml --output design\sysml\runs\<timestamp>\diagram-links.md
```

Plain Python example, when conda is not available:

```powershell
python design\sysml\skills\autofollow-sysml-modeler\scripts\validate_puml.py --puml-dir design\sysml\runs\<timestamp>\puml
python design\sysml\skills\autofollow-sysml-modeler\scripts\plantuml_links.py --puml-dir design\sysml\runs\<timestamp>\puml --output design\sysml\runs\<timestamp>\diagram-links.md
```

`validate_puml.py` checks required files, start/end tags, and high-risk syntax.
`plantuml_links.py` creates PlantUML `/uml/` editor/view links and optional direct render links.
