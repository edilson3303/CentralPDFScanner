from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Sequence

from pypdf import PdfReader, PdfWriter
import fitz

from .progress import ProgressCallback, check_cancel, report


class OCRError(RuntimeError):
    pass


def _hidden_process_options() -> dict[str, object]:
    """Impede que executaveis auxiliares abram uma janela de console no Windows."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


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
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
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
            check_cancel(cancel_event)
            report(progress_callback, f"Aplicando OCR — página {index + 1} de {len(images)}...")
            base = temp_dir / f"pagina_{index + 1:04d}"
            command = [str(executable), str(image), str(base), "-l", language, "pdf"]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_hidden_process_options(),
            )
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event is not None and cancel_event.is_set():
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        check_cancel(cancel_event)
            generated = base.with_suffix(".pdf")
            if process.returncode != 0 or not generated.is_file():
                detail = stderr.strip() or stdout.strip() or "falha não especificada"
                raise OCRError(f"Falha no OCR da página {index + 1}: {detail}")
            partials.append(generated)
        writer = PdfWriter()
        for partial in partials:
            for page in PdfReader(str(partial)).pages:
                writer.add_page(page)
        with target.open("wb") as stream:
            writer.write(stream)
    return target


def pdf_to_searchable_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    language: str = "por+eng",
    app_dir: str | Path | None = None,
    dpi: int = 300,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Renderiza um PDF digitalizado e cria uma camada de texto OCR."""
    source = Path(input_pdf)
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise OCRError("PDF não encontrado.")
    with tempfile.TemporaryDirectory(prefix="central_pdf_ocr_source_") as temp:
        directory = Path(temp)
        images: list[Path] = []
        document = fitz.open(source)
        try:
            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            for index, page in enumerate(document):
                check_cancel(cancel_event)
                report(progress_callback, f"Preparando página {index + 1} de {len(document)} para OCR...")
                image = directory / f"pagina_{index + 1:04d}.png"
                page.get_pixmap(matrix=matrix, alpha=False).save(str(image))
                images.append(image)
        finally:
            document.close()
        return images_to_searchable_pdf(
            images, output_pdf, language, app_dir,
            cancel_event=cancel_event, progress_callback=progress_callback,
        )
