from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import fitz
from PIL import Image, ImageTk


def selection_after_click(
    current: set[int], position: int, anchor: int | None, *, ctrl: bool, shift: bool
) -> tuple[set[int], int]:
    """Aplica a seleção comum do Windows: clique, Ctrl+clique e Shift+clique."""
    if shift and anchor is not None:
        interval = set(range(min(anchor, position), max(anchor, position) + 1))
        return ((current | interval) if ctrl else interval), anchor
    if ctrl:
        selected = set(current)
        if position in selected:
            selected.remove(position)
        else:
            selected.add(position)
        return selected, position
    return {position}, position


def merge_window_size(page_count: int, screen_width: int, screen_height: int) -> tuple[int, int]:
    """Dimensiona a janela para até cinco colunas e três linhas visíveis."""
    columns = max(1, min(5, page_count))
    rows = max(1, math.ceil(max(1, page_count) / columns))
    desired_width = max(900, columns * 175 + 80)
    desired_height = max(520, 190 + min(3, rows) * 220)
    return (
        min(desired_width, max(720, screen_width - 50)),
        min(desired_height, max(520, screen_height - 70)),
    )


def adjusted_zoom(current: float, factor: float) -> float:
    """Limita a ampliação da página entre 50% e 400%."""
    return min(4.0, max(0.5, current * factor))


