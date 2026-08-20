"""Gosterge hesaplama katmani.

Bu modul saf pandas/numpy ile calisir; hicbir cizim kutuphanesine bagimli
degildir. Her fonksiyon OHLCV DataFrame alir ve isimlendirilmis Series'lerden
olusan bir sozluk dondurur. Cizim katmani (plotspec.py) bu sozlukleri okur.

Wilder yumusatmasi (RMA) kullanan gostergelerde TradingView ile ayni sonuc
uretilmesi hedeflenmistir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Temel yardimcilar
# --------------------------------------------------------------------------


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder yumusatmasi. TradingView'daki ta.rma() ile ayni.

    Ilk deger 'length' barlik basit ortalama, sonrasi alpha = 1/length ile
    ussel yumusatma. pandas'in ewm(alpha=..., adjust=False) davranisini
    dogru baslatmak icin seed degeri elle verilir.
    """
    series = series.astype("float64")
    out = pd.Series(np.nan, index=series.index, dtype="float64")
    values = series.to_numpy()
    n = len(values)
    if n < length:
        return out

    # Ilk gecerli pencereyi bul (bastaki NaN'lari atla)
    first_valid = 0
    while first_valid < n and np.isnan(values[first_valid]):
        first_valid += 1
    if n - first_valid < length:
        return out

    seed_end = first_valid + length
    acc = float(np.mean(values[first_valid:seed_end]))
    result = np.full(n, np.nan)
    result[seed_end - 1] = acc
    alpha = 1.0 / length
    for i in range(seed_end, n):
        v = values[i]
        if np.isnan(v):
            result[i] = acc
            continue
        acc = acc + alpha * (v - acc)
        result[i] = acc
    out.iloc[:] = result
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    ranges = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Wilder ATR."""
    return rma(true_range(df), length)


# --------------------------------------------------------------------------
# 1. Hareketli ortalamalar (tek "ortalama" gostergesi)
# --------------------------------------------------------------------------


def moving_averages(
    df: pd.DataFrame,
    specs: tuple[tuple[str, int], ...] = (("ema", 20), ("ema", 50)),
) -> dict[str, pd.Series]:
    """Fiyat uzerine bindirilecek ortalama seti.

    specs: (("ema", 20), ("sma", 200), ...) seklinde tip/periyot ciftleri.

    Varsayilan iki cizgidir: mum paneli tek gostergeye ayrildigi icin uc-dort
    ortalama ust uste binip grafigi okunmaz hale getiriyordu. Uzun vadeli
    ortalama isteyen params={"ma": {"specs": (("ema",20),("sma",200))}} verir.
    """
    close = df["Close"]
    out: dict[str, pd.Series] = {}
    for kind, length in specs:
        key = f"{kind.upper()}{length}"
        out[key] = ema(close, length) if kind.lower() == "ema" else sma(close, length)
    return out


# --------------------------------------------------------------------------
# 2. Bollinger Bantlari
# --------------------------------------------------------------------------


def bollinger(
    df: pd.DataFrame, length: int = 20, mult: float = 2.0
) -> dict[str, pd.Series]:
    close = df["Close"]
    mid = sma(close, length)
    # TradingView ta.stdev() populasyon standart sapmasi kullanir (ddof=0)
    std = close.rolling(length, min_periods=length).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    width = (upper - lower) / mid.replace(0, np.nan)
    percent_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return {
        "BB_mid": mid,
        "BB_upper": upper,
        "BB_lower": lower,
        "BB_width": width,
        "BB_percent_b": percent_b,
    }


# --------------------------------------------------------------------------
# 3. Supertrend
# --------------------------------------------------------------------------


def supertrend(
    df: pd.DataFrame, length: int = 10, mult: float = 3.0
) -> dict[str, pd.Series]:
    """Supertrend. direction: +1 yukari trend, -1 asagi trend."""
    hl2 = (df["High"] + df["Low"]) / 2.0
    band = mult * atr(df, length)
    upper_basic = (hl2 + band).to_numpy()
    lower_basic = (hl2 - band).to_numpy()
    close = df["Close"].to_numpy()
    n = len(df)

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    line = np.full(n, np.nan)

    started = False
    for i in range(n):
        if np.isnan(upper_basic[i]) or np.isnan(lower_basic[i]):
            continue
        if not started:
            upper[i] = upper_basic[i]
            lower[i] = lower_basic[i]
            direction[i] = 1.0
            line[i] = lower[i]
            started = True
            continue

        prev_upper = upper[i - 1]
        prev_lower = lower[i - 1]
        prev_close = close[i - 1]

        upper[i] = (
            min(upper_basic[i], prev_upper)
            if prev_close <= prev_upper
            else upper_basic[i]
        )
        lower[i] = (
            max(lower_basic[i], prev_lower)
            if prev_close >= prev_lower
            else lower_basic[i]
        )

        prev_dir = direction[i - 1]
        if prev_dir == 1.0:
            direction[i] = -1.0 if close[i] < lower[i] else 1.0
        else:
            direction[i] = 1.0 if close[i] > upper[i] else -1.0
        line[i] = lower[i] if direction[i] == 1.0 else upper[i]

    idx = df.index
    return {
        "ST_line": pd.Series(line, index=idx),
        "ST_dir": pd.Series(direction, index=idx),
        "ST_upper": pd.Series(upper, index=idx),
        "ST_lower": pd.Series(lower, index=idx),
    }


# --------------------------------------------------------------------------
# 4. Ichimoku Kinko Hyo
# --------------------------------------------------------------------------


def ichimoku(
    df: pd.DataFrame,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    displacement: int = 26,
) -> dict[str, pd.Series]:
    """Ichimoku bulutu.

    TradingView 'offset = displacement - 1' kadar bar kaydirir; yani varsayilan
    26 ayarinda bulut 25 bar ileri, chikou 25 bar geri gider. Bu detay atlanirsa
    bulut TradingView'a gore 1 bar kayar.
    """
    shift = displacement - 1
    high, low = df["High"], df["Low"]

    def donchian(length: int) -> pd.Series:
        return (
            high.rolling(length, min_periods=length).max()
            + low.rolling(length, min_periods=length).min()
        ) / 2.0

    conv = donchian(tenkan)
    base = donchian(kijun)
    span_a_raw = (conv + base) / 2.0
    span_b_raw = donchian(senkou_b)
    chikou = df["Close"].shift(-shift)
    return {
        "ICH_tenkan": conv,
        "ICH_kijun": base,
        "ICH_span_a": span_a_raw.shift(shift),
        "ICH_span_b": span_b_raw.shift(shift),
        # Kaydirilmamis hallerini de tasiyoruz: bulutu fiyatin onune uzatmak
        # (pipeline.extend_future) bunlara ihtiyac duyar.
        "ICH_span_a_raw": span_a_raw,
        "ICH_span_b_raw": span_b_raw,
        "ICH_chikou": chikou,
        "ICH_shift": pd.Series(float(shift), index=df.index),
    }


# --------------------------------------------------------------------------
# 5. VWAP (+ standart sapma bandi)
# --------------------------------------------------------------------------


def vwap(
    df: pd.DataFrame,
    anchor: str = "session",
    window: int = 20,
    mult: float = 2.0,
) -> dict[str, pd.Series]:
    """Hacim agirlikli ortalama fiyat.

    anchor='session' : her gun/hafta basinda sifirlanan kumulatif VWAP
                       (gun ici barlar icin dogru olan surum)
    anchor='rolling' : son 'window' barin hacim agirlikli ortalamasi
                       (gunluk ve ustu periyotlar icin anlamli olan surum)
    """
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    vol = df["Volume"].astype("float64").fillna(0.0)

    if anchor == "session":
        if isinstance(df.index, pd.DatetimeIndex):
            groups = df.index.normalize()
        else:  # tarih bilgisi yoksa rolling'e dus
            return vwap(df, anchor="rolling", window=window, mult=mult)
        pv = (tp * vol).groupby(groups).cumsum()
        cv = vol.groupby(groups).cumsum()
        line = pv / cv.replace(0, np.nan)
        var = ((tp - line) ** 2 * vol).groupby(groups).cumsum() / cv.replace(0, np.nan)
        dev = np.sqrt(var)
    else:
        pv = (tp * vol).rolling(window, min_periods=window).sum()
        cv = vol.rolling(window, min_periods=window).sum()
        line = pv / cv.replace(0, np.nan)
        dev = (tp - line).rolling(window, min_periods=window).std(ddof=0)

    return {
        "VWAP": line,
        "VWAP_upper": line + mult * dev,
        "VWAP_lower": line - mult * dev,
    }


# --------------------------------------------------------------------------
# 6. Hacim + RVOL
# --------------------------------------------------------------------------


def volume_bars(df: pd.DataFrame, length: int = 20) -> dict[str, pd.Series]:
    """Hacim barlari ve 20 barlik ortalamaya gore bagil hacim."""
    vol = df["Volume"].astype("float64")
    vol_ma = sma(vol, length)
    rvol = vol / vol_ma.replace(0, np.nan)
    return {"VOL": vol, "VOL_ma": vol_ma, "RVOL": rvol}


# --------------------------------------------------------------------------
# 7. RSI (Wilder)
# --------------------------------------------------------------------------


def rsi(
    df: pd.DataFrame, length: int = 14, signal_length: int = 14
) -> dict[str, pd.Series]:
    delta = df["Close"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    value = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss == 0 iken RSI tanim geregi 100
    value = value.where(~((avg_loss == 0) & avg_gain.notna()), 100.0)
    return {"RSI": value, "RSI_ma": sma(value, signal_length)}


# --------------------------------------------------------------------------
# 8. MACD
# --------------------------------------------------------------------------


def macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, pd.Series]:
    close = df["Close"]
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return {"MACD": line, "MACD_signal": sig, "MACD_hist": line - sig}


# --------------------------------------------------------------------------
# 9. Stochastic RSI
# --------------------------------------------------------------------------


def stoch_rsi(
    df: pd.DataFrame,
    rsi_length: int = 14,
    stoch_length: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> dict[str, pd.Series]:
    base = rsi(df, rsi_length)["RSI"]
    lowest = base.rolling(stoch_length, min_periods=stoch_length).min()
    highest = base.rolling(stoch_length, min_periods=stoch_length).max()
    raw = 100.0 * (base - lowest) / (highest - lowest).replace(0, np.nan)
    k = sma(raw, k_smooth)
    d = sma(k, d_smooth)
    return {"SRSI_k": k, "SRSI_d": d}


# --------------------------------------------------------------------------
# 10. ADX / DMI
# --------------------------------------------------------------------------


def adx_dmi(
    df: pd.DataFrame, di_length: int = 14, adx_length: int = 14
) -> dict[str, pd.Series]:
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=df.index, dtype="float64"
    )
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=df.index, dtype="float64"
    )
    tr_rma = rma(true_range(df), di_length).replace(0, np.nan)
    plus_di = 100.0 * rma(plus_dm, di_length) / tr_rma
    minus_di = 100.0 * rma(minus_dm, di_length) / tr_rma
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return {"ADX": rma(dx, adx_length), "DI_plus": plus_di, "DI_minus": minus_di}



# --------------------------------------------------------------------------
# Parabolic SAR
# --------------------------------------------------------------------------


def parabolic_sar(
    df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2
) -> dict[str, pd.Series]:
    """Wilder Parabolic SAR.

    Nokta fiyatin altindaysa yukari trend (+1), ustundeyse asagi trend (-1).
    Donus anlarinda SAR, son iki barin ucuna kirpilir; bu kirpma atlanirsa
    gosterge fiyatin icine girip yanlis sinyal uretir.
    """
    high = df["High"].to_numpy(dtype="float64")
    low = df["Low"].to_numpy(dtype="float64")
    n = len(df)
    sar = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    if n < 3:
        return {"SAR": pd.Series(sar, index=df.index), "SAR_dir": pd.Series(direction, index=df.index)}

    up = high[1] >= high[0]
    af = af_start
    ep = high[1] if up else low[1]
    sar[1] = low[0] if up else high[0]
    direction[1] = 1.0 if up else -1.0

    for i in range(2, n):
        prev = sar[i - 1]
        value = prev + af * (ep - prev)

        if up:
            value = min(value, low[i - 1], low[i - 2])
            if low[i] < value:  # donus
                up = False
                value = ep
                ep = low[i]
                af = af_start
            elif high[i] > ep:
                ep = high[i]
                af = min(af + af_step, af_max)
        else:
            value = max(value, high[i - 1], high[i - 2])
            if high[i] > value:
                up = True
                value = ep
                ep = high[i]
                af = af_start
            elif low[i] < ep:
                ep = low[i]
                af = min(af + af_step, af_max)

        sar[i] = value
        direction[i] = 1.0 if up else -1.0

    return {"SAR": pd.Series(sar, index=df.index), "SAR_dir": pd.Series(direction, index=df.index)}


# --------------------------------------------------------------------------
# CCI / Williams %R / Awesome Oscillator
# --------------------------------------------------------------------------


def cci(df: pd.DataFrame, length: int = 20) -> dict[str, pd.Series]:
    """Commodity Channel Index. Ortalama mutlak sapma kullanir (std degil)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    ma = sma(tp, length)
    mad = tp.rolling(length, min_periods=length).apply(
        lambda w: np.abs(w - w.mean()).mean(), raw=True
    )
    return {"CCI": (tp - ma) / (0.015 * mad.replace(0, np.nan))}


