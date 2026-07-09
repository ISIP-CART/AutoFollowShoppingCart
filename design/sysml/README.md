# SysML 自动建模流水线

本目录用于维护“基于 OpenBot 的自主跟随购物车原型”的 SysML 风格建模产物。这里的流水线只做文档和图，不做任何版本控制操作。

推荐主线是 Codex Desktop + Skill：团队成员不需要安装 Codex CLI，也可以在桌面应用中触发建模、选择图类型、生成 PUML 和 PlantUML 链接。Codex CLI 批处理脚本保留为可选增强，适合已经安装 CLI 且希望一键生成 SVG/PNG 的成员。

## 推荐入口：Codex Desktop + Skill

Skill 源目录在：

```text
design/sysml/skills/autofollow-sysml-modeler/
```

将该目录安装或复制到本机 Codex skills 目录后，新开 Codex Desktop 对话即可使用：

```text
使用 $autofollow-sysml-modeler，读取当前项目文档，更新 SysML 建模文档，生成默认 PlantUML 图并输出链接。
```

也可以指定图类型，例如：

```text
使用 $autofollow-sysml-modeler，只生成需求图和安全状态机图，图内文字尽量用中文，并生成 PlantUML 链接。
```

Skill 默认输出中文图名、中文节点、中文需求、中文状态和中文连线说明；仅保留 `OpenBot`、`Android`、`ReID`、`STOP` 等必要技术名。

## 输出结构

每次运行都会创建一个时间戳目录：

```text
design/sysml/
  sysml-modeling.md
  runs/
    20260709-154200/
      source-manifest.json
      generation-report.md
      diagram-links.md
      puml/
        01_context.puml
        02_use_cases.puml
        03_requirements.puml
        04_block_definition.puml
        05_internal_block.puml
        06_follow_activity.puml
        07_safety_state_machine.puml
        08_deployment_and_interfaces.puml
      svg/
        01_context.svg
        ...
```

`diagram-links.md` 会包含 `https://www.plantuml.com/plantuml/uml/<encoded>` 链接。该链接把 PUML 文本编码进 URL，打开后可以直接在 PlantUML 页面查看图和源码。

`sysml-modeling.md` 是新的 canonical 建模文档。旧的 `design/week2-sysml-modeling.md` 只作为迁移参考。

## CLI 可选批处理

CLI 路径会调用 `codex exec` 生成结构化 JSON，再由外层 Python 写入文件、校验 PUML、生成 PlantUML 链接，并可选下载 SVG/PNG。它不是团队默认入口。

在仓库根目录运行：

```powershell
.\design\sysml\run_sysml.ps1 -Render server -Format svg -CondaEnv base
```

如果 Windows PowerShell 执行策略禁止直接运行 `.ps1`，使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\design\sysml\run_sysml.ps1 -Render server -Format svg -CondaEnv base
```

如果 `conda run` 内部报 `Cannot find Codex CLI in PATH`，可以显式传入外层 PowerShell 可用的 Codex 命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\design\sysml\run_sysml.ps1 -Render server -Format svg -CondaEnv base -CodexCommand codex
```

传入前建议先在同一个 PowerShell 窗口确认：

```powershell
codex --version
```

如果没有 `codex` 命令，Windows 上建议按官网方式安装 CLI：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

安装成功后通常会出现：

```text
%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe
```

也可以传完整路径或包装脚本路径：

```powershell
powershell -ExecutionPolicy Bypass -File .\design\sysml\run_sysml.ps1 -Render server -Format svg -CondaEnv base -CodexCommand "C:\path\to\codex.exe"
```

脚本会通过你提供的 conda 执行 Python，例如：

```powershell
<conda.bat> run -n <env> python design/sysml/generate_sysml.py --render server --format svg
```

默认环境是 `base`，可通过 `-CondaEnv` 改成其他已存在的 conda 环境。脚本只使用 Python 标准库，不会自动创建环境或安装依赖。

## 渲染方式

CLI 默认使用 PlantUML server：

```powershell
.\design\sysml\run_sysml.ps1 -Render server -Format svg
```

这会把生成的 PUML 内容发送到公共 PlantUML 服务。若不希望上传 PUML 内容，可以先只生成源文件：

```powershell
.\design\sysml\run_sysml.ps1 -Render none
```

