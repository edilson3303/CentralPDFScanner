from __future__ import annotations

import platform
import sys
from datetime import datetime
from pathlib import Path

from .escl_scanner import detect_escl_details
from .ocr import find_tesseract
from .scanner import list_scanners


def build_scanner_diagnostic(version: str, app_dir: str | Path, network_ip: str = "") -> str:
    """Gera diagnóstico técnico sem ler ou transmitir documentos do usuário."""
    lines = [
        "DIAGNÓSTICO — PDF & SCANNER",
        f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Versão do software: {version}",
        f"Windows/Sistema: {platform.platform()}",
        f"Arquitetura: {platform.machine()}",
        f"Python interno: {sys.version.split()[0]}",
        f"OCR Tesseract: {find_tesseract(app_dir) or 'não encontrado'}",
        "",
        "SCANNERS INSTALADOS NO WINDOWS",
    ]
    try:
        devices = list_scanners()
        if not devices:
            lines.append("Nenhum scanner WIA encontrado.")
        for index, device in enumerate(devices, 1):
            lines.extend([
                f"{index}. {device.name}",
                f"   Conexão: {device.connection_type}",
                f"   Série: {device.serial_number or 'não informado'}",
                f"   Origens: {', '.join(device.sources)}",
            ])
    except Exception as exc:
        lines.append(f"Falha ao consultar WIA: {type(exc).__name__}: {exc}")
    lines.extend(["", "SCANNER DE REDE"])
    if not network_ip:
        lines.append("Nenhum IP salvo para testar.")
    else:
        lines.append(f"IP testado: {network_ip}")
        try:
            model, serial, sources = detect_escl_details(network_ip, 80, "http", timeout=10)
            lines.extend([
                "eSCL/AirScan: acessível",
                f"Modelo: {model}",
                f"Série: {serial or 'não informada'}",
                f"Origens: {', '.join(sources)}",
            ])
        except Exception as exc:
            lines.append(f"eSCL/AirScan: falha — {type(exc).__name__}: {exc}")
    lines.extend(["", "Este relatório não contém imagens nem conteúdo dos documentos digitalizados."])
    return "\n".join(lines)
