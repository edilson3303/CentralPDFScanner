from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path
from typing import Iterable, Sequence

import fitz  # PyMuPDF
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions


class PDFToolError(RuntimeError):
    pass


def _ensure_pdf(path: str | Path) -> Path:
    result = Path(path)
    if not result.is_file() or result.suffix.lower() != ".pdf":
        raise PDFToolError(f"PDF não encontrado: {result}")
    return result


def parse_page_spec(spec: str, page_count: int, *, allow_empty: bool = False) -> list[int]:
    """Converte '1,3-5' em índices de página baseados em zero."""
    if page_count < 1:
        raise PDFToolError("O PDF não contém páginas.")
    text = spec.strip().replace(" ", "")
    if not text:
        if allow_empty:
            return list(range(page_count))
        raise PDFToolError("Informe ao menos uma página.")

    pages: set[int] = set()
    for part in text.split(","):
        if not part:
            raise PDFToolError("Lista de páginas inválida.")
        if "-" in part:
            if not re.fullmatch(r"\d+-\d+", part):
                raise PDFToolError(f"Intervalo inválido: {part}")
            start, end = (int(value) for value in part.split("-", 1))
            if start > end:
                raise PDFToolError(f"Intervalo invertido: {part}")
            values = range(start, end + 1)
        else:
            if not part.isdigit():
                raise PDFToolError(f"Página inválida: {part}")
            values = [int(part)]
        for value in values:
            if value < 1 or value > page_count:
                raise PDFToolError(f"A página {value} não existe (total: {page_count}).")
            pages.add(value - 1)
    return sorted(pages)


def remove_pages(input_pdf: str | Path, output_pdf: str | Path, page_spec: str) -> Path:
    source = _ensure_pdf(input_pdf)
    reader = PdfReader(str(source))
    remove = set(parse_page_spec(page_spec, len(reader.pages)))
    if len(remove) == len(reader.pages):
        raise PDFToolError("Não é possível remover todas as páginas.")
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index not in remove:
            writer.add_page(page)
    return _write_pdf(writer, output_pdf)


def merge_pdfs(inputs: Sequence[str | Path], output_pdf: str | Path) -> Path:
    if len(inputs) < 2:
        raise PDFToolError("Selecione pelo menos dois PDFs.")
    writer = PdfWriter()
    for item in inputs:
        reader = PdfReader(str(_ensure_pdf(item)))
        for page in reader.pages:
            writer.add_page(page)
    return _write_pdf(writer, output_pdf)


def merge_pdf_pages(page_refs: Sequence[tuple[str | Path, int]], output_pdf: str | Path) -> Path:
    """Une paginas individuais, preservando a ordem visual escolhida."""
    if not page_refs:
        raise PDFToolError("Selecione ao menos uma pagina.")
    readers: dict[Path, PdfReader] = {}
    writer = PdfWriter()
    for source_value, index in page_refs:
        source = _ensure_pdf(source_value)
        reader = readers.setdefault(source, PdfReader(str(source)))
        if index < 0 or index >= len(reader.pages):
            raise PDFToolError(f"A pagina {index + 1} nao existe em {source.name}.")
        writer.add_page(reader.pages[index])
    return _write_pdf(writer, output_pdf)


def split_pdf(input_pdf: str | Path, output_dir: str | Path, page_spec: str = "") -> list[Path]:
    """Cria um PDF para cada intervalo, como ``1-3,4-6,7-10``."""
    source = _ensure_pdf(input_pdf)
    reader = PdfReader(str(source))
    intervals = parse_split_intervals(page_spec, len(reader.pages))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for selected in intervals:
        writer = PdfWriter()
        for index in selected:
            writer.add_page(reader.pages[index])
        first, last = selected[0] + 1, selected[-1] + 1
        suffix = f"pagina_{first:03d}" if first == last else f"paginas_{first:03d}-{last:03d}"
        outputs.append(_write_pdf(writer, destination / f"{source.stem}_{suffix}.pdf"))
    return outputs


