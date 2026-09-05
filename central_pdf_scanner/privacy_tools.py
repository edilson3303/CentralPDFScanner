from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from collections.abc import Sequence

import fitz

from .progress import ProgressCallback, check_cancel, report


class PrivacyToolError(RuntimeError):
    pass


Redaction = tuple[int, float, float, float, float]


def redact_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    redactions: Sequence[Redaction],
) -> Path:
    source = Path(input_pdf)
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise PrivacyToolError("Selecione um arquivo PDF válido.")
    if not redactions:
        raise PrivacyToolError("Marque ao menos uma área para ocultar.")
    destination = Path(output_pdf)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open(source)
    try:
        for page_index, x0, y0, x1, y1 in redactions:
            if page_index < 0 or page_index >= len(document):
                raise PrivacyToolError("Foi indicada uma página inexistente.")
            page = document[page_index]
            rectangle = fitz.Rect(x0, y0, x1, y1) & page.rect
            if rectangle.is_empty or rectangle.width < 1 or rectangle.height < 1:
                raise PrivacyToolError("Uma das áreas marcadas é inválida.")
            page.add_redact_annot(rectangle, fill=(0, 0, 0))
        for page in document:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        document.save(destination, garbage=4, deflate=True)
    finally:
        document.close()
    return destination


def file_sha256(path: str | Path, cancel_event: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check_cancel(cancel_event)
            digest.update(block)
    return digest.hexdigest()


def find_duplicate_pdfs(
    directory: str | Path,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[list[Path]]:
    folder = Path(directory)
    if not folder.is_dir():
        raise PrivacyToolError("Escolha uma pasta válida.")
    files = sorted(path for path in folder.rglob("*.pdf") if path.is_file())
    by_size: dict[int, list[Path]] = {}
    for path in files:
        by_size.setdefault(path.stat().st_size, []).append(path)
    candidates = [path for group in by_size.values() if len(group) > 1 for path in group]
    hashes: dict[str, list[Path]] = {}
    for index, path in enumerate(candidates, 1):
        check_cancel(cancel_event)
        report(progress_callback, f"Comparando PDF {index} de {len(candidates)}...")
        hashes.setdefault(file_sha256(path, cancel_event), []).append(path)
    return [paths for paths in hashes.values() if len(paths) > 1]
