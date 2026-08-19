"""Uctan uca akis: veri -> gosterge -> cizim tarifi.

CLI ve testler bu modulu kullanir; cizim arka uclari (PNG/HTML) yalnizca
buradan cikan ChartSpec'i tuketir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from . import indicators as ind
from .data_sources import SymbolSpec, fetch_ohlcv
from .views import VIEWS_BY_KEY, View
from .plotspec import ChartSpec, build_spec, compute_keys_for

INTERVAL_LABELS = {
    "1m": "1 dakika",
    "5m": "5 dakika",
    "15m": "15 dakika",
    "30m": "30 dakika",
    "1h": "1 saat",
    "4h": "4 saat",
    "1d": "günlük",
    "1wk": "haftalık",
    "1mo": "aylık",
}

#: Periyot secilmediginde araliga gore makul bir varsayilan
DEFAULT_PERIODS = {
    "1m": "5d",
    "5m": "1mo",
    "15m": "1mo",
    "30m": "3mo",
    "1h": "6mo",
    "4h": "1y",
    "1d": "2y",
    "1wk": "5y",
    "1mo": "10y",
}


INTRADAY = {"1m", "5m", "15m", "30m", "1h", "2h", "4h"}


def default_params(interval: str, params: dict[str, dict] | None = None) -> dict[str, dict]:
    """Araliga gore gosterge varsayilanlarini secer.

    Kritik olan VWAP: gun ici barlarda seans basinda sifirlanan kumulatif VWAP
    dogru olandir, ama gunluk barlarda her grup tek bardan olusacagi icin VWAP
    fiyatin kendisine esitlenir ve gosterge anlamsizlasir. Gunluk ve ustu
    periyotlarda 20 barlik hareketli VWAP kullanilir.
    """
    merged: dict[str, dict] = {"vwap": {"anchor": "session" if interval in INTRADAY else "rolling",
                                        "window": 20}}
    for key, value in (params or {}).items():
        merged[key] = {**merged.get(key, {}), **value}
    return merged


def _future_index(index: pd.DatetimeIndex, bars: int) -> pd.DatetimeIndex:
    """Mevcut barlarin ritmini surdurerek ileriye dogru bos zaman damgasi uretir."""
    if len(index) < 3 or bars <= 0:
        return pd.DatetimeIndex([])
    deltas = pd.Series(index[1:]) - pd.Series(index[:-1])
    step = deltas.median()
    daily_or_higher = step >= pd.Timedelta(days=1)
    out: list[pd.Timestamp] = []
    cursor = index[-1]
    while len(out) < bars:
        cursor = cursor + step
        if daily_or_higher and step < pd.Timedelta(days=6) and cursor.weekday() >= 5:
            continue  # gunluk grafikte hafta sonu etiketi uretme
        out.append(cursor)
    return pd.DatetimeIndex(out)


def extend_future(
    df: pd.DataFrame, series: dict[str, pd.Series], bars: int
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Ichimoku bulutunu fiyatin onune tasimak icin grafigi saga uzatir.

    Fiyat barlari bos (NaN) kalir, yalnizca kaydirilmis Senkou A/B degerleri
    doldurulur. TradingView'daki "bulut fiyattan once biter" gorunumu boyle
    elde edilir.
    """
    if bars <= 0 or "ICH_span_a_raw" not in series:
        return df, series

    future = _future_index(df.index, bars)
    if len(future) == 0:
        return df, series

    new_index = df.index.append(future)
    df_ext = df.reindex(new_index)
    ext = {k: v.reindex(new_index) for k, v in series.items()}

    n = len(df.index)
    for span, raw in (("ICH_span_a", "ICH_span_a_raw"), ("ICH_span_b", "ICH_span_b_raw")):
        tail = series[raw].to_numpy(dtype="float64")[-bars:]
        values = ext[span].to_numpy(dtype="float64").copy()
        values[n : n + len(tail)] = tail[: len(values) - n]
        ext[span] = pd.Series(values, index=new_index)
    return df_ext, ext


@dataclass
class ChartResult:
    """Tek bir gorunumun cizime hazir hali."""

    view: View
    spec: ChartSpec

    @property
    def key(self) -> str:
        return self.view.key


@dataclass
class ViewSet:
    """Bir sembol/aralik icin uretilen tum gorunumler."""

    symbol: SymbolSpec
    interval: str
    results: list[ChartResult]
    source_label: str
    generated_at: str
    subtitle: str

    def __iter__(self):
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)


def build_views(
    symbol: str,
    views: tuple[View, ...],
    interval: str = "1d",
    bars: int = 250,
    period: str | None = None,
    params: dict[str, dict] | None = None,
    project_bars: int | None = None,
) -> ViewSet:
    """Tum gorunumleri TEK veri cekimi ve TEK hesap turuyla uretir.

    Gorunumler ayni seriyi paylastigi icin ortak gostergeler (orn. birden fazla
    karede gecen hareketli ortalamalar) yalnizca bir kez hesaplanir.
    """
    if not views:
        raise ValueError("En az bir gorunum gerekli")

    period = period or DEFAULT_PERIODS.get(interval, "2y")
    params = default_params(interval, params)

    needed: list[str] = []
    for view in views:
        for key in view.compute_keys:
            if key not in needed:
                needed.append(key)

    # Gostergeler once TUM gecmis uzerinde hesaplanir, kirpma sonra yapilir;
    # aksi halde EMA200 gibi uzun periyotlar grafigin sol yarisinda bos kalirdi.
    df_full, symbol_spec = fetch_ohlcv(symbol, period=period, interval=interval)
    series_full = ind.compute(df_full, keys=tuple(needed), params=params)

    df_window = df_full.tail(bars)
    series_window = {k: v.reindex(df_window.index) for k, v in series_full.items()}

    interval_label = INTERVAL_LABELS.get(interval, interval)
    last_ts = df_full.index[-1]
    subtitle = (
        f"{interval_label} · {len(df_window)} bar · son bar "
        f"{last_ts.strftime('%d.%m.%Y %H:%M')}"
    )

    results: list[ChartResult] = []
    for view in views:
        wants_cloud = "ichimoku" in view.keys
        ahead = (25 if wants_cloud else 0) if project_bars is None else (
            project_bars if wants_cloud else 0
        )
        df_view, series_view = extend_future(df_window, series_window, ahead)
        results.append(
            ChartResult(
                view=view,
                spec=build_spec(
                    df=df_view,
                    series=series_view,
                    keys=view.keys,
                    title=f"{symbol_spec.display} · {view.title}",
                    subtitle=subtitle,
                    note=view.note,
                    price_height=view.price_height,
                ),
            )
        )

    return ViewSet(
        symbol=symbol_spec,
        interval=interval,
        results=results,
        source_label=symbol_spec.provider,
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        subtitle=subtitle,
    )


def build_chart(
    symbol: str,
    interval: str = "1d",
    bars: int = 250,
    period: str | None = None,
    keys: tuple[str, ...] = ind.ALL_INDICATORS,
    params: dict[str, dict] | None = None,
    project_bars: int | None = None,
) -> ViewSet:
    """Serbest gosterge listesini tek bir gorunum gibi uretir."""
    view = View(
        key="ozel",
        title="Seçili göstergeler",
        keys=keys,
        note=", ".join(keys),
        price_height=3.4,
    )
    return build_views(
        symbol, (view,), interval=interval, bars=bars, period=period,
        params=params, project_bars=project_bars,
    )
