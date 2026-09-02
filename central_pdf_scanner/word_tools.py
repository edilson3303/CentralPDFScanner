from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import fitz
from docx import Document
from docx.enum.section import WD_SECTION
from docx.shared import Inches


class WordToolError(RuntimeError):
    pass


def pdf_to_word(input_pdf: str | Path, output_docx: str | Path) -> Path:
    """Preserva visualmente cada pagina do PDF dentro do Word."""
    source = Path(input_pdf)
    if not source.is_file():
        raise WordToolError("PDF não encontrado.")
    target = Path(output_docx).with_suffix(".docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open(source)
    document = Document()
    with tempfile.TemporaryDirectory(prefix="pdf_word_visual_") as temp:
      try:
        for page_index, page in enumerate(pdf):
            if page_index > 0:
                document.add_section(WD_SECTION.NEW_PAGE)
            section = document.sections[-1]
            section.page_width = Inches(page.rect.width / 72.0)
            section.page_height = Inches(page.rect.height / 72.0)
            section.top_margin = Inches(0)
            section.bottom_margin = Inches(0)
            section.left_margin = Inches(0)
            section.right_margin = Inches(0)
            section.header_distance = Inches(0)
            section.footer_distance = Inches(0)
            image_path = Path(temp) / f"pagina_{page_index + 1:04d}.png"
            page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(str(image_path))
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Inches(0)
            paragraph.paragraph_format.space_after = Inches(0)
            paragraph.add_run().add_picture(
                str(image_path), width=Inches(page.rect.width / 72.0), height=Inches(page.rect.height / 72.0)
            )
        document.save(target)
      finally:
        pdf.close()
    return target


def word_to_pdf(input_docx: str | Path, output_pdf: str | Path) -> Path:
    source = Path(input_docx).resolve()
    if not source.is_file():
        raise WordToolError("Documento Word não encontrado.")
    target = Path(output_pdf).with_suffix(".pdf").resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if _convert_with_word(source, target):
        return target
    if _convert_with_libreoffice(source, target):
        return target
    raise WordToolError(
        "Não foi possível converter. Instale o Microsoft Word ou o LibreOffice. "
        "O programa tentará ambos automaticamente."
    )


def _convert_with_word(source: Path, target: Path) -> bool:
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(str(source), ReadOnly=True)
        document.ExportAsFixedFormat(str(target), 17)
        return target.is_file() and target.stat().st_size > 0
    except Exception:
        return False
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass


def _convert_with_libreoffice(source: Path, target: Path) -> bool:
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        return False
    with tempfile.TemporaryDirectory(prefix="central_pdf_word_") as temp:
        command = [office, "--headless", "--convert-to", "pdf", "--outdir", temp, str(source)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        generated = Path(temp) / f"{source.stem}.pdf"
        if result.returncode != 0 or not generated.is_file():
            return False
        shutil.copy2(generated, target)
    return target.is_file() and target.stat().st_size > 0
