"""Renk ve tipografi belirtecleri.

Iki cizim arka ucu (matplotlib -> PNG, plotly -> HTML) ayni belirtec setini
okur; boylece bir rengi tek yerden degistirdiginizde iki cikti da degisir.
Trace nesneleri hex kod degil, buradaki rol adlarini tasir ("up", "accent1").
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    name: str
    colors: dict[str, str]
    font_body: str
    font_mono: str
    grid_alpha: float = 0.55

    def c(self, role: str) -> str:
        """Rol adini hex renge cevirir. Rol yoksa dogrudan hex kabul edilir."""
        return self.colors.get(role, role)


#: Varsayilan tema: mürekkep mavisi zemin, düşük doygunluklu ızgara.
#: BIST konvansiyonuna uygun olarak yükseliş yeşil, düşüş kırmızı.
INK = Theme(
    name="ink",
    colors={
        "bg": "#0E1420",
        "panel": "#131B29",
        "grid": "#1F2A3C",
        "axis": "#2C3A50",
        "text": "#C9D4E5",
        "muted": "#6E7F98",
        "up": "#26A96C",
        "down": "#E0525B",
        "up_soft": "#1B6E48",
        "down_soft": "#8F3339",
        "accent1": "#E8A33D",
        "accent2": "#9A87F0",
        "accent3": "#45B8E0",
        "accent4": "#E27DB0",
        "mint": "#6FD3B8",
        "vwap": "#EAF0FA",
        "neutral": "#7C8BA1",
    },
    font_body="IBM Plex Sans, DejaVu Sans, sans-serif",
    font_mono="IBM Plex Mono, DejaVu Sans Mono, monospace",
)

#: Baski / acik zemin alternatifi
PAPER = Theme(
    name="paper",
    colors={
        "bg": "#FBFAF7",
        "panel": "#FFFFFF",
        "grid": "#E4E2DC",
        "axis": "#C9C6BE",
        "text": "#1E2430",
        "muted": "#6B7280",
        "up": "#1B8A5A",
        "down": "#C63B43",
        "up_soft": "#9BD3B8",
        "down_soft": "#EFB2B5",
        "accent1": "#B7791F",
        "accent2": "#6D57C4",
        "accent3": "#1F7FA6",
        "accent4": "#B5527F",
        "mint": "#2F8F79",
        "vwap": "#2B3346",
        "neutral": "#8A94A6",
    },
    font_body="IBM Plex Sans, DejaVu Sans, sans-serif",
    font_mono="IBM Plex Mono, DejaVu Sans Mono, monospace",
    grid_alpha=0.8,
)

THEMES: dict[str, Theme] = {"ink": INK, "paper": PAPER}


def get_theme(name: str) -> Theme:
    if name not in THEMES:
        raise KeyError(f"Bilinmeyen tema: {name}. Gecerli: {sorted(THEMES)}")
    return THEMES[name]
