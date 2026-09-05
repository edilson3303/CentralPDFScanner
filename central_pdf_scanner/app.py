from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageTk

from . import __version__
from .diagnostics import build_scanner_diagnostic
from .advanced_pdf import compact_pdf, convert_pdf_to_pdfa, separate_pdf_batch
from .activity_history import export_history_csv, load_history, record_operation
from .escl_scanner import ESCLScannerError, detect_escl_details, scan_escl_to_pdf, validate_ip_settings
from .ocr import find_tesseract, pdf_to_searchable_pdf
from .pdf_tools import (
    compose_scanned_pdf,
    crop_pdf,
    images_to_pdf,
    merge_pdfs,
    merge_pdf_pages,
    pdf_to_jpg,
    protect_pdf,
    remove_pages,
    rotate_pages,
    save_preview_images_as_jpg,
    split_pdf,
    trim_vertical_pdf,
    unprotect_pdf,
)
from .scanner import filter_direct_scanners, list_scanners, scan_to_pdf
from .scan_options import PAPER_SIZES_MM
from .progress import OperationCancelled
from .privacy_tools import redact_pdf
from .security import is_process_elevated, is_windows_administrator, launch_elevated_settings
from .word_tools import pdf_to_word, word_to_pdf
from .thumbnail_dialogs import MergePagesDialog, PageSelectionDialog, RedactionDialog, ScanPreviewDialog


APP_TITLE = "PDF & Scanner"
PDF_TYPES = [("Arquivo PDF", "*.pdf")]
WORD_TYPES = [("Documento Word", "*.docx")]
IMAGE_TYPES = [("Imagens", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff")]
OCR_LANGUAGES = {
    "Português": "por",
    "Português + Inglês": "por+eng",
    "Inglês": "eng",
}
DEFAULT_SCAN_PROFILES = {
    "Documento padrão": {
        "dpi": "300", "color": "Cor", "output_format": "PDF", "use_ocr": False,
        "language": "Português + Inglês", "remove_blank": False, "auto_deskew": False,
        "auto_orient": False, "source": "", "paper_size": "Automático (área máxima)",
    },
    "Documento colorido": {
        "dpi": "300", "color": "Cor", "output_format": "PDF", "use_ocr": False,
        "language": "Português + Inglês", "remove_blank": False, "auto_deskew": False,
        "auto_orient": False, "source": "", "paper_size": "Automático (área máxima)",
    },
    "Frente e verso": {
        "dpi": "300", "color": "Cor", "output_format": "PDF", "use_ocr": False,
        "language": "Português + Inglês", "remove_blank": False, "auto_deskew": False,
        "auto_orient": False, "source": "Alimentador superior - frente e verso", "paper_size": "A4 (210 × 297 mm)",
    },
    "OCR pesquisável": {
        "dpi": "300", "color": "Cor", "output_format": "PDF", "use_ocr": True,
        "language": "Português + Inglês", "remove_blank": False, "auto_deskew": False,
        "auto_orient": False, "source": "", "paper_size": "Automático (área máxima)",
    },
}
DEFAULT_OUTPUT_SETTINGS = {
    "pasta_saida": "",
    "modelo_nome": "Scan_{serie}_{data}_{hora}_{setor}",
    "setor": "",
    "salvar_automaticamente": False,
}


def _safe_filename(value: str, fallback: str = "") -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" ._")
    safe = re.sub(r"\s+", "_", safe)
    return safe or fallback


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "bytes" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} GB"


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for number in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError("Não foi possível criar um nome de arquivo livre na pasta escolhida.")


def _load_output_settings() -> dict:
    result = dict(DEFAULT_OUTPUT_SETTINGS)
    saved = _read_machine_settings().get("saida_digitalizacao", {})
    if not isinstance(saved, dict) or not saved:
        # Migra, na primeira configuração administrativa, os valores das
        # versões que armazenavam essas opções por usuário.
        saved = _read_settings().get("saida_digitalizacao", {})
    if isinstance(saved, dict):
        result.update({key: saved[key] for key in result if key in saved})
    # Migra silenciosamente o antigo modelo padrão, sem alterar modelos
    # personalizados pelo administrador.
    if result.get("modelo_nome") == "Scan_{serie}_{data}_{hora}":
        result["modelo_nome"] = DEFAULT_OUTPUT_SETTINGS["modelo_nome"]
    return result


def _configuration_payload(
    output_settings: dict,
    scanners: list[dict[str, str]],
) -> dict:
    return {
        "formato": "PDFScannerALAP-config",
        "versao_schema": 1,
        "scanners_rede": scanners,
        "saida_digitalizacao": output_settings,
    }