def parse_split_intervals(spec: str, page_count: int) -> list[list[int]]:
    """Converte intervalos separados por virgula em grupos de indices baseados em zero."""
    if page_count < 1:
        raise PDFToolError("O PDF não contém páginas.")
    text = spec.strip().replace(" ", "")
    if not text:
        raise PDFToolError("Informe ao menos um intervalo, por exemplo: 1-3,4-6.")
    groups: list[list[int]] = []
    used: set[int] = set()
    for part in text.split(","):
        if re.fullmatch(r"\d+", part):
            start = end = int(part)
        elif re.fullmatch(r"\d+-\d+", part):
            start, end = (int(value) for value in part.split("-", 1))
        else:
            raise PDFToolError(f"Intervalo inválido: {part or '(vazio)'}")
        if start > end:
            raise PDFToolError(f"Intervalo invertido: {part}")
        if start < 1 or end > page_count:
            raise PDFToolError(f"O intervalo {part} excede o total de {page_count} páginas.")
        group = list(range(start - 1, end))
        overlap = used.intersection(group)
        if overlap:
            raise PDFToolError(f"Há páginas repetidas no intervalo {part}.")
        used.update(group)
        groups.append(group)
    return groups


def trim_vertical_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    top_cm: float,
    bottom_cm: float,
    page_spec: str = "",
) -> Path:
    """Recorta somente as margens superior e inferior, informadas em centimetros."""
    return crop_pdf(input_pdf, output_pdf, 0, top_cm * 10, 0, bottom_cm * 10, page_spec)


def rotate_pages(
    input_pdf: str | Path,
    output_pdf: str | Path,
    degrees: int,
    page_spec: str = "",
) -> Path:
    if degrees not in (90, 180, 270):
        raise PDFToolError("A rotação deve ser 90, 180 ou 270 graus.")
    reader = PdfReader(str(_ensure_pdf(input_pdf)))
    selected = set(parse_page_spec(page_spec, len(reader.pages), allow_empty=True))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in selected:
            page.rotate(degrees)
        writer.add_page(page)
    return _write_pdf(writer, output_pdf)


def crop_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    left_mm: float,
    top_mm: float,
    right_mm: float,
    bottom_mm: float,
    page_spec: str = "",
) -> Path:
    margins = (left_mm, top_mm, right_mm, bottom_mm)
    if any(value < 0 for value in margins):
        raise PDFToolError("As margens não podem ser negativas.")
    reader = PdfReader(str(_ensure_pdf(input_pdf)))
    selected = set(parse_page_spec(page_spec, len(reader.pages), allow_empty=True))
    points = [value * 72.0 / 25.4 for value in margins]
    left, top, right, bottom = points
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in selected:
            box = page.cropbox
            new_left = float(box.left) + left
            new_right = float(box.right) - right
            new_bottom = float(box.bottom) + bottom
            new_top = float(box.top) - top
            if new_left >= new_right or new_bottom >= new_top:
                raise PDFToolError(f"O corte elimina toda a página {index + 1}.")
            page.cropbox.lower_left = (new_left, new_bottom)
            page.cropbox.upper_right = (new_right, new_top)
        writer.add_page(page)
    return _write_pdf(writer, output_pdf)


def pdf_to_jpg(input_pdf: str | Path, output_dir: str | Path, dpi: int = 200) -> list[Path]:
    if dpi < 72 or dpi > 600:
        raise PDFToolError("Use uma resolução entre 72 e 600 DPI.")
    source = _ensure_pdf(input_pdf)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    document = fitz.open(source)
    outputs: list[Path] = []
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    try:
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            target = destination / f"{source.stem}_pagina_{index + 1:03d}.jpg"
            pixmap.save(str(target), jpg_quality=92)
            outputs.append(target)
    finally:
        document.close()
    return outputs


