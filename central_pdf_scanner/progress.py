from __future__ import annotations

from threading import Event
from typing import Callable


ProgressCallback = Callable[[str], None]


class OperationCancelled(RuntimeError):
    """Interrupção solicitada pelo usuário, sem indicar falha do documento."""


def report(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def check_cancel(event: Event | None) -> None:
    if event is not None and event.is_set():
        raise OperationCancelled("Operação cancelada pelo usuário.")
