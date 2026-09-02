from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__
from .ocr import find_tesseract
from .pdf_tools import (
    crop_pdf,
    images_to_pdf,
    merge_pdfs,
    pdf_to_jpg,
    protect_pdf,
    remove_pages,
    rotate_pages,
    unprotect_pdf,
)
from .scanner import list_scanners, scan_to_pdf
from .word_tools import pdf_to_word, word_to_pdf


APP_TITLE = "Central PDF & Scanner"
PDF_TYPES = [("Arquivo PDF", "*.pdf")]
WORD_TYPES = [("Documento Word", "*.docx")]
IMAGE_TYPES = [("Imagens", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff")]


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class CentralApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE} {__version__}")
        self.geometry("980x760")
        self.minsize(780, 650)
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
        style.configure("Header.TLabel", background="#173b67", foreground="white", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background="#173b67", foreground="#dbeafe", font=("Segoe UI", 10))
        style.configure("Card.TButton", font=("Segoe UI", 11, "bold"), padding=(16, 18))
        style.configure("Status.TLabel", background="#e8eef6", foreground="#173b67", padding=(12, 9))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(28, 22))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Digitalização, OCR e conversões locais em um só lugar",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        content = ttk.Frame(self, padding=(26, 24))
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="Escolha uma ferramenta", font=("Segoe UI", 15, "bold"), background="#f4f7fb").pack(anchor="w", pady=(0, 16))

        grid = ttk.Frame(content)
        grid.pack(fill="both", expand=True)
        for column in range(3):
            grid.columnconfigure(column, weight=1, uniform="cards")
        for row in range(4):
            grid.rowconfigure(row, weight=1, uniform="cards")

        actions = [
            ("Digitalizar / OCR", self.scan),
            ("Remover páginas", self.remove),
            ("Juntar PDFs", self.merge),
            ("Cortar PDF", self.crop),
            ("PDF para Word", self.to_word),
            ("Word para PDF", self.from_word),
            ("PDF para JPG", self.to_jpg),
            ("JPG para PDF", self.from_images),
            ("Girar páginas", self.rotate),
            ("Proteger PDF", self.protect),
            ("Desproteger PDF", self.unprotect),
        ]
        for index, (label, command) in enumerate(actions):
            button = ttk.Button(grid, text=label, command=command, style="Card.TButton")
            button.grid(row=index // 3, column=index % 3, sticky="nsew", padx=7, pady=7)

        footer = ttk.Frame(self, padding=(20, 0, 20, 18))
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=150)
        self.progress.pack(side="right", padx=(10, 0))
        self.status = ttk.Label(footer, text="Pronto. Seus arquivos permanecem no computador.", style="Status.TLabel")
        self.status.pack(side="left", fill="x", expand=True)

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
        pages = simpledialog.askstring("Remover páginas", "Páginas a remover (ex.: 2,4-6):", parent=self)
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
        output = self._save_pdf("Salvar PDF unido", "pdfs_unidos.pdf")
        if output:
            self._run("Juntando PDFs...", merge_pdfs, list(sources), output)

    def crop(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        dialog = CropDialog(self)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF cortado", f"{Path(source).stem}_cortado.pdf")
        if output:
            left, top, right, bottom, pages = dialog.result
            self._run("Cortando PDF...", crop_pdf, source, output, left, top, right, bottom, pages)

    def rotate(self) -> None:
        source = self._pick_pdf("Escolha o PDF")
        if not source:
            return
        dialog = RotateDialog(self)
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
        dpi = simpledialog.askinteger("PDF para JPG", "Resolução em DPI (72 a 600):", initialvalue=200, minvalue=72, maxvalue=600, parent=self)
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
        dialog = PasswordDialog(self, "Proteger PDF", confirm=True)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        output = self._save_pdf("Salvar PDF protegido", f"{Path(source).stem}_protegido.pdf")
        if output:
            self._run("Protegendo PDF com AES-256...", protect_pdf, source, output, dialog.result)

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
        device_id, dpi, color, use_ocr, language = dialog.result
        output = self._save_pdf("Salvar digitalização", "digitalizacao.pdf")
        if not output:
            return

        def ask_next(page: int) -> bool:
            event = threading.Event()
            answer = {"value": False}
            def prompt() -> None:
                answer["value"] = messagebox.askyesno(APP_TITLE, f"Página {page} digitalizada.\n\nDeseja digitalizar outra página?", parent=self)
                event.set()
            self.after(0, prompt)
            event.wait()
            return answer["value"]

        self._run(
            "Digitalizando documento...",
            scan_to_pdf,
            device_id,
            output,
            dpi=dpi,
            color_mode=color,
            use_ocr=use_ocr,
            language=language,
            app_dir=app_directory(),
            ask_next_page=ask_next,
        )


class BaseDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.body = ttk.Frame(self, padding=20)
        self.body.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def buttons(self, callback) -> None:
        row = ttk.Frame(self.body)
        row.grid(column=0, row=99, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(row, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Continuar", command=callback).pack(side="right", padx=(0, 8))


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
        self.ocr = tk.BooleanVar(value=False)
        ocr_text = "Aplicar OCR (PDF pesquisável)" if ocr_available else "Aplicar OCR (Tesseract não encontrado)"
        ttk.Checkbutton(self.body, text=ocr_text, variable=self.ocr, state="normal" if ocr_available else "disabled").grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 4))
        ttk.Label(self.body, text="Idioma OCR").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=5)
        self.language = ttk.Combobox(self.body, values=("por", "por+eng", "eng"), width=34)
        self.language.set("por+eng")
        self.language.grid(row=4, column=1, pady=5)
        ttk.Label(
            self.body,
            text="A lista inclui scanners de rede e USB instalados no Windows.",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.buttons(self.accept)

    def accept(self) -> None:
        index = self.combos[0].current()
        self.result = (
            self.devices[index].device_id,
            int(self.combos[1].get()),
            self.combos[2].get(),
            bool(self.ocr.get()),
            self.language.get().strip() or "por+eng",
        )
        self.destroy()


def main() -> None:
    app = CentralApp()
    app.mainloop()


if __name__ == "__main__":
    main()
