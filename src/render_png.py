"""PNG cizici (matplotlib).

Mumlar elle cizilir: hafta sonu/tatil bosluklarini yok etmek icin x ekseni
tarih degil tam sayi konumudur, etiketler sonradan takilir. Ayni yaklasim
plotly tarafinda da kullanildigi icin iki cikti bar bar ortusur.

Yerlesim inc cinsinden sabitlenmistir (oransal degil); boylece panel sayisi
degistiginde baslik seridi kaymaz.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter

from .plotspec import ChartSpec, Trace, segment_ranges
from .theme import Theme

_DASH = {None: "solid", "dash": (0, (5, 3)), "dot": (0, (1, 2.5))}

#: Baslik seridi ve alt bosluk (inc)
_HEADER_IN = 1.62
_FOOTER_IN = 0.45


def _compact(value: float, _pos: int = 0) -> str:
    """1_250_000 -> 1.25M. Hacim ekseninde '1e6' ofsetinden kurtarir."""
    for limit, suffix in ((1e12, "T"), (1e9, "Mr"), (1e6, "M"), (1e3, "B")):
        if abs(value) >= limit:
            return f"{value / limit:.2f}".rstrip("0").rstrip(".") + suffix
    return f"{value:.0f}"


def _price_fmt(value: float, _pos: int = 0) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", " ")
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.4g}"


def _x_ticks(index: pd.DatetimeIndex, count: int = 9) -> tuple[list[int], list[str]]:
    n = len(index)
    if n == 0:
        return [], []
    step = max(1, n // count)
    positions = list(range(0, n, step))
    # Son etiketi ancak bir onceki ile cakismayacaksa ekle
    if positions[-1] < n - 1 - step * 0.55:
        positions.append(n - 1)
    span_days = (index[-1] - index[0]).total_seconds() / 86400 if n > 1 else 1
    if span_days <= 3:
        fmt = "%H:%M"
    elif span_days <= 20:
        fmt = "%d %b %H:%M"
    elif span_days <= 400:
        fmt = "%d %b"
    else:
        fmt = "%b %y"
    return positions, [index[p].strftime(fmt) for p in positions]


def _draw_candles(ax, df: pd.DataFrame, theme: Theme) -> None:
    o = df["Open"].to_numpy(dtype="float64")
    h = df["High"].to_numpy(dtype="float64")
    low = df["Low"].to_numpy(dtype="float64")
    c = df["Close"].to_numpy(dtype="float64")
    n = len(df)
    x = np.arange(n)
    valid = ~np.isnan(o) & ~np.isnan(c)
    colors = np.where(c >= o, theme.c("up"), theme.c("down"))

    wicks = [[(x[i], low[i]), (x[i], h[i])] for i in range(n) if valid[i]]
    ax.add_collection(
        LineCollection(
            wicks,
            colors=[colors[i] for i in range(n) if valid[i]],
            linewidths=0.9,
            zorder=2,
            capstyle="butt",
        )
    )

    half = 0.32
    bodies, body_colors = [], []
    for i in range(n):
        if not valid[i]:
            continue
        top, bottom = max(o[i], c[i]), min(o[i], c[i])
        if top == bottom:  # doji gorunur kalsin
            pad = max((h[i] - low[i]) * 0.012, abs(top) * 1e-4)
            top, bottom = top + pad, bottom - pad
        bodies.append(
            [(x[i] - half, bottom), (x[i] - half, top), (x[i] + half, top), (x[i] + half, bottom)]
        )
        body_colors.append(colors[i])
    ax.add_collection(
        PolyCollection(
            bodies, facecolors=body_colors, edgecolors=body_colors, linewidths=0.4, zorder=3
        )
    )


def _draw_trace(ax, trace: Trace, theme: Theme, n: int) -> None:
    x = np.arange(n)
    color = theme.c(trace.color)

    if trace.kind in {"bars", "hist"} and trace.y is not None:
        y = np.nan_to_num(trace.y.to_numpy(dtype="float64"))
        bar_colors = (
            [theme.c(str(r)) for r in trace.colors] if trace.colors is not None else color
        )
        ax.bar(x, y, width=0.7, color=bar_colors, linewidth=0, zorder=2)
        return

    if trace.kind == "band" and trace.y is not None and trace.y2 is not None:
        upper = trace.y.to_numpy(dtype="float64")
        lower = trace.y2.to_numpy(dtype="float64")
        if trace.fill_alpha:
            ax.fill_between(x, lower, upper, color=color, alpha=trace.fill_alpha,
                            linewidth=0, zorder=trace.zorder)
        style = _DASH[trace.dash]
        ax.plot(x, upper, color=color, lw=trace.width, ls=style, zorder=trace.zorder,
                label=trace.name if trace.legend else None)
        ax.plot(x, lower, color=color, lw=trace.width, ls=style, zorder=trace.zorder)
        return

    if trace.kind == "cloud" and trace.y is not None and trace.y2 is not None:
        a = trace.y.to_numpy(dtype="float64")
        b = trace.y2.to_numpy(dtype="float64")
        up, down = theme.c(trace.color), theme.c(trace.color2 or trace.color)
        ax.fill_between(x, a, b, where=a >= b, color=up, alpha=trace.fill_alpha,
                        linewidth=0, zorder=trace.zorder, interpolate=True)
        ax.fill_between(x, a, b, where=a < b, color=down, alpha=trace.fill_alpha,
                        linewidth=0, zorder=trace.zorder, interpolate=True)
        ax.plot(x, a, color=up, lw=trace.width, zorder=trace.zorder, alpha=0.85,
                label=trace.name if trace.legend else None)
        ax.plot(x, b, color=down, lw=trace.width, zorder=trace.zorder, alpha=0.85)
        return

    if trace.kind == "segments" and trace.y is not None and trace.colors is not None:
        y = trace.y.to_numpy(dtype="float64")
        labelled = False
        # Yon degisiminde cizgi bilerek kopar: aksi halde flip noktalarinda
        # grafigi kesen dikey bir sicrama olusur.
        for start, end, role in segment_ranges(trace.colors):
            ax.plot(x[start:end], y[start:end], color=theme.c(role), lw=trace.width,
                    zorder=trace.zorder, solid_capstyle="round",
                    label=None if labelled or not trace.legend else trace.name)
            labelled = True
        return

    if trace.y is not None:
        ax.plot(x, trace.y.to_numpy(dtype="float64"), color=color, lw=trace.width,
                ls=_DASH[trace.dash], zorder=trace.zorder,
                label=trace.name if trace.legend else None)


def _style_axis(ax, theme: Theme, is_last: bool) -> None:
    ax.set_facecolor(theme.c("panel"))
    ax.grid(True, color=theme.c("grid"), lw=0.6, alpha=theme.grid_alpha, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_color(theme.c("axis"))
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=theme.c("muted"), labelsize=8, length=3, width=0.7)
    ax.tick_params(labelbottom=is_last)


def _panel_header(ax, title: str, theme: Theme) -> None:
    """Panel adini cizim alaninin USTUNE yazar.

    Icine yazilinca RSI/Stoch gibi dolu panellerde cizgilerin uzerine biniyordu.
    """
    ax.set_title(title, loc="left", color=theme.c("muted"), fontsize=8.5, pad=5)


def _legend(ax, theme: Theme, ncol: int = 6) -> None:
    """Efsaneyi de cizim alaninin ustune, saga yaslayarak koyar."""
    handles, _ = ax.get_legend_handles_labels()
    if not handles:
        return
    leg = ax.legend(
        loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=7.5,
        ncol=min(len(handles), ncol), handlelength=1.5, columnspacing=1.1,
        borderaxespad=0.15, labelspacing=0.2, handletextpad=0.5,
    )
    for text in leg.get_texts():
        text.set_color(theme.c("muted"))
    leg.set_zorder(6)


def _draw_header(fig, spec: ChartSpec, theme: Theme, fig_h: float) -> None:
    """Baslik seridi: solda sembol + alt bilgi, sagda durum rozetleri.

    Rozetler esit genislikte yuvalara yerlestirilir; metin genisligi olculmedigi
    icin panel sayisi ya da yazi tipi degistiginde yerlesim bozulmaz.
    """
    band = fig.add_axes([0.0, 1 - _HEADER_IN / fig_h, 1.0, _HEADER_IN / fig_h])
    band.set_axis_off()
    band.set_xlim(0, 1)
    band.set_ylim(0, 1)
    band.patch.set_alpha(0.0)

    left = 0.055
    # Uc satir: sembol+gorunum / bar bilgisi / gorunum notu. Tek satira
    # sikistirilinca uzun notlar sagdaki rozetlerin altina giriyordu.
    band.text(left, 0.80, spec.title, color=theme.c("text"), fontsize=18,
              fontweight="bold", va="center", ha="left")
    band.text(left, 0.50, spec.subtitle, color=theme.c("muted"), fontsize=9,
              va="center", ha="left")
    if spec.note:
        band.text(left, 0.24, spec.note, color=theme.c("muted"), fontsize=8.5,
                  va="center", ha="left", alpha=0.85)

    chips = spec.snapshot
    if not chips:
        return
    right_edge = 0.955
    block_start = max(0.40, right_edge - 0.070 * len(chips))
    slot = (right_edge - block_start) / len(chips)
    for i, (label, value, role) in enumerate(chips):
        cx = block_start + slot * (i + 0.5)
        band.text(cx, 0.72, value, color=theme.c(role), fontsize=11, fontweight="bold",
                  va="center", ha="center", family="DejaVu Sans Mono")
        band.text(cx, 0.47, label.upper(), color=theme.c("muted"), fontsize=7,
                  va="center", ha="center")
    divider = block_start - slot * 0.30
    band.plot([divider, divider], [0.36, 0.90], color=theme.c("axis"), lw=0.8)


def render_png(
    spec: ChartSpec,
    theme: Theme,
    path: str | Path,
    width_px: int = 1600,
    dpi: int = 130,
) -> Path:
    df = spec.df
    n = len(df)
    ratios = [spec.price_height] + [p.height for p in spec.panels]

    fig_w = width_px / dpi
    plot_h = sum(ratios) * fig_w / 10.8
    fig_h = plot_h + _HEADER_IN + _FOOTER_IN

    plt.rcParams["font.family"] = ["DejaVu Sans"]
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=theme.c("bg"))
    gs = GridSpec(
        len(ratios), 1,
        height_ratios=ratios,
        hspace=0.20,
        top=1 - _HEADER_IN / fig_h,
        bottom=_FOOTER_IN / fig_h,
        left=0.055,
        right=0.955,
    )

    _draw_header(fig, spec, theme, fig_h)

    # Fiyatin bittigi, yalnizca projeksiyonun (Ichimoku bulutu) surdugu bolge
    filled = df["Close"].notna().to_numpy().nonzero()[0]
    last_real = int(filled[-1]) if len(filled) else n - 1

    axes = []
    price_ax = fig.add_subplot(gs[0])
    axes.append(price_ax)
    if last_real < n - 1:
        price_ax.axvspan(last_real + 0.5, n - 0.5, color=theme.c("bg"), alpha=0.35, zorder=0)
    _draw_candles(price_ax, df, theme)
    for trace in spec.overlays:
        _draw_trace(price_ax, trace, theme, n)
    _style_axis(price_ax, theme, is_last=not spec.panels)
    price_ax.yaxis.set_major_formatter(FuncFormatter(_price_fmt))
    _legend(price_ax, theme, ncol=6)

    closes = df["Close"].dropna()
    if len(closes):
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else last
        role = "up" if last >= prev else "down"
        price_ax.axhline(last, color=theme.c(role), lw=0.8, ls=(0, (4, 3)), alpha=0.7, zorder=5)
        price_ax.annotate(
            f" {_price_fmt(last)} ",
            xy=(1.0, last), xycoords=("axes fraction", "data"),
            va="center", ha="left", fontsize=8.5, color=theme.c("bg"),
            family="DejaVu Sans Mono",
            bbox=dict(boxstyle="square,pad=0.3", fc=theme.c(role), ec="none"),
            annotation_clip=False, zorder=7,
        )

    for i, panel in enumerate(spec.panels):
        ax = fig.add_subplot(gs[i + 1], sharex=price_ax)
        axes.append(ax)
        if last_real < n - 1:
            ax.axvspan(last_real + 0.5, n - 0.5, color=theme.c("bg"), alpha=0.35, zorder=0)
        for hline in panel.hlines:
            ax.axhline(hline.value, color=theme.c(hline.color), lw=hline.width,
                       ls=_DASH[hline.dash], alpha=0.6, zorder=1)
        if panel.zero_line:
            ax.axhline(0, color=theme.c("axis"), lw=0.9, zorder=1)
        for trace in panel.traces:
            _draw_trace(ax, trace, theme, n)
        if panel.yrange:
            ax.set_ylim(*panel.yrange)
        if panel.key == "volume":
            ax.yaxis.set_major_formatter(FuncFormatter(_compact))
        _style_axis(ax, theme, is_last=(i == len(spec.panels) - 1))
        _panel_header(ax, panel.title, theme)
        _legend(ax, theme, ncol=4)

    ticks, labels = _x_ticks(df.index)
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels(labels, fontsize=8)
    price_ax.set_xlim(-1, n)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=theme.c("bg"), dpi=dpi)
    plt.close(fig)
    return path
