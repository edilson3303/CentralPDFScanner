from __future__ import annotations


# Dimensões em milímetros. ``None`` preserva a área máxima informada pelo
# scanner e é a opção mais compatível com vidros e alimentadores variados.
PAPER_SIZES_MM: dict[str, tuple[float, float] | None] = {
    "Automático (área máxima)": None,
    "A4 (210 × 297 mm)": (210.0, 297.0),
    "Carta (216 × 279 mm)": (215.9, 279.4),
    "Ofício (216 × 330 mm)": (215.9, 330.2),
    "Legal (216 × 356 mm)": (215.9, 355.6),
    "A3 (297 × 420 mm)": (297.0, 420.0),
    "A5 (148 × 210 mm)": (148.0, 210.0),
}


def paper_size_pixels(paper_size: str, dpi: int) -> tuple[int, int] | None:
    """Converte um tamanho conhecido para pixels na resolução escolhida."""
    dimensions = PAPER_SIZES_MM.get(paper_size)
    if dimensions is None:
        return None
    width_mm, height_mm = dimensions
    return round(width_mm / 25.4 * dpi), round(height_mm / 25.4 * dpi)


def paper_size_escl_units(paper_size: str) -> tuple[int, int] | None:
    """Converte para as unidades de 1/300 de polegada definidas pelo eSCL."""
    dimensions = PAPER_SIZES_MM.get(paper_size)
    if dimensions is None:
        return None
    width_mm, height_mm = dimensions
    return round(width_mm / 25.4 * 300), round(height_mm / 25.4 * 300)
