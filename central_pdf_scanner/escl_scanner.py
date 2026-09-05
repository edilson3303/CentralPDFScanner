from __future__ import annotations

import ipaddress
import io
import tempfile
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

import fitz
from defusedxml import ElementTree as ET
from PIL import Image

from .ocr import images_to_searchable_pdf
from .pdf_tools import images_to_pdf, save_images_as_jpg
from .scan_processing import prepare_scanned_images
from .progress import ProgressCallback, check_cancel, report
from .scan_options import PAPER_SIZES_MM, paper_size_escl_units


class ESCLScannerError(RuntimeError):
    pass


CAPABILITIES_PATH = "/eSCL/ScannerCapabilities"
SCAN_JOBS_PATH = "/eSCL/ScanJobs"
SCAN_NAMESPACE = "http://schemas.hp.com/imaging/escl/2011/05/03"
PWG_NAMESPACE = "http://www.pwg.org/schemas/2010/12/sm"
MAX_CAPABILITIES_BYTES = 2_000_000
MAX_DOCUMENT_BYTES = 256 * 1024 * 1024
MAX_SCAN_PAGES = 1000


def validate_ip_settings(ip_address: str, port: int, protocol: str = "http") -> tuple[str, int, str]:
    address = ip_address.strip()
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ESCLScannerError("Digite um endereço IP válido, por exemplo: 192.168.1.50.") from exc
    if not (parsed.is_private or parsed.is_loopback or parsed.is_link_local):
        raise ESCLScannerError("Por segurança, informe um endereço IP da rede local.")
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _opener(protocol: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    handlers.append(_NoRedirect())
    return urllib.request.build_opener(*handlers)


def _friendly_network_error(exc: Exception) -> ESCLScannerError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return ESCLScannerError("A multifuncional exige autenticação para digitalizar por IP.")
        if exc.code in (404, 405):
            return ESCLScannerError(
                "O equipamento respondeu, mas não oferece digitalização eSCL/AirScan nesse endereço. "
                "Instale o driver WIA do fabricante e use 'Scanner USB'."
            )
        if exc.code == 409:
            return ESCLScannerError(
                "A multifuncional está ocupada, possui outro trabalho ativo, o alimentador está sem papel "
                "ou recusou a configuração escolhida. Coloque as folhas, aguarde alguns segundos e tente novamente."
            )
        if exc.code == 503:
            return ESCLScannerError("A multifuncional está temporariamente ocupada. Aguarde e tente novamente.")
        return ESCLScannerError(f"A multifuncional respondeu com erro HTTP {exc.code}.")
    return ESCLScannerError(
        "Não foi possível acessar a multifuncional. Confira o IP, a porta, o protocolo e se o computador está na mesma rede."
    )


def _read_capabilities(ip_address: str, port: int, protocol: str, timeout: int) -> bytes:
    base = _base_url(ip_address, port, protocol)
    request = urllib.request.Request(
        base + CAPABILITIES_PATH,
        headers={"Accept": "application/xml, text/xml"},
        method="GET",
    )
    try:
        with _opener(protocol).open(request, timeout=timeout) as response:
            content = response.read(MAX_CAPABILITIES_BYTES + 1)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise _friendly_network_error(exc) from exc
    if len(content) > MAX_CAPABILITIES_BYTES:
        raise ESCLScannerError("A resposta de recursos da multifuncional excedeu o limite permitido.")
    if b"ScannerCapabilities" not in content:
        raise ESCLScannerError("O endereço respondeu, mas não foi identificado como scanner eSCL/AirScan.")
    return content


def detect_escl_details(
    ip_address: str,
    port: int = 80,
    protocol: str = "http",
    timeout: int = 8,
) -> tuple[str, str, tuple[str, ...]]:
    content = _read_capabilities(ip_address, port, protocol, timeout)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ESCLScannerError("A multifuncional devolveu informações de digitalização inválidas.") from exc

    names = {element.tag.rsplit("}", 1)[-1].lower() for element in root.iter()}
    model = ""
    serial_number = ""
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        value = element.text.strip() if element.text and element.text.strip() else ""
        if not model and tag in {"makeandmodel", "model"} and value:
            model = value
        if not serial_number and tag in {"serialnumber", "deviceserialnumber", "serialno", "serial"} and value:
            serial_number = value
    sources: list[str] = []
    if any(name in names for name in ("platen", "plateninputcaps")):
        sources.append("Platen")
    if any(name in names for name in ("adfsimplexinputcaps", "feeder")):
        sources.append("Feeder")
    if "adfduplexinputcaps" in names:
        sources.append("FeederDuplex")
    # Alguns equipamentos omitem a seção Platen, embora o vidro esteja disponível.
    return model or f"Scanner_{ip_address}", serial_number, tuple(sources) or ("Platen",)


def detect_escl_info(
    ip_address: str,
    port: int = 80,
    protocol: str = "http",
    timeout: int = 8,
) -> tuple[str, tuple[str, ...]]:
    model, _serial_number, sources = detect_escl_details(ip_address, port, protocol, timeout)
    return model, sources

def detect_escl_sources(
    ip_address: str, port: int = 80, protocol: str = "http", timeout: int = 8
) -> tuple[str, ...]:
    return detect_escl_info(ip_address, port, protocol, timeout)[1]


def probe_escl_scanner(ip_address: str, port: int = 80, protocol: str = "http", timeout: int = 8) -> str:
    _read_capabilities(ip_address, port, protocol, timeout)
    return "Scanner eSCL/AirScan encontrado"


def _scan_settings(
    dpi: int,
    color_mode: str,
    input_source: str = "Platen",
    paper_size: str = "Automático (área máxima)",
) -> bytes:
    if dpi not in (150, 200, 300, 400, 600):
        raise ESCLScannerError("Resolução inválida.")
    colors = {"Cor": "RGB24", "Cinza": "Grayscale8", "Preto e branco": "BlackAndWhite1"}
    color = colors.get(color_mode)
    if color is None:
        raise ESCLScannerError("Modo de cor inválido.")
    if input_source not in {"Platen", "Feeder", "FeederDuplex"}:
        raise ESCLScannerError("Origem de digitalização inválida.")
    if paper_size not in PAPER_SIZES_MM:
        raise ESCLScannerError("Tamanho de papel inválido.")
    source = "Platen" if input_source == "Platen" else "Feeder"
    duplex_setting = ""
    if source == "Feeder":
        duplex = "true" if input_source == "FeederDuplex" else "false"
        duplex_setting = f"\n  <scan:Duplex>{duplex}</scan:Duplex>"
    region_setting = ""
    dimensions = paper_size_escl_units(paper_size)
    if dimensions is not None:
        width, height = dimensions
        region_setting = f"""
  <pwg:ScanRegions>
    <pwg:ScanRegion>
      <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
      <pwg:XOffset>0</pwg:XOffset>
      <pwg:YOffset>0</pwg:YOffset>
      <pwg:Width>{width}</pwg:Width>
      <pwg:Height>{height}</pwg:Height>
    </pwg:ScanRegion>
  </pwg:ScanRegions>"""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="{SCAN_NAMESPACE}" xmlns:escl="{SCAN_NAMESPACE}" xmlns:pwg="{PWG_NAMESPACE}">
  <pwg:Version>2.0</pwg:Version>
{region_setting}
  <pwg:InputSource>{source}</pwg:InputSource>{duplex_setting}
  <scan:ColorMode>{color}</scan:ColorMode>
  <scan:XResolution>{dpi}</scan:XResolution>
  <scan:YResolution>{dpi}</scan:YResolution>
  <scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>
</scan:ScanSettings>"""
    return xml.encode("utf-8")


def _job_url(base: str, location: str) -> str:
    cleaned_location = location.strip().strip("<>\"'")
    parsed = urllib.parse.urlparse(urllib.parse.urljoin(base + "/", cleaned_location))
    path = parsed.path.rstrip("/")
    normalized_path = path.casefold()
    normalized_root = SCAN_JOBS_PATH.casefold()
    lexmark_root = "/eSCL/ScanJob".casefold()
    # Alguns modelos Lexmark devolvem o próprio /eSCL/ScanJobs, sem um
    # identificador adicional, alteram a capitalização ou usam ScanJob
    # no singular no cabeçalho Location.
    valid_standard = normalized_path == normalized_root or normalized_path.startswith(normalized_root + "/")
    valid_lexmark = normalized_path.startswith(lexmark_root + "/")
    if not (valid_standard or valid_lexmark):
        raise ESCLScannerError("A multifuncional devolveu um endereço de trabalho inválido.")
    # Alguns equipamentos devolvem seu nome DNS no Location. Mantemos o caminho,
    # mas usamos o IP informado para evitar falha de resolução desse nome local.
    return base + path


def _create_scan_job(
    base: str,
    protocol: str,
    dpi: int,
    color_mode: str,
    input_source: str,
    paper_size: str,
    timeout: int,
) -> tuple[urllib.request.OpenerDirector, str]:
    request = urllib.request.Request(
        base + SCAN_JOBS_PATH,
        data=_scan_settings(dpi, color_mode, input_source, paper_size),
        headers={"Content-Type": "application/xml", "Accept": "application/xml"},
        method="POST",
    )
    opener = _opener(protocol)
    for attempt in range(15):
        try:
            with opener.open(request, timeout=timeout) as response:
                location = response.headers.get("Location", "")
            if not location:
                raise ESCLScannerError("A multifuncional não informou o endereço do trabalho de digitalização.")
            return opener, _job_url(base, location)
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 503) and attempt < 14:
                time.sleep(1.0)
                continue
            raise _friendly_network_error(exc) from exc
        except ESCLScannerError:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise _friendly_network_error(exc) from exc
    raise ESCLScannerError("A multifuncional permaneceu ocupada após várias tentativas.")


def _next_document(
    opener: urllib.request.OpenerDirector,
    job_url: str,
    timeout: int,
    *,
    allow_end: bool = False,
) -> tuple[bytes, str] | None:
    request = urllib.request.Request(
        job_url + "/NextDocument",
        headers={"Accept": "image/jpeg, image/png, image/tiff, application/pdf"},
        method="GET",
    )
    # O vidro pode levar vários segundos para aquecer e preparar a primeira
    # página. Nesse período, Lexmark e outros fabricantes respondem 409/503.
    for attempt in range(90):
        try:
            with opener.open(request, timeout=timeout) as response:
                data = response.read(MAX_DOCUMENT_BYTES + 1)
                if len(data) > MAX_DOCUMENT_BYTES:
                    raise ESCLScannerError("A página recebida excedeu o limite de tamanho permitido.")
                return data, response.headers.get_content_type().lower()
        except urllib.error.HTTPError as exc:
            if allow_end and exc.code in (404, 410):
                return None
            if exc.code in (409, 503):
                if attempt < 89:
                    time.sleep(0.5)
                    continue
                if allow_end:
                    return None
            raise _friendly_network_error(exc) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise _friendly_network_error(exc) from exc
    return None


def _release_scan_job(opener: urllib.request.OpenerDirector, job_url: str, timeout: int = 8) -> None:
    """Libera trabalhos específicos sem cancelar a fila compartilhada do equipamento."""
    path = urllib.parse.urlparse(job_url).path.rstrip("/")
    if path.casefold() == SCAN_JOBS_PATH.casefold():
        return
    request = urllib.request.Request(job_url, method="DELETE")
    try:
        with opener.open(request, timeout=timeout):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 405, 409, 410, 501):
            return
    except (OSError, urllib.error.URLError):
        return


def _document_to_images(data: bytes, content_type: str, destination: Path, page_start: int, dpi: int) -> list[Path]:
    outputs: list[Path] = []
    if content_type == "application/pdf" or data.startswith(b"%PDF"):
        document = fitz.open(stream=data, filetype="pdf")
        try:
            if page_start - 1 + document.page_count > MAX_SCAN_PAGES:
                raise ESCLScannerError(f"A digitalização excedeu o limite de {MAX_SCAN_PAGES} páginas.")
            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            for offset, page in enumerate(document):
                target = destination / f"ip_scan_{page_start + offset:04d}.jpg"
                page.get_pixmap(matrix=matrix, alpha=False).save(str(target), jpg_quality=92)
                outputs.append(target)
        finally:
            document.close()
        return outputs

    # A maioria dos scanners eSCL já entrega JPEG. Valida e preserva esses
    # bytes, evitando gravar e recodificar a mesma página duas vezes.
    if content_type == "image/jpeg" or data.startswith(b"\xff\xd8\xff"):
        try:
            with Image.open(io.BytesIO(data)) as image:
                if getattr(image, "n_frames", 1) == 1:
                    image.verify()
                    target = destination / f"ip_scan_{page_start:04d}.jpg"
                    target.write_bytes(data)
                    return [target]
        except (OSError, SyntaxError):
            pass

    source = destination / f"received_{page_start:04d}.img"
    source.write_bytes(data)
    try:
        with Image.open(source) as image:
            frame_count = getattr(image, "n_frames", 1)
            if page_start - 1 + frame_count > MAX_SCAN_PAGES:
                raise ESCLScannerError(f"A digitalização excedeu o limite de {MAX_SCAN_PAGES} páginas.")
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
    input_source: str = "Platen",
    paper_size: str = "Automático (área máxima)",
    use_ocr: bool = False,
    language: str = "por+eng",
    app_dir: str | Path | None = None,
    ask_next_page: Callable[[int], bool] | None = None,
    output_format: str = "PDF",
    filename_prefix: str = "Scan",
    remove_blank_pages: bool = False,
    auto_deskew: bool = False,
    auto_orient: bool = False,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path | list[Path]:
    base = _base_url(ip_address, port, protocol)
    report(progress_callback, "Aquecendo e conectando ao scanner de rede...")
    check_cancel(cancel_event)
    # O diálogo já consultou as capacidades e validou o equipamento. Criar o
    # trabalho abaixo confirma novamente a conexão sem repetir essa consulta.
    with tempfile.TemporaryDirectory(prefix="pdf_scanner_ip_") as temp:
        directory = Path(temp)
        images: list[Path] = []
        scanned_pages = 0
        if input_source in {"Feeder", "FeederDuplex"}:
            opener, job_url = _create_scan_job(
                base, protocol, dpi, color_mode, input_source, paper_size, timeout=180
            )
            try:
                while scanned_pages < MAX_SCAN_PAGES:
                    check_cancel(cancel_event)
                    report(progress_callback, f"Digitalizando página {scanned_pages + 1}...")
                    document = _next_document(opener, job_url, timeout=180, allow_end=True)
                    if document is None:
                        break
                    data, content_type = document
                    new_images = _document_to_images(data, content_type, directory, scanned_pages + 1, dpi)
                    images.extend(new_images)
                    scanned_pages += len(new_images)
            finally:
                _release_scan_job(opener, job_url)
        else:
            while True:
                check_cancel(cancel_event)
                report(progress_callback, f"Digitalizando página {scanned_pages + 1}...")
                opener, job_url = _create_scan_job(
                    base, protocol, dpi, color_mode, input_source, paper_size, timeout=180
                )
                try:
                    document = _next_document(opener, job_url, timeout=180)
                    if document is None:
                        break
                    data, content_type = document
                    new_images = _document_to_images(data, content_type, directory, scanned_pages + 1, dpi)
                    images.extend(new_images)
                    scanned_pages += len(new_images)
                finally:
                    _release_scan_job(opener, job_url)
                if ask_next_page is None or not ask_next_page(scanned_pages):
                    break
        if not images:
            raise ESCLScannerError("Nenhuma página foi recebida da multifuncional.")
        check_cancel(cancel_event)
        report(progress_callback, "Corrigindo e analisando as páginas...")
        images = prepare_scanned_images(
            images,
            remove_blank_pages=remove_blank_pages,
            auto_deskew=auto_deskew,
            auto_orient=auto_orient,
            app_dir=app_dir,
        )
        if output_format.upper() == "JPG":
            report(progress_callback, "Salvando arquivos JPG...")
            return save_images_as_jpg(images, output_pdf, filename_prefix)
        if use_ocr:
            report(progress_callback, "Aplicando OCR...")
            return images_to_searchable_pdf(
                images, output_pdf, language, app_dir,
                cancel_event=cancel_event, progress_callback=progress_callback,
            )
        report(progress_callback, "Montando o PDF...")
        return images_to_pdf(images, output_pdf)
