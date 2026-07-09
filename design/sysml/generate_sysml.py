from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zlib


REQUIRED_PUML_FILES = [
    "01_context.puml",
    "02_use_cases.puml",
    "03_requirements.puml",
    "04_block_definition.puml",
    "05_internal_block.puml",
    "06_follow_activity.puml",
    "07_safety_state_machine.puml",
    "08_deployment_and_interfaces.puml",
]

MAX_TOTAL_SOURCE_CHARS = 180_000
MAX_SOURCE_CHARS_PER_FILE = 14_000

SKIP_DIR_PARTS = {
    ".git",
    ".gradle",
    ".idea",
    "__pycache__",
    "build",
    "runs",
    "outputs",
    "weights",
    "images",
    "images_openbot_clean",
}

IMPORTANT_RELATIVE_FILES = [
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "design/structure.md",
    "design/week2-sysml-modeling.md",
    "design/OpenBot与四驱麦轮AT8236下位机适配风险说明.md",
    "design/OpenBot源码分析与上位机架构理解.md",
    "design/自主跟随购物车上位机软件开发计划.md",
    "design/工程决策与实现策略记录.md",
    "design/ReID-deep-research-report.md",
    "design/上位机软件开发 Phase 2——修正跟随距离控制计划书.md",
    "design/障碍处理计划书.md",
    "design/货架拐角跟随目标转弯讨论总结与后续工作计划.md",
    "dev/OpenBot/android/cartfollow-devlog.md",
    "tools/reid_pc_test/README.md",
]

ENCODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
RAW_ANGLE_RE = re.compile(r"(?<!<)<(?!<|/?(?:b|i|u|br|color|size|img)\b)([^>\n]{1,80})(?<!>)>(?!>)")


def relpath(path: pathlib.Path, repo: pathlib.Path) -> str:
    return path.relative_to(repo).as_posix()


def is_skipped(path: pathlib.Path, repo: pathlib.Path) -> bool:
    try:
        parts = path.relative_to(repo).parts
    except ValueError:
        return True
    return any(part in SKIP_DIR_PARTS for part in parts)


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def run(
    cmd: list[str],
    cwd: pathlib.Path,
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), flush=True)
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed


def build_codex_env() -> dict[str, str]:
    env = os.environ.copy()
    host_path = env.get("CODEX_HOST_PATH")
    if host_path:
        env["PATH"] = host_path + os.pathsep + env.get("PATH", "")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def resolve_codex_command(requested: str | None, env: dict[str, str]) -> str:
    requested = (requested or "").strip()
    if requested:
        return requested

    codex = shutil.which("codex", path=env.get("PATH"))
    if codex is None:
        raise SystemExit(
            "Cannot find Codex CLI in PATH. Run this from a PowerShell session where `codex` is available, "
            "or pass -CodexCommand to design/sysml/run_sysml.ps1."
        )
    return codex


def check_codex_available(repo: pathlib.Path, requested: str | None) -> tuple[str, dict[str, str]]:
    env = build_codex_env()
    codex = resolve_codex_command(requested, env)

    try:
        completed = run([codex, "--version"], cwd=repo, check=False, env=env)
    except OSError as exc:
        raise SystemExit(
            "Codex CLI was found but cannot be executed in this shell. "
            "Open a normal PowerShell or the correct Codex CLI environment, then rerun design/sysml/run_sysml.ps1. "
            f"Underlying error: {exc}"
        ) from exc

    if completed.returncode != 0:
        raise SystemExit(
            "Codex CLI was found but failed its preflight check. "
            "Open a normal PowerShell or the correct Codex CLI environment, then rerun design/sysml/run_sysml.ps1. "
            "If needed, pass -CodexCommand with the exact Codex executable or wrapper."
        )
    return codex, env


