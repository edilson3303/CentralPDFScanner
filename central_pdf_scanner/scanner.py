from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ocr import images_to_searchable_pdf
from .pdf_tools import images_to_pdf


class ScannerError(RuntimeError):
    pass


WIA_SCANNER_DEVICE_TYPE = 1
WIA_FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"


@dataclass(frozen=True)
class ScannerDevice:
    device_id: str
    name: str


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
        devices.append(ScannerDevice(str(info.DeviceID), name))
    return devices


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
    use_ocr: bool = False,
    language: str = "por+eng",
    app_dir: str | Path | None = None,
    ask_next_page: Callable[[int], bool] | None = None,
) -> Path:
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
    with tempfile.TemporaryDirectory(prefix="central_pdf_scan_") as temp:
        images: list[Path] = []
        page_number = 1
        while True:
            device = selected.Connect()
            item = device.Items(1)
            _set_property(item, 6146, color_codes.get(color_mode, 1))
            _set_property(item, 6147, dpi)
            _set_property(item, 6148, dpi)
            try:
                image = item.Transfer(WIA_FORMAT_JPEG)
            except Exception as exc:
                raise ScannerError(
                    "Não foi possível digitalizar. Confirme se a multifuncional está instalada "
                    "no Windows como scanner WIA e se está acessível na rede."
                ) from exc
            path = Path(temp) / f"scan_{page_number:04d}.jpg"
            image.SaveFile(str(path))
            images.append(path)
            if ask_next_page is None or not ask_next_page(page_number):
                break
            page_number += 1

        if use_ocr:
            return images_to_searchable_pdf(images, output_pdf, language, app_dir)
        return images_to_pdf(images, output_pdf)

