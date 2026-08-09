#!/usr/bin/env python3
"""
generate_readme.py

Scans every room folder for a writeup.md, reads its metadata header
(Machine Name / Platform / Difficulty / Category), and regenerates the
write-up table inside README.md between the WRITEUPS:START / :END
markers. Everything else in README.md is left untouched.

Usage (run from the repo root, after adding a new room folder):
    python3 generate_readme.py

Expected layout:
    repo-root/
    ├── README.md
    ├── generate_readme.py
    ├── chocolate-factory/
    │   ├── writeup.md
    │   └── screenshots/
    └── glitch/
        ├── writeup.md
        └── screenshots/

Each writeup.md must start with a metadata block like:
    **Machine Name:** Chocolate Factory
    **Platform:** TryHackMe
    **Difficulty:** Easy
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
README = ROOT / "README.md"
START_MARKER = "<!-- WRITEUPS:START -->"
END_MARKER = "<!-- WRITEUPS:END -->"

FIELD_TEMPLATE = r"\*\*{}:\*\*\s*(.+)"


def parse_writeup(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")

    def field(name: str, default: str = "—") -> str:
        match = re.search(FIELD_TEMPLATE.format(re.escape(name)), text)
        return match.group(1).strip() if match else default

    return {
        "room": field("Machine Name", default=md_path.parent.name.replace("-", " ").title()),
        "platform": field("Platform"),
        "difficulty": field("Difficulty"),
        "link": f"{md_path.parent.name}/{md_path.name}",
    }


def collect_writeups() -> list:
    entries = []
    for folder in sorted(ROOT.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        writeup = folder / "writeup.md"
        if writeup.exists():
            entries.append(parse_writeup(writeup))
        else:
            print(f"  (skipping {folder.name}/ — no writeup.md found)")
    entries.sort(key=lambda e: e["room"].lower())
    return entries


def build_table(entries: list) -> str:
    if not entries:
        return "_No write-ups yet — add a room folder with a `writeup.md` and re-run this script._"
    lines = [
        "| Room | Platform | Difficulty |",
        "|---|---|---|",
    ]
    for e in entries:
        lines.append(
            f"| [{e['room']}]({e['link']}) | {e['platform']} | {e['difficulty']} |"
        )
    return "\n".join(lines)


def update_readme(table: str) -> None:
    if not README.exists():
        sys.exit("README.md not found next to this script.")

    content = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)

    if not pattern.search(content):
        sys.exit(
            f"Couldn't find {START_MARKER} / {END_MARKER} markers in README.md.\n"
            "Add both marker lines (on their own lines) where the table should go."
        )

    replacement = f"{START_MARKER}\n{table}\n{END_MARKER}"
    README.write_text(pattern.sub(replacement, content), encoding="utf-8")


def main() -> None:
    print("Scanning room folders...")
    entries = collect_writeups()
    table = build_table(entries)
    update_readme(table)
    print(f"Done — README.md updated with {len(entries)} write-up(s).")


if __name__ == "__main__":
    main()
