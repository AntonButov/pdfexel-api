#!/usr/bin/env python3
"""Compare a PDF page screenshot to an Excel sheet screenshot via SSIM."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


DPI = 150


def _find_soffice() -> str | None:
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if mac.exists():
        return str(mac)
    return shutil.which("soffice") or shutil.which("libreoffice")


def _ssim(a: np.ndarray, b: np.ndarray) -> tuple[float, np.ndarray]:
    """Structural similarity on float images in [0, 255]. Returns score and full map."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    # Gaussian-ish local window via uniform 7x7 for portability (no scipy).
    kernel = np.ones((7, 7), dtype=np.float64) / 49.0

    def conv(img: np.ndarray) -> np.ndarray:
        pad = 3
        padded = np.pad(img, pad, mode="reflect")
        out = np.empty_like(img)
        for y in range(img.shape[0]):
            for x in range(img.shape[1]):
                out[y, x] = np.sum(padded[y : y + 7, x : x + 7] * kernel)
        return out

    mu_a = conv(a)
    mu_b = conv(b)
    mu_a2 = mu_a * mu_a
    mu_b2 = mu_b * mu_b
    mu_ab = mu_a * mu_b
    sigma_a2 = conv(a * a) - mu_a2
    sigma_b2 = conv(b * b) - mu_b2
    sigma_ab = conv(a * b) - mu_ab
    num = (2 * mu_ab + c1) * (2 * sigma_ab + c2)
    den = (mu_a2 + mu_b2 + c1) * (sigma_a2 + sigma_b2 + c2)
    full = num / den
    return float(full.mean()), full


def _try_skimage_ssim(a: np.ndarray, b: np.ndarray) -> tuple[float, np.ndarray] | None:
    try:
        from skimage.metrics import structural_similarity
    except ImportError:
        return None
    score, full = structural_similarity(a, b, data_range=255, full=True)
    return float(score), full


