from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence

import fitz

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
