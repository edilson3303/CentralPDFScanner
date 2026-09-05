from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path


def _machine_identity() -> str:
    raw = ""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                raw = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except (OSError, AttributeError):
            pass
    raw = raw or platform.node() or os.environ.get("COMPUTERNAME", "computador-desconhecido")
    return hashlib.sha256(f"ALAP-PDF-SCANNER|{raw}".encode("utf-8")).hexdigest()


def register_installation(directory: str | Path, version: str) -> Path | None:
    """Atualiza o registro deste computador em uma pasta compartilhada interna."""
    folder = Path(str(directory).strip())
    if not str(directory).strip():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    identifier = _machine_identity()
    target = folder / f"{identifier}.json"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    first_seen = now
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            first_seen = str(existing.get("primeiro_uso", now))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    record = {
        "id": identifier,
        "computador": platform.node() or os.environ.get("COMPUTERNAME", "não informado"),
        "versao": version,
        "primeiro_uso": first_seen,
        "ultimo_uso": now,
    }
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def list_installations(directory: str | Path) -> list[dict[str, str]]:
    folder = Path(str(directory).strip())
    if not str(directory).strip() or not folder.is_dir():
        return []
    records: list[dict[str, str]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or not value.get("id"):
            continue
        records.append({key: str(item) for key, item in value.items()})
    return sorted(records, key=lambda item: item.get("computador", "").casefold())
