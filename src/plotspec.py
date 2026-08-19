"""Cizim tarifi (backend'den bagimsiz).

indicators.py'nin urettigi Series sozlugu burada "ne cizilecek" tarifine
donusur: fiyat uzerine binen katmanlar (overlay) ve alttaki ayri paneller.
matplotlib ve plotly arka uclari bu tarifi okuyup kendi dilinde cizer. Yeni
bir gosterge eklemek icin tek yapilacak sey buraya bir builder yazmaktir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Trace:
    """Tek bir cizgi/bant/bar serisi."""

    name: str
    kind: str = "line"  # line | band | cloud | bars | hist | segments
    y: pd.Series | None = None
    y2: pd.Series | None = None  # band/cloud/segments icin ikinci sinir
    color: str = "accent1"  # tema rol adi
    color2: str | None = None  # cloud/bars icin ikinci renk
    width: float = 1.4
    dash: str | None = None  # None | dash | dot
    fill_alpha: float = 0.0
    colors: pd.Series | None = None  # bar/segment basina rol adi
    legend: bool = True
    zorder: int = 2


@dataclass
class HLine:
    value: float
    color: str = "muted"
    dash: str | None = "dot"
    label: str | None = None
    width: float = 0.9


@dataclass
class Panel:
    """Fiyatin altindaki bagimsiz cizim alani."""

    key: str
    title: str
    traces: list[Trace]
    height: float = 1.0  # fiyat paneline gore oransal yukseklik
    hlines: list[HLine] = field(default_factory=list)
    yrange: tuple[float, float] | None = None
    zero_line: bool = False


@dataclass
class ChartSpec:
    df: pd.DataFrame
    overlays: list[Trace]
    panels: list[Panel]
    title: str
    subtitle: str
    snapshot: list[tuple[str, str, str]]  # (etiket, deger, renk rolu)
    note: str = ""  # gorunum aciklamasi (baslikta ucuncu satir)
    price_height: float = 3.4


# --------------------------------------------------------------------------
# Gosterge -> Trace/Panel donusturuculeri
# --------------------------------------------------------------------------

#: Ortalamalar amber -> camgobegi -> mor sirasiyla; VWAP ve Ichimoku
#: cizgileri baska belirtec kullanir, boylece hicbir ikisi ayni renk olmaz.
_MA_COLORS = ("accent1", "accent3", "accent2", "accent4")


def _ma_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    keys = [k for k in s if k.startswith(("EMA", "SMA"))]
    # Uzun periyot daha kalin cizilsin
    keys.sort(key=lambda k: int("".join(ch for ch in k if ch.isdigit()) or 0))
    out = []
    for i, key in enumerate(keys):
        length = int("".join(ch for ch in key if ch.isdigit()) or 0)
        out.append(
            Trace(
                name=key,
                y=s[key],
                color=_MA_COLORS[i % len(_MA_COLORS)],
                width=1.1 + min(length, 200) / 250.0,
                zorder=3,
            )
        )
    return out


def _bb_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(
            name="Bollinger 20/2",
            kind="band",
            y=s["BB_upper"],
            y2=s["BB_lower"],
            color="neutral",
            width=0.9,
            dash="dash",
            fill_alpha=0.07,
            zorder=1,
        ),
        Trace(name="BB orta", y=s["BB_mid"], color="neutral", width=0.8, dash="dot", legend=False),
    ]


def _supertrend_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    roles = s["ST_dir"].map({1.0: "up", -1.0: "down"})
    return [
        Trace(
            name="Supertrend",
            kind="segments",
            y=s["ST_line"],
            colors=roles,
            width=1.9,
            zorder=4,
        )
    ]


def _ichimoku_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(
            name="Kumo",
            kind="cloud",
            y=s["ICH_span_a"],
            y2=s["ICH_span_b"],
            color="up_soft",
            color2="down_soft",
            fill_alpha=0.20,
            width=0.7,
            zorder=0,
        ),
        Trace(name="Tenkan 9", y=s["ICH_tenkan"], color="mint", width=1.0),
        Trace(name="Kijun 26", y=s["ICH_kijun"], color="accent4", width=1.2),
    ]


def _vwap_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(
            name="VWAP bandi",
            kind="band",
            y=s["VWAP_upper"],
            y2=s["VWAP_lower"],
            color="vwap",
            width=0.7,
            dash="dot",
            fill_alpha=0.05,
            legend=False,
            zorder=1,
        ),
        Trace(name="VWAP", y=s["VWAP"], color="vwap", width=1.3, zorder=3),
    ]


def _volume_panel(df: pd.DataFrame, s: dict[str, pd.Series]) -> Panel:
    roles = np.where(df["Close"] >= df["Open"], "up", "down")
    return Panel(
        key="volume",
        title="Hacim · RVOL",
        height=0.75,
        traces=[
            Trace(
                name="Hacim",
                kind="bars",
                y=s["VOL"],
                colors=pd.Series(roles, index=df.index),
                legend=False,
            ),
            Trace(name="Hacim ort. 20", y=s["VOL_ma"], color="accent1", width=1.2),
        ],
    )


def _rsi_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="rsi",
        title="RSI 14",
        height=0.8,
        traces=[
            Trace(name="RSI", y=s["RSI"], color="accent3", width=1.5),
            Trace(name="RSI MA 14", y=s["RSI_ma"], color="muted", width=1.0, dash="dash"),
        ],
        hlines=[
            HLine(70, "down", "dash", "70"),
            HLine(50, "muted", "dot", "50"),
            HLine(30, "up", "dash", "30"),
        ],
        yrange=(0, 100),
    )


def _macd_panel(s: dict[str, pd.Series]) -> Panel:
    hist = s["MACD_hist"]
    rising = hist.diff() >= 0
    roles = pd.Series(
        np.where(hist >= 0, np.where(rising, "up", "up_soft"), np.where(rising, "down_soft", "down")),
        index=hist.index,
    )
    return Panel(
        key="macd",
        title="MACD 12/26/9",
        height=0.85,
        traces=[
            Trace(name="Histogram", kind="hist", y=hist, colors=roles, legend=False),
            Trace(name="MACD", y=s["MACD"], color="accent3", width=1.4),
            Trace(name="Sinyal", y=s["MACD_signal"], color="accent1", width=1.2),
        ],
        zero_line=True,
    )


def _stochrsi_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="stochrsi",
        title="Stoch RSI 14/14/3/3",
        height=0.7,
        traces=[
            Trace(name="%K", y=s["SRSI_k"], color="accent2", width=1.4),
            Trace(name="%D", y=s["SRSI_d"], color="accent1", width=1.1, dash="dash"),
        ],
        hlines=[HLine(80, "down", "dash", "80"), HLine(20, "up", "dash", "20")],
        yrange=(0, 100),
    )


def _adx_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="adx",
        title="ADX / DMI 14",
        height=0.75,
        traces=[
            Trace(name="+DI", y=s["DI_plus"], color="up", width=1.1),
            Trace(name="-DI", y=s["DI_minus"], color="down", width=1.1),
            Trace(name="ADX", y=s["ADX"], color="accent1", width=1.6),
        ],
        hlines=[HLine(25, "muted", "dash", "25")],
    )


def _bbstate_panel(s: dict[str, pd.Series]) -> Panel:
    """%B: fiyatin bantlar icindeki konumu. 1 = ust bant, 0 = alt bant."""
    return Panel(
        key="bbstate",
        title="Bollinger %B",
        height=0.7,
        traces=[Trace(name="%B", y=s["BB_percent_b"], color="accent3", width=1.4)],
        hlines=[
            HLine(1.0, "down", "dash", "1"),
            HLine(0.5, "muted", "dot", "0.5"),
            HLine(0.0, "up", "dash", "0"),
        ],
    )


def _bbwidth_panel(s: dict[str, pd.Series]) -> Panel:
    """Bant genisligi: sikisma (squeeze) ve genisleme donemlerini gosterir."""
    width = s["BB_width"]
    clean = width.dropna()
    # Sikisma esigi: gecmisin en dar %20'si. Sabit bir sayi her hissede
    # anlamli olmadigi icin serinin kendi dagilimindan turetiliyor.
    squeeze = float(clean.quantile(0.20)) if len(clean) else 0.0
    hlines = [HLine(squeeze, "accent2", "dash", "sıkışma")] if squeeze > 0 else []
    return Panel(
        key="bbwidth",
        title="Bant genişliği",
        height=0.65,
        traces=[Trace(name="Genişlik", y=width, color="accent1", width=1.4)],
        hlines=hlines,
    )


def _rvol_panel(s: dict[str, pd.Series]) -> Panel:
    """Bagil hacim: 1.0 = 20 barlik ortalamayla ayni hacim."""
    return Panel(
        key="rvol",
        title="RVOL",
        height=0.6,
        traces=[Trace(name="RVOL", y=s["RVOL"], color="accent2", width=1.4)],
        hlines=[HLine(2.0, "down", "dash", "2x"), HLine(1.0, "muted", "dash", "1x")],
    )


_OVERLAY_BUILDERS = {
    "ma": lambda df, s: _ma_overlays(s),
    "bbands": lambda df, s: _bb_overlays(s),
    "supertrend": lambda df, s: _supertrend_overlays(s),
    "ichimoku": lambda df, s: _ichimoku_overlays(s),
    "vwap": lambda df, s: _vwap_overlays(s),
}

_PANEL_BUILDERS = {
    "volume": lambda df, s: _volume_panel(df, s),
    "rsi": lambda df, s: _rsi_panel(s),
    "macd": lambda df, s: _macd_panel(s),
    "stochrsi": lambda df, s: _stochrsi_panel(s),
    "adx": lambda df, s: _adx_panel(s),
    "bbstate": lambda df, s: _bbstate_panel(s),
    "bbwidth": lambda df, s: _bbwidth_panel(s),
    "rvol": lambda df, s: _rvol_panel(s),
}

#: Cizim anahtari -> ihtiyac duydugu hesap anahtari.
#: Bir gorunum yalnizca kullandigi gostergeleri hesaplatsin diye gerekli.
REQUIRES: dict[str, tuple[str, ...]] = {
    "ma": ("ma",),
    "bbands": ("bbands",),
    "supertrend": ("supertrend",),
    "ichimoku": ("ichimoku",),
    "vwap": ("vwap",),
    "volume": ("volume",),
    "rsi": ("rsi",),
    "macd": ("macd",),
    "stochrsi": ("stochrsi",),
    "adx": ("adx",),
    "bbstate": ("bbands",),
    "bbwidth": ("bbands",),
    "rvol": ("volume",),
}


def compute_keys_for(draw_keys: tuple[str, ...]) -> tuple[str, ...]:
    """Cizilecek katmanlarin gerektirdigi hesap anahtarlarini sirali dondurur."""
    out: list[str] = []
    for key in draw_keys:
        for required in REQUIRES.get(key, (key,)):
            if required not in out:
                out.append(required)
    return tuple(out)


# --------------------------------------------------------------------------
# Ozet serit
# --------------------------------------------------------------------------


def _fmt(value: float, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ")


def _last(series: pd.Series | None) -> float:
    if series is None:
        return float("nan")
    clean = series.dropna()
    return float(clean.iloc[-1]) if len(clean) else float("nan")


def build_snapshot(df: pd.DataFrame, s: dict[str, pd.Series]) -> list[tuple[str, str, str]]:
    """Baslikta gosterilecek durum rozetleri."""
    chips: list[tuple[str, str, str]] = []
    # Grafik ileri dogru uzatilmis olabilir (Ichimoku projeksiyonu): bu barlarda
    # fiyat NaN'dir, ozet her zaman son GERCEK bardan okunmalidir.
    closes = df["Close"].dropna()
    if len(closes) == 0:
        return chips
    close = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) > 1 else close
    change = (close / prev - 1.0) * 100.0 if prev else 0.0
    chips.append(("Son", _fmt(close), "up" if change >= 0 else "down"))
    chips.append(("Değişim", f"{change:+.2f}%", "up" if change >= 0 else "down"))

    if "RSI" in s:
        value = _last(s["RSI"])
        role = "down" if value >= 70 else "up" if value <= 30 else "neutral"
        chips.append(("RSI", _fmt(value, 1), role))
    if "MACD_hist" in s:
        value = _last(s["MACD_hist"])
        chips.append(("MACD hist", _fmt(value, 3), "up" if value >= 0 else "down"))
    if "ADX" in s:
        value = _last(s["ADX"])
        role = "accent1" if value >= 25 else "muted"
        chips.append(("ADX", _fmt(value, 1), role))
    if "ST_dir" in s:
        direction = _last(s["ST_dir"])
        chips.append(
            ("Supertrend", "yukarı" if direction > 0 else "aşağı", "up" if direction > 0 else "down")
        )
    if "BB_percent_b" in s:
        chips.append(("%B", _fmt(_last(s["BB_percent_b"]), 2), "neutral"))
    if "RVOL" in s:
        value = _last(s["RVOL"])
        chips.append(("RVOL", f"{value:.2f}x" if np.isfinite(value) else "—", "accent1" if value >= 1.5 else "neutral"))
    return chips


def build_spec(
    df: pd.DataFrame,
    series: dict[str, pd.Series],
    keys: tuple[str, ...],
    title: str,
    subtitle: str,
    price_height: float = 3.4,
    note: str = "",
) -> ChartSpec:
    overlays: list[Trace] = []
    panels: list[Panel] = []
    for key in keys:
        if key in _OVERLAY_BUILDERS:
            overlays.extend(_OVERLAY_BUILDERS[key](df, series))
        elif key in _PANEL_BUILDERS:
            panels.append(_PANEL_BUILDERS[key](df, series))
    return ChartSpec(
        df=df,
        overlays=overlays,
        panels=panels,
        title=title,
        subtitle=subtitle,
        snapshot=build_snapshot(df, series),
        price_height=price_height,
        note=note,
    )


def segment_ranges(colors: pd.Series) -> list[tuple[int, int, str]]:
    """Ardisik ayni renkli bolgeleri (baslangic, bitis, rol) olarak dondurur.

    Supertrend gibi renk degistiren cizgileri iki arka ucta da ayni sekilde
    parcalamak icin kullanilir.
    """
    values = list(colors)
    out: list[tuple[int, int, str]] = []
    start = None
    current = None
    for i, role in enumerate(values):
        role = role if isinstance(role, str) else None
        if role != current:
            if current is not None and start is not None and i - start >= 1:
                out.append((start, i, current))
            start, current = i, role
    if current is not None and start is not None:
        out.append((start, len(values), current))
    return [(a, b, r) for a, b, r in out if r]
