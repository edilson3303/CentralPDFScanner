from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import fitz
from docx import Document
from docx.enum.section import WD_SECTION
from docx.shared import Inches, Pt


class WordToolError(RuntimeError):
    pass


def pdf_to_word(input_pdf: str | Path, output_docx: str | Path) -> Path:
    """Conversão local com texto editável e posicionamento aproximado."""
    source = Path(input_pdf)
    if not source.is_file():
        raise WordToolError("PDF não encontrado.")
    target = Path(output_docx).with_suffix(".docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open(source)
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10.5)
    try:
        for page_index, page in enumerate(pdf):
            if page_index > 0:
                document.add_section(WD_SECTION.NEW_PAGE)
            section = document.sections[-1]
            section.page_width = Inches(page.rect.width / 72.0)
            section.page_height = Inches(page.rect.height / 72.0)
            section.top_margin = Inches(0.5)
            section.bottom_margin = Inches(0.5)
            section.left_margin = Inches(0.55)
            section.right_margin = Inches(0.55)

            blocks = sorted(page.get_text("blocks"), key=lambda b: (round(b[1], 1), b[0]))
            text_blocks = [block for block in blocks if len(block) >= 7 and block[6] == 0 and block[4].strip()]
            if not text_blocks:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_image:
                    image_path = Path(temp_image.name)
                try:
                    pix.save(str(image_path))
                    document.add_picture(str(image_path), width=Inches(max(1.0, page.rect.width / 72.0 - 1.1)))
                finally:
                    image_path.unlink(missing_ok=True)
                continue
            previous_bottom = 0.0
            for x0, y0, x1, y1, text, *_ in text_blocks:
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(min(12, max(0, y0 - previous_bottom) * 0.35))
                paragraph.paragraph_format.space_after = Pt(2)
                paragraph.add_run(text.replace("\n", " ").strip())
                previous_bottom = y1
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
