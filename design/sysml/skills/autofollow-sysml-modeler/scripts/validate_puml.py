from __future__ import annotations

import argparse
import pathlib
import re
import sys
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

ENCODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
RAW_ANGLE_RE = re.compile(r"(?<!<)<(?!<|/?(?:b|i|u|br|color|size|img)\b)([^>\n]{1,80})(?<!>)>(?!>)")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{2,}\b")
ALLOWED_ENGLISH_TOKENS = {
    "OpenBot",
    "Android",
    "ReID",
    "STOP",
    "LOCAL_SEARCH",
    "TargetTrackManager",
    "IdentityBeliefAccumulator",
    "Human",
    "Cart",
    "Simulator",
    "ESP32",
    "MCU",
    "PUML",
    "REQ",
}


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


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def validate(puml_dir: pathlib.Path, require_default_set: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    files = sorted(puml_dir.glob("*.puml"))
    if require_default_set:
        missing = [name for name in REQUIRED_PUML_FILES if not (puml_dir / name).exists()]
        if missing:
            errors.append("Missing required PUML files: " + ", ".join(missing))
    elif not files:
        errors.append(f"No .puml files found in {puml_dir}")

    for path in files:
        text = read_text(path).strip()
        if not text.startswith("@startuml"):
            errors.append(f"{path.name}: missing @startuml")
        if not text.endswith("@enduml"):
            errors.append(f"{path.name}: missing @enduml")
        for match in RAW_ANGLE_RE.finditer(text):
            value = match.group(0)
            if value.startswith("<<") and value.endswith(">>"):
                continue
            warnings.append(f"{path.name}: raw angle-bracket label may break server rendering: {value}")
        lowered = text.lower()
        if "defaultfontname" in lowered:
            warnings.append(f"{path.name}: avoid local font settings such as skinparam defaultFontName")
        if "skinparam linetype ortho" in lowered:
            warnings.append(f"{path.name}: avoid skinparam linetype ortho unless necessary")
        english_words = [
            word
            for word in ASCII_WORD_RE.findall(text)
            if word not in ALLOWED_ENGLISH_TOKENS and not word.startswith("REQ")
        ]
        chinese_chars = CHINESE_RE.findall(text)
        if len(english_words) > 20 and len(chinese_chars) < 80:
            warnings.append(
                f"{path.name}: diagram appears English-heavy; use Chinese for titles, labels, states, notes, and relationships"
            )
        encoded_len = len(encode_plantuml(text))
        if encoded_len > 7000:
            warnings.append(f"{path.name}: encoded URL is long ({encoded_len} chars); split the diagram if server rendering fails")
    return errors, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated PlantUML files.")
    parser.add_argument("--puml-dir", required=True)
    parser.add_argument("--require-default-set", action="store_true")
    parser.add_argument("--warnings-as-errors", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    puml_dir = pathlib.Path(args.puml_dir).resolve()
    errors, warnings = validate(puml_dir, args.require_default_set)
    for warning in warnings:
        print("WARNING: " + warning)
    for error in errors:
        print("ERROR: " + error, file=sys.stderr)
    if errors or (args.warnings_as_errors and warnings):
        raise SystemExit(1)
    print(f"Validated {puml_dir}")


if __name__ == "__main__":
    main()
