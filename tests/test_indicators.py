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
        """Varsayilan iki cizgi; mum paneli tek gostergeye ayrildigi icin."""
        out = ind.moving_averages(self.df)
        self.assertEqual(set(out), {"EMA20", "EMA50"})

    def test_moving_averages_custom_specs(self) -> None:
        out = ind.moving_averages(self.df, specs=(("ema", 20), ("sma", 200)))
        self.assertEqual(set(out), {"EMA20", "SMA200"})
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
        out = ind.volume_bars(self.df)
        rvol = out["RVOL"].dropna()
        self.assertTrue((rvol > 0).all())
        self.assertAlmostEqual(float(rvol.mean()), 1.0, delta=0.35)

    def test_compute_all_returns_every_key(self) -> None:
        series = ind.compute(self.df)
        for key in ("EMA20", "BB_upper", "ST_line", "ICH_span_a", "VWAP",
                    "RVOL", "RSI", "MACD_hist", "SRSI_k", "ADX",
                    "SAR", "CCI", "WILLR", "AO", "ATR", "KC_upper",
                    "DC_upper", "OBV"):
            self.assertIn(key, series)
            if key != "VP_hist":
                self.assertEqual(len(series[key]), len(self.df))

    def test_every_indicator_has_a_category(self) -> None:
        self.assertEqual(set(ind.CATEGORY), set(ind.ALL_INDICATORS))
        self.assertEqual(set(ind.CATEGORY.values()),
                         {"trend", "momentum", "volatilite", "hacim"})


class TestNewIndicators(unittest.TestCase):
    def setUp(self) -> None:
        self.df = synthetic_ohlcv()

    def test_sar_flips_and_sits_on_correct_side(self) -> None:
        out = ind.parabolic_sar(self.df)
        direction = out["SAR_dir"].dropna()
        self.assertTrue(set(direction.unique()) <= {1.0, -1.0})
        self.assertGreater(direction.diff().abs().gt(0).sum(), 3)  # birden fazla donus
        up = out["SAR_dir"] == 1.0
        below = out["SAR"][up] <= self.df["High"][up]
        self.assertGreater(below.mean(), 0.95)

    def test_cci_zero_mean_ish(self) -> None:
        cci = ind.cci(self.df)["CCI"].dropna()
        self.assertTrue(((cci > -600) & (cci < 600)).all())
        self.assertLess(abs(float(cci.mean())), 120)

    def test_williams_r_bounds(self) -> None:
        willr = ind.williams_r(self.df)["WILLR"].dropna()
        self.assertTrue(((willr >= -100.0001) & (willr <= 0.0001)).all())

    def test_keltner_ordering_and_atr_basis(self) -> None:
        out = ind.keltner(self.df)
        valid = out["KC_upper"].notna()
        self.assertTrue((out["KC_upper"][valid] > out["KC_mid"][valid]).all())
        self.assertTrue((out["KC_mid"][valid] > out["KC_lower"][valid]).all())

    def test_donchian_contains_price(self) -> None:
        out = ind.donchian(self.df, 20)
        valid = out["DC_upper"].notna()
        self.assertTrue((self.df["Close"][valid] <= out["DC_upper"][valid] + 1e-9).all())
        self.assertTrue((self.df["Close"][valid] >= out["DC_lower"][valid] - 1e-9).all())

    def test_obv_direction_matches_price(self) -> None:
        out = ind.obv(self.df)
        step = out["OBV"].diff().dropna()
        change = self.df["Close"].diff().dropna().reindex(step.index)
        agree = ((step > 0) == (change > 0))[change != 0]
        self.assertGreater(agree.mean(), 0.99)

    def test_volume_profile_conserves_total_volume(self) -> None:
        """Her barin hacmi yuksek-dusuk araligina dagitilir; toplam korunmali."""
        hist = ind.volume_profile(self.df, bins=40)["VP_hist"]
        self.assertEqual(len(hist), 40)
        self.assertAlmostEqual(float(hist.sum()), float(self.df["Volume"].sum()),
                               delta=float(self.df["Volume"].sum()) * 1e-9)
        self.assertGreaterEqual(float(hist.index[0]), float(self.df["Low"].min()) - 1e-9)

    def test_atr_pct_is_relative(self) -> None:
        out = ind.atr_bands(self.df)
        ratio = (out["ATR"] / self.df["Close"] * 100).dropna()
        pd.testing.assert_series_equal(ratio, out["ATR_pct"].dropna(),
                                       check_names=False)

    def test_compute_rejects_unknown_key(self) -> None:
        with self.assertRaises(KeyError):
            ind.compute(self.df, keys=("supertrend", "yok_boyle_bir_sey"))


if __name__ == "__main__":
    unittest.main()
