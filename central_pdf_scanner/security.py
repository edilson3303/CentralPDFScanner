from __future__ import annotations

import ctypes
import os
import re
import sys
from pathlib import Path


LOCAL_ADMINISTRATORS_SID = "S-1-5-32-544"
AD_ADMINISTRATIVE_RIDS = {"512", "518", "519"}


def is_administrative_sid(value: str) -> bool:
    """Reconhece Administradores locais e grupos administrativos do AD."""
    sid = value.strip().upper()
    if sid == LOCAL_ADMINISTRATORS_SID:
        return True
    match = re.fullmatch(r"S-1-5-21-(?:\d+-){3}(\d+)", sid)
    return bool(match and match.group(1) in AD_ADMINISTRATIVE_RIDS)


def current_group_sids() -> tuple[str, ...]:
    if sys.platform != "win32":
        return ()
    try:
        import win32api  # type: ignore
        import win32con  # type: ignore
        import win32security  # type: ignore

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        groups = win32security.GetTokenInformation(token, win32security.TokenGroups)
        return tuple(win32security.ConvertSidToStringSid(group[0]) for group in groups)
    except (ImportError, OSError):
        return ()


def is_windows_administrator() -> bool:
    """Verifica associação administrativa, mesmo com o token filtrado pelo UAC."""
    if sys.platform != "win32":
        return False
    if any(is_administrative_sid(sid) for sid in current_group_sids()):
        return True
    return is_process_elevated()


def is_process_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def launch_elevated_mode(mode: str) -> bool:
    """Abre uma área administrativa em um processo elevado pelo UAC."""
    if sys.platform != "win32":
        return False
    if mode not in {"--configuracoes", "--historico"}:
        return False
    executable = str(Path(sys.executable).resolve())
    if getattr(sys, "frozen", False):
        parameters = mode
    else:
        script = str(Path(sys.argv[0]).resolve())
        parameters = f'"{script}" {mode}'
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, parameters, os.getcwd(), 1
        )
        return int(result) > 32
    except (AttributeError, OSError, ValueError):
        return False


def launch_elevated_settings() -> bool:
    """Abre somente as configurações em um processo elevado pelo UAC."""
    return launch_elevated_mode("--configuracoes")


def launch_elevated_history() -> bool:
    """Abre somente o histórico em um processo elevado pelo UAC."""
    return launch_elevated_mode("--historico")