def williams_r(df: pd.DataFrame, length: int = 14) -> dict[str, pd.Series]:
    highest = df["High"].rolling(length, min_periods=length).max()
    lowest = df["Low"].rolling(length, min_periods=length).min()
    value = -100.0 * (highest - df["Close"]) / (highest - lowest).replace(0, np.nan)
    return {"WILLR": value}


def awesome_oscillator(
    df: pd.DataFrame, fast: int = 5, slow: int = 34
) -> dict[str, pd.Series]:
    hl2 = (df["High"] + df["Low"]) / 2.0
    return {"AO": sma(hl2, fast) - sma(hl2, slow)}


# --------------------------------------------------------------------------
# ATR paneli / Keltner / Donchian
# --------------------------------------------------------------------------


def atr_bands(df: pd.DataFrame, length: int = 14) -> dict[str, pd.Series]:
    """Panel olarak cizilen ATR: mutlak deger ve fiyata orani."""
    value = atr(df, length)
    return {"ATR": value, "ATR_pct": 100.0 * value / df["Close"].replace(0, np.nan)}


def keltner(
    df: pd.DataFrame, length: int = 20, atr_length: int = 10, mult: float = 2.0
) -> dict[str, pd.Series]:
    """Keltner Kanallari: EMA merkez, ATR genislik.

    Bollinger'dan farki sapma yerine ATR kullanmasidir; bantlar daha yumusak
    olur ve ani volatilite siciramalarinda daha az genisler.
    """
    mid = ema(df["Close"], length)
    band = mult * atr(df, atr_length)
    return {"KC_mid": mid, "KC_upper": mid + band, "KC_lower": mid - band}


