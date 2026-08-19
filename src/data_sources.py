"""Veri kaynagi yonlendiricisi.

BIST hisseleri -> borsapy
Yabanci hisse / ETF / endeks / kripto -> yfinance

Iki kutuphane de ayni imzayi (Ticker.history(period, interval)) sundugu icin
donen DataFrame'i tek bir normalize adiminda birlestiriyoruz.

Sembol yazimi:
    THYAO           -> BIST olarak cozulur (borsapy)
    bist:THYAO      -> zorla borsapy
    AAPL            -> yfinance
    yf:ASELS.IS     -> zorla yfinance
    BTC-USD         -> yfinance (kripto)
    crypto:BTC      -> BTC-USD olarak yfinance
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .bist_symbols import is_bist

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

#: yfinance tarafinda dogrudan tanimli olan kripto kisayollari
_CRYPTO_ALIASES = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "AVAX": "AVAX-USD",
    "BNB": "BNB-USD",
    "DOGE": "DOGE-USD",
    "ADA": "ADA-USD",
}

_BIST_PATTERN = re.compile(r"^[A-Z]{3,6}$")


@dataclass(frozen=True)
class SymbolSpec:
    """Cozumlenmis sembol."""

    raw: str
    provider: str  # "borsapy" | "yfinance"
    query: str  # saglayiciya gonderilecek sembol
    market: str  # "bist" | "equity" | "crypto"
    display: str  # baslikta gosterilecek ad

    @property
    def is_crypto(self) -> bool:
        return self.market == "crypto"


def resolve_symbol(symbol: str) -> SymbolSpec:
    """Sembolu dogru saglayiciya yonlendirir."""
    raw = symbol.strip()
    prefix, _, rest = raw.partition(":")
    prefix, rest = prefix.lower(), rest.strip()

    if prefix == "bist" and rest:
        code = rest.upper()
        return SymbolSpec(raw, "borsapy", code, "bist", code)

    if prefix == "yf" and rest:
        code = rest.upper()
        market = "crypto" if code.endswith(("-USD", "-USDT", "-TRY")) else "equity"
        return SymbolSpec(raw, "yfinance", code, market, code)

    if prefix == "crypto" and rest:
        code = rest.upper()
        code = _CRYPTO_ALIASES.get(code, code if "-" in code else f"{code}-USD")
        return SymbolSpec(raw, "yfinance", code, "crypto", code)

    code = raw.upper()

    if code.endswith(".IS"):
        return SymbolSpec(raw, "borsapy", code[:-3], "bist", code[:-3])

    if "-" in code and code.split("-")[-1] in {"USD", "USDT", "TRY", "EUR"}:
        return SymbolSpec(raw, "yfinance", code, "crypto", code)

    if code in _CRYPTO_ALIASES:
        return SymbolSpec(raw, "yfinance", _CRYPTO_ALIASES[code], "crypto", code)

    # Cıplak harf kodlari: listede varsa BIST, yoksa yabanci hisse.
    # "AAPL" ile "THYAO" bicimsel olarak ayni gorundugu icin liste sart.
    if _BIST_PATTERN.match(code):
        if is_bist(code):
            return SymbolSpec(raw, "borsapy", code, "bist", code)
        return SymbolSpec(raw, "yfinance", code, "equity", code)

    return SymbolSpec(raw, "yfinance", code, "equity", code)


def _normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Saglayicidan gelen tabloyu ortak OHLCV formatina cevirir."""
    if df is None or len(df) == 0:
        raise ValueError(f"{source}: bos veri dondu")

    out = df.copy()

    # yfinance coklu sembol istendiginde MultiIndex kolon dondurebiliyor
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)

    out.columns = [str(c).strip().title().replace(" ", "") for c in out.columns]
    rename = {"AdjClose": "AdjClose", "Vol": "Volume"}
    out = out.rename(columns=rename)

    missing = [c for c in OHLCV_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"{source}: eksik kolonlar {missing} (gelen: {list(out.columns)})")

    out = out[OHLCV_COLUMNS].astype("float64")

    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)

    out = out[~out.index.duplicated(keep="last")].sort_index()
    # Fiyati olmayan satirlar cizimde bosluk yaratir
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out["Volume"] = out["Volume"].fillna(0.0)
    return out


def _fetch_borsapy(spec: SymbolSpec, period: str, interval: str) -> pd.DataFrame:
    import borsapy as bp  # gec import: yalnizca BIST istendiginde gerekir

    ticker = bp.Ticker(spec.query)
    return _normalize(ticker.history(period=period, interval=interval), "borsapy")


def _fetch_yfinance(spec: SymbolSpec, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    ticker = yf.Ticker(spec.query)
    return _normalize(
        ticker.history(period=period, interval=interval, auto_adjust=False), "yfinance"
    )


def fetch_ohlcv(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    bars: int | None = None,
) -> tuple[pd.DataFrame, SymbolSpec]:
    """OHLCV verisini ceker.

    BIST sembollerinde borsapy basarisiz olursa yfinance'a ('.IS' ekiyle)
    duser; boylece tek bir saglayicinin kesintisi raporu durdurmaz.
    """
    spec = resolve_symbol(symbol)
    errors: list[str] = []

    attempts: list[tuple[str, SymbolSpec]] = []
    if spec.provider == "borsapy":
        attempts.append(("borsapy", spec))
        # borsapy kesintiye ugrarsa BIST verisi yfinance'tan ".IS" ekiyle de gelir
        attempts.append(
            ("yfinance", SymbolSpec(spec.raw, "yfinance", f"{spec.query}.IS", "bist", spec.display))
        )
    else:
        attempts.append(("yfinance", spec))
        if spec.market == "equity" and _BIST_PATTERN.match(spec.query):
            # Listede olmayan yeni bir BIST kodu olabilir
            attempts.append(
                ("borsapy", SymbolSpec(spec.raw, "borsapy", spec.query, "bist", spec.display))
            )

    for provider, attempt_spec in attempts:
        try:
            fetcher = _fetch_borsapy if provider == "borsapy" else _fetch_yfinance
            df = fetcher(attempt_spec, period, interval)
            if bars:
                df = df.tail(bars)
            if len(df) < 30:
                raise ValueError(f"yalnizca {len(df)} bar dondu, cizim icin yetersiz")
            return df, spec
        except Exception as exc:  # noqa: BLE001 - saglayici hatalarini toplayip raporluyoruz
            errors.append(f"{provider}({attempt_spec.query}): {exc}")

    raise RuntimeError(
        "Veri cekilemedi -> " + " | ".join(errors)
    )
