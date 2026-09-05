from __future__ import annotations

import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ocr import images_to_searchable_pdf
from .pdf_tools import images_to_pdf, save_images_as_jpg
from .scan_processing import prepare_scanned_images
from .progress import ProgressCallback, check_cancel, report
from .scan_options import PAPER_SIZES_MM, paper_size_pixels


class ScannerError(RuntimeError):
    pass


WIA_SCANNER_DEVICE_TYPE = 1
WIA_FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"


@dataclass(frozen=True)
class ScannerDevice:
    device_id: str
    name: str
    connection_type: str
    sources: tuple[str, ...] = ("Vidro",)
    serial_number: str = ""

    @property
    def display_name(self) -> str:
        serial = f" — Série: {self.serial_number}" if self.serial_number else ""
        return f"[{self.connection_type}] {self.name}{serial}"


def _serial_from_wia_properties(properties) -> str:
    """Extrai somente um número de série explicitamente informado pelo driver."""
    try:
        for prop in properties:
            name = unicodedata.normalize("NFKD", str(getattr(prop, "Name", "")))
            normalized_name = "".join(character for character in name if not unicodedata.combining(character)).casefold()
            if "serial" not in normalized_name and "serie" not in normalized_name:
                continue
            value = str(getattr(prop, "Value", "")).strip()
            if value and value.casefold() not in {"0", "unknown", "desconhecido", "n/a", "none"}:
                return value
    except Exception:
        pass
    return ""


def _win32_client():
    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise ScannerError("O componente WIA requer Windows e o pacote pywin32.") from exc
    return win32com.client


def list_scanners() -> list[ScannerDevice]:
    client = _win32_client()
    manager = client.Dispatch("WIA.DeviceManager")
    devices: list[ScannerDevice] = []
    for info in manager.DeviceInfos:
        if int(info.Type) != WIA_SCANNER_DEVICE_TYPE:
            continue
        name = str(info.Properties("Name").Value)
        device_id = str(info.DeviceID)
        details = [device_id, name]
        serial_number = _serial_from_wia_properties(info.Properties)
        try:
            details.extend(str(prop.Value) for prop in info.Properties)
        except Exception:
            pass
        connection_type = _detect_connection_type(" ".join(details))
        sources = ("Vidro",)
        try:
            device = info.Connect()
            if not serial_number:
                serial_number = _serial_from_wia_properties(device.Properties)
            capabilities = _property(device, 3086)
            if capabilities is not None:
                sources = _sources_from_wia_capabilities(int(capabilities.Value))
        except Exception:
            pass
        devices.append(ScannerDevice(device_id, name, connection_type, sources, serial_number))
    return devices


def filter_direct_scanners(devices: list[ScannerDevice]) -> list[ScannerDevice]:
    """Exclui dispositivos que o WIA identificou explicitamente como rede."""
    return [device for device in devices if device.connection_type != "Rede"]


def _detect_connection_type(details: str) -> str:
    value = details.upper().replace("Í", "I")
    network_hints = ("WSD", "TCPIP", "TCP/IP", "NETWORK", "REDE", "WI-FI", "WIFI", "ETHERNET", "WIAIP")
    usb_hints = ("USB\\", "\\USB", "VID_", "USBSCAN", "USB ")
    if any(hint in value for hint in network_hints):
        return "Rede"
    if any(hint in value for hint in usb_hints):
        return "USB / conectado"
    return "Instalado no Windows"


def _sources_from_wia_capabilities(capabilities: int) -> tuple[str, ...]:
    sources: list[str] = []
    if capabilities & 2:  # WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES: FLAT
        sources.append("Vidro")
    if capabilities & 1:  # WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES: FEED
        sources.append("Alimentador superior - somente frente")
        if capabilities & 4:  # DUP
            sources.append("Alimentador superior - frente e verso")
    return tuple(sources) or ("Vidro",)


def _property(item, property_id: int):
    for prop in item.Properties:
        if int(prop.PropertyID) == property_id:
            return prop
    return None


def _set_property(item, property_id: int, value: int) -> None:
    prop = _property(item, property_id)
    if prop is not None:
        try:
            prop.Value = value
        except Exception:
            pass


def scan_to_pdf(
    device_id: str,
    output_pdf: str | Path,
    *,
    dpi: int = 300,
    color_mode: str = "Cor",
    input_source: str = "Vidro",
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
    if dpi not in (150, 200, 300, 400, 600):
        raise ScannerError("Resolução inválida.")
    client = _win32_client()
    report(progress_callback, "Aquecendo e conectando ao scanner...")
    check_cancel(cancel_event)
    manager = client.Dispatch("WIA.DeviceManager")
    selected = None
    for info in manager.DeviceInfos:
        if str(info.DeviceID) == device_id:
            selected = info
            break
    if selected is None:
        raise ScannerError("O scanner selecionado não está mais disponível.")

    color_codes = {"Cor": 1, "Cinza": 2, "Preto e branco": 4}
    source_codes = {
        "Vidro": 2,
        "Alimentador superior - somente frente": 1,
        "Alimentador superior - frente e verso": 1 | 4,
    }
    if input_source not in source_codes:
        raise ScannerError("Origem de digitalização inválida.")
    if paper_size not in PAPER_SIZES_MM:
        raise ScannerError("Tamanho de papel inválido.")
    with tempfile.TemporaryDirectory(prefix="central_pdf_scan_") as temp:
        images: list[Path] = []
        page_number = 1
        feeder = input_source != "Vidro"
        device = selected.Connect()
        _set_property(device, 3088, source_codes[input_source])
        while True:
            check_cancel(cancel_event)
            report(progress_callback, f"Digitalizando página {page_number}...")
            item = device.Items(1)
            _set_property(item, 6146, color_codes.get(color_mode, 1))
            _set_property(item, 6147, dpi)
            _set_property(item, 6148, dpi)
            dimensions = paper_size_pixels(paper_size, dpi)
            if dimensions is not None:
                width, height = dimensions
                _set_property(item, 3097, 0)  # WIA_PAGE_CUSTOM
                _set_property(item, 6149, 0)  # WIA_IPS_XPOS
                _set_property(item, 6150, 0)  # WIA_IPS_YPOS
                _set_property(item, 6151, width)  # WIA_IPS_XEXTENT
                _set_property(item, 6152, height)  # WIA_IPS_YEXTENT
            try:
                image = item.Transfer(WIA_FORMAT_JPEG)
            except Exception as exc:
                if feeder and images:
                    break
                raise ScannerError(
                    "Não foi possível digitalizar. Se escolheu o alimentador, coloque as folhas na bandeja. "
                    "Confirme também se o scanner WIA está instalado e acessível."
                ) from exc
            path = Path(temp) / f"scan_{page_number:04d}.jpg"
            image.SaveFile(str(path))
            images.append(path)
            check_cancel(cancel_event)
            if feeder:
                page_number += 1
                if page_number > 1000:
                    break
                continue
            if ask_next_page is None or not ask_next_page(page_number):
                break
            page_number += 1

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