def donchian(df: pd.DataFrame, length: int = 20) -> dict[str, pd.Series]:
    """Donchian Kanallari: N barlik en yuksek ve en dusuk."""
    upper = df["High"].rolling(length, min_periods=length).max()
    lower = df["Low"].rolling(length, min_periods=length).min()
    return {"DC_upper": upper, "DC_lower": lower, "DC_mid": (upper + lower) / 2.0}


# --------------------------------------------------------------------------
# OBV / Volume Profile
# --------------------------------------------------------------------------


def obv(df: pd.DataFrame, signal_length: int = 20) -> dict[str, pd.Series]:
    """On-Balance Volume: kapanis yukselirse hacmi ekler, duserse cikarir."""
    direction = np.sign(df["Close"].diff().fillna(0.0))
    value = (direction * df["Volume"].fillna(0.0)).cumsum()
    return {"OBV": value, "OBV_ma": ema(value, signal_length)}


def volume_profile(df: pd.DataFrame, bins: int = 48) -> dict[str, pd.Series]:
    """Hacmi zamana degil FIYAT SEVIYELERINE dagitir (VPVR).

    Donen Series'in indeksi fiyat kovasinin merkezi, degeri o seviyede
    birikmis hacimdir. Zaman eksenli olmadigi icin diger serilerle birlikte
    yeniden indekslenemez; pipeline bunu ayrica ele alir.

    Her barin hacmi, barin yuksek-dusuk araligina esit dagitilir; boylece
    yalnizca kapanisa bakan kaba yaklasimdan daha gercekci bir profil cikar.
    """
    low = float(df["Low"].min())
    high = float(df["High"].max())
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return {"VP_hist": pd.Series(dtype="float64")}

    edges = np.linspace(low, high, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    totals = np.zeros(bins)

    lows = df["Low"].to_numpy(dtype="float64")
    highs = df["High"].to_numpy(dtype="float64")
    vols = df["Volume"].fillna(0.0).to_numpy(dtype="float64")

    for lo, hi, vol in zip(lows, highs, vols):
        if not np.isfinite(lo) or not np.isfinite(hi) or vol <= 0:
            continue
        start = np.searchsorted(edges, lo, side="right") - 1
        end = np.searchsorted(edges, hi, side="left")
        start = max(start, 0)
        end = min(max(end, start + 1), bins)
        totals[start:end] += vol / (end - start)

    return {"VP_hist": pd.Series(totals, index=pd.Index(centers, name="price"))}


# --------------------------------------------------------------------------
# Toplu hesaplama
# --------------------------------------------------------------------------

#: Tum gostergelerin kanonik sirasi. CLI'daki --indicators bu anahtarlari alir.
ALL_INDICATORS: tuple[str, ...] = (
    # Trend
    "ma", "supertrend", "ichimoku", "sar", "adx",
    # Momentum
    "rsi", "macd", "stochrsi", "cci", "willr", "ao",
    # Volatilite
    "bbands", "atr", "keltner", "donchian",
    # Hacim
    "volume", "vwap", "obv", "vprofile",
)

#: Gostergenin ait oldugu kategori. Kareler her kategoriden birer tane secer.
CATEGORY: dict[str, str] = {
    "ma": "trend", "supertrend": "trend", "ichimoku": "trend", "sar": "trend", "adx": "trend",
    "rsi": "momentum", "macd": "momentum", "stochrsi": "momentum",
    "cci": "momentum", "willr": "momentum", "ao": "momentum",
    "bbands": "volatilite", "atr": "volatilite", "keltner": "volatilite", "donchian": "volatilite",
    "volume": "hacim", "vwap": "hacim", "obv": "hacim", "vprofile": "hacim",
}

#: Zaman eksenli olmayan gostergeler (fiyat seviyesine gore hesaplananlar).
#: Pencere kirpildiktan SONRA hesaplanmalari gerekir.
NON_TEMPORAL: frozenset[str] = frozenset({"vprofile"})

_COMPUTE = {
    "ma": moving_averages,
    "supertrend": supertrend,
    "ichimoku": ichimoku,
    "sar": parabolic_sar,
    "adx": adx_dmi,
    "rsi": rsi,
    "macd": macd,
    "stochrsi": stoch_rsi,
    "cci": cci,
    "willr": williams_r,
    "ao": awesome_oscillator,
    "bbands": bollinger,
    "atr": atr_bands,
    "keltner": keltner,
    "donchian": donchian,
    "volume": volume_bars,
    "vwap": vwap,
    "obv": obv,
    "vprofile": volume_profile,
}


def compute(
    df: pd.DataFrame,
    keys: tuple[str, ...] = ALL_INDICATORS,
    params: dict[str, dict] | None = None,
) -> dict[str, pd.Series]:
    """Secilen gostergeleri hesaplayip tek bir Series sozlugunde birlestirir."""
    params = params or {}
    result: dict[str, pd.Series] = {}
    for key in keys:
        if key not in _COMPUTE:
            raise KeyError(f"Bilinmeyen gosterge: {key}. Gecerli: {ALL_INDICATORS}")
        result.update(_COMPUTE[key](df, **params.get(key, {})))
    return result
