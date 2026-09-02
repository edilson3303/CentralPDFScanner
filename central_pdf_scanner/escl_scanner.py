from __future__ import annotations

import ipaddress
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

import fitz
from PIL import Image

from .ocr import images_to_searchable_pdf
from .pdf_tools import images_to_pdf


class ESCLScannerError(RuntimeError):
    pass


CAPABILITIES_PATH = "/eSCL/ScannerCapabilities"
SCAN_JOBS_PATH = "/eSCL/ScanJobs"
SCAN_NAMESPACE = "http://schemas.hp.com/imaging/escl/2011/05/03"
PWG_NAMESPACE = "http://www.pwg.org/schemas/2010/12/sm"


def validate_ip_settings(ip_address: str, port: int, protocol: str = "http") -> tuple[str, int, str]:
    address = ip_address.strip()
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ESCLScannerError("Digite um endereço IP válido, por exemplo: 192.168.1.50.") from exc
    if not 1 <= int(port) <= 65535:
        raise ESCLScannerError("A porta deve estar entre 1 e 65535.")
    scheme = protocol.strip().lower()
    if scheme not in {"http", "https"}:
        raise ESCLScannerError("Escolha o protocolo HTTP ou HTTPS.")
    return str(parsed), int(port), scheme


def _base_url(ip_address: str, port: int, protocol: str) -> str:
    address, port, scheme = validate_ip_settings(ip_address, port, protocol)
    host = f"[{address}]" if ":" in address else address
    return f"{scheme}://{host}:{port}"


def _opener(protocol: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    if protocol == "https":
        # Multifuncionais normalmente usam certificado local/autossinado.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def _friendly_network_error(exc: Exception) -> ESCLScannerError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return ESCLScannerError("A multifuncional exige autenticação para digitalizar por IP.")
        if exc.code in (404, 405):
            return ESCLScannerError(
                "O equipamento respondeu, mas não oferece digitalização eSCL/AirScan nesse endereço. "
                "Instale o driver WIA do fabricante e use 'Scanner instalado no Windows'."
            )
        return ESCLScannerError(f"A multifuncional respondeu com erro HTTP {exc.code}.")
    return ESCLScannerError(
        "Não foi possível acessar a multifuncional. Confira o IP, a porta, o protocolo e se o computador está na mesma rede."
    )


def probe_escl_scanner(ip_address: str, port: int = 80, protocol: str = "http", timeout: int = 8) -> str:
    base = _base_url(ip_address, port, protocol)
    request = urllib.request.Request(
        base + CAPABILITIES_PATH,
        headers={"Accept": "application/xml, text/xml"},
        method="GET",
    )
    try:
        with _opener(protocol).open(request, timeout=timeout) as response:
            content = response.read(2_000_000)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise _friendly_network_error(exc) from exc
    if b"ScannerCapabilities" not in content:
        raise ESCLScannerError("O endereço respondeu, mas não foi identificado como scanner eSCL/AirScan.")
    return "Scanner eSCL/AirScan encontrado"


def _scan_settings(dpi: int, color_mode: str) -> bytes:
    if dpi not in (150, 200, 300, 400, 600):
        raise ESCLScannerError("Resolução inválida.")
    colors = {"Cor": "RGB24", "Cinza": "Grayscale8", "Preto e branco": "BlackAndWhite1"}
    color = colors.get(color_mode)
    if color is None:
        raise ESCLScannerError("Modo de cor inválido.")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="{SCAN_NAMESPACE}" xmlns:pwg="{PWG_NAMESPACE}">
  <pwg:Version>2.0</pwg:Version>
  <pwg:InputSource>Platen</pwg:InputSource>
  <scan:ColorMode>{color}</scan:ColorMode>
  <scan:XResolution>{dpi}</scan:XResolution>
  <scan:YResolution>{dpi}</scan:YResolution>
  <scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>
</scan:ScanSettings>"""
    return xml.encode("utf-8")


def _job_url(base: str, location: str) -> str:
    parsed = urllib.parse.urlparse(urllib.parse.urljoin(base + "/", location))
    # Alguns equipamentos devolvem seu nome DNS no Location. Mantemos o caminho,
    # mas usamos o IP informado para evitar falha de resolução desse nome local.
    return base + parsed.path.rstrip("/")


def _acquire_document(base: str, protocol: str, dpi: int, color_mode: str, timeout: int) -> tuple[bytes, str]:
    request = urllib.request.Request(
        base + SCAN_JOBS_PATH,
        data=_scan_settings(dpi, color_mode),
        headers={"Content-Type": "application/xml", "Accept": "application/xml"},
        method="POST",
    )
    opener = _opener(protocol)
    try:
        with opener.open(request, timeout=timeout) as response:
            location = response.headers.get("Location", "")
        if not location:
            raise ESCLScannerError("A multifuncional não informou o endereço do trabalho de digitalização.")
        document_request = urllib.request.Request(
            _job_url(base, location) + "/NextDocument",
            headers={"Accept": "image/jpeg, image/png, image/tiff, application/pdf"},
            method="GET",
        )
        with opener.open(document_request, timeout=timeout) as response:
            return response.read(), response.headers.get_content_type().lower()
    except ESCLScannerError:
        raise
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise _friendly_network_error(exc) from exc


def _document_to_images(data: bytes, content_type: str, destination: Path, page_start: int, dpi: int) -> list[Path]:
    outputs: list[Path] = []
    if content_type == "application/pdf" or data.startswith(b"%PDF"):
        document = fitz.open(stream=data, filetype="pdf")
        try:
            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            for offset, page in enumerate(document):
                target = destination / f"ip_scan_{page_start + offset:04d}.jpg"
                page.get_pixmap(matrix=matrix, alpha=False).save(str(target), jpg_quality=92)
                outputs.append(target)
        finally:
            document.close()
        return outputs

    source = destination / f"received_{page_start:04d}.img"
    source.write_bytes(data)
    try:
        with Image.open(source) as image:
            frame_count = getattr(image, "n_frames", 1)
            for offset in range(frame_count):
                image.seek(offset)
                target = destination / f"ip_scan_{page_start + offset:04d}.jpg"
                image.convert("RGB").save(target, "JPEG", quality=92)
                outputs.append(target)
    except Exception as exc:
        raise ESCLScannerError("A multifuncional devolveu um formato de imagem não reconhecido.") from exc
    return outputs


def scan_escl_to_pdf(
    ip_address: str,
    port: int,
    protocol: str,
    output_pdf: str | Path,
    *,
    dpi: int = 300,
    color_mode: str = "Cor",
    use_ocr: bool = False,
    language: str = "por+eng",
    app_dir: str | Path | None = None,
    ask_next_page: Callable[[int], bool] | None = None,
) -> Path:
    base = _base_url(ip_address, port, protocol)
    probe_escl_scanner(ip_address, port, protocol)
    with tempfile.TemporaryDirectory(prefix="pdf_scanner_ip_") as temp:
        directory = Path(temp)
        images: list[Path] = []
        scanned_pages = 0
        while True:
            data, content_type = _acquire_document(base, protocol, dpi, color_mode, timeout=180)
            new_images = _document_to_images(data, content_type, directory, scanned_pages + 1, dpi)
            images.extend(new_images)
            scanned_pages += len(new_images)
            if ask_next_page is None or not ask_next_page(scanned_pages):
                break
        if not images:
            raise ESCLScannerError("Nenhuma página foi recebida da multifuncional.")
        if use_ocr:
            return images_to_searchable_pdf(images, output_pdf, language, app_dir)
        return images_to_pdf(images, output_pdf)
