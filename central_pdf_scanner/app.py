from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

from . import __version__
from .escl_scanner import ESCLScannerError, detect_escl_info, scan_escl_to_pdf, validate_ip_settings
from .ocr import find_tesseract, pdf_to_searchable_pdf
from .pdf_tools import (
    crop_pdf,
    images_to_pdf,
    merge_pdfs,
    merge_pdf_pages,
    pdf_to_jpg,
    protect_pdf,
    remove_pages,
    rotate_pages,
    split_pdf,
    trim_vertical_pdf,
    unprotect_pdf,
)
from .scanner import list_scanners, scan_to_pdf
from .word_tools import pdf_to_word, word_to_pdf
from .thumbnail_dialogs import MergePagesDialog, PageSelectionDialog


APP_TITLE = "PDF & Scanner"
PDF_TYPES = [("Arquivo PDF", "*.pdf")]
WORD_TYPES = [("Documento Word", "*.docx")]
IMAGE_TYPES = [("Imagens", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff")]
OCR_LANGUAGES = {
    "Português": "por",
    "Português + Inglês": "por+eng",
    "Inglês": "eng",
}


def default_scan_basename(scanner_name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", scanner_name).strip(" ._") or "Scanner"
    safe = re.sub(r"\s+", "_", safe)
    return f"Scan_{safe}_{datetime.now():%Y-%m-%d_%H-%M-%S}"


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return app_directory() / relative


def _load_last_scanner_ip() -> str:
    try:
        data = json.loads((app_directory() / "configuracao.json").read_text(encoding="utf-8"))
        address, _, _ = validate_ip_settings(str(data.get("ultimo_ip_scanner", "")), 80, "http")
        return address
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ESCLScannerError):
        return ""


def _save_last_scanner_ip(ip_address: str) -> None:
    target = app_directory() / "configuracao.json"
    temporary = target.with_suffix(".tmp")
    try:
        temporary.write_text(
            json.dumps({"ultimo_ip_scanner": ip_address}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


class CentralApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE} {__version__}")
        self.geometry("1040x780")
        self.minsize(820, 680)
        self.configure(bg="#f4f7fb")
        self._results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self._configure_style()
        self._build_ui()
        self.after(100, self._poll_results)

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
            ],
            columns=2,
            primary=True,
        ).pack(fill="x", pady=(0, 12))
        self._build_section(
            content,
            "Edição de PDF",
            [
                ("Remover páginas", self.remove),
                ("Juntar PDFs", self.merge),
                ("Proteger PDF", self.protect),
                ("Girar páginas", self.rotate),
                ("Dividir PDF", self.divide),
                ("Desproteger PDF", self.unprotect),
                ("Cortar PDF", self.trim),
            ],
            columns=3,
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
            ],
            columns=4,
        ).pack(fill="x")

        footer = ttk.Frame(self, padding=(20, 0, 20, 18))
        footer.pack(fill="x")
        ttk.Button(footer, text="Licença", command=self.show_license).pack(side="left", padx=(0, 8))
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

    def _save_pdf(self, title: str, suggested: str) -> str:
        return filedialog.asksaveasfilename(parent=self, title=title, defaultextension=".pdf", initialfile=suggested, filetypes=PDF_TYPES)

    def _run(self, label: str, function, *args, **kwargs) -> None:
        if self._busy:
            messagebox.showinfo(APP_TITLE, "Aguarde a operação atual terminar.", parent=self)
            return
        self._busy = True
        self.status.configure(text=label)
        self.progress.start(12)

        def worker() -> None:
            try:
                result = function(*args, **kwargs)
                self._results.put(("ok", result))
            except Exception as exc:
                details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                self._results.put(("error", details))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self) -> None:
        try:
            kind, payload = self._results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_results)
            return
        self._busy = False
        self.progress.stop()
        if kind == "ok":
            self.status.configure(text="Operação concluída com sucesso.")
            display = payload
            if isinstance(payload, list):
                display = f"{len(payload)} arquivo(s) criado(s)."
            if messagebox.askyesno(APP_TITLE, f"Concluído.\n\n{display}\n\nDeseja abrir o local do resultado?", parent=self):
                self._open_location(payload)
        else:
            self.status.configure(text="Não foi possível concluir a operação.")
            messagebox.showerror(APP_TITLE, str(payload), parent=self)
        self.after(100, self._poll_results)

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
        folder = filedialog.askdirectory(parent=self, title="Escolha a pasta para as paginas divididas")
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
            self._run("Aplicando OCR ao PDF...", pdf_to_searchable_pdf, source, output, dialog.result, app_directory())

    def show_license(self) -> None:
        LicenseDialog(self)

    def to_word(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        output = filedialog.asksaveasfilename(parent=self, title="Salvar documento Word", defaultextension=".docx", initialfile=f"{Path(source).stem}.docx", filetypes=WORD_TYPES)
        if output:
            self._run("Convertendo PDF para Word...", pdf_to_word, source, output, "best", app_directory())

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
        dialog = PasswordDialog(self, "Desproteger PDF", confirm=False)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF sem senha", f"{Path(source).stem}_sem_senha.pdf")
        if output:
            self._run("Removendo proteção do PDF...", unprotect_pdf, source, output, dialog.result)

    def scan(self) -> None:
        try:
            devices = list_scanners()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        if not devices:
            messagebox.showwarning(APP_TITLE, "Nenhum scanner WIA foi encontrado no Windows.", parent=self)
            return
        dialog = ScanDialog(self, devices, find_tesseract(app_directory()) is not None)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        device_id, device_name, dpi, color, input_source, output_format, use_ocr, language = dialog.result
        basename = default_scan_basename(device_name)
        if output_format == "PDF":
            output = self._save_pdf("Salvar digitalização", f"{basename}.pdf")
        else:
            output = filedialog.askdirectory(parent=self, title="Escolha a pasta para os arquivos JPG")
        if not output:
            return

        self._run(
            "Digitalizando documento...",
            scan_to_pdf,
            device_id,
            output,
            dpi=dpi,
            color_mode=color,
            input_source=input_source,
            use_ocr=use_ocr,
            language=language,
            app_dir=app_directory(),
            ask_next_page=self._ask_next_page,
            output_format=output_format,
            filename_prefix=basename,
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
        dialog = IPScanDialog(self, find_tesseract(app_directory()) is not None, _load_last_scanner_ip())
        self.wait_window(dialog)
        if dialog.result is None:
            return
        ip_address, scanner_name, port, protocol, dpi, color, input_source, output_format, use_ocr, language = dialog.result
        _save_last_scanner_ip(ip_address)
        basename = default_scan_basename(scanner_name)
        if output_format == "PDF":
            output = self._save_pdf("Salvar digitalização por IP", f"{basename}.pdf")
        else:
            output = filedialog.askdirectory(parent=self, title="Escolha a pasta para os arquivos JPG")
        if not output:
            return
        self._run(
            f"Conectando ao scanner {ip_address}...",
            scan_escl_to_pdf,
            ip_address,
            port,
            protocol,
            output,
            dpi=dpi,
            color_mode=color,
            input_source=input_source,
            use_ocr=use_ocr,
            language=language,
            app_dir=app_directory(),
            ask_next_page=self._ask_next_page,
            output_format=output_format,
            filename_prefix=basename,
        )


class BaseDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
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


class CropDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Cortar PDF")
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
        super().__init__(parent, "Girar páginas")
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
        self.require_opening = tk.BooleanVar(value=True)
        self.restrict_editing = tk.BooleanVar(value=True)
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


class LicenseDialog(BaseDialog):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Licença de uso")
        self.resizable(True, True)
        text = tk.Text(self.body, width=90, height=28, wrap="word", padx=12, pady=12)
        scroll = ttk.Scrollbar(self.body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        try:
            content = (app_directory() / "LICENCA.txt").read_text(encoding="utf-8")
        except OSError:
            content = "Termos de licença não encontrados neste pacote."
        text.insert("1.0", content)
        text.configure(state="disabled")
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)
        row = ttk.Frame(self.body)
        row.grid(row=99, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(row, text="Fechar", command=self.destroy).pack()
        self.after_idle(lambda: self._show_centered_size(900, 620))

    def _show_centered_size(self, width: int, height: int) -> None:
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.grab_set()


class ScanDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, devices, ocr_available: bool) -> None:
        super().__init__(parent, "Digitalizar documento")
        self.devices = devices
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
        ttk.Label(self.body, text="Formato de saída").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=5)
        self.output_format = ttk.Combobox(self.body, state="readonly", values=("PDF", "JPG"), width=34)
        self.output_format.set("PDF")
        self.output_format.grid(row=4, column=1, pady=5)
        self.ocr = tk.BooleanVar(value=False)
        ocr_text = "Aplicar OCR (PDF pesquisável)" if ocr_available else "Aplicar OCR (Tesseract não encontrado)"
        ttk.Checkbutton(self.body, text=ocr_text, variable=self.ocr, state="normal" if ocr_available else "disabled").grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 4))
        ttk.Label(self.body, text="Idioma OCR").grid(row=6, column=0, sticky="w", padx=(0, 12), pady=5)
        self.language = ttk.Combobox(self.body, state="readonly", values=tuple(OCR_LANGUAGES), width=34)
        self.language.set("Português + Inglês")
        self.language.grid(row=6, column=1, pady=5)
        ttk.Label(
            self.body,
            text="A lista inclui scanners de rede e USB instalados no Windows.",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.buttons(self.accept)

    def _scanner_changed(self, _event=None) -> None:
        index = self.combos[0].current()
        sources = self.devices[index].sources if index >= 0 else ("Vidro",)
        self.source.configure(values=sources)
        self.source.current(0)

    def accept(self) -> None:
        index = self.combos[0].current()
        self.result = (
            self.devices[index].device_id,
            self.devices[index].name,
            int(self.combos[1].get()),
            self.combos[2].get(),
            self.source.get(),
            self.output_format.get(),
            bool(self.ocr.get()) if self.output_format.get() == "PDF" else False,
            OCR_LANGUAGES[self.language.get()],
        )
        self.destroy()


class IPScanDialog(BaseDialog):
    SOURCE_LABELS = {
        "Platen": "Vidro",
        "Feeder": "Alimentador superior - somente frente",
        "FeederDuplex": "Alimentador superior - frente e verso",
    }

    def __init__(self, parent: tk.Misc, ocr_available: bool, last_ip: str = "") -> None:
        super().__init__(parent, "Scanner de rede")
        self._source_results: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self._detect_after = None
        self._detected_ip = ""
        self._detected_name = ""
        ttk.Label(self.body, text="IP da multifuncional").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=5)
        self.ip_address = ttk.Entry(self.body, width=35)
        self.ip_address.insert(0, last_ip)
        self.ip_address.grid(row=0, column=1, pady=5)
        self.ip_address.focus_set()

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

        ttk.Label(self.body, text="Formato de saída").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=5)
        self.output_format = ttk.Combobox(self.body, state="readonly", values=("PDF", "JPG"), width=32)
        self.output_format.set("PDF")
        self.output_format.grid(row=4, column=1, pady=5)

        self.ocr = tk.BooleanVar(value=False)
        ocr_text = "Aplicar OCR (PDF pesquisável)" if ocr_available else "Aplicar OCR (Tesseract não encontrado)"
        ttk.Checkbutton(
            self.body,
            text=ocr_text,
            variable=self.ocr,
            state="normal" if ocr_available else "disabled",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 4))

        ttk.Label(self.body, text="Idioma OCR").grid(row=6, column=0, sticky="w", padx=(0, 12), pady=5)
        self.language = ttk.Combobox(self.body, state="readonly", values=tuple(OCR_LANGUAGES), width=32)
        self.language.set("Português + Inglês")
        self.language.grid(row=6, column=1, pady=5)
        self.detection_status = ttk.Label(
            self.body,
            text="Digite o IP para detectar vidro e alimentador.",
            foreground="#476582",
        )
        self.detection_status.grid(row=7, column=0, columnspan=2, sticky="w", pady=(9, 0))
        self.ip_address.bind("<KeyRelease>", self._schedule_detection)
        self.bind("<Return>", lambda _event: self.accept())
        self.buttons(self.accept)
        self.after(100, self._poll_source_results)
        if last_ip:
            self._schedule_detection(delay=150)

    def _schedule_detection(self, _event=None, *, delay: int = 700) -> None:
        if self._detect_after is not None:
            self.after_cancel(self._detect_after)
        self._detected_ip = ""
        self._detected_name = ""
        self.source.set("")
        self.source.configure(state="disabled", values=())
        self.detection_status.configure(text="Aguardando o endereço IP...")
        self._detect_after = self.after(delay, self._start_detection)

    def _start_detection(self) -> None:
        self._detect_after = None
        try:
            address, _, _ = validate_ip_settings(self.ip_address.get(), 80, "http")
        except ESCLScannerError:
            self.detection_status.configure(text="Digite um endereço IP válido.")
            return
        self.detection_status.configure(text="Detectando vidro e alimentador...")

        def worker() -> None:
            try:
                info = detect_escl_info(address, 80, "http")
                self._source_results.put((address, "ok", info))
            except Exception as exc:
                self._source_results.put((address, "error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_source_results(self) -> None:
        try:
            address, kind, payload = self._source_results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_source_results)
            return
        if address == self.ip_address.get().strip():
            if kind == "ok":
                scanner_name, sources = payload
                values = [self.SOURCE_LABELS[source] for source in sources]
                self.source.configure(state="readonly", values=values)
                self.source.current(0)
                self._detected_ip = address
                self._detected_name = scanner_name
                self.detection_status.configure(text=f"{scanner_name} - origens detectadas automaticamente.")
            else:
                self.detection_status.configure(text=str(payload))
        self.after(100, self._poll_source_results)

    def accept(self) -> None:
        try:
            address, port, protocol = validate_ip_settings(self.ip_address.get(), 80, "http")
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
            port,
            protocol,
            int(self.dpi.get()),
            self.color.get(),
            source_code,
            self.output_format.get(),
            bool(self.ocr.get()) if self.output_format.get() == "PDF" else False,
            OCR_LANGUAGES[self.language.get()],
        )
        self.destroy()


def main() -> None:
    app = CentralApp()
    app.mainloop()


if __name__ == "__main__":
    main()
