from __future__ import annotations

import argparse
import pathlib
import zlib


ENCODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"


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


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_links(puml_dir: pathlib.Path, server: str, fmt: str) -> str:
    lines = [
        "# PlantUML Diagram Links",
        "",
        "These links encode the PUML text in the URL. Opening a `/uml/` link shows the PlantUML editor/viewer with the diagram source loaded.",
        "",
        "| PUML | Editor link | Direct render | Encoded length |",
        "| --- | --- | --- | ---: |",
    ]
    for puml in sorted(puml_dir.glob("*.puml")):
        text = sanitize_puml_text(read_text(puml))
        encoded = encode_plantuml(text)
        base = server.rstrip("/")
        editor = f"{base}/plantuml/uml/{encoded}"
        render = f"{base}/plantuml/{fmt}/{encoded}"
        lines.append(f"| `{puml.name}` | [uml]({editor}) | [{fmt}]({render}) | {len(encoded)} |")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PlantUML server links for PUML files.")
    parser.add_argument("--puml-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--server", default="https://www.plantuml.com")
    parser.add_argument("--format", choices=["svg", "png"], default="svg")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    puml_dir = pathlib.Path(args.puml_dir).resolve()
    output = pathlib.Path(args.output).resolve()
    if not puml_dir.exists():
        raise SystemExit(f"PUML directory does not exist: {puml_dir}")
    write_text(output, build_links(puml_dir, args.server, args.format))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
