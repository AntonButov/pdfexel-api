#!/usr/bin/env python3
"""Rebuild the invoice xlsx and climb SSIM vs the PDF page screenshot."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_STAND = Path("/Users/antonbutov/Documents/MYPROJECTS/pdf-stand")
JSON_STAND = Path("/Users/antonbutov/Documents/MYPROJECTS/json-stand")
sys.path.insert(0, str(PDF_STAND))
sys.path.insert(0, str(JSON_STAND))

from pdf_stand.pipeline import parse_file  # noqa: E402
from json_stand.pipeline import convert_data  # noqa: E402

COMPARE = Path.home() / "Downloads/pdfexel-2026-11-16/compare"
PDF = Path.home() / "Downloads/pdfexel-2026-11-16/счет Резиденция детства 05.11 (1).pdf"
XLSX = Path.home() / "Downloads/pdfexel-2026-11-16/счет Резиденция детства 05.11 (1).xlsx"
COMPARE_PY = ROOT / "scripts" / "compare_pages.py"


def score_once(tag: str) -> float:
    out = COMPARE / tag
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            str(COMPARE_PY),
            "--pdf",
            str(PDF),
            "--xlsx",
            str(XLSX),
            "--out",
            str(out),
            "--page",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    print(proc.stdout.strip() or proc.stderr.strip())
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout or "compare failed")
    return float((out / "score.txt").read_text().strip())


def apply_image_delta(sheets: list[dict], dx: float, dy: float) -> list[dict]:
    cloned = json.loads(json.dumps(sheets))
    for sheet in cloned:
        for image in sheet.get("images") or []:
            image["x_pt"] = round(float(image["x_pt"]) + dx, 2)
            image["y_pt"] = round(float(image["y_pt"]) + dy, 2)
    return cloned


def main() -> None:
    COMPARE.mkdir(parents=True, exist_ok=True)
    parsed = parse_file(PDF)
    assert parsed.ok, parsed.errors
    best_sheets = parsed.sheets
    convert_data({"sheets": best_sheets}, XLSX, normalize=True)
    best = score_once("iter0")
    history = [("iter0", 0.0, 0.0, best)]
    print(f"baseline SSIM={best:.6f}")

    # Search small image-anchor offsets; keep improvements only.
    candidates = [
        (0, -6),
        (0, 6),
        (-6, 0),
        (6, 0),
        (0, -12),
        (12, 0),
    ]
    for i, (dx, dy) in enumerate(candidates, start=1):
        trial = apply_image_delta(best_sheets, dx, dy)
        convert_data({"sheets": trial}, XLSX, normalize=True)
        tag = f"iter{i}_dx{dx}_dy{dy}"
        score = score_once(tag)
        history.append((tag, dx, dy, score))
        print(f"{tag} SSIM={score:.6f} best={best:.6f}")
        if score > best + 0.005:
            best = score
            best_sheets = trial
            print(f"  keep {tag}")
        else:
            # restore best workbook
            convert_data({"sheets": best_sheets}, XLSX, normalize=True)
        if best >= 0.85:
            break

    convert_data({"sheets": best_sheets}, XLSX, normalize=True)
    final = score_once("final")
    lines = [f"{tag}\tdx={dx}\tdy={dy}\tSSIM={score:.6f}" for tag, dx, dy, score in history]
    lines.append(f"FINAL\tSSIM={final:.6f}")
    (COMPARE / "score.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("done", final)
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