def images_to_pdf(images: Iterable[str | Path], output_pdf: str | Path) -> Path:
    files = [Path(item) for item in images]
    if not files:
        raise PDFToolError("Selecione ao menos uma imagem.")
    opened: list[Image.Image] = []
    try:
        for path in files:
            if not path.is_file():
                raise PDFToolError(f"Imagem não encontrada: {path}")
            image = Image.open(path)
            if image.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", image.size, "white")
                if image.mode in ("RGBA", "LA"):
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            opened.append(image)
        target = Path(output_pdf)
        target.parent.mkdir(parents=True, exist_ok=True)
        opened[0].save(target, "PDF", resolution=200.0, save_all=True, append_images=opened[1:])
        return target
    finally:
        for image in opened:
            image.close()


def save_images_as_jpg(
    images: Iterable[str | Path], output_dir: str | Path, filename_prefix: str
) -> list[Path]:
    files = [Path(item) for item in images]
    if not files:
        raise PDFToolError("Nenhuma imagem foi recebida.")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, source in enumerate(files, 1):
        target = destination / f"{filename_prefix}_pagina_{index:03d}.jpg"
        try:
            with Image.open(source) as image:
                image.convert("RGB").save(target, "JPEG", quality=94)
        except Exception:
            shutil.copy2(source, target)
        outputs.append(target)
    return outputs


def protect_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    open_password: str = "",
    owner_password: str = "",
    restrict_editing: bool = False,
) -> Path:
    """Protege a abertura e/ou bloqueia edicao, selecao e copia com AES-256."""
    if not open_password and not restrict_editing:
        raise PDFToolError("Escolha proteção de abertura e/ou de edição.")
    if open_password and len(open_password) < 4:
        raise PDFToolError("Use uma senha de abertura com pelo menos 4 caracteres.")
    if restrict_editing and len(owner_password) < 4:
        raise PDFToolError("Use uma senha de proprietário com pelo menos 4 caracteres.")
    if restrict_editing and open_password == owner_password:
        raise PDFToolError("As senhas de abertura e de proprietário devem ser diferentes.")
    reader = PdfReader(str(_ensure_pdf(input_pdf)))
    if reader.is_encrypted:
        raise PDFToolError("Este PDF já está protegido. Desproteja-o antes de criar uma nova senha.")
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    try:
        permissions = (
            UserAccessPermissions.PRINT | UserAccessPermissions.PRINT_TO_REPRESENTATION
            if restrict_editing
            else UserAccessPermissions.all()
        )
        writer.encrypt(
            user_password=open_password,
            owner_password=owner_password or secrets.token_urlsafe(32),
            permissions_flag=permissions,
            algorithm="AES-256",
        )
    except ImportError as exc:
        raise PDFToolError("O componente de criptografia AES não está disponível.") from exc
    return _write_pdf(writer, output_pdf)


def unprotect_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    password: str,
) -> Path:
    """Remove a criptografia quando a senha fornecida é válida."""
    if not password:
        raise PDFToolError("Informe a senha do PDF.")
    reader = PdfReader(str(_ensure_pdf(input_pdf)))
    if not reader.is_encrypted:
        raise PDFToolError("Este PDF não possui proteção por senha.")
    try:
        result = reader.decrypt(password)
    except Exception as exc:
        raise PDFToolError("Não foi possível abrir o PDF com essa senha.") from exc
    if int(result) == 0:
        raise PDFToolError("Senha incorreta.")
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    return _write_pdf(writer, output_pdf)


def page_count(input_pdf: str | Path) -> int:
    return len(PdfReader(str(_ensure_pdf(input_pdf))).pages)


def _write_pdf(writer: PdfWriter, output_pdf: str | Path) -> Path:
    target = Path(output_pdf)
    if target.suffix.lower() != ".pdf":
        target = target.with_suffix(".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        writer.write(stream)
    return target