def append3bytes(b1: int, b2: int, b3: int) -> str:
    c1 = b1 >> 2
    c2 = ((b1 & 0x3) << 4) | (b2 >> 4)
    c3 = ((b2 & 0xF) << 2) | (b3 >> 6)
    c4 = b3 & 0x3F
    return (
        ENCODE_ALPHABET[c1 & 0x3F]
        + ENCODE_ALPHABET[c2 & 0x3F]
        + ENCODE_ALPHABET[c3 & 0x3F]
        + ENCODE_ALPHABET[c4 & 0x3F]
    )


def encode_plantuml(text: str) -> str:
    compressed = zlib.compress(text.encode("utf-8"))[2:-4]
    encoded: list[str] = []
    for i in range(0, len(compressed), 3):
        chunk = compressed[i : i + 3]
        if len(chunk) == 3:
            encoded.append(append3bytes(chunk[0], chunk[1], chunk[2]))
        elif len(chunk) == 2:
            encoded.append(append3bytes(chunk[0], chunk[1], 0))
        elif len(chunk) == 1:
            encoded.append(append3bytes(chunk[0], 0, 0))
    return "".join(encoded)


def sanitize_puml_text(text: str) -> str:
    text = text.replace("c<left,right>", "c(left,right)")
    text = text.replace("h<ms>", "h(ms)")
    text = text.replace("c&lt;left,right&gt;", "c(left,right)")
    return text


def plantuml_links_for_text(text: str, server: str, fmt: str) -> tuple[str, str, int]:
    encoded = encode_plantuml(sanitize_puml_text(text))
    base = server.rstrip("/")
    return f"{base}/plantuml/uml/{encoded}", f"{base}/plantuml/{fmt}/{encoded}", len(encoded)


def write_diagram_links(puml_dir: pathlib.Path, output: pathlib.Path, server: str, fmt: str) -> None:
    lines = [
        "# PlantUML Diagram Links",
        "",
        "These links encode the PUML text in the URL. Opening a `/uml/` link shows the PlantUML editor/viewer with the diagram source loaded.",
        "",
        "| PUML | Editor link | Direct render | Encoded length |",
        "| --- | --- | --- | ---: |",
    ]
    for puml in sorted(puml_dir.glob("*.puml")):
        editor, render, encoded_len = plantuml_links_for_text(read_text(puml), server, fmt)
        lines.append(f"| `{puml.name}` | [uml]({editor}) | [{fmt}]({render}) | {encoded_len} |")
    write_text(output, "\n".join(lines) + "\n")


def append_render_report(run_dir: pathlib.Path, lines: list[str]) -> None:
    if not lines:
        return
    report = run_dir / "render-report.md"
    existing = read_text(report) if report.exists() else "# Render Report\n\n"
    write_text(report, existing.rstrip() + "\n\n" + "\n".join(lines) + "\n")


