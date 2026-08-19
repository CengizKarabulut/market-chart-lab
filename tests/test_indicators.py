"""Gosterge dogrulamalari.

Ag baglantisi gerektirmez: sentetik ama gercekci bir OHLCV serisi uretilir.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src import indicators as ind


def synthetic_ohlcv(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2023-01-02", periods=n)
    drift = np.linspace(0, 0.35, n)
    noise = rng.normal(0, 0.012, n).cumsum()
    close = 100 * np.exp(drift + noise)
    spread = close * rng.uniform(0.004, 0.02, n)
    open_ = close + rng.normal(0, 1, n) * spread * 0.4
    high = np.maximum(open_, close) + spread * rng.uniform(0.2, 1.0, n)
    low = np.minimum(open_, close) - spread * rng.uniform(0.2, 1.0, n)
    volume = rng.lognormal(13, 0.4, n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )


class TestHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self.df = synthetic_ohlcv()

    def test_rma_seed_and_recursion(self) -> None:
        """Wilder RMA: ilk deger SMA, sonrasi alpha=1/n ile ussel."""
        s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8])
        out = ind.rma(s, 4)
        self.assertTrue(np.isnan(out.iloc[2]))
        self.assertAlmostEqual(out.iloc[3], 2.5)  # (1+2+3+4)/4
        expected = 2.5 + (5 - 2.5) / 4
        self.assertAlmostEqual(out.iloc[4], expected)

    def test_ema_matches_pandas(self) -> None:
        out = ind.ema(self.df["Close"], 20)
        ref = self.df["Close"].ewm(span=20, adjust=False, min_periods=20).mean()
        pd.testing.assert_series_equal(out, ref)

    def test_atr_positive(self) -> None:
        atr = ind.atr(self.df, 14).dropna()
        self.assertGreater(len(atr), 300)
        self.assertTrue((atr > 0).all())


class TestIndicators(unittest.TestCase):
    def setUp(self) -> None:
        self.df = synthetic_ohlcv()

    def test_moving_averages_keys(self) -> None:
        out = ind.moving_averages(self.df)
        self.assertEqual(set(out), {"EMA20", "EMA50", "SMA200"})
        self.assertAlmostEqual(
            out["SMA200"].iloc[-1], self.df["Close"].iloc[-200:].mean()
        )

    def test_bollinger_ordering(self) -> None:
        out = ind.bollinger(self.df)
        valid = out["BB_upper"].notna()
        self.assertTrue((out["BB_upper"][valid] >= out["BB_mid"][valid]).all())
        self.assertTrue((out["BB_mid"][valid] >= out["BB_lower"][valid]).all())
        # %B tanimi: fiyat ust bandin uzerindeyse 1'i asmali
        pb = out["BB_percent_b"].dropna()
        self.assertTrue(((pb > -3) & (pb < 4)).all())

    def test_rsi_bounds_and_extremes(self) -> None:
        out = ind.rsi(self.df)["RSI"].dropna()
        self.assertTrue(((out >= 0) & (out <= 100)).all())
        # Kesintisiz yukselen seride RSI 100 olmali
        rising = self.df.copy()
        rising["Close"] = np.arange(1.0, len(rising) + 1.0)
        self.assertAlmostEqual(ind.rsi(rising)["RSI"].iloc[-1], 100.0, places=6)

    def test_macd_histogram_identity(self) -> None:
        out = ind.macd(self.df)
        diff = (out["MACD"] - out["MACD_signal"] - out["MACD_hist"]).abs().max()
        self.assertLess(diff, 1e-12)

    def test_stochrsi_bounds(self) -> None:
        out = ind.stoch_rsi(self.df)
        for key in ("SRSI_k", "SRSI_d"):
            values = out[key].dropna()
            self.assertTrue(((values >= -1e-9) & (values <= 100 + 1e-9)).all(), key)

    def test_adx_bounds(self) -> None:
        out = ind.adx_dmi(self.df)
        adx = out["ADX"].dropna()
        self.assertTrue(((adx >= 0) & (adx <= 100)).all())
        self.assertTrue((out["DI_plus"].dropna() >= 0).all())

    def test_supertrend_direction_and_side(self) -> None:
        out = ind.supertrend(self.df)
        direction = out["ST_dir"].dropna()
        self.assertTrue(set(direction.unique()) <= {1.0, -1.0})
        # Yukari trendde cizgi fiyatin altinda kalmali
        up_mask = out["ST_dir"] == 1.0
        below = out["ST_line"][up_mask] <= self.df["Close"][up_mask]
        self.assertGreater(below.mean(), 0.95)

    def test_ichimoku_displacement(self) -> None:
        """Bulut, kaydirilmamis degerin tam 25 bar ilerisinde olmali."""
        out = ind.ichimoku(self.df, displacement=26)
        raw = out["ICH_span_a_raw"]
        shifted = out["ICH_span_a"]
        self.assertAlmostEqual(shifted.iloc[-1], raw.iloc[-26])
        self.assertTrue(np.isnan(shifted.iloc[0]))

    def test_vwap_between_low_and_high_range(self) -> None:
        out = ind.vwap(self.df, anchor="rolling", window=20)
        line = out["VWAP"].dropna()
        window_low = self.df["Low"].rolling(20).min().reindex(line.index)
        window_high = self.df["High"].rolling(20).max().reindex(line.index)
        self.assertTrue((line >= window_low).all())
        self.assertTrue((line <= window_high).all())

    def test_volume_rvol(self) -> None:
        out = ind.volume_profile(self.df)
        rvol = out["RVOL"].dropna()
        self.assertTrue((rvol > 0).all())
        self.assertAlmostEqual(float(rvol.mean()), 1.0, delta=0.35)

    def test_compute_all_returns_every_key(self) -> None:
        series = ind.compute(self.df)
        for key in ("EMA20", "BB_upper", "ST_line", "ICH_span_a", "VWAP",
                    "RVOL", "RSI", "MACD_hist", "SRSI_k", "ADX"):
            self.assertIn(key, series)
            self.assertEqual(len(series[key]), len(self.df))

    def test_compute_rejects_unknown_key(self) -> None:
        with self.assertRaises(KeyError):
            ind.compute(self.df, keys=("supertrend", "yok_boyle_bir_sey"))


if __name__ == "__main__":
    unittest.main()
