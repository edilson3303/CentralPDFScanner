from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ocr import images_to_searchable_pdf
from .pdf_tools import images_to_pdf, save_images_as_jpg


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

    @property
    def display_name(self) -> str:
        return f"[{self.connection_type}] {self.name}"


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
        try:
            details.extend(str(prop.Value) for prop in info.Properties)
        except Exception:
            pass
        connection_type = _detect_connection_type(" ".join(details))
        sources = ("Vidro",)
        try:
            device = info.Connect()
            capabilities = _property(device, 3086)
            if capabilities is not None:
                sources = _sources_from_wia_capabilities(int(capabilities.Value))
        except Exception:
            pass
        devices.append(ScannerDevice(device_id, name, connection_type, sources))
    return devices


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
    use_ocr: bool = False,
    language: str = "por+eng",
    app_dir: str | Path | None = None,
    ask_next_page: Callable[[int], bool] | None = None,
    output_format: str = "PDF",
    filename_prefix: str = "Scan",
) -> Path | list[Path]:
    if dpi not in (150, 200, 300, 400, 600):
        raise ScannerError("Resolução inválida.")
    client = _win32_client()
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
    with tempfile.TemporaryDirectory(prefix="central_pdf_scan_") as temp:
        images: list[Path] = []
        page_number = 1
        feeder = input_source != "Vidro"
        device = selected.Connect()
        _set_property(device, 3088, source_codes[input_source])
        while True:
            item = device.Items(1)
            _set_property(item, 6146, color_codes.get(color_mode, 1))
            _set_property(item, 6147, dpi)
            _set_property(item, 6148, dpi)
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
            if feeder:
                page_number += 1
                if page_number > 1000:
                    break
                continue
            if ask_next_page is None or not ask_next_page(page_number):
                break
            page_number += 1

        if output_format.upper() == "JPG":
            return save_images_as_jpg(images, output_pdf, filename_prefix)
        if use_ocr:
            return images_to_searchable_pdf(images, output_pdf, language, app_dir)
        return images_to_pdf(images, output_pdf)
