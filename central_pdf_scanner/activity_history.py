from __future__ import annotations

import csv
import getpass
import json
import platform
import threading
from datetime import datetime
from pathlib import Path


_LOCK = threading.Lock()
MAX_HISTORY_RECORDS = 2000


def history_file(directory: str | Path) -> Path:
    return Path(directory) / "historico_operacoes.jsonl"


def record_operation(
    directory: str | Path,
    operation: str,
    status: str,
    version: str,
    detail: str = "",
) -> None:
    """Registra somente metadados operacionais, nunca nomes ou conteúdo de arquivos."""
    record = {
        "data_hora": datetime.now().astimezone().isoformat(timespec="seconds"),
        "operacao": str(operation).strip()[:180],
        "status": str(status).strip()[:40],
        "usuario": getpass.getuser()[:120],
        "computador": platform.node()[:120],
        "versao": version[:40],
        "detalhe": str(detail).replace("\r", " ").replace("\n", " ")[:300],
    }
    target = history_file(directory)
    with _LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        lines = target.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_HISTORY_RECORDS:
            temporary = target.with_suffix(".tmp")
            temporary.write_text("\n".join(lines[-MAX_HISTORY_RECORDS:]) + "\n", encoding="utf-8")
            temporary.replace(target)


def load_history(directory: str | Path, limit: int = 500) -> list[dict[str, str]]:
    target = history_file(directory)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, str]] = []
    for line in lines[-max(1, limit):]:
        try:
            value = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records.append({key: str(item) for key, item in value.items()})
    return list(reversed(records))


def export_history_csv(records: list[dict[str, str]], destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = ("data_hora", "operacao", "status", "usuario", "computador", "versao", "detalhe")
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return target