def render_pdf_page(pdf: Path, out_png: Path, page: int = 1) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        prefix = out_png.with_suffix("")
        proc = subprocess.run(
            [pdftoppm, "-png", "-r", str(DPI), "-f", str(page), "-l", str(page), "-singlefile", str(pdf), str(prefix)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode == 0 and out_png.exists() and out_png.stat().st_size:
            return
    try:
        import pymupdf
    except ImportError:
        pymupdf = None
    if pymupdf is not None:
        doc = pymupdf.open(pdf)
        try:
            pix = doc[page - 1].get_pixmap(matrix=pymupdf.Matrix(DPI / 72.0, DPI / 72.0), alpha=False)
            pix.save(out_png)
            return
        finally:
            doc.close()
    # LibreOffice: PDF → PNG (exports page images).
    soffice = _find_soffice()
    if not soffice:
        raise SystemExit("Need pdftoppm, pymupdf, or LibreOffice to render PDF")
    work = Path(tempfile.mkdtemp(prefix="compare-pdf-"))
    profile = work / "profile"
    profile.mkdir()
    try:
        src = work / "input.pdf"
        shutil.copy2(pdf, src)
        proc = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation=file://{profile}",
                "--headless",
                "--norestore",
                "--convert-to",
                "png",
                "--outdir",
                str(work),
                str(src),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        candidates = sorted(work.glob("input*.png"))
        if not candidates:
            raise SystemExit((proc.stderr or proc.stdout or "pdf render failed")[:400])
        # LibreOffice may emit one PNG per page named input.png / input-1.png etc.
        idx = max(0, page - 1)
        chosen = candidates[idx] if idx < len(candidates) else candidates[-1]
        shutil.copy2(chosen, out_png)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def render_xlsx_sheet(xlsx: Path, out_png: Path, sheet_index: int = 1) -> None:
    soffice = _find_soffice()
    if not soffice:
        raise SystemExit("LibreOffice soffice not found")
    work = Path(tempfile.mkdtemp(prefix="compare-xlsx-"))
    profile = work / "profile"
    profile.mkdir()
    try:
        src = work / "input.xlsx"
        shutil.copy2(xlsx, src)
        from openpyxl import load_workbook

        wb = load_workbook(src)
        keep = sheet_index - 1
        if keep < 0 or keep >= len(wb.worksheets):
            raise SystemExit(f"sheet {sheet_index} out of range 1..{len(wb.worksheets)}")
        for i, ws in enumerate(list(wb.worksheets)):
            if i != keep:
                wb.remove(ws)
        wb.save(src)
        proc = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation=file://{profile}",
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(work),
                str(src),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        pdf = work / "input.pdf"
        if proc.returncode != 0 or not pdf.exists():
            raise SystemExit((proc.stderr or proc.stdout or "libreoffice_fail")[:400])
        render_pdf_page(pdf, out_png, page=1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _content_bbox(img: Image.Image, threshold: int = 245) -> tuple[int, int, int, int]:
    gray = img.convert("L")
    arr = np.asarray(gray)
    mask = arr < threshold
    if not mask.any():
        return 0, 0, img.width, img.height
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _trim(img: Image.Image) -> Image.Image:
    box = _content_bbox(img)
    return img.crop(box)


def align_images(
    pdf_img: Image.Image,
    xlsx_img: Image.Image,
    *,
    trim: bool = False,
) -> tuple[Image.Image, Image.Image]:
    pdf_rgb = pdf_img.convert("RGB")
    xls_rgb = xlsx_img.convert("RGB")
    if trim:
        pdf_rgb = _trim(pdf_rgb)
        xls_rgb = _trim(xls_rgb)
    target_h = pdf_rgb.height
    scale = target_h / max(1, xls_rgb.height)
    new_w = max(1, int(round(xls_rgb.width * scale)))
    xls_scaled = xls_rgb.resize((new_w, target_h), Image.Resampling.LANCZOS)
    target_w = pdf_rgb.width
    if xls_scaled.width >= target_w:
        xls_fitted = xls_scaled.crop((0, 0, target_w, target_h))
    else:
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        canvas.paste(xls_scaled, (0, 0))
        xls_fitted = canvas
    return pdf_rgb, xls_fitted


def compare_pngs(pdf_png: Path, xlsx_png: Path, diff_png: Path, *, trim: bool = False) -> float:
    left, right = align_images(Image.open(pdf_png), Image.open(xlsx_png), trim=trim)
    a = np.asarray(left.convert("L"), dtype=np.float64)
    b = np.asarray(right.convert("L"), dtype=np.float64)
    sk = _try_skimage_ssim(a, b)
    if sk is not None:
        score, diff = sk
    else:
        # Downsample for the pure-numpy path (7x7 conv is O(n) heavy at 150 DPI).
        step = max(1, min(a.shape) // 400)
        score, diff = _ssim(a[::step, ::step], b[::step, ::step])
        # upsample diff for saving
        diff_img = Image.fromarray(((1.0 - diff) * 255).astype(np.uint8), mode="L")
        diff_img = diff_img.resize(left.size, Image.Resampling.NEAREST)
        diff_img.save(diff_png)
        left.save(diff_png.with_name(f"pdf-aligned-p{diff_png.stem.split('-p')[-1]}.png".replace("diff-", "")))
        # simpler names:
        left.save(diff_png.parent / diff_png.name.replace("diff-", "pdf-aligned-"))
        right.save(diff_png.parent / diff_png.name.replace("diff-", "xlsx-aligned-"))
        return score
    Image.fromarray(((1.0 - diff) * 255).astype(np.uint8), mode="L").save(diff_png)
    left.save(diff_png.parent / diff_png.name.replace("diff-", "pdf-aligned-"))
    right.save(diff_png.parent / diff_png.name.replace("diff-", "xlsx-aligned-"))
    return score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--trim", action="store_true", help="crop whitespace before SSIM")
    args = parser.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    pdf_png = out / f"pdf-p{args.page}.png"
    xlsx_png = out / f"xlsx-p{args.page}.png"
    diff_png = out / f"diff-p{args.page}.png"
    score_path = out / "score.txt"

    render_pdf_page(args.pdf, pdf_png, page=args.page)
    render_xlsx_sheet(args.xlsx, xlsx_png, sheet_index=args.page)
    score = compare_pngs(pdf_png, xlsx_png, diff_png, trim=args.trim)
    score_path.write_text(f"{score:.6f}\n", encoding="utf-8")
    print(f"SSIM={score:.6f}")
    print(f"pdf={pdf_png}")
    print(f"xlsx={xlsx_png}")
    print(f"diff={diff_png}")
    print(f"score={score_path}")


if __name__ == "__main__":
    main()
