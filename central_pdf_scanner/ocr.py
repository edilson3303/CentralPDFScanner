from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from pypdf import PdfReader, PdfWriter


class OCRError(RuntimeError):
    pass


def find_tesseract(app_dir: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if app_dir:
        root = Path(app_dir)
        candidates.extend([
            root / "engines" / "tesseract" / "tesseract.exe",
            root / "tesseract" / "tesseract.exe",
        ])
    configured = os.environ.get("TESSERACT_CMD")
    if configured:
        candidates.append(Path(configured))
    found = shutil.which("tesseract")
    if found:
        candidates.append(Path(found))
    candidates.extend([
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ])
    return next((path for path in candidates if path.is_file()), None)


def images_to_searchable_pdf(
    images: Sequence[str | Path],
    output_pdf: str | Path,
    language: str = "por+eng",
    app_dir: str | Path | None = None,
) -> Path:
    executable = find_tesseract(app_dir)
    if not executable:
        raise OCRError(
            "O mecanismo OCR Tesseract não foi encontrado. Instale o Tesseract OCR "
            "ou copie sua pasta para engines\\tesseract."
        )
    if not images:
        raise OCRError("Nenhuma imagem foi recebida para OCR.")
    target = Path(output_pdf)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="central_pdf_ocr_") as temp:
        temp_dir = Path(temp)
        partials: list[Path] = []
        for index, image in enumerate(images):
            base = temp_dir / f"pagina_{index + 1:04d}"
            command = [str(executable), str(image), str(base), "-l", language, "pdf"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            generated = base.with_suffix(".pdf")
            if result.returncode != 0 or not generated.is_file():
                detail = result.stderr.strip() or "falha não especificada"
                raise OCRError(f"Falha no OCR da página {index + 1}: {detail}")
            partials.append(generated)
        writer = PdfWriter()
        for partial in partials:
            for page in PdfReader(str(partial)).pages:
                writer.add_page(page)
        with target.open("wb") as stream:
            writer.write(stream)
    return target

