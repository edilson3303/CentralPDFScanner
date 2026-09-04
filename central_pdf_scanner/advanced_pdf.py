from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from io import BytesIO
from pathlib import Path
from typing import Sequence

import fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter

from .ocr import _hidden_process_options
from .pdf_tools import PDFToolError, _ensure_pdf, _write_pdf
from .progress import ProgressCallback, check_cancel, report
from .scan_processing import is_blank_image


COMPRESSION_PRESETS = {
    "Alta qualidade": (300, 220, 85),
    "Equilibrado": (240, 150, 70),
    "Tamanho reduzido": (180, 110, 55),
}


def _find_libreoffice() -> Path | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    candidates = [
        Path(found) if found else None,
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def convert_pdf_to_pdfa(
    input_pdf: str | Path,
    output_pdf: str | Path,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Converte para PDF/A-2b com o mecanismo de exportação do LibreOffice."""
    source = _ensure_pdf(input_pdf)
    office = _find_libreoffice()
    if office is None:
        raise PDFToolError(
            "O LibreOffice não foi encontrado. Instale o LibreOffice para gerar PDF/A-2b."
        )
    target = Path(output_pdf).with_suffix(".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    check_cancel(cancel_event)
    report(progress_callback, "Convertendo para PDF/A-2b...")
    filter_options = json.dumps(
        {"SelectPdfVersion": {"type": "long", "value": "2"}},
        separators=(",", ":"),
    )
    with tempfile.TemporaryDirectory(prefix="pdf_scanner_pdfa_") as temp:
        command = [
            str(office), "--headless", "--convert-to",
            f"pdf:draw_pdf_Export:{filter_options}", "--outdir", temp, str(source),
        ]
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **_hidden_process_options(),
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
        generated = Path(temp) / f"{source.stem}.pdf"
        if process.returncode != 0 or not generated.is_file():
            detail = stderr.strip() or stdout.strip() or "falha não especificada"
            raise PDFToolError(f"O LibreOffice não conseguiu gerar o PDF/A: {detail}")
        verification = fitz.open(generated)
        try:
            metadata = verification.get_xml_metadata()
        finally:
            verification.close()
        if "<pdfaid:part>2</pdfaid:part>" not in metadata or "<pdfaid:conformance>B</pdfaid:conformance>" not in metadata:
            raise PDFToolError("O arquivo foi gerado, mas não pôde ser confirmado como PDF/A-2b.")
        check_cancel(cancel_event)
        shutil.copy2(generated, target)
    return target


def compact_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    preset: str,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[Path, int, int]:
    """Reduz imagens internas sem rasterizar o texto ou remover a camada OCR."""
    source = _ensure_pdf(input_pdf)
    if preset not in COMPRESSION_PRESETS:
        raise PDFToolError("Qualidade de compactação inválida.")
    threshold, target_dpi, quality = COMPRESSION_PRESETS[preset]
    target = Path(output_pdf).with_suffix(".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    before = source.stat().st_size
    check_cancel(cancel_event)
    report(progress_callback, "Analisando imagens do PDF...")
    document = fitz.open(source)
    temporary = target.with_name(target.stem + "_compactando.pdf")
    try:
        document.rewrite_images(
            dpi_threshold=threshold, dpi_target=target_dpi, quality=quality,
            lossy=True, lossless=True, bitonal=True, color=True, gray=True,
        )
        check_cancel(cancel_event)
        report(progress_callback, "Regravando e compactando o PDF...")
        document.save(
            temporary, garbage=4, clean=True, deflate=True,
            deflate_images=True, deflate_fonts=True,
        )
    finally:
        document.close()
    check_cancel(cancel_event)
    if temporary.stat().st_size >= before:
        shutil.copy2(source, target)
        temporary.unlink(missing_ok=True)
    else:
        temporary.replace(target)
    return target, before, target.stat().st_size


def _render_page_image(page: fitz.Page, dpi: int = 120) -> Image.Image:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
    return Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")


def _page_has_barcode(image: Image.Image) -> bool:
    try:
        import cv2  # type: ignore
        import numpy as np
    except ImportError as exc:
        raise PDFToolError("O componente de leitura de códigos de barras não está disponível.") from exc
    data = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    detector_type = getattr(cv2, "barcode_BarcodeDetector", None)
    if detector_type is not None:
        detector = detector_type()
        try:
            result = detector.detectAndDecode(data)
            decoded = result[0] if isinstance(result, tuple) and result else result
            if isinstance(decoded, str) and decoded.strip():
                return True
            if isinstance(decoded, (tuple, list)) and any(str(value).strip() for value in decoded):
                return True
        except cv2.error:
            pass
    try:
        decoded, _points, _straight = cv2.QRCodeDetector().detectAndDecode(data)
        return bool(decoded.strip())
    except cv2.error:
        return False


def _write_groups(reader: PdfReader, groups: Sequence[Sequence[int]], destination: Path, stem: str) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for number, group in enumerate(groups, 1):
        if not group:
            continue
        writer = PdfWriter()
        for page_index in group:
            writer.add_page(reader.pages[page_index])
        outputs.append(_write_pdf(writer, destination / f"{stem}_lote_{number:03d}.pdf"))
    if not outputs:
        raise PDFToolError("Nenhum lote com conteúdo foi encontrado.")
    return outputs


def separate_pdf_batch(
    input_pdf: str | Path,
    output_dir: str | Path,
    mode: str,
    pages_per_file: int = 1,
    remove_separator: bool = True,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[Path]:
    """Separa um lote por página em branco, quantidade fixa ou código de barras."""
    source = _ensure_pdf(input_pdf)
    reader = PdfReader(str(source))
    count = len(reader.pages)
    if mode == "Quantidade de páginas":
        if pages_per_file < 1:
            raise PDFToolError("A quantidade de páginas deve ser maior que zero.")
        groups = [list(range(start, min(start + pages_per_file, count))) for start in range(0, count, pages_per_file)]
    elif mode in {"Página em branco", "Código de barras"}:
        document = fitz.open(source)
        groups: list[list[int]] = []
        current: list[int] = []
        try:
            for index, page in enumerate(document):
                check_cancel(cancel_event)
                report(progress_callback, f"Analisando separador — página {index + 1} de {count}...")
                image = _render_page_image(page)
                separator = is_blank_image(image) if mode == "Página em branco" else _page_has_barcode(image)
                image.close()
                if separator:
                    if current:
                        groups.append(current)
                        current = []
                    if not remove_separator:
                        current.append(index)
                else:
                    current.append(index)
            if current:
                groups.append(current)
        finally:
            document.close()
    else:
        raise PDFToolError("Forma de separação inválida.")
    check_cancel(cancel_event)
    report(progress_callback, "Criando os arquivos separados...")
    return _write_groups(reader, groups, Path(output_dir), source.stem)