如果本机有 PlantUML CLI 或 jar，可以本地渲染：

```powershell
.\design\sysml\run_sysml.ps1 -Render local -Format svg -PlantumlJar C:\tools\plantuml.jar
```

## 安全边界

流水线要求 Codex 只写入 `design/sysml/`，并明确跳过以下内容：

- `.git/`
- 构建产物和缓存目录
- `tools/reid_pc_test/images*/`
- `tools/reid_pc_test/outputs/`
- `tools/reid_pc_test/weights/`

流水线不会提交、拉取、合并、推送、切换分支或清理仓库。

## Codex CLI 预检

脚本会先在外层 PowerShell 检查 `codex` 是否存在，再进入 conda。Codex 桌面 App 和终端里的 `codex` 命令是不同入口；本流水线需要终端 CLI，因为它调用 `codex exec`。

入口脚本会优先使用官方安装器放在 `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe` 的 CLI；如果找不到，才退回 `Get-Command codex`。如果 `codex` 来自 WindowsApps，入口脚本会在系统临时目录创建一个 `sysml-codex-wrapper.cmd` 转发器，避免 Python 直接启动受保护的 WindowsApps 内部路径。当前某些受限 shell 仍可能返回 Access denied；如果遇到这个错误，请在普通 PowerShell 或正确的 Codex CLI 环境中重新运行 `run_sysml.ps1`。

如果报错包含 `api.openai.com/v1/responses`、`os error 10013`、`Could not connect to server` 或 `stream disconnected before completion`，说明已经进入 Codex CLI，但网络或系统安全策略阻止了它连接 OpenAI API。此时脚本参数通常已经没有问题，需要换到普通 PowerShell、检查代理/防火墙/VPN，或确认当前环境允许 Codex CLI 出网。

如果报错包含 `codex-windows-sandbox-setup.exe ... program not found`，说明旧版流水线或 Codex 子进程尝试使用内部文件系统/命令工具。当前版本已经改成让外层 Python 负责读写文件，Codex 只返回 JSON；重新运行 `run_sysml.ps1` 即可。

这个 helper 通常不需要单独安装。官方 standalone 包里应包含：

```text
%USERPROFILE%\.codex\packages\standalone\releases\<version>-x86_64-pc-windows-msvc\codex-resources\codex-windows-sandbox-setup.exe
```

入口脚本会自动扫描 `%USERPROFILE%\.codex\packages\standalone\releases\`，并把最新 release 的 `codex-resources` 和 `codex-path` 加入传给 conda/Codex 的 PATH。若仍报 helper 找不到，可以先确认该文件存在：

```powershell
Get-ChildItem "$env:USERPROFILE\.codex\packages\standalone\releases" -Recurse -Filter codex-windows-sandbox-setup.exe
```

## PlantUML server 403

如果输出已经显示 `codex-final-message.md`、`sysml-modeling.md` 和 8 个 `.puml` 已生成，但随后在
`urllib.error.HTTPError: HTTP Error 403: Forbidden` 处失败，说明失败点只在公共 PlantUML server 渲染。
这通常不是 Codex CLI 生成失败，而是公共服务拒绝了本次 HTTP 请求。

可以只对已有 run 补渲染，避免重新调用 Codex：

```powershell
powershell -ExecutionPolicy Bypass -File .\design\sysml\run_sysml.ps1 -Render server -Format svg -CondaEnv base -RenderOnlyRun 20260709-121845
```

如果公共 server 仍然 403，可以改成本地 PlantUML：

```powershell
powershell -ExecutionPolicy Bypass -File .\design\sysml\run_sysml.ps1 -Render local -Format svg -CondaEnv base -PlantumlJar C:\tools\plantuml.jar -RenderOnlyRun 20260709-121845
```

也可以换一个兼容 PlantUML server URL：

```powershell
powershell -ExecutionPolicy Bypass -File .\design\sysml\run_sysml.ps1 -Render server -Format svg -CondaEnv base -Server https://www.plantuml.com -RenderOnlyRun 20260709-121845
```

## CLI 渲染容错

CLI 每次都会生成 `diagram-links.md`。即使公共 PlantUML server 对某张图返回 `400/403`，已成功的 SVG/PNG 会保留，失败详情会写入 `render-report.md`，用户仍可通过 `diagram-links.md` 打开对应 `/uml/` 链接继续查看或调试。