def collect_sources(repo: pathlib.Path, manifest_path: pathlib.Path) -> dict[str, object]:
    candidates: dict[str, pathlib.Path] = {}

    for relative in IMPORTANT_RELATIVE_FILES:
        path = repo / relative
        if path.exists() and not is_skipped(path, repo):
            candidates[relative] = path

    for base in [repo / "design", repo / "firmware"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or is_skipped(path, repo):
                continue
            if path.suffix.lower() in {".md", ".puml", ".plantuml", ".pdf", ".pptx"}:
                candidates.setdefault(relpath(path, repo), path)

    sources = []
    for relative, path in sorted(candidates.items()):
        stat = path.stat()
        sources.append(
            {
                "path": relative,
                "size_bytes": stat.st_size,
                "mtime": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "kind": path.suffix.lower().lstrip(".") or "file",
            }
        )

    manifest = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "repo": str(repo),
        "source_policy": {
            "priority": [
                "AGENTS.md and design/structure.md define first-version architecture boundaries",
                "newer dated project documents can update implementation status when they do not conflict with boundaries",
                "unclear conflicts must be recorded in sysml-modeling.md",
            ],
            "skipped": sorted(SKIP_DIR_PARTS),
        },
        "sources": sources,
    }
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def collect_source_excerpt(repo: pathlib.Path, manifest: dict[str, object]) -> str:
    parts: list[str] = []
    total = 0

    for item in manifest["sources"]:
        relative = item["path"]
        path = repo / relative
        suffix = path.suffix.lower()
        header = f"\n\n===== SOURCE: {relative} | mtime={item['mtime']} | kind={item['kind']} =====\n"

        if suffix not in {".md", ".puml", ".plantuml"}:
            body = f"[binary or non-text source; metadata only, size={item['size_bytes']} bytes]\n"
        else:
            try:
                text = read_text(path)
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > MAX_SOURCE_CHARS_PER_FILE:
                body = (
                    text[:MAX_SOURCE_CHARS_PER_FILE]
                    + f"\n\n[truncated after {MAX_SOURCE_CHARS_PER_FILE} chars]\n"
                )
            else:
                body = text

        chunk = header + body
        if total + len(chunk) > MAX_TOTAL_SOURCE_CHARS:
            remaining = MAX_TOTAL_SOURCE_CHARS - total
            if remaining > 500:
                parts.append(chunk[:remaining] + "\n\n[overall source excerpt budget exhausted]\n")
            break
        parts.append(chunk)
        total += len(chunk)

    return "".join(parts)


def ensure_seed_model_doc(model_doc: pathlib.Path) -> None:
    if model_doc.exists():
        return
    write_text(
        model_doc,
        """# 自主跟随购物车 SysML 建模文档

> 本文档是 `design/sysml` 自动建模流水线的 canonical 建模入口。旧版 `design/week2-sysml-modeling.md` 仅作为迁移参考。

## 生成说明

- 运行入口：`design/sysml/run_sysml.ps1`
- 产物目录：`design/sysml/runs/<YYYYMMDD-HHMMSS>/`
- 本文档会由流水线根据当前项目文档更新。

## 待生成内容

流水线会补充系统概览、利益相关者、需求、上下文、功能架构、逻辑块、接口、内部结构、活动/状态、部署、假设、冲突与开放问题。
""",
    )


