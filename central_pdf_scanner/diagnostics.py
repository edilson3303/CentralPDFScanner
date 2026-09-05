from __future__ import annotations

from datetime import datetime
from pathlib import Path
from collections.abc import Sequence

from .escl_scanner import detect_escl_details
from .ocr import find_tesseract
from .scanner import list_scanners


def build_scanner_diagnostic(
    version: str,
    app_dir: str | Path,
    network_scanners: Sequence[dict[str, str]] | str = (),
) -> str:
    """Gera diagnóstico técnico sem ler ou transmitir documentos do usuário."""
    lines = [
        "DIAGNÓSTICO — PDF & SCANNER",
        f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Versão do software: {version}",
        f"OCR: {'disponível' if find_tesseract(app_dir) else 'não disponível'}",
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
    if isinstance(network_scanners, str):
        scanners = ([{"nome": "Scanner de rede 1", "ip": network_scanners}]
                    if network_scanners else [])
    else:
        scanners = [item for item in network_scanners if isinstance(item, dict)]
    lines.extend(["", "SCANNERS DE REDE CADASTRADOS"])
    if not scanners:
        lines.append("Nenhum scanner de rede cadastrado para testar.")
    for index, scanner in enumerate(scanners, 1):
        name = str(scanner.get("nome", "")).strip() or f"Scanner de rede {index}"
        network_ip = str(scanner.get("ip", "")).strip()
        lines.append(f"{index}. {name}")
        try:
            model, serial, sources = detect_escl_details(network_ip, 80, "http", timeout=10)
            lines.extend([
                "   eSCL/AirScan: acessível",
                f"   Modelo: {model}",
                f"   Série: {serial or 'não informada'}",
                f"   Origens: {', '.join(sources)}",
            ])
        except Exception as exc:
            lines.append(f"   eSCL/AirScan: falha — {type(exc).__name__}: {exc}")
    lines.extend(["", "Este relatório não contém imagens nem conteúdo dos documentos digitalizados."])
    return "\n".join(lines)
