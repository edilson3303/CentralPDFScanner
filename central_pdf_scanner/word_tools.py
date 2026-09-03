from __future__ import annotations

import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

import fitz
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor


class WordToolError(RuntimeError):
    pass


def pdf_to_word(input_pdf: str | Path, output_docx: str | Path, mode: str = "editable") -> Path:
    """Converte PDF para Word editavel ou para uma copia visual fiel."""
    source = Path(input_pdf)
    if not source.is_file():
        raise WordToolError("PDF não encontrado.")
    target = Path(output_docx).with_suffix(".docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "editable":
        return _pdf_to_word_editable(source, target)
    if mode == "visual":
        return _pdf_to_word_visual(source, target)
    raise WordToolError("Modo de conversão para Word inválido.")


def _configure_section(section, page: fitz.Page, *, margins: float) -> None:
    section.page_width = Inches(page.rect.width / 72.0)
    section.page_height = Inches(page.rect.height / 72.0)
    section.top_margin = Inches(margins)
    section.bottom_margin = Inches(margins)
    section.left_margin = Inches(margins)
    section.right_margin = Inches(margins)
    section.header_distance = Inches(0)
    section.footer_distance = Inches(0)


def _remove_initial_paragraph(document: Document) -> None:
    if document.paragraphs:
        paragraph = document.paragraphs[0]
        paragraph._element.getparent().remove(paragraph._element)


def _pdf_to_word_editable(source: Path, target: Path) -> Path:
    """Recria texto, estilos basicos, imagens e espacamento em elementos editaveis."""
    pdf = fitz.open(source)
    document = Document()
    _remove_initial_paragraph(document)
    text_characters = 0
    try:
        for page_index, page in enumerate(pdf):
            if page_index > 0:
                document.add_section(WD_SECTION.NEW_PAGE)
            section = document.sections[-1]
            margin = 0.28
            _configure_section(section, page, margins=margin)
            usable_width = page.rect.width - 2 * margin * 72
            previous_bottom = margin * 72
            blocks = sorted(page.get_text("dict").get("blocks", []), key=lambda item: (item["bbox"][1], item["bbox"][0]))
            for block in blocks:
                x0, y0, x1, y1 = block["bbox"]
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(max(0, min(36, y0 - previous_bottom)))
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.left_indent = Pt(max(0, x0 - margin * 72))
                # Reserva uma pequena folga para diferenças de métrica entre a fonte do PDF e a do Word.
                paragraph.paragraph_format.right_indent = Pt(max(0, page.rect.width - margin * 72 - x1 - 36))
                block_center = (x0 + x1) / 2
                if abs(block_center - page.rect.width / 2) < 18 and (x1 - x0) < usable_width * 0.88:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif x0 > page.rect.width * 0.55:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

                if block.get("type") == 0:
                    for line_index, line in enumerate(block.get("lines", [])):
                        if line_index:
                            paragraph.add_run().add_break()
                        for span in line.get("spans", []):
                            text = span.get("text", "")
                            text_characters += len(text.strip())
                            run = paragraph.add_run(text)
                            font_name = str(span.get("font", "Arial")).split(",", 1)[0]
                            run.font.name = font_name
                            run.font.size = Pt(max(5, min(72, float(span.get("size", 11)))))
                            flags = int(span.get("flags", 0))
                            run.bold = bool(flags & 16) or "bold" in font_name.lower()
                            run.italic = bool(flags & 2) or "italic" in font_name.lower()
                            color = int(span.get("color", 0))
                            run.font.color.rgb = RGBColor((color >> 16) & 255, (color >> 8) & 255, color & 255)
                elif block.get("type") == 1 and block.get("image"):
                    try:
                        width = min(max(0.25, (x1 - x0) / 72), usable_width / 72)
                        paragraph.add_run().add_picture(BytesIO(block["image"]), width=Inches(width))
                    except Exception:
                        paragraph._element.getparent().remove(paragraph._element)
                        continue
                else:
                    paragraph._element.getparent().remove(paragraph._element)
                    continue
                previous_bottom = max(previous_bottom, y1)
        if text_characters == 0:
            raise WordToolError(
                "Este PDF não possui texto reconhecido. Primeiro use 'PDF digitalizado para OCR' "
                "e depois converta o resultado para Word editável."
            )
        document.save(target)
    finally:
        pdf.close()
    return target


def _pdf_to_word_visual(source: Path, target: Path) -> Path:
    """Preserva visualmente cada pagina do PDF como imagem dentro do Word."""
    pdf = fitz.open(source)
    document = Document()
    with tempfile.TemporaryDirectory(prefix="pdf_word_visual_") as temp:
      try:
        for page_index, page in enumerate(pdf):
            if page_index > 0:
                document.add_section(WD_SECTION.NEW_PAGE)
            section = document.sections[-1]
            _configure_section(section, page, margins=0)
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