def build_prompt(repo: pathlib.Path, timestamp: str, model_doc: pathlib.Path, puml_dir: pathlib.Path, report: pathlib.Path, manifest: dict[str, object], source_excerpt: str) -> str:
    source_lines = []
    for item in manifest["sources"]:
        source_lines.append(f"- {item['path']} (mtime: {item['mtime']}, kind: {item['kind']})")

    required = "\n".join(f"- {name}" for name in REQUIRED_PUML_FILES)
    sources = "\n".join(source_lines)
    relative_model_doc = relpath(model_doc, repo)
    relative_puml_dir = relpath(puml_dir, repo)
    relative_report = relpath(report, repo)

    return f"""You are updating SysML-style modeling artifacts for the OpenBot-based autonomous following shopping cart repository.

Hard safety boundaries:
- Do not use tools.
- Do not run shell commands.
- Do not read or write files yourself.
- Do not run version-control commands or branch operations.
- Do not delete files.
- Do not modify source code.
- The wrapper Python script will write files under design/sysml/ after parsing your JSON response.
- Do not inspect private ReID image, output, weight, cache, build, or hidden VCS directories.
- Do not render diagrams; the wrapper script renders images after PUML generation.

Important execution note:
- You may be running in a Codex CLI environment whose Windows filesystem sandbox helper is unavailable.
- Therefore, do not attempt to use filesystem or shell tools.
- Use only the source excerpts embedded in this prompt.

Task timestamp: {timestamp}

Use the source excerpts below. Treat AGENTS.md and design/structure.md as the first-version architecture boundary. Prefer newer dated or newer mtime documents for implementation status when they do not conflict with that boundary. If a conflict cannot be safely resolved, record it in the modeling document instead of inventing a resolution.

Prepare {relative_model_doc} as the canonical SysML modeling document. Cover:
- system overview
- stakeholders and external actors
- requirements
- system context
- functional architecture
- logical blocks and interfaces
- internal structure
- main activities and states
- deployment and physical interfaces
- assumptions
- conflicts and open questions

Prepare these PlantUML files for {relative_puml_dir}:
{required}

PUML requirements:
- each file starts with @startuml and ends with @enduml
- each file is valid PlantUML
- use Chinese for titles, actors, blocks, requirements, states, transitions, notes, and relationship labels
- keep English only for stable technical names such as OpenBot, Android, ReID, STOP, LOCAL_SEARCH, TargetTrackManager, IdentityBeliefAccumulator, file names, and protocol tokens
- use SysML-like stereotypes where useful, including <<block>>, <<requirement>>, <<interfaceBlock>>, <<constraint>>, and <<valueType>>
- avoid raw angle-bracket protocol examples in labels, such as c<left,right> or h<ms>; write c(left,right) and h(ms) instead
- do not set local or platform-specific fonts with skinparam defaultFontName
- prefer simple rectangle/node/component/state/usecase syntax over fragile HTML labels or class compartments

Prepare a concise generation report for {relative_report}. Include documents consulted, updates made, generated files, assumptions, conflict handling, and open questions.

Output requirement:
- Return only one JSON object.
- Do not wrap the JSON in Markdown fences.
- Do not include commentary outside the JSON.
- Use this exact top-level shape:
  {{
    "model_doc": "...markdown...",
    "report": "...markdown...",
    "puml_files": {{
      "01_context.puml": "...",
      "02_use_cases.puml": "...",
      "03_requirements.puml": "...",
      "04_block_definition.puml": "...",
      "05_internal_block.puml": "...",
      "06_follow_activity.puml": "...",
      "07_safety_state_machine.puml": "...",
      "08_deployment_and_interfaces.puml": "..."
    }}
  }}

Source manifest:
{sources}

Source excerpts:
{source_excerpt}
"""


def build_output_schema(schema_path: pathlib.Path) -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["model_doc", "report", "puml_files"],
        "properties": {
            "model_doc": {"type": "string"},
            "report": {"type": "string"},
            "puml_files": {
                "type": "object",
                "additionalProperties": False,
                "required": REQUIRED_PUML_FILES,
                "properties": {name: {"type": "string"} for name in REQUIRED_PUML_FILES},
            },
        },
    }
    write_text(schema_path, json.dumps(schema, ensure_ascii=False, indent=2))


def call_codex(
    repo: pathlib.Path,
    codex: str,
    prompt: str,
    final_message: pathlib.Path,
    env: dict[str, str],
    schema_path: pathlib.Path,
) -> None:
    final_message.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            codex,
            "exec",
            "--cd",
            str(repo),
            "--sandbox",
            "workspace-write",
            "--output-last-message",
            str(final_message),
            "--output-schema",
            str(schema_path),
            "-",
        ],
        cwd=repo,
        env=env,
        input_text=prompt,
    )


def load_artifact_bundle(final_message: pathlib.Path) -> dict[str, object]:
    raw = read_text(final_message).strip()
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise SystemExit(f"Codex did not return a JSON artifact bundle. See {final_message}")
        try:
            bundle = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Codex returned invalid JSON. See {final_message}: {exc}") from exc

    if not isinstance(bundle, dict):
        raise SystemExit(f"Codex artifact bundle is not a JSON object. See {final_message}")
    return bundle


def write_artifact_bundle(
    bundle: dict[str, object],
    model_doc: pathlib.Path,
    puml_dir: pathlib.Path,
    report_path: pathlib.Path,
) -> None:
    model_text = bundle.get("model_doc")
    report_text = bundle.get("report")
    puml_files = bundle.get("puml_files")

    if not isinstance(model_text, str) or not isinstance(report_text, str) or not isinstance(puml_files, dict):
        raise SystemExit("Codex JSON bundle must contain string model_doc, string report, and object puml_files.")

    write_text(model_doc, model_text.rstrip() + "\n")
    write_text(report_path, report_text.rstrip() + "\n")
    for name in REQUIRED_PUML_FILES:
        content = puml_files.get(name)
        if not isinstance(content, str):
            raise SystemExit(f"Codex JSON bundle missing string puml_files.{name}")
        write_text(puml_dir / name, sanitize_puml_text(content).rstrip() + "\n")