def _validate_configuration_payload(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("formato") != "PDFScannerALAP-config":
        raise ValueError("O arquivo não é uma configuração válida do PDF & Scanner.")
    if payload.get("versao_schema") != 1:
        raise ValueError("A versão deste arquivo de configuração não é compatível.")
    raw_scanners = payload.get("scanners_rede", [])
    if not isinstance(raw_scanners, list) or len(raw_scanners) > 100:
        raise ValueError("A lista de scanners do arquivo é inválida.")
    scanners: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_scanners:
        if not isinstance(item, dict):
            raise ValueError("Há um scanner inválido no arquivo.")
        name = str(item.get("nome", "")).strip()
        if not name or len(name) > 160:
            raise ValueError("Há um nome de scanner inválido no arquivo.")
        address, _, _ = validate_ip_settings(str(item.get("ip", "")), 80, "http")
        if address in seen:
            raise ValueError("O arquivo contém endereços IP duplicados.")
        seen.add(address)
        scanners.append({"nome": name, "ip": address})
    raw_output = payload.get("saida_digitalizacao", {})
    if not isinstance(raw_output, dict):
        raise ValueError("As opções de saída do arquivo são inválidas.")
    output = dict(DEFAULT_OUTPUT_SETTINGS)
    output.update({key: raw_output[key] for key in output if key in raw_output})
    if not isinstance(output["pasta_saida"], str) or not isinstance(output["setor"], str):
        raise ValueError("As opções de saída do arquivo são inválidas.")
    if not isinstance(output["modelo_nome"], str):
        raise ValueError("O modelo de nome do arquivo é inválido.")
    if not isinstance(output["salvar_automaticamente"], bool):
        raise ValueError("A opção de salvamento automático é inválida.")
    output["pasta_saida"] = output["pasta_saida"].strip()
    output["setor"] = output["setor"].strip()[:160]
    template = output["modelo_nome"].strip()
    fields = set(re.findall(r"\{([^{}]+)\}", template))
    if not template or fields.difference({"serie", "data", "hora", "setor"}):
        raise ValueError("O modelo de nome do arquivo é inválido.")
    try:
        template.format(serie="SERIE", data="2026-09-05", hora="12-30-00", setor="SETOR")
    except (KeyError, ValueError) as exc:
        raise ValueError("O modelo de nome do arquivo é inválido.") from exc
    output["modelo_nome"] = template
    return _configuration_payload(output, scanners)


def default_scan_basename(serial_number: str, settings: dict | None = None) -> str:
    values = settings or _load_output_settings()
    now = datetime.now()
    fields = {
        "serie": _safe_filename(serial_number, "SEM_NUMERO_DE_SERIE"),
        "data": now.strftime("%Y-%m-%d"),
        "hora": now.strftime("%H-%M-%S"),
        "setor": _safe_filename(str(values.get("setor", "")), "SEM_SETOR"),
    }
    template = str(values.get("modelo_nome", DEFAULT_OUTPUT_SETTINGS["modelo_nome"]))
    try:
        return _safe_filename(template.format(**fields), f"Scan_{fields['serie']}_{fields['data']}_{fields['hora']}_{fields['setor']}")
    except (KeyError, ValueError):
        return f"Scan_{fields['serie']}_{fields['data']}_{fields['hora']}_{fields['setor']}"

def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def settings_directory() -> Path:
    """Retorna uma pasta gravável para as preferências do usuário."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "ALAP" / "PDFScanner"
    return app_directory()


def machine_settings_directory() -> Path:
    """Pasta comum, gravável por administradores e legível pelos usuários."""
    if sys.platform == "win32":
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(program_data) / "ALAP" / "PDFScanner"
    return app_directory() / "configuracao_sistema"


def resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return app_directory() / relative


def _apply_native_windows_icon(window: tk.Misc, ico_icon: Path) -> None:
    """Força os ícones pequeno e grande da janela já criada pelo Windows."""
    if sys.platform != "win32" or not ico_icon.is_file():
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = (
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        )
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        user32.SendMessageW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        )
        user32.SendMessageW.restype = ctypes.c_ssize_t

        load_from_file = 0x0010 | 0x8000  # LR_LOADFROMFILE | LR_SHARED
        image_icon = 1
        hwnd = user32.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
        large = user32.LoadImageW(None, str(ico_icon), image_icon, 32, 32, load_from_file)
        small = user32.LoadImageW(None, str(ico_icon), image_icon, 16, 16, load_from_file)
        if large:
            user32.SendMessageW(hwnd, 0x0080, 1, large)  # WM_SETICON / ICON_BIG
        if small:
            user32.SendMessageW(hwnd, 0x0080, 0, small)  # WM_SETICON / ICON_SMALL
        window._native_icon_handles = (large, small)  # type: ignore[attr-defined]
    except (AttributeError, OSError, TypeError, ValueError):
        pass


def _apply_window_icon(window: tk.Misc) -> None:
    """Aplica o ícone do produto pelo Tk e pela API nativa do Windows."""
    png_icon = resource_path("assets/pdf_scanner_multifuncional_v282.png")
    ico_icon = resource_path("assets/pdf_scanner_multifuncional_v282.ico")
    try:
        if png_icon.is_file():
            photo = tk.PhotoImage(file=str(png_icon))
            window._window_icon = photo  # type: ignore[attr-defined]
            window.iconphoto(True, photo)  # type: ignore[attr-defined]
    except tk.TclError:
        pass
    try:
        if sys.platform == "win32" and ico_icon.is_file():
            window.iconbitmap(str(ico_icon))  # type: ignore[attr-defined]
    except tk.TclError:
        pass
    _apply_native_windows_icon(window, ico_icon)


def _read_settings() -> dict:
    try:
        value = json.loads((settings_directory() / "configuracao.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _write_settings(data: dict) -> None:
    directory = settings_directory()
    target = directory / "configuracao.json"
    temporary = target.with_suffix(".tmp")
    directory.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def _read_machine_settings() -> dict:
    try:
        value = json.loads((machine_settings_directory() / "configuracao.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _write_machine_settings(data: dict) -> None:
    directory = machine_settings_directory()
    target = directory / "configuracao.json"
    temporary = target.with_suffix(".tmp")
    directory.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def _load_network_scanners() -> list[dict[str, str]]:
    scanners: list[dict[str, str]] = []
    raw = _read_machine_settings().get("scanners_rede", [])
    if isinstance(raw, list):
        for index, item in enumerate(raw, 1):
            if not isinstance(item, dict):
                continue
            try:
                address, _, _ = validate_ip_settings(str(item.get("ip", "")), 80, "http")
            except ESCLScannerError:
                continue
            name = str(item.get("nome", "")).strip() or f"Scanner de rede {index}"
            scanners.append({"nome": name, "ip": address})
    return scanners


def _load_last_scanner_ip() -> str:
    scanners = _load_network_scanners()
    if not scanners:
        return ""
    preferred = str(_read_settings().get("ultimo_scanner_rede", ""))
    return preferred if any(item["ip"] == preferred for item in scanners) else scanners[0]["ip"]


def _save_last_scanner_ip(ip_address: str) -> None:
    try:
        if not any(item["ip"] == ip_address for item in _load_network_scanners()):
            return
        data = _read_settings()
        data["ultimo_scanner_rede"] = ip_address
        _write_settings(data)
    except OSError:
        pass


def _load_scan_profiles() -> dict[str, dict]:
    profiles = {name: dict(values) for name, values in DEFAULT_SCAN_PROFILES.items()}
    custom = _read_settings().get("perfis_digitalizacao", {})
    if isinstance(custom, dict):
        for name, values in custom.items():
            if isinstance(name, str) and isinstance(values, dict):
                profiles[name] = values
    return profiles


def _save_scan_profile(name: str, values: dict) -> None:
    data = _read_settings()
    profiles = data.setdefault("perfis_digitalizacao", {})
    if not isinstance(profiles, dict):
        profiles = {}
        data["perfis_digitalizacao"] = profiles
    profiles[name] = values
    _write_settings(data)


def _delete_scan_profile(name: str) -> bool:
    if name in DEFAULT_SCAN_PROFILES:
        return False
    data = _read_settings()
    profiles = data.get("perfis_digitalizacao", {})
    if isinstance(profiles, dict) and name in profiles:
        del profiles[name]
        _write_settings(data)
        return True
    return False


class CentralApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self._configure_window_icon()
        self.title(f"{APP_TITLE} {__version__}")
        self.minsize(820, 680)
        self.configure(bg="#f4f7fb")
        self._results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self._success_callback = None
        self._error_callback = None
        self._cancel_event: threading.Event | None = None
        self._operation_label = ""
        self._configure_style()
        self._build_ui()
        self._center_main_window()
        self.deiconify()
        # O Windows cria o HWND definitivo ao exibir a janela. Reaplicamos o
        # ícone depois desse momento para impedir o ícone genérico do Tk.
        self.after_idle(self._configure_window_icon)
        self.after(250, self._configure_window_icon)
        self.after(100, self._poll_results)

    def _center_main_window(self) -> None:
        """Abre a janela principal centralizada e ajustada à tela disponível."""
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(1040, max(820, screen_width - 40))
        height = min(780, max(680, screen_height - 80))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _configure_window_icon(self) -> None:
        """Usa o mesmo ícone na janela, nos diálogos e na barra de tarefas."""
        _apply_window_icon(self)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f4f7fb")
        style.configure("Header.TFrame", background="#173b67")
        style.configure("Header.TLabel", background="white", foreground="#173b67", font=("Segoe UI", 23, "bold"))
        style.configure("Subtitle.TLabel", background="white", foreground="#476582", font=("Segoe UI", 10))
        style.configure("Card.TButton", font=("Segoe UI", 10, "bold"), padding=(13, 13))
        style.configure("Primary.Card.TButton", font=("Segoe UI", 11, "bold"), padding=(14, 16))
        style.configure("Section.TLabelframe", background="#f4f7fb", borderwidth=1, relief="solid")
        style.configure("Section.TLabelframe.Label", background="#f4f7fb", foreground="#173b67", font=("Segoe UI", 12, "bold"))
        style.configure("Status.TLabel", background="#e8eef6", foreground="#173b67", padding=(12, 9))

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg="white", padx=26, pady=15, highlightthickness=0)
        header.pack(fill="x")
        logo_path = resource_path("assets/logo_assembleia_legislativa_amapa.png")
        if logo_path.is_file():
            logo = Image.open(logo_path)
            logo.thumbnail((360, 85), Image.Resampling.LANCZOS)
            self._logo_photo = ImageTk.PhotoImage(logo)
            tk.Label(header, image=self._logo_photo, bg="white", bd=0).pack(side="left", anchor="w")
        title_block = tk.Frame(header, bg="white")
        title_block.pack(side="right", anchor="e", padx=(24, 0))
        ttk.Label(title_block, text=APP_TITLE, style="Header.TLabel").pack(anchor="e")
        ttk.Label(title_block, text="Digitalização, edição e conversão de documentos", style="Subtitle.TLabel").pack(anchor="e", pady=(3, 0))
        ttk.Label(title_block, text=f"Versão {__version__}", style="Subtitle.TLabel").pack(anchor="e", pady=(2, 0))
        tk.Frame(self, bg="#2f65ad", height=4).pack(fill="x")

        content = ttk.Frame(self, padding=(24, 18))
        content.pack(fill="both", expand=True)
        self._build_section(
            content,
            "Digitalização",
            [
                ("Scanner USB", self.scan),
                ("Scanner de rede", self.scan_by_ip),
                ("Testar scanner", self.diagnose_scanners),
            ],
            columns=3,
            primary=True,
        ).pack(fill="x", pady=(0, 12))
        self._build_section(
            content,
            "Edição de PDF",
            [
                ("Juntar PDFs", self.merge),
                ("Dividir PDF", self.divide),
                ("Proteger PDF", self.protect),
                ("Desproteger PDF", self.unprotect),
                ("Remover páginas", self.remove),
                ("Rotacionar páginas", self.rotate),
                ("Cortar páginas", self.trim),
                ("Compactar PDF", self.compress),
                ("Separar em lotes", self.separate_batch),
                ("Tarjar Informações", self.redact_information),
            ],
            columns=4,
        ).pack(fill="x", pady=(0, 12))
        self._build_section(
            content,
            "Conversões",
            [
                ("PDF para Word", self.to_word),
                ("Word para PDF", self.from_word),
                ("PDF para JPG", self.to_jpg),
                ("JPG para PDF", self.from_images),
                ("PDF Digitalizado para OCR", self.to_ocr),
                ("PDF/A (arquivamento)", self.to_pdfa),
            ],
            columns=4,
        ).pack(fill="x")

        footer = ttk.Frame(self, padding=(20, 0, 20, 18))
        footer.pack(fill="x")
        ttk.Button(footer, text="Licença", command=self.show_license).pack(side="left", padx=(0, 8))
        ttk.Button(footer, text="Manual", command=self.show_manual).pack(side="left", padx=(0, 8))
        ttk.Button(footer, text="Configurações", command=self.output_settings).pack(side="left", padx=(0, 8))
        self.cancel_button = ttk.Button(footer, text="Cancelar operação", command=self.cancel_operation, state="disabled")
        self.cancel_button.pack(side="right", padx=(10, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=150)
        self.progress.pack(side="right", padx=(10, 0))
        self.status = ttk.Label(footer, text="Pronto.", style="Status.TLabel")
        self.status.pack(side="left", fill="x", expand=True)

    def _build_section(self, parent, title: str, actions, *, columns: int, primary: bool = False):
        section = ttk.LabelFrame(parent, text=f"  {title}  ", style="Section.TLabelframe", padding=(12, 10))
        for column in range(columns):
            section.columnconfigure(column, weight=1, uniform=f"{title}-buttons")
        for index, (label, command) in enumerate(actions):
            if primary:
                button = tk.Button(
                    section, text=label, command=command, bg="#2f65ad", fg="white",
                    activebackground="#173b67", activeforeground="white", relief="flat",
                    font=("Segoe UI", 11, "bold"), padx=14, pady=14, cursor="hand2",
                )
            else:
                button = ttk.Button(section, text=label, command=command, style="Card.TButton")
            button.grid(
                row=index // columns,
                column=index % columns,
                sticky="nsew",
                padx=16 if primary else 5,
                pady=8 if primary else 5,
            )
        return section

    def _pick_pdf(self, title: str) -> str:
        return filedialog.askopenfilename(parent=self, title=title, filetypes=PDF_TYPES)

    def _save_pdf(self, title: str, suggested: str, initialdir: str = "") -> str:
        options = {
            "parent": self, "title": title, "defaultextension": ".pdf",
            "initialfile": suggested, "filetypes": PDF_TYPES,
        }
        if initialdir:
            options["initialdir"] = initialdir
        return filedialog.asksaveasfilename(**options)

    def _run(
        self, label: str, function, *args, on_success=None, on_error=None,
        cancellable: bool = False, **kwargs,
    ) -> None:
        if self._busy:
            messagebox.showinfo(APP_TITLE, "Aguarde a operação atual terminar.", parent=self)
            return
        self._busy = True
        self._operation_label = label.rstrip(".")
        self._success_callback = on_success
        self._error_callback = on_error
        self._cancel_event = threading.Event() if cancellable else None
        if cancellable:
            kwargs["cancel_event"] = self._cancel_event
            kwargs["progress_callback"] = lambda message: self._results.put(("progress", message))
            self.cancel_button.configure(state="normal")
        else:
            self.cancel_button.configure(state="disabled")
        self.status.configure(text=label)
        self.progress.start(12)

        def worker() -> None:
            try:
                result = function(*args, **kwargs)
                self._results.put(("ok", result))
            except Exception as exc:
                if isinstance(exc, OperationCancelled):
                    self._results.put(("cancelled", str(exc)))
                    return
                details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                self._results.put(("error", details))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self) -> None:
        try:
            kind, payload = self._results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_results)
            return
        if kind == "progress":
            self.status.configure(text=str(payload))
            self.after(100, self._poll_results)
            return
        self._busy = False
        self.progress.stop()
        self.cancel_button.configure(state="disabled")
        self._cancel_event = None
        if kind == "ok":
            self._record_history("Concluída")
            self.status.configure(text="Operação concluída com sucesso.")
            callback = self._success_callback
            self._success_callback = None
            self._error_callback = None
            if callback is not None:
                callback(payload)
            else:
                self._show_result(payload)
        elif kind == "cancelled":
            self._record_history("Cancelada")
            self._success_callback = None
            callback = self._error_callback
            self._error_callback = None
            if callback is not None:
                callback(payload)
            self.status.configure(text="Operação cancelada.")
            messagebox.showinfo(APP_TITLE, "Operação cancelada com segurança.", parent=self)
        else:
            self._record_history("Falhou")
            self._success_callback = None
            callback = self._error_callback
            self._error_callback = None
            self.status.configure(text="Não foi possível concluir a operação.")
            if callback is not None:
                callback(payload)
            messagebox.showerror(APP_TITLE, str(payload), parent=self)
        self.after(100, self._poll_results)

    def _record_history(self, status: str) -> None:
        try:
            record_operation(settings_directory(), self._operation_label, status, __version__)
        except OSError:
            pass

    def cancel_operation(self) -> None:
        if self._busy and self._cancel_event is not None:
            self._cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status.configure(text="Cancelando com segurança...")

    def _show_result(self, payload: object) -> None:
        display = payload
        if isinstance(payload, list):
            display = f"{len(payload)} arquivo(s) criado(s)."
        if messagebox.askyesno(APP_TITLE, f"Concluído.\n\n{display}\n\nDeseja abrir o local do resultado?", parent=self):
            self._open_location(payload)

    def _open_location(self, result: object) -> None:
        if isinstance(result, list) and result:
            path = Path(result[0]).parent
        else:
            path = Path(str(result))
            if path.is_file():
                path = path.parent
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    def remove(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        dialog = PageSelectionDialog(self, source, "remove")
        self.wait_window(dialog)
        pages = dialog.result
        if not pages:
            return
        output = self._save_pdf("Salvar PDF", f"{Path(source).stem}_sem_paginas.pdf")
        if output:
            self._run("Removendo páginas...", remove_pages, source, output, pages)

    def merge(self) -> None:
        sources = filedialog.askopenfilenames(parent=self, title="Selecione os PDFs na ordem desejada", filetypes=PDF_TYPES)
        if len(sources) < 2:
            if sources:
                messagebox.showwarning(APP_TITLE, "Selecione pelo menos dois PDFs.", parent=self)
            return
        dialog = MergePagesDialog(self, list(sources))
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF unido", "pdfs_unidos.pdf")
        if output:
            self._run("Juntando PDFs...", merge_pdf_pages, dialog.result, output)

    def crop(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        dialog = PageSelectionDialog(self, source, "divide")
        self.wait_window(dialog)
        if dialog.result is None:
            return
        folder = filedialog.askdirectory(parent=self, title="Escolha a pasta para as páginas divididas")
        if folder:
            self._run("Dividindo PDF...", split_pdf, source, folder, dialog.result)

    def divide(self) -> None:
        self.crop()

    def trim(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        dialog = PageSelectionDialog(self, source, "trim")
        self.wait_window(dialog)
        if dialog.result is None:
            return
        top, bottom, pages = dialog.result
        output = self._save_pdf("Salvar PDF recortado", f"{Path(source).stem}_margens_cortadas.pdf")
        if output:
            self._run("Cortando margens...", trim_vertical_pdf, source, output, top, bottom, pages)

    def rotate(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        dialog = PageSelectionDialog(self, source, "rotate")
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF girado", f"{Path(source).stem}_girado.pdf")
        if output:
            degrees, pages = dialog.result
            self._run("Girando páginas...", rotate_pages, source, output, degrees, pages)

    def redact_information(self) -> None:
        source = self._pick_pdf("Escolha o PDF com informações a ocultar")
        if not source:
            return
        try:
            dialog = RedactionDialog(self, source)
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível abrir o PDF: {exc}", parent=self)
            return
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf(
            "Salvar PDF com informações ocultadas",
            f"{Path(source).stem}_com_tarjas.pdf",
        )
        if output:
            if Path(output).resolve() == Path(source).resolve():
                messagebox.showerror(
                    APP_TITLE,
                    "Salve o resultado com outro nome para preservar o arquivo original.",
                    parent=self,
                )
                return
            self._run("Aplicando tarjas permanentes...", redact_pdf, source, output, dialog.result)

    def to_jpg(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        dialog = IntegerInputDialog(self, "PDF para JPG", "Resolução em DPI (72 a 600):", 200, 72, 600)
        self.wait_window(dialog)
        dpi = dialog.result
        if dpi is None:
            return
        folder = filedialog.askdirectory(parent=self, title="Escolha a pasta de destino")
        if folder:
            self._run("Convertendo páginas para JPG...", pdf_to_jpg, source, folder, dpi)

    def from_images(self) -> None:
        sources = filedialog.askopenfilenames(parent=self, title="Selecione as imagens na ordem desejada", filetypes=IMAGE_TYPES)
        if not sources:
            return
        output = self._save_pdf("Salvar PDF", "imagens_convertidas.pdf")
        if output:
            self._run("Convertendo imagens para PDF...", images_to_pdf, list(sources), output)

    def to_ocr(self) -> None:
        source = self._pick_pdf("Escolha o PDF digitalizado")
        if not source:
            return
        dialog = LanguageDialog(self)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF com OCR", f"{Path(source).stem}_OCR.pdf")
        if output:
            self._run(
                "Aplicando OCR ao PDF...", pdf_to_searchable_pdf,
                source, output, dialog.result, app_directory(), cancellable=True,
            )

    def to_pdfa(self) -> None:
        source = self._pick_pdf("Escolha o PDF para arquivamento")
        if not source:
            return
        output = self._save_pdf("Salvar PDF/A-2b", f"{Path(source).stem}_PDFA.pdf")
        if output:
            self._run(
                "Preparando PDF/A-2b...", convert_pdf_to_pdfa,
                source, output, cancellable=True,
            )

    def compress(self) -> None:
        source = self._pick_pdf("Escolha o PDF para compactar")
        if not source:
            return
        dialog = CompressionDialog(self, Path(source).stat().st_size)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF compactado", f"{Path(source).stem}_compactado.pdf")
        if output:
            self._run(
                "Compactando PDF...", compact_pdf, source, output, dialog.result,
                cancellable=True, on_success=self._show_compression_result,
            )

    def _show_compression_result(self, result: object) -> None:
        path, before, after = result
        reduction = 0 if not before else max(0, (before - after) * 100 / before)
        messagebox.showinfo(
            APP_TITLE,
            f"Compactação concluída.\n\nAntes: {_format_size(before)}\n"
            f"Depois: {_format_size(after)}\nRedução: {reduction:.1f}%",
            parent=self,
        )
        self._show_result(path)

    def separate_batch(self) -> None:
        source = self._pick_pdf("Escolha o lote em PDF")
        if not source:
            return
        dialog = BatchSeparationDialog(self)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        folder = filedialog.askdirectory(parent=self, title="Escolha a pasta para os lotes separados")
        if not folder:
            return
        mode, pages_per_file, remove_separator = dialog.result
        self._run(
            "Separando em lotes...", separate_pdf_batch, source, folder, mode,
            pages_per_file, remove_separator, cancellable=True,
        )

    def output_settings(self) -> None:
        dialog = SettingsMenuDialog(self)
        self.wait_window(dialog)
        if dialog.result == "historico":
            self.show_history()
        elif dialog.result == "administrativas":
            self._open_administrative_settings()

    def _open_administrative_settings(self) -> None:
        if sys.platform == "win32" and not is_process_elevated():
            if not launch_elevated_settings():
                messagebox.showerror(
                    APP_TITLE,
                    "As configurações exigem as credenciais de um administrador local ou do Active Directory.",
                    parent=self,
                )
            return
        dialog = OutputSettingsDialog(self, _load_output_settings(), _load_network_scanners())
        self.wait_window(dialog)

    def show_license(self) -> None:
        LicenseDialog(self)

    def show_manual(self) -> None:
        manual = app_directory() / "MANUAL_DO_USUARIO.pdf"
        if not manual.is_file():
            messagebox.showerror(
                APP_TITLE,
                "O Manual do Usuário não foi encontrado nesta instalação.",
                parent=self,
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(manual))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(manual)])
            else:
                subprocess.Popen(["xdg-open", str(manual)])
        except Exception as exc:
            messagebox.showerror(
                APP_TITLE,
                f"Não foi possível abrir o Manual do Usuário: {exc}",
                parent=self,
            )

    def show_history(self) -> None:
        HistoryDialog(self, load_history(settings_directory()))

    def to_word(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        output = filedialog.asksaveasfilename(parent=self, title="Salvar documento Word", defaultextension=".docx", initialfile=f"{Path(source).stem}.docx", filetypes=WORD_TYPES)
        if output:
            self._run("Convertendo PDF para Word...", pdf_to_word, source, output)

    def from_word(self) -> None:
        source = filedialog.askopenfilename(parent=self, title="Escolha o documento Word", filetypes=[("Documentos Word", "*.docx *.doc")])
        if not source:
            return
        output = self._save_pdf("Salvar PDF", f"{Path(source).stem}.pdf")
        if output:
            self._run("Convertendo Word para PDF...", word_to_pdf, source, output)

    def protect(self) -> None:
        source = self._pick_pdf("Escolha o PDF que será protegido")
        if not source:
            return
        dialog = ProtectOptionsDialog(self)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF protegido", f"{Path(source).stem}_protegido.pdf")
        if output:
            open_password, owner_password, restrict_editing = dialog.result
            self._run(
                "Protegendo PDF com AES-256...",
                protect_pdf,
                source,
                output,
                open_password,
                owner_password,
                restrict_editing,
            )

    def unprotect(self) -> None:
        source = self._pick_pdf("Escolha o PDF protegido")
        if not source:
            return
        dialog = UnprotectOptionsDialog(self)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF sem senha", f"{Path(source).stem}_sem_senha.pdf")
        if output:
            opening_password, owner_password = dialog.result
            self._run(
                "Removendo as proteções do PDF...",
                unprotect_pdf,
                source,
                output,
                opening_password,
                owner_password,
            )

    def diagnose_scanners(self) -> None:
        self._run(
            "Testando scanners e OCR...",
            build_scanner_diagnostic,
            __version__,
            app_directory(),
            _load_network_scanners(),
            on_success=lambda report: DiagnosticDialog(self, str(report)),
        )

    def scan(self) -> None:
        try:
            devices = filter_direct_scanners(list_scanners())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        if not devices:
            messagebox.showwarning(
                APP_TITLE,
                "Nenhum scanner USB ou conectado diretamente ao computador foi encontrado pelo WIA.",
                parent=self,
            )
            return
        dialog = ScanDialog(self, devices, find_tesseract(app_directory()) is not None)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        (
            device_id, device_name, serial_number, dpi, color, input_source, paper_size, output_format,
            use_ocr, language, remove_blank, auto_deskew, auto_orient,
        ) = dialog.result
        output_settings = _load_output_settings()
        basename = default_scan_basename(serial_number, output_settings)
        staging = Path(tempfile.mkdtemp(prefix="pdf_scanner_preview_"))
        output = staging / "digitalizacao.pdf" if output_format == "PDF" else staging
        self._run(
            "Digitalizando e preparando pré-visualização...",
            scan_to_pdf,
            device_id,
            output,
            dpi=dpi,
            color_mode=color,
            input_source=input_source,
            paper_size=paper_size,
            use_ocr=use_ocr,
            language=language,
            app_dir=app_directory(),
            ask_next_page=self._ask_next_page,
            output_format=output_format,
            filename_prefix=basename,
            remove_blank_pages=remove_blank,
            auto_deskew=auto_deskew,
            auto_orient=auto_orient,
            on_success=lambda result: self._preview_scan_result(
                result, output_format, basename, staging, output_settings
            ),
            on_error=lambda _error: shutil.rmtree(staging, ignore_errors=True),
            cancellable=True,
        )

    def _ask_next_page(self, page: int) -> bool:
        event = threading.Event()
        answer = {"value": False}

        def prompt() -> None:
            answer["value"] = messagebox.askyesno(
                APP_TITLE,
                f"Página {page} digitalizada.\n\nDeseja digitalizar outra página?",
                parent=self,
            )
            event.set()

        self.after(0, prompt)
        event.wait()
        return answer["value"]

    def scan_by_ip(self) -> None:
        scanners = _load_network_scanners()
        if not scanners:
            messagebox.showwarning(
                APP_TITLE,
                "Nenhum scanner de rede foi cadastrado. Solicite a um administrador que abra Configurações e cadastre o equipamento.",
                parent=self,
            )
            return
        dialog = IPScanDialog(
            self,
            find_tesseract(app_directory()) is not None,
            scanners,
            _load_last_scanner_ip(),
        )
        self.wait_window(dialog)
        if dialog.result is None:
            return
        (
            ip_address, scanner_name, serial_number, port, protocol, dpi, color, input_source,
            paper_size, output_format, use_ocr, language, remove_blank, auto_deskew, auto_orient,
        ) = dialog.result
        _save_last_scanner_ip(ip_address)
        output_settings = _load_output_settings()
        basename = default_scan_basename(serial_number, output_settings)
        staging = Path(tempfile.mkdtemp(prefix="pdf_scanner_preview_"))
        output = staging / "digitalizacao.pdf" if output_format == "PDF" else staging
        self._run(
            f"Conectando ao scanner {ip_address} e preparando pré-visualização...",
            scan_escl_to_pdf,
            ip_address,
            port,
            protocol,
            output,
            dpi=dpi,
            color_mode=color,
            input_source=input_source,
            paper_size=paper_size,
            use_ocr=use_ocr,
            language=language,
            app_dir=app_directory(),
            ask_next_page=self._ask_next_page,
            output_format=output_format,
            filename_prefix=basename,
            remove_blank_pages=remove_blank,
            auto_deskew=auto_deskew,
            auto_orient=auto_orient,
            on_success=lambda result: self._preview_scan_result(
                result, output_format, basename, staging, output_settings
            ),
            on_error=lambda _error: shutil.rmtree(staging, ignore_errors=True),
            cancellable=True,
        )

    def _preview_scan_result(
        self, result: object, output_format: str, basename: str, staging: Path,
        output_settings: dict,
    ) -> None:
        try:
            if output_format == "PDF":
                dialog = ScanPreviewDialog(self, pdf_path=Path(str(result)))
            else:
                dialog = ScanPreviewDialog(self, image_paths=[Path(value) for value in result])
            self.wait_window(dialog)
            if dialog.result is None:
                shutil.rmtree(staging, ignore_errors=True)
                self.status.configure(text="Pronto.")
                return
            configured_folder = str(output_settings.get("pasta_saida", ""))
            automatic = bool(output_settings.get("salvar_automaticamente")) and bool(configured_folder)
            if automatic:
                Path(configured_folder).mkdir(parents=True, exist_ok=True)
            if output_format == "PDF":
                output = (
                    str(_available_path(Path(configured_folder) / f"{basename}.pdf"))
                    if automatic else
                    self._save_pdf("Salvar digitalização", f"{basename}.pdf", configured_folder)
                )
                function = compose_scanned_pdf
                args = (dialog.result, output)
                label = "Salvando PDF revisado..."
            else:
                if automatic:
                    output = configured_folder
                    original_basename = basename
                    number = 2
                    while any(Path(configured_folder).glob(f"{basename}_pagina_*.jpg")):
                        basename = f"{original_basename}_{number}"
                        number += 1
                else:
                    directory_options = {
                        "parent": self, "title": "Escolha a pasta para os arquivos JPG",
                    }
                    if configured_folder:
                        directory_options["initialdir"] = configured_folder
                    output = filedialog.askdirectory(**directory_options)
                function = save_preview_images_as_jpg
                args = (dialog.result, output, basename)
                label = "Salvando imagens revisadas..."
            if not output:
                shutil.rmtree(staging, ignore_errors=True)
                self.status.configure(text="Pronto.")
                return
            self._run(
                label,
                function,
                *args,
                on_success=lambda payload: self._finish_scanned_result(payload, staging),
                on_error=lambda _error: shutil.rmtree(staging, ignore_errors=True),
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _finish_scanned_result(self, payload: object, staging: Path) -> None:
        shutil.rmtree(staging, ignore_errors=True)
        self._show_result(payload)


class BaseDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
        # Uma janela transient ligada a uma raiz oculta pode não aparecer no
        # Windows. Isso ocorre no processo elevado que abre as configurações.
        if parent.winfo_viewable():
            self.transient(parent)
        self.result = None
        self.body = ttk.Frame(self, padding=20)
        self.body.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def buttons(self, callback) -> None:
        row = ttk.Frame(self.body)
        row.grid(column=0, row=99, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(row, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Continuar", command=callback).pack(side="right", padx=(0, 8))
        self.after_idle(self._show_centered)

    def _show_centered(self) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        _apply_window_icon(self)
        self.lift()
        self.grab_set()


class TextInputDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, title: str, prompt: str) -> None:
        super().__init__(parent, title)
        ttk.Label(self.body, text=prompt).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=5)
        self.entry = ttk.Entry(self.body, width=28)
        self.entry.grid(row=0, column=1, pady=5)
        self.entry.focus_set()
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)

    def accept(self) -> None:
        value = self.entry.get().strip()
        if not value:
            messagebox.showerror(APP_TITLE, "Preencha o campo.", parent=self)
            return
        self.result = value
        self.destroy()


class IntegerInputDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, title: str, prompt: str, initial: int, minimum: int, maximum: int) -> None:
        super().__init__(parent, title)
        self.minimum = minimum
        self.maximum = maximum
        ttk.Label(self.body, text=prompt).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=5)
        self.entry = ttk.Entry(self.body, width=12)
        self.entry.insert(0, str(initial))
        self.entry.grid(row=0, column=1, pady=5)
        self.entry.focus_set()
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)

    def accept(self) -> None:
        try:
            value = int(self.entry.get().strip())
            if not self.minimum <= value <= self.maximum:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                APP_TITLE,
                f"Digite um número entre {self.minimum} e {self.maximum}.",
                parent=self,
            )
            return
        self.result = value
        self.destroy()


class CompressionDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, original_size: int) -> None:
        super().__init__(parent, "Compactar PDF")
        ttk.Label(self.body, text=f"Tamanho atual: {_format_size(original_size)}").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        ttk.Label(self.body, text="Qualidade").grid(row=1, column=0, sticky="w", padx=(0, 12))
        self.quality = ttk.Combobox(
            self.body, state="readonly",
            values=("Alta qualidade", "Equilibrado", "Tamanho reduzido"), width=28,
        )
        self.quality.set("Equilibrado")
        self.quality.grid(row=1, column=1)
        ttk.Label(
            self.body,
            text="O texto e a camada OCR são preservados. Imagens são reduzidas conforme a opção.",
            wraplength=470,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.buttons(self.accept)

    def accept(self) -> None:
        self.result = self.quality.get()
        self.destroy()


class BatchSeparationDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Separação automática de lote")
        ttk.Label(self.body, text="Separar por").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=5)
        self.mode = ttk.Combobox(
            self.body, state="readonly",
            values=("Página em branco", "Quantidade de páginas", "Código de barras"), width=30,
        )
        self.mode.set("Página em branco")
        self.mode.grid(row=0, column=1, pady=5)
        self.mode.bind("<<ComboboxSelected>>", self._update_fields)
        ttk.Label(self.body, text="Páginas por arquivo").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=5)
        self.quantity = ttk.Entry(self.body, width=10)
        self.quantity.insert(0, "10")
        self.quantity.grid(row=1, column=1, sticky="w", pady=5)
        self.remove_separator = tk.BooleanVar(value=True)
        self.separator_check = ttk.Checkbutton(
            self.body, text="Remover a página separadora do resultado",
            variable=self.remove_separator,
        )
        self.separator_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(
            self.body,
            text="No modo código de barras, a página que contém o código inicia um novo lote.",
            wraplength=480,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._update_fields()
        self.buttons(self.accept)

    def _update_fields(self, _event=None) -> None:
        quantity_mode = self.mode.get() == "Quantidade de páginas"
        self.quantity.configure(state="normal" if quantity_mode else "disabled")
        self.separator_check.configure(state="disabled" if quantity_mode else "normal")

    def accept(self) -> None:
        try:
            pages = int(self.quantity.get()) if self.mode.get() == "Quantidade de páginas" else 1
            if pages < 1 or pages > 10000:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_TITLE, "Informe uma quantidade válida de páginas.", parent=self)
            return
        self.result = (self.mode.get(), pages, bool(self.remove_separator.get()))
        self.destroy()


class NetworkScannerEntryDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, scanner: dict[str, str] | None = None) -> None:
        super().__init__(parent, "Cadastrar scanner de rede")
        values = scanner or {}
        ttk.Label(self.body, text="Nome do scanner").grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.name = ttk.Entry(self.body, width=38)
        self.name.insert(0, values.get("nome", ""))
        self.name.grid(row=0, column=1, pady=5)
        ttk.Label(self.body, text="Endereço IP").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.address = ttk.Entry(self.body, width=38)
        self.address.insert(0, values.get("ip", ""))
        self.address.grid(row=1, column=1, pady=5)
        ttk.Label(
            self.body,
            text="Exemplo: 10.40.10.8. O equipamento deve estar na rede local.",
            foreground="#476582",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        (self.name if not values.get("nome") else self.address).focus_set()
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)

    def accept(self) -> None:
        name = self.name.get().strip()
        if not name:
            messagebox.showerror(APP_TITLE, "Informe o nome do scanner.", parent=self)
            return
        try:
            address, _, _ = validate_ip_settings(self.address.get(), 80, "http")
        except ESCLScannerError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        self.result = {"nome": name, "ip": address}
        self.destroy()


class SettingsMenuDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Configurações")
        ttk.Label(
            self.body,
            text="Escolha a área que deseja abrir.",
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        ttk.Button(
            self.body,
            text="Histórico de operações",
            command=lambda: self._select("historico"),
            width=38,
        ).grid(row=1, column=0, sticky="ew", pady=4)
        ttk.Button(
            self.body,
            text="Configurações administrativas",
            command=lambda: self._select("administrativas"),
            width=38,
        ).grid(row=2, column=0, sticky="ew", pady=4)
        ttk.Label(
            self.body,
            text="As configurações administrativas exigem autorização do Windows.",
            foreground="#476582",
        ).grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Button(self.body, text="Fechar", command=self.destroy).grid(
            row=4, column=0, sticky="e", pady=(16, 0)
        )
        self.after_idle(self._show_centered)

    def _select(self, value: str) -> None:
        self.result = value
        self.destroy()


class OutputSettingsDialog(BaseDialog):
    ALLOWED_FIELDS = {"serie", "data", "hora", "setor"}

    def __init__(
        self,
        parent: tk.Misc,
        settings: dict,
        scanners: list[dict[str, str]],
    ) -> None:
        super().__init__(parent, "Configurações administrativas")
        self.scanners = [dict(item) for item in scanners]
        network = ttk.LabelFrame(self.body, text="Scanners de rede cadastrados", padding=8)
        network.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 12))
        self.scanner_list = ttk.Treeview(
            network, columns=("nome", "ip"), show="headings", height=5, selectmode="browse"
        )
        self.scanner_list.heading("nome", text="Nome")
        self.scanner_list.heading("ip", text="Endereço IP")
        self.scanner_list.column("nome", width=320, anchor="w")
        self.scanner_list.column("ip", width=150, anchor="center")
        self.scanner_list.grid(row=0, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(network, orient="vertical", command=self.scanner_list.yview)
        scrollbar.grid(row=0, column=3, sticky="ns")
        self.scanner_list.configure(yscrollcommand=scrollbar.set)
        ttk.Button(network, text="Adicionar", command=self._add_scanner).grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Button(network, text="Editar", command=self._edit_scanner).grid(row=1, column=1, sticky="w", padx=6, pady=(7, 0))
        ttk.Button(network, text="Remover", command=self._remove_scanner).grid(row=1, column=2, sticky="w", pady=(7, 0))
        network.columnconfigure(0, weight=1)
        self._refresh_scanners()

        ttk.Separator(self.body).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(self.body, text="Pasta padrão").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=5)
        folder_row = ttk.Frame(self.body)
        folder_row.grid(row=2, column=1, sticky="ew", pady=5)
        self.folder = ttk.Entry(folder_row, width=42)
        self.folder.insert(0, str(settings.get("pasta_saida", "")))
        self.folder.pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="Escolher...", command=self._choose_folder).pack(side="left", padx=(6, 0))
        ttk.Label(self.body, text="Modelo do nome").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=5)
        self.template = ttk.Entry(self.body, width=53)
        self.template.insert(0, str(settings.get("modelo_nome", DEFAULT_OUTPUT_SETTINGS["modelo_nome"])))
        self.template.grid(row=3, column=1, sticky="ew", pady=5)
        ttk.Label(self.body, text="Setor").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=5)
        self.sector = ttk.Entry(self.body, width=35)
        self.sector.insert(0, str(settings.get("setor", "")))
        self.sector.grid(row=4, column=1, sticky="w", pady=5)
        self.automatic = tk.BooleanVar(value=bool(settings.get("salvar_automaticamente", False)))
        ttk.Checkbutton(
            self.body, text="Salvar automaticamente na pasta padrão após a pré-visualização",
            variable=self.automatic,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(
            self.body,
            text="Campos disponíveis: {serie}, {data}, {hora} e {setor}.\n"
                 "Exemplo: Scan_{serie}_{data}_{hora}_{setor}",
            foreground="#476582",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))
        transfer = ttk.LabelFrame(self.body, text="Arquivo de configurações", padding=8)
        transfer.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        actions = ttk.Frame(transfer)
        actions.pack(anchor="w")
        ttk.Button(actions, text="Exportar configurações", command=self._export_configuration).pack(side="left")
        ttk.Button(actions, text="Importar configurações", command=self._import_configuration).pack(side="left", padx=6)
        ttk.Label(
            transfer,
            text="O arquivo exportado contém os scanners de rede e as opções de saída.",
            foreground="#476582",
        ).pack(anchor="w", pady=(8, 0))
        self.body.columnconfigure(1, weight=1)
        self.buttons(self.accept)

    def _refresh_scanners(self) -> None:
        self.scanner_list.delete(*self.scanner_list.get_children())
        for index, scanner in enumerate(self.scanners):
            self.scanner_list.insert("", "end", iid=str(index), values=(scanner["nome"], scanner["ip"]))

    def _selected_scanner_index(self) -> int | None:
        selected = self.scanner_list.selection()
        return int(selected[0]) if selected else None

    def _add_scanner(self) -> None:
        dialog = NetworkScannerEntryDialog(self)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        if any(item["ip"] == dialog.result["ip"] for item in self.scanners):
            messagebox.showerror(APP_TITLE, "Este endereço IP já está cadastrado.", parent=self)
            return
        self.scanners.append(dialog.result)
        self._refresh_scanners()
        self.scanner_list.selection_set(str(len(self.scanners) - 1))

    def _edit_scanner(self) -> None:
        index = self._selected_scanner_index()
        if index is None:
            messagebox.showinfo(APP_TITLE, "Selecione um scanner para editar.", parent=self)
            return
        dialog = NetworkScannerEntryDialog(self, self.scanners[index])
        self.wait_window(dialog)
        if dialog.result is None:
            return
        if any(position != index and item["ip"] == dialog.result["ip"] for position, item in enumerate(self.scanners)):
            messagebox.showerror(APP_TITLE, "Este endereço IP já está cadastrado.", parent=self)
            return
        self.scanners[index] = dialog.result
        self._refresh_scanners()
        self.scanner_list.selection_set(str(index))

    def _remove_scanner(self) -> None:
        index = self._selected_scanner_index()
        if index is None:
            messagebox.showinfo(APP_TITLE, "Selecione um scanner para remover.", parent=self)
            return
        scanner = self.scanners[index]
        if not messagebox.askyesno(
            APP_TITLE, f"Remover o scanner '{scanner['nome']}' ({scanner['ip']})?", parent=self
        ):
            return
        self.scanners.pop(index)
        self._refresh_scanners()

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(parent=self, title="Escolha a pasta padrão")
        if selected:
            self.folder.delete(0, "end")
            self.folder.insert(0, selected)

    def _current_payload(self) -> dict:
        values = {
            "pasta_saida": self.folder.get().strip(),
            "modelo_nome": self.template.get().strip(),
            "setor": self.sector.get().strip(),
            "salvar_automaticamente": bool(self.automatic.get()),
        }
        return _validate_configuration_payload(_configuration_payload(values, self.scanners))

    @staticmethod
    def _replace_entry(entry: ttk.Entry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    def _export_configuration(self) -> None:
        try:
            payload = self._current_payload()
        except (ValueError, ESCLScannerError) as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self, title="Exportar configurações", defaultextension=".json",
            initialfile=f"PDFScannerALAP_configuracao_{datetime.now():%Y-%m-%d}.json",
            filetypes=[("Configuração JSON", "*.json")],
        )
        if not target:
            return
        try:
            Path(target).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível exportar as configurações: {exc}", parent=self)
            return
        messagebox.showinfo(APP_TITLE, "Configurações exportadas com sucesso.", parent=self)

    def _import_configuration(self) -> None:
        source = filedialog.askopenfilename(
            parent=self, title="Importar configurações", filetypes=[("Configuração JSON", "*.json")]
        )
        if not source:
            return
        try:
            path = Path(source)
            if path.stat().st_size > 2_000_000:
                raise ValueError("O arquivo de configuração excede o limite permitido.")
            payload = _validate_configuration_payload(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, ESCLScannerError) as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível importar: {exc}", parent=self)
            return
        output = payload["saida_digitalizacao"]
        self.scanners = payload["scanners_rede"]
        self._refresh_scanners()
        self._replace_entry(self.folder, output["pasta_saida"])
        self._replace_entry(self.template, output["modelo_nome"])
        self._replace_entry(self.sector, output["setor"])
        self.automatic.set(bool(output["salvar_automaticamente"]))
        messagebox.showinfo(
            APP_TITLE,
            "Configurações importadas. Clique em Continuar para salvá-las neste computador.",
            parent=self,
        )

    def accept(self) -> None:
        try:
            payload = self._current_payload()
        except (ValueError, ESCLScannerError) as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        values = payload["saida_digitalizacao"]
        folder = values["pasta_saida"]
        if values["salvar_automaticamente"] and not folder:
            messagebox.showerror(APP_TITLE, "Escolha uma pasta para o salvamento automático.", parent=self)
            return
        if folder:
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_TITLE, f"Não foi possível acessar a pasta: {exc}", parent=self)
                return
        try:
            data = _read_machine_settings()
            data["saida_digitalizacao"] = values
            data["scanners_rede"] = payload["scanners_rede"]
            data.pop("pasta_inventario_instalacoes", None)
            _write_machine_settings(data)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível salvar as configurações: {exc}", parent=self)
            return
        self.result = values
        self.destroy()


class CropDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Cortar páginas")
        self.entries: list[ttk.Entry] = []
        defaults = ("0", "0", "0", "0")
        for row, (label, default) in enumerate(zip(("Esquerda (mm)", "Superior (mm)", "Direita (mm)", "Inferior (mm)"), defaults)):
            ttk.Label(self.body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            entry = ttk.Entry(self.body, width=18)
            entry.insert(0, default)
            entry.grid(row=row, column=1, pady=4)
            self.entries.append(entry)
        ttk.Label(self.body, text="Páginas (vazio = todas)").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=4)
        self.pages = ttk.Entry(self.body, width=18)
        self.pages.grid(row=4, column=1, pady=4)
        self.buttons(self.accept)

    def accept(self) -> None:
        try:
            values = [float(entry.get().replace(",", ".")) for entry in self.entries]
            if any(value < 0 for value in values):
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_TITLE, "Digite margens válidas e não negativas.", parent=self)
            return
        self.result = (*values, self.pages.get().strip())
        self.destroy()


class RotateDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Rotacionar páginas")
        ttk.Label(self.body, text="Rotação").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        self.degrees = ttk.Combobox(self.body, state="readonly", values=("90", "180", "270"), width=15)
        self.degrees.set("90")
        self.degrees.grid(row=0, column=1, pady=4)
        ttk.Label(self.body, text="Páginas (vazio = todas)").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        self.pages = ttk.Entry(self.body, width=18)
        self.pages.grid(row=1, column=1, pady=4)
        self.buttons(self.accept)

    def accept(self) -> None:
        self.result = (int(self.degrees.get()), self.pages.get().strip())
        self.destroy()


class PasswordDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, title: str, *, confirm: bool) -> None:
        super().__init__(parent, title)
        self.confirm_required = confirm
        ttk.Label(self.body, text="Senha").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=5)
        self.password = ttk.Entry(self.body, width=34, show="•")
        self.password.grid(row=0, column=1, pady=5)
        self.password.focus_set()
        self.confirmation = None
        if confirm:
            ttk.Label(self.body, text="Confirmar senha").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=5)
            self.confirmation = ttk.Entry(self.body, width=34, show="•")
            self.confirmation.grid(row=1, column=1, pady=5)
            ttk.Label(self.body, text="Mínimo de 4 caracteres. Guarde a senha em local seguro.").grid(
                row=2, column=0, columnspan=2, sticky="w", pady=(8, 0)
            )
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)

    def accept(self) -> None:
        password = self.password.get()
        if not password:
            messagebox.showerror(APP_TITLE, "Informe a senha.", parent=self)
            return
        if self.confirm_required:
            if len(password) < 4:
                messagebox.showerror(APP_TITLE, "Use uma senha com pelo menos 4 caracteres.", parent=self)
                return
            if self.confirmation is None or password != self.confirmation.get():
                messagebox.showerror(APP_TITLE, "As senhas não coincidem.", parent=self)
                return
        self.result = password
        self.destroy()


class ProtectOptionsDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Proteger PDF")
        self.require_opening = tk.BooleanVar(value=False)
        self.restrict_editing = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.body,
            text="Exigir senha para abrir o PDF",
            variable=self.require_opening,
            command=self.update_fields,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 7))
        ttk.Label(self.body, text="Senha de abertura").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        self.open_password = ttk.Entry(self.body, width=34, show="•")
        self.open_password.grid(row=1, column=1, pady=4)
        ttk.Label(self.body, text="Confirmar abertura").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        self.open_confirmation = ttk.Entry(self.body, width=34, show="•")
        self.open_confirmation.grid(row=2, column=1, pady=4)

        ttk.Separator(self.body).grid(row=3, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Checkbutton(
            self.body,
            text="Bloquear edição, seleção e cópia",
            variable=self.restrict_editing,
            command=self.update_fields,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 7))
        ttk.Label(self.body, text="Senha de proprietário").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=4)
        self.owner_password = ttk.Entry(self.body, width=34, show="•")
        self.owner_password.grid(row=5, column=1, pady=4)
        ttk.Label(self.body, text="Confirmar proprietário").grid(row=6, column=0, sticky="w", padx=(0, 12), pady=4)
        self.owner_confirmation = ttk.Entry(self.body, width=34, show="•")
        self.owner_confirmation.grid(row=6, column=1, pady=4)
        ttk.Label(
            self.body,
            text="As opções são independentes. Se marcar as duas, use senhas diferentes.",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.open_password.focus_set()
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)
        self.update_fields()

    def update_fields(self) -> None:
        opening_state = "normal" if self.require_opening.get() else "disabled"
        editing_state = "normal" if self.restrict_editing.get() else "disabled"
        self.open_password.configure(state=opening_state)
        self.open_confirmation.configure(state=opening_state)
        self.owner_password.configure(state=editing_state)
        self.owner_confirmation.configure(state=editing_state)

    def accept(self) -> None:
        opening = self.require_opening.get()
        editing = self.restrict_editing.get()
        if not opening and not editing:
            messagebox.showerror(APP_TITLE, "Escolha ao menos uma forma de proteção.", parent=self)
            return
        open_password = self.open_password.get() if opening else ""
        owner_password = self.owner_password.get() if editing else ""
        if opening and (len(open_password) < 4 or open_password != self.open_confirmation.get()):
            messagebox.showerror(APP_TITLE, "Confira a senha de abertura (mínimo de 4 caracteres).", parent=self)
            return
        if editing and (len(owner_password) < 4 or owner_password != self.owner_confirmation.get()):
            messagebox.showerror(APP_TITLE, "Confira a senha de proprietário (mínimo de 4 caracteres).", parent=self)
            return
        if opening and editing and open_password == owner_password:
            messagebox.showerror(APP_TITLE, "Use senhas diferentes para abertura e proprietário.", parent=self)
            return
        self.result = (open_password, owner_password, editing)
        self.destroy()


class UnprotectOptionsDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Desproteger PDF")
        self.unlock_opening = tk.BooleanVar(value=False)
        self.unlock_editing = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.body,
            text="Desbloquear a abertura do PDF",
            variable=self.unlock_opening,
            command=self.update_fields,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 7))
        ttk.Label(self.body, text="Senha de abertura").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=4
        )
        self.opening_password = ttk.Entry(self.body, width=34, show="•")
        self.opening_password.grid(row=1, column=1, pady=4)

        ttk.Separator(self.body).grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Checkbutton(
            self.body,
            text="Desbloquear edição, seleção e cópia",
            variable=self.unlock_editing,
            command=self.update_fields,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 7))
        ttk.Label(self.body, text="Senha de edição/proprietário").grid(
            row=4, column=0, sticky="w", padx=(0, 12), pady=4
        )
        self.owner_password = ttk.Entry(self.body, width=34, show="•")
        self.owner_password.grid(row=4, column=1, pady=4)
        ttk.Label(
            self.body,
            text="As senhas podem ser diferentes. Marque e preencha as proteções que deseja remover.",
            wraplength=500,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)
        self.update_fields()

    def update_fields(self) -> None:
        self.opening_password.configure(state="normal" if self.unlock_opening.get() else "disabled")
        self.owner_password.configure(state="normal" if self.unlock_editing.get() else "disabled")

    def accept(self) -> None:
        opening = self.unlock_opening.get()
        editing = self.unlock_editing.get()
        if not opening and not editing:
            messagebox.showerror(APP_TITLE, "Escolha ao menos uma proteção para remover.", parent=self)
            return
        opening_password = self.opening_password.get() if opening else ""
        owner_password = self.owner_password.get() if editing else ""
        if opening and not opening_password:
            messagebox.showerror(APP_TITLE, "Informe a senha de abertura.", parent=self)
            return
        if editing and not owner_password:
            messagebox.showerror(APP_TITLE, "Informe a senha de edição/proprietário.", parent=self)
            return
        self.result = (opening_password, owner_password)
        self.destroy()


class LanguageDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Idioma do OCR")
        ttk.Label(self.body, text="Idioma do documento").grid(row=0, column=0, padx=(0, 12), pady=5)
        self.language = ttk.Combobox(
            self.body, state="readonly", values=tuple(OCR_LANGUAGES), width=30
        )
        self.language.set("Português + Inglês")
        self.language.grid(row=0, column=1, pady=5)
        self.buttons(self.accept)

    def accept(self) -> None:
        self.result = OCR_LANGUAGES[self.language.get()]
        self.destroy()


class HistoryDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, records: list[dict[str, str]]) -> None:
        super().__init__(parent, "Histórico de operações")
        self.records = records
        self.resizable(True, True)
        columns = ("data_hora", "operacao", "status", "usuario", "computador", "versao")
        self.table = ttk.Treeview(self.body, columns=columns, show="headings", height=18)
        headings = {
            "data_hora": "Data e hora", "operacao": "Operação", "status": "Status",
            "usuario": "Usuário", "computador": "Computador", "versao": "Versão",
        }
        widths = {"data_hora": 175, "operacao": 300, "status": 90, "usuario": 120, "computador": 140, "versao": 70}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor="w")
        for record in records:
            self.table.insert("", "end", values=tuple(record.get(column, "") for column in columns))
        vertical = ttk.Scrollbar(self.body, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(self.body, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)
        actions = ttk.Frame(self.body)
        actions.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Exportar CSV", command=self._export).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Fechar", command=self.destroy).pack(side="left")
        self.after_idle(lambda: self._show_size(1080, 620))

    def _export(self) -> None:
        target = filedialog.asksaveasfilename(
            parent=self, title="Exportar histórico", defaultextension=".csv",
            initialfile=f"historico_operacoes_{datetime.now():%Y-%m-%d}.csv",
            filetypes=[("Arquivo CSV", "*.csv")],
        )
        if not target:
            return
        try:
            export_history_csv(self.records, target)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível exportar o histórico: {exc}", parent=self)
            return
        messagebox.showinfo(APP_TITLE, "Histórico exportado com sucesso.", parent=self)

    def _show_size(self, width: int, height: int) -> None:
        width = min(width, self.winfo_screenwidth() - 60)
        height = min(height, self.winfo_screenheight() - 80)
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        _apply_window_icon(self)
        self.lift()
        self.grab_set()


class DiagnosticDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, report: str) -> None:
        super().__init__(parent, "Diagnóstico do scanner")
        self.report = report
        self.resizable(True, True)
        ttk.Label(
            self.body,
            text="Use este relatório para identificar driver, conexão, origem e OCR.",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.text = tk.Text(
            self.body, wrap="word", font=("Consolas", 10), background="white",
            foreground="#1f2937", padx=10, pady=10,
        )
        scroll = ttk.Scrollbar(self.body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.insert("1.0", report)
        self.text.configure(state="disabled")
        self.text.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        self.body.rowconfigure(1, weight=1)
        self.body.columnconfigure(0, weight=1)
        actions = ttk.Frame(self.body)
        actions.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Copiar", command=self._copy).pack(side="left")
        ttk.Button(actions, text="Salvar relatório", command=self._save).pack(side="left", padx=8)
        ttk.Button(actions, text="Fechar", command=self.destroy).pack(side="left")
        self.after_idle(lambda: self._show_centered_size(820, 600))

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.report)
        messagebox.showinfo(APP_TITLE, "Relatório copiado.", parent=self)

    def _save(self) -> None:
        target = filedialog.asksaveasfilename(
            parent=self, title="Salvar diagnóstico", defaultextension=".txt",
            initialfile=f"diagnostico_scanner_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt",
            filetypes=[("Arquivo de texto", "*.txt")],
        )
        if not target:
            return
        try:
            Path(target).write_text(self.report, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível salvar o relatório: {exc}", parent=self)
            return
        messagebox.showinfo(APP_TITLE, "Relatório salvo com sucesso.", parent=self)

    def _show_centered_size(self, width: int, height: int) -> None:
        width = min(width, self.winfo_screenwidth() - 80)
        height = min(height, self.winfo_screenheight() - 100)
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        _apply_window_icon(self)
        self.lift()
        self.grab_set()


class LicenseDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Licença de uso")
        self.resizable(True, True)
        try:
            self._license_content = (app_directory() / "LICENCA.txt").read_text(encoding="utf-8")
        except OSError:
            self._license_content = "Termos de licença não encontrados neste pacote."

        self._license_canvas = tk.Canvas(
            self.body,
            background="white",
            highlightthickness=1,
            highlightbackground="#c7d2df",
        )
        scroll = ttk.Scrollbar(self.body, orient="vertical", command=self._license_canvas.yview)
        self._license_canvas.configure(yscrollcommand=scroll.set)
        self._license_font = tkfont.Font(family="Segoe UI", size=10)
        self._license_bold_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._license_title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self._render_job: str | None = None

        self._license_canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)
        self._license_canvas.bind("<Configure>", self._schedule_license_render)
        self._license_canvas.bind(
            "<MouseWheel>",
            lambda event: self._license_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"),
        )

        row = ttk.Frame(self.body)
        row.grid(row=99, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(row, text="Copiar texto", command=self._copy_license).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Fechar", command=self.destroy).pack(side="left")
        self.after_idle(lambda: self._show_centered_size(900, 620))

    def _copy_license(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._license_content)
        messagebox.showinfo(APP_TITLE, "Texto da licença copiado.", parent=self)

    def _schedule_license_render(self, _event=None) -> None:
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(60, self._render_license)

    def _draw_justified_paragraph(self, text: str, y: float, width: float) -> float:
        words = text.split()
        if not words:
            return y
        space = self._license_font.measure(" ")
        lines: list[list[str]] = []
        current: list[str] = []
        current_width = 0
        for word in words:
            word_width = self._license_font.measure(word)
            candidate = current_width + (space if current else 0) + word_width
            if current and candidate > width:
                lines.append(current)
                current = [word]
                current_width = word_width
            else:
                current.append(word)
                current_width = candidate
        if current:
            lines.append(current)

        line_height = self._license_font.metrics("linespace") + 5
        for line_number, line_words in enumerate(lines):
            word_widths = [self._license_font.measure(word) for word in line_words]
            justify = line_number < len(lines) - 1 and len(line_words) > 1
            gap = (
                (width - sum(word_widths)) / (len(line_words) - 1)
                if justify
                else space
            )
            x = 18.0
            for word, word_width in zip(line_words, word_widths):
                self._license_canvas.create_text(
                    x,
                    y,
                    text=word,
                    anchor="nw",
                    font=self._license_font,
                    fill="#1f2937",
                )
                x += word_width + gap
            y += line_height
        return y

    def _render_license(self) -> None:
        self._render_job = None
        canvas_width = max(360, self._license_canvas.winfo_width())
        text_width = canvas_width - 36
        self._license_canvas.delete("all")
        y = 18.0
        blocks = re.split(r"\n\s*\n", self._license_content.strip())
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            first = lines[0]
            if first.startswith("LICENÇA INSTITUCIONAL"):
                self._license_canvas.create_text(
                    canvas_width / 2,
                    y,
                    text=first,
                    anchor="n",
                    font=self._license_title_font,
                    fill="#173b67",
                )
                y += self._license_title_font.metrics("linespace") + 14
            elif re.match(r"^\d+\.\s", first):
                self._license_canvas.create_text(
                    18,
                    y,
                    text=first,
                    anchor="nw",
                    font=self._license_bold_font,
                    fill="#173b67",
                )
                y += self._license_bold_font.metrics("linespace") + 7
                if len(lines) > 1:
                    y = self._draw_justified_paragraph(" ".join(lines[1:]), y, text_width)
                y += 10
            elif first.startswith(("Titular:", "Copyright", "Versão dos termos:")):
                for line in lines:
                    self._license_canvas.create_text(
                        18,
                        y,
                        text=line,
                        anchor="nw",
                        font=self._license_font,
                        fill="#1f2937",
                    )
                    y += self._license_font.metrics("linespace") + 5
                y += 7
            else:
                y = self._draw_justified_paragraph(" ".join(lines), y, text_width)
                y += 10
        self._license_canvas.configure(scrollregion=(0, 0, canvas_width, y + 18))

    def _show_centered_size(self, width: int, height: int) -> None:
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        _apply_window_icon(self)
        self.lift()
        self.grab_set()

class ScanDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, devices, ocr_available: bool) -> None:
        super().__init__(parent, "Digitalizar documento")
        self.devices = devices
        self.ocr_available = ocr_available
        self.profiles = _load_scan_profiles()
        labels = [device.display_name for device in devices]
        fields = (("Scanner", labels), ("Resolução", ("150", "200", "300", "400", "600")), ("Modo", ("Cor", "Cinza", "Preto e branco")))
        self.combos = []
        for row, (label, values) in enumerate(fields):
            ttk.Label(self.body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            combo = ttk.Combobox(self.body, state="readonly", values=values, width=34)
            combo.current(0 if row != 1 else 2)
            combo.grid(row=row, column=1, pady=5)
            self.combos.append(combo)
        self.combos[0].bind("<<ComboboxSelected>>", self._scanner_changed)
        ttk.Label(self.body, text="Origem").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=5)
        self.source = ttk.Combobox(self.body, state="readonly", width=34)
        self.source.grid(row=3, column=1, pady=5)
        self._scanner_changed()
        ttk.Label(self.body, text="Tamanho do papel").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=5)
        self.paper_size = ttk.Combobox(
            self.body, state="readonly", values=tuple(PAPER_SIZES_MM), width=34
        )
        self.paper_size.set("Automático (área máxima)")
        self.paper_size.grid(row=4, column=1, pady=5)
        ttk.Label(self.body, text="Formato de saída").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=5)
        self.output_format = ttk.Combobox(self.body, state="readonly", values=("PDF", "JPG"), width=34)
        self.output_format.set("PDF")
        self.output_format.grid(row=5, column=1, pady=5)
        self.ocr = tk.BooleanVar(value=False)
        ocr_text = "Aplicar OCR (PDF pesquisável)" if ocr_available else "Aplicar OCR (Tesseract não encontrado)"
        ttk.Checkbutton(self.body, text=ocr_text, variable=self.ocr, state="normal" if ocr_available else "disabled").grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 4))
        ttk.Label(self.body, text="Idioma OCR").grid(row=7, column=0, sticky="w", padx=(0, 12), pady=5)
        self.language = ttk.Combobox(self.body, state="readonly", values=tuple(OCR_LANGUAGES), width=34)
        self.language.set("Português + Inglês")
        self.language.grid(row=7, column=1, pady=5)
        ttk.Label(
            self.body,
            text="A lista mostra scanners USB ou conectados diretamente ao computador.",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.remove_blank = tk.BooleanVar(value=False)
        self.auto_deskew = tk.BooleanVar(value=False)
        self.auto_orient = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="Remover páginas em branco automaticamente", variable=self.remove_blank).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Checkbutton(self.body, text="Corrigir inclinação automaticamente", variable=self.auto_deskew).grid(row=10, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(self.body, text="Detectar e corrigir orientação", variable=self.auto_orient).grid(row=11, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(
            self.body,
            text="As correções automáticas aumentam o tempo de processamento.",
            foreground="#6b7280",
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(3, 0))
        profile_row = ttk.LabelFrame(self.body, text="Perfil de digitalização", padding=8)
        profile_row.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.profile = ttk.Combobox(profile_row, state="readonly", values=tuple(self.profiles), width=24)
        self.profile.set("Documento padrão")
        self.profile.pack(side="left")
        ttk.Button(profile_row, text="Aplicar", command=self._apply_profile).pack(side="left", padx=5)
        ttk.Button(profile_row, text="Salvar novo", command=self._save_profile).pack(side="left")
        ttk.Button(profile_row, text="Excluir", command=self._delete_profile).pack(side="left", padx=(5, 0))
        self._apply_profile()
        self.buttons(self.accept)

    def _scanner_changed(self, _event=None) -> None:
        index = self.combos[0].current()
        sources = self.devices[index].sources if index >= 0 else ("Vidro",)
        self.source.configure(values=sources)
        self.source.current(0)

    def _profile_values(self) -> dict:
        return {
            "dpi": self.combos[1].get(), "color": self.combos[2].get(),
            "output_format": self.output_format.get(), "use_ocr": bool(self.ocr.get()),
            "language": self.language.get(), "source": self.source.get(),
            "paper_size": self.paper_size.get(),
            "remove_blank": bool(self.remove_blank.get()), "auto_deskew": bool(self.auto_deskew.get()),
            "auto_orient": bool(self.auto_orient.get()),
        }

    def _apply_profile(self) -> None:
        values = self.profiles.get(self.profile.get())
        if not values:
            return
        self.combos[1].set(str(values.get("dpi", "300")))
        self.combos[2].set(str(values.get("color", "Cor")))
        self.output_format.set(str(values.get("output_format", "PDF")))
        paper_size = str(values.get("paper_size", "Automático (área máxima)"))
        self.paper_size.set(paper_size if paper_size in PAPER_SIZES_MM else "Automático (área máxima)")
        self.ocr.set(bool(values.get("use_ocr", False)) and self.ocr_available)
        language = str(values.get("language", "Português + Inglês"))
        if language in OCR_LANGUAGES:
            self.language.set(language)
        desired_source = str(values.get("source", ""))
        if desired_source in tuple(self.source["values"]):
            self.source.set(desired_source)
        self.remove_blank.set(bool(values.get("remove_blank", False)))
        self.auto_deskew.set(bool(values.get("auto_deskew", False)))
        self.auto_orient.set(bool(values.get("auto_orient", False)))

    def _save_profile(self) -> None:
        name = simpledialog.askstring(APP_TITLE, "Nome do novo perfil:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name or name in DEFAULT_SCAN_PROFILES:
            messagebox.showerror(APP_TITLE, "Escolha um nome diferente dos perfis padrão.", parent=self)
            return
        try:
            _save_scan_profile(name, self._profile_values())
            self.profiles = _load_scan_profiles()
            self.profile.configure(values=tuple(self.profiles))
            self.profile.set(name)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível salvar o perfil: {exc}", parent=self)

    def _delete_profile(self) -> None:
        name = self.profile.get()
        if not _delete_scan_profile(name):
            messagebox.showinfo(APP_TITLE, "Os perfis padrão não podem ser excluídos.", parent=self)
            return
        self.profiles = _load_scan_profiles()
        self.profile.configure(values=tuple(self.profiles))
        self.profile.set("Documento padrão")

    def accept(self) -> None:
        index = self.combos[0].current()
        self.result = (
            self.devices[index].device_id,
            self.devices[index].name,
            self.devices[index].serial_number,
            int(self.combos[1].get()),
            self.combos[2].get(),
            self.source.get(),
            self.paper_size.get(),
            self.output_format.get(),
            bool(self.ocr.get()) if self.output_format.get() == "PDF" else False,
            OCR_LANGUAGES[self.language.get()],
            bool(self.remove_blank.get()),
            bool(self.auto_deskew.get()),
            bool(self.auto_orient.get()),
        )
        self.destroy()


class IPScanDialog(BaseDialog):
    SOURCE_LABELS = {
        "Platen": "Vidro",
        "Feeder": "Alimentador superior - somente frente",
        "FeederDuplex": "Alimentador superior - frente e verso",
    }

    def __init__(
        self,
        parent: tk.Misc,
        ocr_available: bool,
        scanners: list[dict[str, str]],
        preferred_ip: str = "",
    ) -> None:
        super().__init__(parent, "Scanner de rede")
        self.ocr_available = ocr_available
        self.scanners = scanners
        self.profiles = _load_scan_profiles()
        self._source_results: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self._detect_after = None
        self._detected_ip = ""
        self._detected_name = ""
        self._detected_serial = ""
        ttk.Label(self.body, text="Scanner cadastrado").grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.scanner_values = [f"{item['nome']} — {item['ip']}" for item in scanners]
        self.scanner_choice = ttk.Combobox(
            self.body, state="readonly", values=self.scanner_values, width=42
        )
        selected_index = next(
            (index for index, item in enumerate(scanners) if item["ip"] == preferred_ip), 0
        )
        self.scanner_choice.current(selected_index)
        self.scanner_choice.grid(row=0, column=1, pady=5)
        self.scanner_choice.bind("<<ComboboxSelected>>", self._scanner_changed)
        self.address = scanners[selected_index]["ip"]

        ttk.Label(self.body, text="Resolução").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=5)
        self.dpi = ttk.Combobox(self.body, state="readonly", values=("150", "200", "300", "400", "600"), width=32)
        self.dpi.set("300")
        self.dpi.grid(row=1, column=1, pady=5)

        ttk.Label(self.body, text="Modo").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=5)
        self.color = ttk.Combobox(self.body, state="readonly", values=("Cor", "Cinza", "Preto e branco"), width=32)
        self.color.set("Cor")
        self.color.grid(row=2, column=1, pady=5)

        ttk.Label(self.body, text="Origem").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=5)
        self.source = ttk.Combobox(self.body, state="disabled", width=32)
        self.source.grid(row=3, column=1, pady=5)

        ttk.Label(self.body, text="Tamanho do papel").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=5)
        self.paper_size = ttk.Combobox(
            self.body, state="readonly", values=tuple(PAPER_SIZES_MM), width=32
        )
        self.paper_size.set("Automático (área máxima)")
        self.paper_size.grid(row=4, column=1, pady=5)

        ttk.Label(self.body, text="Formato de saída").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=5)
        self.output_format = ttk.Combobox(self.body, state="readonly", values=("PDF", "JPG"), width=32)
        self.output_format.set("PDF")
        self.output_format.grid(row=5, column=1, pady=5)

        self.ocr = tk.BooleanVar(value=False)
        ocr_text = "Aplicar OCR (PDF pesquisável)" if ocr_available else "Aplicar OCR (Tesseract não encontrado)"
        ttk.Checkbutton(
            self.body,
            text=ocr_text,
            variable=self.ocr,
            state="normal" if ocr_available else "disabled",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 4))

        ttk.Label(self.body, text="Idioma OCR").grid(row=7, column=0, sticky="w", padx=(0, 12), pady=5)
        self.language = ttk.Combobox(self.body, state="readonly", values=tuple(OCR_LANGUAGES), width=32)
        self.language.set("Português + Inglês")
        self.language.grid(row=7, column=1, pady=5)
        self.detection_status = ttk.Label(
            self.body,
            text="Detectando as opções do scanner cadastrado...",
            foreground="#476582",
            wraplength=560,
            justify="left",
        )
        self.detection_status.grid(row=8, column=0, columnspan=2, sticky="w", pady=(9, 0))
        self.remove_blank = tk.BooleanVar(value=False)
        self.auto_deskew = tk.BooleanVar(value=False)
        self.auto_orient = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="Remover páginas em branco automaticamente", variable=self.remove_blank).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Checkbutton(self.body, text="Corrigir inclinação automaticamente", variable=self.auto_deskew).grid(row=10, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(self.body, text="Detectar e corrigir orientação", variable=self.auto_orient).grid(row=11, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(
            self.body,
            text="As correções automáticas aumentam o tempo de processamento.",
            foreground="#6b7280",
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(3, 0))
        profile_row = ttk.LabelFrame(self.body, text="Perfil de digitalização", padding=8)
        profile_row.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.profile = ttk.Combobox(profile_row, state="readonly", values=tuple(self.profiles), width=24)
        self.profile.set("Documento padrão")
        self.profile.pack(side="left")
        ttk.Button(profile_row, text="Aplicar", command=self._apply_profile).pack(side="left", padx=5)
        ttk.Button(profile_row, text="Salvar novo", command=self._save_profile).pack(side="left")
        ttk.Button(profile_row, text="Excluir", command=self._delete_profile).pack(side="left", padx=(5, 0))
        self._apply_profile()
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)
        self.after(100, self._poll_source_results)
        self._schedule_detection(delay=150)

    def _scanner_changed(self, _event=None) -> None:
        index = self.scanner_choice.current()
        if index < 0:
            return
        self.address = self.scanners[index]["ip"]
        self._schedule_detection(delay=150)

    def _schedule_detection(self, _event=None, *, delay: int = 700) -> None:
        if self._detect_after is not None:
            self.after_cancel(self._detect_after)
        self._detected_ip = ""
        self._detected_name = ""
        self._detected_serial = ""
        self.source.set("")
        self.source.configure(state="disabled", values=())
        self.detection_status.configure(text="Aguardando a detecção do scanner...")
        self._detect_after = self.after(delay, self._start_detection)

    def _start_detection(self) -> None:
        self._detect_after = None
        try:
            address, _, _ = validate_ip_settings(self.address, 80, "http")
        except ESCLScannerError:
            self.detection_status.configure(text="O scanner cadastrado possui um endereço IP inválido.")
            return
        self.detection_status.configure(text="Detectando vidro e alimentador...")

        def worker() -> None:
            try:
                info = detect_escl_details(address, 80, "http")
                self._source_results.put((address, "ok", info))
            except Exception as exc:
                self._source_results.put((address, "error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _profile_values(self) -> dict:
        return {
            "dpi": self.dpi.get(), "color": self.color.get(),
            "output_format": self.output_format.get(), "use_ocr": bool(self.ocr.get()),
            "language": self.language.get(), "source": self.source.get(),
            "paper_size": self.paper_size.get(),
            "remove_blank": bool(self.remove_blank.get()), "auto_deskew": bool(self.auto_deskew.get()),
            "auto_orient": bool(self.auto_orient.get()),
        }

    def _apply_profile(self) -> None:
        values = self.profiles.get(self.profile.get())
        if not values:
            return
        self.dpi.set(str(values.get("dpi", "300")))
        self.color.set(str(values.get("color", "Cor")))
        self.output_format.set(str(values.get("output_format", "PDF")))
        paper_size = str(values.get("paper_size", "Automático (área máxima)"))
        self.paper_size.set(paper_size if paper_size in PAPER_SIZES_MM else "Automático (área máxima)")
        self.ocr.set(bool(values.get("use_ocr", False)) and self.ocr_available)
        language = str(values.get("language", "Português + Inglês"))
        if language in OCR_LANGUAGES:
            self.language.set(language)
        desired_source = str(values.get("source", ""))
        if desired_source in tuple(self.source["values"]):
            self.source.set(desired_source)
        self.remove_blank.set(bool(values.get("remove_blank", False)))
        self.auto_deskew.set(bool(values.get("auto_deskew", False)))
        self.auto_orient.set(bool(values.get("auto_orient", False)))

    def _save_profile(self) -> None:
        name = simpledialog.askstring(APP_TITLE, "Nome do novo perfil:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name or name in DEFAULT_SCAN_PROFILES:
            messagebox.showerror(APP_TITLE, "Escolha um nome diferente dos perfis padrão.", parent=self)
            return
        try:
            _save_scan_profile(name, self._profile_values())
            self.profiles = _load_scan_profiles()
            self.profile.configure(values=tuple(self.profiles))
            self.profile.set(name)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Não foi possível salvar o perfil: {exc}", parent=self)

    def _delete_profile(self) -> None:
        name = self.profile.get()
        if not _delete_scan_profile(name):
            messagebox.showinfo(APP_TITLE, "Os perfis padrão não podem ser excluídos.", parent=self)
            return
        self.profiles = _load_scan_profiles()
        self.profile.configure(values=tuple(self.profiles))
        self.profile.set("Documento padrão")

    def _poll_source_results(self) -> None:
        try:
            address, kind, payload = self._source_results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_source_results)
            return
        if address == self.address:
            if kind == "ok":
                scanner_name, serial_number, sources = payload
                values = [self.SOURCE_LABELS[source] for source in sources]
                self.source.configure(state="readonly", values=values)
                self.source.current(0)
                self._detected_ip = address
                self._detected_name = scanner_name
                self._detected_serial = serial_number
                serial_status = f"série {serial_number}" if serial_number else "número de série não informado"
                self.detection_status.configure(
                    text=f"{scanner_name} — {serial_status} — origens detectadas automaticamente."
                )
            else:
                self.detection_status.configure(text=str(payload))
            # A resposta pode ser maior que o texto inicial. Recalcula o tamanho
            # para evitar conteúdo e botões cortados e mantém a janela centralizada.
            self.after_idle(self._show_centered)
        self.after(100, self._poll_source_results)

    def accept(self) -> None:
        try:
            address, port, protocol = validate_ip_settings(self.address, 80, "http")
        except ESCLScannerError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        if self._detected_ip != address or self.source.current() < 0:
            self._start_detection()
            messagebox.showinfo(APP_TITLE, "Aguarde a detecção das opções de digitalização.", parent=self)
            return
        source_code = next(code for code, label in self.SOURCE_LABELS.items() if label == self.source.get())
        self.result = (
            address,
            self._detected_name or f"Scanner_{address}",
            self._detected_serial,
            port,
            protocol,
            int(self.dpi.get()),
            self.color.get(),
            source_code,
            self.paper_size.get(),
            self.output_format.get(),
            bool(self.ocr.get()) if self.output_format.get() == "PDF" else False,
            OCR_LANGUAGES[self.language.get()],
            bool(self.remove_blank.get()),
            bool(self.auto_deskew.get()),
            bool(self.auto_orient.get()),
        )
        self.destroy()


def _run_administrative_settings() -> None:
    root = tk.Tk()
    root.withdraw()
    root.title(f"{APP_TITLE} - Configurações administrativas")
    _apply_window_icon(root)
    if (
        sys.platform == "win32"
        and not is_process_elevated()
        and not is_windows_administrator()
    ):
        messagebox.showerror(
            APP_TITLE,
            "As configurações somente podem ser alteradas por um administrador local "
            "ou do Active Directory.",
            parent=root,
        )
        root.destroy()
        return
    dialog = OutputSettingsDialog(root, _load_output_settings(), _load_network_scanners())
    root.wait_window(dialog)
    root.destroy()


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ALAP.PDFScanner.v291")
        except (AttributeError, OSError):
            pass
    if "--configuracoes" in sys.argv:
        _run_administrative_settings()
    else:
        app = CentralApp()
        app.mainloop()


if __name__ == "__main__":
    main()
