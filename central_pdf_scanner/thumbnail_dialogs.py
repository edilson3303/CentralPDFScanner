from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import fitz
from PIL import Image, ImageTk


class ThumbnailDialog(tk.Toplevel):
    """Janela visual centralizada para escolher paginas de PDF."""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent)
        self.resizable(True, True)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def show_centered(self, width: int = 940, height: int = 690) -> None:
        self.update_idletasks()
        width = min(width, self.winfo_screenwidth() - 80)
        height = min(height, self.winfo_screenheight() - 100)
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.grab_set()

    @staticmethod
    def render_page(page: fitz.Page, size: tuple[int, int] = (145, 185)) -> ImageTk.PhotoImage:
        scale = min(size[0] / page.rect.width, size[1] / page.rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.open(BytesIO(pix.tobytes("png")))
        return ImageTk.PhotoImage(image)


class PageSelectionDialog(ThumbnailDialog):
    def __init__(self, parent: tk.Misc, source: str | Path, mode: str) -> None:
        titles = {
            "remove": "Remover paginas - escolha pelas miniaturas",
            "divide": "Dividir PDF - escolha pelas miniaturas",
            "rotate": "Girar paginas - escolha pelas miniaturas",
            "trim": "Cortar margem superior/inferior",
        }
        super().__init__(parent, titles[mode])
        self.source = Path(source)
        self.mode = mode
        self.selected: set[int] = set()
        self.cards: list[tk.Button] = []
        self.photos: list[ImageTk.PhotoImage] = []
        self.document = fitz.open(self.source)
        self.protocol("WM_DELETE_WINDOW", self.close)

        header = ttk.Frame(self, padding=(16, 12))
        header.pack(fill="x")
        prompt = "Clique nas paginas desejadas. Clique novamente para desmarcar."
        if mode == "divide":
            prompt = "Use as miniaturas como referência e informe os intervalos que formarão arquivos separados."
        ttk.Label(header, text=prompt, font=("Segoe UI", 10, "bold")).pack(side="left")
        self.summary = ttk.Label(header, text="0 selecionada(s)")
        self.summary.pack(side="right")

        controls = ttk.Frame(self, padding=(16, 0, 16, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text="Selecionar todas", command=self.select_all).pack(side="left")
        ttk.Button(controls, text="Limpar", command=self.clear).pack(side="left", padx=6)
        if mode == "divide":
            ttk.Label(controls, text="Intervalos:").pack(side="left", padx=(18, 5))
            self.intervals = ttk.Entry(controls, width=30)
            self.intervals.insert(0, f"1-{len(self.document)}")
            self.intervals.pack(side="left")
            ttk.Label(controls, text="Ex.: 1-3,4-6,7-10").pack(side="left", padx=(8, 0))
        if mode == "rotate":
            ttk.Label(controls, text="Rotacao:").pack(side="left", padx=(18, 5))
            self.degrees = ttk.Combobox(controls, state="readonly", values=("90", "180", "270"), width=8)
            self.degrees.set("90")
            self.degrees.pack(side="left")
        if mode == "trim":
            ttk.Label(controls, text="Superior (cm):").pack(side="left", padx=(18, 5))
            self.top = ttk.Entry(controls, width=7)
            self.top.insert(0, "0")
            self.top.pack(side="left")
            ttk.Label(controls, text="Inferior (cm):").pack(side="left", padx=(12, 5))
            self.bottom = ttk.Entry(controls, width=7)
            self.bottom.insert(0, "0")
            self.bottom.pack(side="left")

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=16)
        canvas = tk.Canvas(container, bg="#eef3f8", highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.grid = tk.Frame(canvas, bg="#eef3f8")
        self.grid.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.grid, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        for index, page in enumerate(self.document):
            photo = self.render_page(page)
            self.photos.append(photo)
            card = tk.Button(
                self.grid,
                image=photo,
                text=f"Pagina {index + 1}",
                compound="top",
                bg="white",
                activebackground="#dbeafe",
                relief="solid",
                bd=2,
                padx=7,
                pady=7,
                command=lambda value=index: self.toggle(value),
            )
            card.grid(row=index // 5, column=index % 5, padx=10, pady=10, sticky="n")
            self.cards.append(card)

        footer = ttk.Frame(self, padding=16)
        footer.pack(fill="x")
        ttk.Button(footer, text="Cancelar", command=self.close).pack(side="right")
        ttk.Button(footer, text="Continuar", command=self.accept).pack(side="right", padx=8)
        if mode in {"divide", "rotate", "trim"}:
            self.select_all()
        self.after_idle(self.show_centered)

    def toggle(self, index: int) -> None:
        if index in self.selected:
            self.selected.remove(index)
            self.cards[index].configure(bg="white")
        else:
            self.selected.add(index)
            self.cards[index].configure(bg="#93c5fd")
        self.summary.configure(text=f"{len(self.selected)} selecionada(s)")

    def select_all(self) -> None:
        self.selected = set(range(len(self.cards)))
        for card in self.cards:
            card.configure(bg="#93c5fd")
        self.summary.configure(text=f"{len(self.selected)} selecionada(s)")

    def clear(self) -> None:
        self.selected.clear()
        for card in self.cards:
            card.configure(bg="white")
        self.summary.configure(text="0 selecionada(s)")

    def accept(self) -> None:
        if self.mode == "divide":
            value = self.intervals.get().strip()
            if not value:
                messagebox.showerror("PDF & Scanner", "Informe os intervalos, por exemplo: 1-3,4-6.", parent=self)
                return
            self.result = value
            self.close(keep_result=True)
            return
        if not self.selected:
            messagebox.showerror("PDF & Scanner", "Selecione ao menos uma pagina.", parent=self)
            return
        spec = ",".join(str(index + 1) for index in sorted(self.selected))
        if self.mode == "rotate":
            self.result = (int(self.degrees.get()), spec)
        elif self.mode == "trim":
            try:
                top = float(self.top.get().replace(",", "."))
                bottom = float(self.bottom.get().replace(",", "."))
                if top < 0 or bottom < 0 or top + bottom <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("PDF & Scanner", "Informe cortes validos em centimetros.", parent=self)
                return
            self.result = (top, bottom, spec)
        else:
            self.result = spec
        self.close(keep_result=True)

    def close(self, keep_result: bool = False) -> None:
        if not keep_result:
            self.result = None
        self.document.close()
        self.destroy()


class MergePagesDialog(ThumbnailDialog):
    def __init__(self, parent: tk.Misc, sources: list[str]) -> None:
        super().__init__(parent, "Juntar PDFs - organize as paginas")
        self.refs: list[tuple[str, int]] = []
        self.photos: list[ImageTk.PhotoImage] = []
        self.selected = 0
        for source in sources:
            document = fitz.open(source)
            try:
                for index, page in enumerate(document):
                    self.refs.append((source, index))
                    self.photos.append(self.render_page(page, (115, 150)))
            finally:
                document.close()

        ttk.Label(
            self,
            text="Clique numa miniatura e use os botoes para alterar a ordem ou remover da uniao.",
            padding=(16, 12),
            font=("Segoe UI", 10, "bold"),
        ).pack(fill="x")
        tools = ttk.Frame(self, padding=(16, 0, 16, 8))
        tools.pack(fill="x")
        ttk.Button(tools, text="Mover antes", command=lambda: self.move(-1)).pack(side="left")
        ttk.Button(tools, text="Mover depois", command=lambda: self.move(1)).pack(side="left", padx=6)
        ttk.Button(tools, text="Remover da uniao", command=self.remove).pack(side="left")

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=16)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(container, bg="#eef3f8", highlightthickness=0)
        vertical = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=self.canvas.xview)
        self.grid = tk.Frame(self.canvas, bg="#eef3f8")
        self.grid.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.grid, anchor="nw")
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(int(-e.delta / 120), "units"))
        self.buttons: list[tk.Button] = []
        self.redraw()

        footer = ttk.Frame(self, padding=16)
        footer.pack(fill="x")
        ttk.Button(footer, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Juntar", command=self.accept).pack(side="right", padx=8)
        self.after_idle(lambda: self.show_centered(1120, 620))

    def redraw(self) -> None:
        for widget in self.grid.winfo_children():
            widget.destroy()
        self.buttons.clear()
        self.selected = min(self.selected, max(0, len(self.refs) - 1))
        for position, ((source, page_index), photo) in enumerate(zip(self.refs, self.photos)):
            button = tk.Button(
                self.grid,
                image=photo,
                text=f"{position + 1}. {Path(source).name}\nPagina {page_index + 1}",
                compound="top",
                bg="#93c5fd" if position == self.selected else "white",
                relief="solid",
                bd=2,
                padx=5,
                pady=5,
                command=lambda value=position: self.choose(value),
            )
            button.grid(row=0, column=position, padx=7, pady=7, sticky="n")
            self.buttons.append(button)

    def choose(self, position: int) -> None:
        self.selected = position
        self.redraw()

    def move(self, change: int) -> None:
        target = self.selected + change
        if target < 0 or target >= len(self.refs):
            return
        self.refs[self.selected], self.refs[target] = self.refs[target], self.refs[self.selected]
        self.photos[self.selected], self.photos[target] = self.photos[target], self.photos[self.selected]
        self.selected = target
        self.redraw()

    def remove(self) -> None:
        if len(self.refs) <= 1:
            return
        self.refs.pop(self.selected)
        self.photos.pop(self.selected)
        self.redraw()

    def accept(self) -> None:
        if not self.refs:
            return
        self.result = list(self.refs)
        self.destroy()