def validate_puml(puml_dir: pathlib.Path) -> None:
    missing = [name for name in REQUIRED_PUML_FILES if not (puml_dir / name).exists()]
    if missing:
        raise SystemExit("Missing required PUML files: " + ", ".join(missing))

    failures = []
    warnings = []
    for name in REQUIRED_PUML_FILES:
        text = read_text(puml_dir / name).strip()
        if not text.startswith("@startuml"):
            failures.append(f"{name}: missing @startuml")
        if not text.endswith("@enduml"):
            failures.append(f"{name}: missing @enduml")
        for match in RAW_ANGLE_RE.finditer(text):
            warnings.append(f"{name}: raw angle-bracket label may break server rendering: {match.group(0)}")
        encoded_len = len(encode_plantuml(sanitize_puml_text(text)))
        if encoded_len > 7000:
            warnings.append(f"{name}: encoded URL is long ({encoded_len} chars); split the diagram if server rendering fails")
    for warning in warnings:
        print("WARNING: " + warning)
    if failures:
        raise SystemExit("PUML validation failed:\n" + "\n".join(failures))


def render_with_server(puml_dir: pathlib.Path, image_dir: pathlib.Path, fmt: str, server: str) -> list[str]:
    image_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for name in REQUIRED_PUML_FILES:
        puml = puml_dir / name
        source = sanitize_puml_text(read_text(puml))
        encoded = encode_plantuml(source)
        url = f"{server.rstrip('/')}/plantuml/{fmt}/{encoded}"
        target = image_dir / f"{puml.stem}.{fmt}"
        print(f"Rendering via server: {puml.name} -> {target.name}")
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 sysml-modeling-pipeline/1.0",
                "Accept": "image/svg+xml,image/png,*/*",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace") if exc.fp else ""
            failures.append(
                f"- `{puml.name}`: HTTP {exc.code} {exc.reason}. "
                f"[Open PlantUML editor]({server.rstrip('/')}/plantuml/uml/{encoded}). "
                f"Response excerpt: `{detail[:300].replace('`', '')}`"
            )
            print(f"WARNING: PlantUML server failed for {puml.name}: HTTP {exc.code} {exc.reason}")
            continue
        except urllib.error.URLError as exc:
            failures.append(
                f"- `{puml.name}`: network error while contacting PlantUML server: `{exc.reason}`. "
                f"[Open PlantUML editor]({server.rstrip('/')}/plantuml/uml/{encoded})."
            )
            print(f"WARNING: PlantUML server network error for {puml.name}: {exc.reason}")
            continue
        if b"PlantUML" in data[:500] and b"Syntax Error" in data[:2000]:
            failures.append(
                f"- `{puml.name}`: PlantUML server returned a syntax error. "
                f"[Open PlantUML editor]({server.rstrip('/')}/plantuml/uml/{encoded})."
            )
            print(f"WARNING: PlantUML server returned a syntax error for {puml.name}")
            continue
        target.write_bytes(data)
    return failures