class ThumbnailDialog(tk.Toplevel):
    """Janela visual centralizada para escolher páginas de PDF."""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent)
        self.resizable(True, True)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        try:
            inherited_icon = getattr(parent, "_window_icon", None)
            if inherited_icon is not None:
                self.iconphoto(True, inherited_icon)
        except tk.TclError:
            pass

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
            "remove": "Remover páginas - escolha pelas miniaturas",
            "divide": "Dividir PDF - escolha pelas miniaturas",
            "rotate": "Rotacionar páginas - escolha pelas miniaturas",
            "trim": "Cortar páginas - margem superior/inferior",
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
        prompt = "Clique nas páginas desejadas. Clique novamente para desmarcar."
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
            ttk.Label(controls, text="Rotação:").pack(side="left", padx=(18, 5))
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
                text=f"Página {index + 1}",
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
            messagebox.showerror("PDF & Scanner", "Selecione ao menos uma página.", parent=self)
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
                messagebox.showerror("PDF & Scanner", "Informe cortes válidos em centímetros.", parent=self)
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
        super().__init__(parent, "Juntar PDFs - organize as páginas")
        self.refs: list[tuple[str, int]] = []
        self.photos: list[ImageTk.PhotoImage] = []
        self.selected_indices: set[int] = {0}
        self.selection_anchor: int | None = 0
        for source in sources:
            document = fitz.open(source)
            try:
                for index, page in enumerate(document):
                    self.refs.append((source, index))
                    self.photos.append(self.render_page(page))
            finally:
                document.close()

        header = ttk.Frame(self, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Selecione páginas com clique, Ctrl+clique ou Shift+clique. Depois, altere a ordem ou remova.",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        self.summary = ttk.Label(header, text="")
        self.summary.pack(side="right")
        tools = ttk.Frame(self, padding=(16, 0, 16, 8))
        tools.pack(fill="x")
        ttk.Button(tools, text="Selecionar todas", command=self.select_all).pack(side="left")
        ttk.Button(tools, text="Limpar", command=self.clear_selection).pack(side="left", padx=6)
        ttk.Button(tools, text="Mover antes", command=lambda: self.move(-1)).pack(side="left")
        ttk.Button(tools, text="Mover depois", command=lambda: self.move(1)).pack(side="left", padx=6)
        ttk.Button(tools, text="Remover da união", command=self.remove).pack(side="left")

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=16)
        self.canvas = tk.Canvas(container, bg="#eef3f8", highlightthickness=0)
        vertical = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.grid = tk.Frame(self.canvas, bg="#eef3f8")
        self.grid.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid, anchor="nw")
        self.canvas.configure(yscrollcommand=vertical.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vertical.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind("<Configure>", lambda e: self._layout_buttons(e.width))
        self.buttons: list[tk.Button] = []
        self.redraw()

        footer = ttk.Frame(self, padding=16)
        footer.pack(fill="x")
        ttk.Button(footer, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Juntar", command=self.accept).pack(side="right", padx=8)
        self.after_idle(self._show_responsive)

    def _show_responsive(self) -> None:
        width, height = merge_window_size(
            len(self.refs), self.winfo_screenwidth(), self.winfo_screenheight()
        )
        self.show_centered(width, height)
        self.after_idle(lambda: self._layout_buttons(self.canvas.winfo_width()))

    def _layout_buttons(self, available_width: int) -> None:
        # Cinco páginas por linha no tamanho normal, reduzindo apenas quando o
        # usuário estreitar a janela.
        columns = max(1, min(5, (max(165, available_width) - 10) // 165))
        self.canvas.itemconfigure(self.canvas_window, width=max(1, available_width))
        for column in range(5):
            self.grid.columnconfigure(column, weight=1 if column < columns else 0)
        for position, button in enumerate(self.buttons):
            button.grid_configure(
                row=position // columns,
                column=position % columns,
                padx=10,
                pady=10,
                sticky="n",
            )

    def redraw(self) -> None:
        for widget in self.grid.winfo_children():
            widget.destroy()
        self.buttons.clear()
        self.selected_indices = {index for index in self.selected_indices if index < len(self.refs)}
        if self.refs and not self.selected_indices:
            self.selected_indices = {min(self.selection_anchor or 0, len(self.refs) - 1)}
        for position, ((source, page_index), photo) in enumerate(zip(self.refs, self.photos)):
            button = tk.Button(
                self.grid,
                image=photo,
                text=f"{position + 1}. {Path(source).name}\nPágina {page_index + 1}",
                compound="top",
                bg="#93c5fd" if position in self.selected_indices else "white",
                relief="solid",
                bd=2,
                padx=5,
                pady=5,
            )
            button.bind("<Button-1>", lambda event, value=position: self.choose(event, value))
            self.buttons.append(button)
        self._layout_buttons(self.canvas.winfo_width())
        self.summary.configure(
            text=f"{len(self.selected_indices)} selecionada(s) de {len(self.refs)} página(s)"
        )

    def select_all(self) -> None:
        self.selected_indices = set(range(len(self.refs)))
        self.selection_anchor = 0 if self.refs else None
        self.redraw()

    def clear_selection(self) -> None:
        self.selected_indices.clear()
        self.selection_anchor = None
        for button in self.buttons:
            button.configure(bg="white")
        self.summary.configure(text=f"0 selecionada(s) de {len(self.refs)} página(s)")

    def choose(self, event: tk.Event, position: int) -> str:
        self.selected_indices, self.selection_anchor = selection_after_click(
            self.selected_indices,
            position,
            self.selection_anchor,
            ctrl=bool(event.state & 0x0004),
            shift=bool(event.state & 0x0001),
        )
        self.redraw()
        return "break"

    def move(self, change: int) -> None:
        if not self.selected_indices:
            return
        selected = set(self.selected_indices)
        if change < 0:
            for index in sorted(selected):
                if index > 0 and index - 1 not in selected:
                    self.refs[index - 1], self.refs[index] = self.refs[index], self.refs[index - 1]
                    self.photos[index - 1], self.photos[index] = self.photos[index], self.photos[index - 1]
                    selected.remove(index)
                    selected.add(index - 1)
        else:
            for index in sorted(selected, reverse=True):
                if index < len(self.refs) - 1 and index + 1 not in selected:
                    self.refs[index + 1], self.refs[index] = self.refs[index], self.refs[index + 1]
                    self.photos[index + 1], self.photos[index] = self.photos[index], self.photos[index + 1]
                    selected.remove(index)
                    selected.add(index + 1)
        self.selected_indices = selected
        self.selection_anchor = min(selected) if selected else None
        self.redraw()

    def remove(self) -> None:
        if not self.selected_indices:
            return
        if len(self.selected_indices) >= len(self.refs):
            messagebox.showwarning("PDF & Scanner", "A união deve manter pelo menos uma página.", parent=self)
            return
        first = min(self.selected_indices)
        for index in sorted(self.selected_indices, reverse=True):
            self.refs.pop(index)
            self.photos.pop(index)
        self.selection_anchor = min(first, len(self.refs) - 1)
        self.selected_indices = {self.selection_anchor}
        self.redraw()

    def accept(self) -> None:
        if not self.refs:
            return
        self.result = list(self.refs)
        self.destroy()


class RedactionDialog(ThumbnailDialog):
    """Permite desenhar tarjas removidas definitivamente do PDF."""

    def __init__(self, parent: tk.Misc, source: str | Path) -> None:
        super().__init__(parent, "Tarjar Informações")
        self.source = Path(source)
        self.document = fitz.open(self.source)
        if self.document.needs_pass:
            self.document.close()
            raise ValueError("o arquivo está protegido por senha")
        if len(self.document) == 0:
            self.document.close()
            raise ValueError("o arquivo não contém páginas")
        self.page_index = 0
        self.redactions: dict[int, list[fitz.Rect]] = {}
        self.photo: ImageTk.PhotoImage | None = None
        self.scale = 1.0
        self.zoom_level = 1.0
        self._center_after_render = True
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.drag_start: tuple[float, float] | None = None
        self.drag_item: int | None = None
        self._render_after: str | None = None
        self.protocol("WM_DELETE_WINDOW", self.close)

        header = ttk.Frame(self, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Arraste o mouse sobre cada informação que deve ser removida definitivamente.",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        self.summary = ttk.Label(header, text="")
        self.summary.pack(side="right")

        tools = ttk.Frame(self, padding=(16, 0, 16, 8))
        tools.pack(fill="x")
        ttk.Button(tools, text="Página anterior", command=lambda: self.change_page(-1)).pack(side="left")
        ttk.Button(tools, text="Próxima página", command=lambda: self.change_page(1)).pack(side="left", padx=6)
        ttk.Button(tools, text="Desfazer última tarja", command=self.undo).pack(side="left", padx=(16, 6))
        ttk.Button(tools, text="Limpar página", command=self.clear_page).pack(side="left")
        ttk.Button(tools, text="Zoom −", command=lambda: self.change_zoom(0.8)).pack(side="left", padx=(16, 4))
        self.zoom_text = ttk.Label(tools, text="100%", width=6, anchor="center")
        self.zoom_text.pack(side="left")
        ttk.Button(tools, text="Zoom +", command=lambda: self.change_zoom(1.25)).pack(side="left", padx=4)
        ttk.Button(tools, text="Ajustar", command=self.fit_page).pack(side="left", padx=(0, 6))
        self.maximize_button = ttk.Button(tools, text="Maximizar", command=self.toggle_maximize)
        self.maximize_button.pack(side="left")

        content = ttk.Frame(self)
        content.pack(fill="both", expand=True, padx=16)
        side = ttk.Frame(content)
        side.pack(side="left", fill="y", padx=(0, 10))
        self.pages = tk.Listbox(side, width=18, exportselection=False, font=("Segoe UI", 10))
        page_scroll = ttk.Scrollbar(side, orient="vertical", command=self.pages.yview)
        self.pages.configure(yscrollcommand=page_scroll.set)
        self.pages.pack(side="left", fill="y")
        page_scroll.pack(side="right", fill="y")
        for index in range(len(self.document)):
            self.pages.insert("end", f"Página {index + 1}")
        self.pages.selection_set(0)
        self.pages.bind("<<ListboxSelect>>", self._page_selected)

        canvas_frame = ttk.Frame(content)
        canvas_frame.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#27364a", highlightthickness=0, cursor="crosshair")
        horizontal = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        vertical = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", self._schedule_render)
        self.canvas.bind("<ButtonPress-1>", self._drag_begin)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Control-MouseWheel>", self._zoom_wheel)

        footer = ttk.Frame(self, padding=16)
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="A tarja elimina o texto e a imagem da área marcada; não é apenas uma cobertura visual.",
            foreground="#8b1e1e",
        ).pack(side="left")
        ttk.Button(footer, text="Cancelar", command=self.close).pack(side="right")
        ttk.Button(footer, text="Aplicar tarjas", command=self.accept).pack(side="right", padx=8)
        self.after_idle(lambda: self.show_centered(1120, 780))

    def _schedule_render(self, _event=None) -> None:
        if self._render_after is not None:
            self.after_cancel(self._render_after)
        self._render_after = self.after(80, self.render_current_page)

    def render_current_page(self) -> None:
        self._render_after = None
        page = self.document[self.page_index]
        available_width = max(200, self.canvas.winfo_width() - 24)
        available_height = max(200, self.canvas.winfo_height() - 24)
        fit_scale = min(available_width / page.rect.width, available_height / page.rect.height)
        self.scale = fit_scale * self.zoom_level
        pixmap = page.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale), alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png")))
        self.photo = ImageTk.PhotoImage(image)
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        self.offset_x = max(12.0, (canvas_width - image.width) / 2)
        self.offset_y = max(12.0, (canvas_height - image.height) / 2)
        scroll_width = max(canvas_width, self.offset_x + image.width + 12)
        scroll_height = max(canvas_height, self.offset_y + image.height + 12)
        self.canvas.delete("all")
        self.canvas.create_image(self.offset_x, self.offset_y, image=self.photo, anchor="nw")
        for rectangle in self.redactions.get(self.page_index, []):
            self.canvas.create_rectangle(
                self.offset_x + rectangle.x0 * self.scale,
                self.offset_y + rectangle.y0 * self.scale,
                self.offset_x + rectangle.x1 * self.scale,
                self.offset_y + rectangle.y1 * self.scale,
                fill="black", outline="#dc2626", width=2, stipple="gray50",
            )
        self.canvas.configure(scrollregion=(0, 0, scroll_width, scroll_height))
        if self._center_after_render:
            if scroll_width > canvas_width:
                self.canvas.xview_moveto(((scroll_width - canvas_width) / 2) / scroll_width)
            else:
                self.canvas.xview_moveto(0)
            if scroll_height > canvas_height:
                self.canvas.yview_moveto(((scroll_height - canvas_height) / 2) / scroll_height)
            else:
                self.canvas.yview_moveto(0)
            self._center_after_render = False
        count = sum(len(items) for items in self.redactions.values())
        self.summary.configure(text=f"Página {self.page_index + 1} de {len(self.document)} - {count} tarja(s)")

    def change_zoom(self, factor: float) -> None:
        self.zoom_level = adjusted_zoom(self.zoom_level, factor)
        self.zoom_text.configure(text=f"{round(self.zoom_level * 100):d}%")
        self._center_after_render = True
        self.render_current_page()

    def fit_page(self) -> None:
        self.zoom_level = 1.0
        self.zoom_text.configure(text="100%")
        self._center_after_render = True
        self.render_current_page()

    def _zoom_wheel(self, event: tk.Event) -> str:
        self.change_zoom(1.25 if event.delta > 0 else 0.8)
        return "break"

    def toggle_maximize(self) -> None:
        try:
            maximized = self.state() == "zoomed"
            self.state("normal" if maximized else "zoomed")
            self.maximize_button.configure(text="Maximizar" if maximized else "Restaurar")
        except tk.TclError:
            # Alguns gerenciadores de janela usam o atributo em vez do estado.
            maximized = bool(self.attributes("-zoomed"))
            self.attributes("-zoomed", not maximized)
            self.maximize_button.configure(text="Maximizar" if maximized else "Restaurar")
        self._center_after_render = True
        self.after_idle(self.render_current_page)

    def _page_selected(self, _event=None) -> None:
        selection = self.pages.curselection()
        if selection:
            self.page_index = int(selection[0])
            self._center_after_render = True
            self.render_current_page()

    def change_page(self, change: int) -> None:
        target = min(max(0, self.page_index + change), len(self.document) - 1)
        self.pages.selection_clear(0, "end")
        self.pages.selection_set(target)
        self.pages.see(target)
        self.page_index = target
        self._center_after_render = True
        self.render_current_page()

    def _canvas_point(self, event: tk.Event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _inside_page(self, x: float, y: float) -> bool:
        page = self.document[self.page_index]
        return (
            self.offset_x <= x <= self.offset_x + page.rect.width * self.scale
            and self.offset_y <= y <= self.offset_y + page.rect.height * self.scale
        )

    def _drag_begin(self, event: tk.Event) -> None:
        x, y = self._canvas_point(event)
        if not self._inside_page(x, y):
            return
        self.drag_start = (x, y)
        self.drag_item = self.canvas.create_rectangle(
            x, y, x, y,
            fill="black", outline="#dc2626", width=2, stipple="gray50",
        )

    def _drag_move(self, event: tk.Event) -> None:
        if self.drag_start is not None and self.drag_item is not None:
            x, y = self._canvas_point(event)
            self.canvas.coords(self.drag_item, *self.drag_start, x, y)

    def _drag_end(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        x0, y0 = self.drag_start
        event_x, event_y = self._canvas_point(event)
        page = self.document[self.page_index]
        x1 = min(max(event_x, self.offset_x), self.offset_x + page.rect.width * self.scale)
        y1 = min(max(event_y, self.offset_y), self.offset_y + page.rect.height * self.scale)
        self.drag_start = None
        self.drag_item = None
        left, right = sorted(((x0 - self.offset_x) / self.scale, (x1 - self.offset_x) / self.scale))
        top, bottom = sorted(((y0 - self.offset_y) / self.scale, (y1 - self.offset_y) / self.scale))
        if right - left >= 2 and bottom - top >= 2:
            self.redactions.setdefault(self.page_index, []).append(fitz.Rect(left, top, right, bottom))
        self.render_current_page()

    def undo(self) -> None:
        values = self.redactions.get(self.page_index, [])
        if values:
            values.pop()
        self.render_current_page()

    def clear_page(self) -> None:
        self.redactions.pop(self.page_index, None)
        self.render_current_page()

    def accept(self) -> None:
        result = [
            (page_index, rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1)
            for page_index, rectangles in self.redactions.items()
            for rectangle in rectangles
        ]
        if not result:
            messagebox.showerror("PDF & Scanner", "Marque ao menos uma área para ocultar.", parent=self)
            return
        if not messagebox.askyesno(
            "PDF & Scanner",
            "As informações marcadas serão removidas definitivamente do novo PDF. Continuar?",
            parent=self,
        ):
            return
        self.result = result
        self.close(keep_result=True)

    def close(self, keep_result: bool = False) -> None:
        if not keep_result:
            self.result = None
        self.document.close()
        self.destroy()


class ScanPreviewDialog(ThumbnailDialog):
    """Pré-visualiza páginas digitalizadas antes de escolher o destino final."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        pdf_path: str | Path | None = None,
        image_paths: list[str | Path] | None = None,
    ) -> None:
        super().__init__(parent, "Pré-visualização da digitalização")
        if pdf_path:
            source = str(pdf_path)
            document = fitz.open(source)
            try:
                self.refs = [(source, index, 0) for index in range(len(document))]
            finally:
                document.close()
        else:
            self.refs = [(str(path), -1, 0) for path in (image_paths or [])]
        self.selected = 0
        self.photos: list[ImageTk.PhotoImage] = []
        self.buttons: list[tk.Button] = []

        ttk.Label(
            self,
            text="Revise as páginas. É possível reordenar, girar e excluir antes de salvar.",
            padding=(16, 12),
            font=("Segoe UI", 10, "bold"),
        ).pack(fill="x")
        tools = ttk.Frame(self, padding=(16, 0, 16, 8))
        tools.pack(fill="x")
        ttk.Button(tools, text="Mover antes", command=lambda: self.move(-1)).pack(side="left")
        ttk.Button(tools, text="Mover depois", command=lambda: self.move(1)).pack(side="left", padx=6)
        ttk.Button(tools, text="Girar à esquerda", command=lambda: self.rotate(-90)).pack(side="left", padx=(12, 6))
        ttk.Button(tools, text="Girar à direita", command=lambda: self.rotate(90)).pack(side="left")
        ttk.Button(tools, text="Excluir página", command=self.remove).pack(side="left", padx=(12, 0))
        self.summary = ttk.Label(tools, text="")
        self.summary.pack(side="right")

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=16)
        self.canvas = tk.Canvas(container, bg="#eef3f8", highlightthickness=0)
        vertical = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.grid = tk.Frame(self.canvas, bg="#eef3f8")
        self.grid.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.grid, anchor="nw")
        self.canvas.configure(yscrollcommand=vertical.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vertical.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        footer = ttk.Frame(self, padding=16)
        footer.pack(fill="x")
        ttk.Button(footer, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Salvar digitalização", command=self.accept).pack(side="right", padx=8)
        self.redraw()
        self.after_idle(lambda: self.show_centered(980, 700))

    def _render_ref(self, ref: tuple[str, int, int]) -> ImageTk.PhotoImage:
        source, page_index, rotation = ref
        if page_index >= 0:
            document = fitz.open(source)
            try:
                page = document[page_index]
                scale = min(145 / page.rect.width, 185 / page.rect.height)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
            finally:
                document.close()
        else:
            with Image.open(source) as opened:
                image = opened.convert("RGB")
                image.thumbnail((145, 185), Image.Resampling.LANCZOS)
        if rotation:
            image = image.rotate(-rotation, expand=True, fillcolor="white")
            image.thumbnail((145, 185), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

    def redraw(self) -> None:
        for widget in self.grid.winfo_children():
            widget.destroy()
        self.photos.clear()
        self.buttons.clear()
        self.selected = min(self.selected, max(0, len(self.refs) - 1))
        for position, ref in enumerate(self.refs):
            photo = self._render_ref(ref)
            self.photos.append(photo)
            rotation = f" — {ref[2]}°" if ref[2] else ""
            button = tk.Button(
                self.grid,
                image=photo,
                text=f"Página {position + 1}{rotation}",
                compound="top",
                bg="#93c5fd" if position == self.selected else "white",
                relief="solid",
                bd=2,
                padx=7,
                pady=7,
                command=lambda value=position: self.choose(value),
            )
            button.grid(row=position // 5, column=position % 5, padx=10, pady=10, sticky="n")
            self.buttons.append(button)
        self.summary.configure(text=f"{len(self.refs)} página(s)")

    def choose(self, position: int) -> None:
        self.selected = position
        self.redraw()

    def move(self, change: int) -> None:
        target = self.selected + change
        if target < 0 or target >= len(self.refs):
            return
        self.refs[self.selected], self.refs[target] = self.refs[target], self.refs[self.selected]
        self.selected = target
        self.redraw()

    def rotate(self, degrees: int) -> None:
        if not self.refs:
            return
        source, page_index, rotation = self.refs[self.selected]
        self.refs[self.selected] = (source, page_index, (rotation + degrees) % 360)
        self.redraw()

    def remove(self) -> None:
        if len(self.refs) <= 1:
            messagebox.showwarning("PDF & Scanner", "A digitalização deve manter pelo menos uma página.", parent=self)
            return
        self.refs.pop(self.selected)
        self.redraw()

    def accept(self) -> None:
        if not self.refs:
            return
        self.result = list(self.refs)
        self.destroy()
