from __future__ import annotations

import math
import re
import statistics
import subprocess
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps, ImageStat

from .ocr import _hidden_process_options, find_tesseract


class ScanProcessingError(RuntimeError):
    pass


def is_blank_image(image: Image.Image) -> bool:
    """Detecta páginas praticamente vazias usando uma amostra em tons de cinza."""
    sample = ImageOps.grayscale(image)
    sample.thumbnail((360, 360), Image.Resampling.LANCZOS)
    histogram = sample.histogram()
    total = max(1, sample.width * sample.height)
    ink_ratio = sum(histogram[:245]) / total
    deviation = ImageStat.Stat(sample).stddev[0]
    # O limite é conservador para não apagar páginas com pouco texto, como
    # recibos, capas ou folhas contendo apenas um número de processo.
    return ink_ratio < 0.0004 and deviation < 4.0


def _deskew(image: Image.Image) -> Image.Image:
    try:
        import cv2  # type: ignore
        import numpy as np
    except ImportError:
        return image
    rgb = image.convert("RGB")
    data = np.asarray(rgb)
    gray = cv2.cvtColor(data, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 60, 180)
    minimum = max(80, image.width // 5)
    lines = cv2.HoughLinesP(
        edges, 1, math.pi / 180, threshold=80,
        minLineLength=minimum, maxLineGap=20,
    )
    if lines is None:
        return rgb
    angles: list[float] = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = (int(value) for value in line)
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        while angle <= -90:
            angle += 180
        while angle > 90:
            angle -= 180
        if abs(angle) <= 12:
            angles.append(angle)
    if not angles:
        return rgb
    angle = statistics.median(angles)
    if abs(angle) < 0.3:
        return rgb
    return rgb.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")


def _orientation_rotation(path: Path, app_dir: str | Path | None) -> int:
    executable = find_tesseract(app_dir)
    if not executable:
        return 0
    result = subprocess.run(
        [str(executable), str(path), "stdout", "--psm", "0"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        **_hidden_process_options(),
    )
    match = re.search(r"Rotate:\s*(0|90|180|270)", result.stdout + "\n" + result.stderr)
    return int(match.group(1)) if match else 0


def prepare_scanned_images(
    images: Sequence[str | Path],
    *,
    remove_blank_pages: bool = False,
    auto_deskew: bool = False,
    auto_orient: bool = False,
    app_dir: str | Path | None = None,
) -> list[Path]:
    """Aplica correções opcionais e devolve as páginas mantidas."""
    kept: list[Path] = []
    for page_number, value in enumerate(images, 1):
        path = Path(value)
        try:
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                if remove_blank_pages and is_blank_image(image):
                    continue
                if auto_deskew:
                    image = _deskew(image)
                if auto_orient:
                    temporary = path.with_name(path.stem + "_orientacao.jpg")
                    image.save(temporary, "JPEG", quality=94)
                    try:
                        rotation = _orientation_rotation(temporary, app_dir)
                    finally:
                        temporary.unlink(missing_ok=True)
                    if rotation:
                        image = image.rotate(-rotation, expand=True, fillcolor="white")
                image.save(path, "JPEG", quality=94)
                kept.append(path)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ScanProcessingError(f"Não foi possível corrigir a página {page_number}.") from exc
    if not kept:
        raise ScanProcessingError("Todas as páginas foram identificadas como vazias.")
    return kept