def render_with_local(puml_dir: pathlib.Path, image_dir: pathlib.Path, fmt: str, plantuml_jar: str | None) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    if plantuml_jar:
        command = ["java", "-jar", plantuml_jar]
    else:
        plantuml = shutil.which("plantuml")
        if plantuml is None:
            raise SystemExit("Cannot find PlantUML CLI. Pass --plantuml-jar or use --render server/none.")
        command = [plantuml]

    for name in REQUIRED_PUML_FILES:
        run(command + [f"-t{fmt}", "-o", str(image_dir.resolve()), str((puml_dir / name).resolve())], cwd=puml_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate SysML modeling artifacts under design/sysml.")
    parser.add_argument("--repo", default=".", help="Repository root.")
    parser.add_argument("--render", choices=["server", "local", "none"], default="server")
    parser.add_argument("--format", choices=["svg", "png"], default="svg")
    parser.add_argument("--server", default="https://www.plantuml.com")
    parser.add_argument("--plantuml-jar", default=None)
    parser.add_argument("--codex-command", default=None, help="Codex executable or wrapper command.")
    parser.add_argument(
        "--render-only-run",
        default=None,
        help="Render an existing design/sysml/runs/<timestamp> directory without calling Codex.",
    )
    return parser.parse_args()


def resolve_existing_run(sysml_dir: pathlib.Path, value: str) -> pathlib.Path:
    candidate = pathlib.Path(value)
    if not candidate.is_absolute():
        named = sysml_dir / "runs" / value
        candidate = named if named.exists() else candidate
    run_dir = candidate.resolve()
    if not run_dir.exists():
        raise SystemExit(f"Cannot find existing run directory: {run_dir}")
    if not (run_dir / "puml").exists():
        raise SystemExit(f"Existing run directory has no puml/ folder: {run_dir}")
    return run_dir


def main() -> None:
    args = parse_args()
    repo = pathlib.Path(args.repo).resolve()
    sysml_dir = repo / "design" / "sysml"

    if args.render_only_run:
        run_dir = resolve_existing_run(sysml_dir, args.render_only_run)
        puml_dir = run_dir / "puml"
        image_dir = run_dir / args.format
        diagram_links = run_dir / "diagram-links.md"
        validate_puml(puml_dir)
        write_diagram_links(puml_dir, diagram_links, args.server, args.format)
        if args.render == "server":
            failures = render_with_server(puml_dir, image_dir, args.format, args.server)
            append_render_report(run_dir, failures)
        elif args.render == "local":
            render_with_local(puml_dir, image_dir, args.format, args.plantuml_jar)
        else:
            print("Skipping image rendering.")
        print()
        print("Done.")
        print(f"Rendered existing run: {run_dir}")
        print(f"Diagram links: {diagram_links}")
        return

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = sysml_dir / "runs" / timestamp
    puml_dir = run_dir / "puml"
    image_dir = run_dir / args.format
    manifest_path = run_dir / "source-manifest.json"
    report_path = run_dir / "generation-report.md"
    diagram_links = run_dir / "diagram-links.md"
    final_message = run_dir / "codex-final-message.md"
    schema_path = run_dir / "codex-output-schema.json"
    model_doc = sysml_dir / "sysml-modeling.md"

    codex, codex_env = check_codex_available(repo, args.codex_command)
    puml_dir.mkdir(parents=True, exist_ok=True)
    ensure_seed_model_doc(model_doc)
    manifest = collect_sources(repo, manifest_path)
    source_excerpt = collect_source_excerpt(repo, manifest)
    build_output_schema(schema_path)
    prompt = build_prompt(repo, timestamp, model_doc, puml_dir, report_path, manifest, source_excerpt)
    call_codex(repo, codex, prompt, final_message, codex_env, schema_path)
    bundle = load_artifact_bundle(final_message)
    write_artifact_bundle(bundle, model_doc, puml_dir, report_path)
    validate_puml(puml_dir)
    write_diagram_links(puml_dir, diagram_links, args.server, args.format)

    if args.render == "server":
        failures = render_with_server(puml_dir, image_dir, args.format, args.server)
        append_render_report(run_dir, failures)
    elif args.render == "local":
        render_with_local(puml_dir, image_dir, args.format, args.plantuml_jar)
    else:
        print("Skipping image rendering.")

    print()
    print("Done.")
    print(f"Model doc: {model_doc}")
    print(f"Run dir:   {run_dir}")
    print(f"Diagram links: {diagram_links}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Interrupted.")
