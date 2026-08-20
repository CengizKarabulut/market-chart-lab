"""Cizim katmani duman testleri (ag baglantisi gerektirmez)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src import indicators as ind
from src.data_sources import resolve_symbol
from src.pipeline import extend_future
from src.plotspec import build_spec, segment_ranges
from src.render_html import render_html
from src.render_png import render_png
from src.theme import get_theme
from tests.test_indicators import synthetic_ohlcv


class TestSymbolRouting(unittest.TestCase):
    def test_bist_default(self) -> None:
        spec = resolve_symbol("THYAO")
        self.assertEqual(spec.provider, "borsapy")
        self.assertEqual(spec.market, "bist")

    def test_dot_is_suffix_routes_to_borsapy(self) -> None:
        self.assertEqual(resolve_symbol("ASELS.IS").query, "ASELS")

    def test_foreign_equity(self) -> None:
        spec = resolve_symbol("AAPL")
        self.assertEqual(spec.provider, "yfinance")

    def test_crypto_pair_and_alias(self) -> None:
        self.assertEqual(resolve_symbol("BTC-USD").market, "crypto")
        self.assertEqual(resolve_symbol("crypto:ETH").query, "ETH-USD")
        self.assertEqual(resolve_symbol("ETH").query, "ETH-USD")

    def test_explicit_prefix_wins(self) -> None:
        self.assertEqual(resolve_symbol("yf:AAPL").provider, "yfinance")
        self.assertEqual(resolve_symbol("bist:GARAN").provider, "borsapy")


class TestSegments(unittest.TestCase):
    def test_segment_ranges(self) -> None:
        colors = pd.Series(["up", "up", "down", "down", "down", "up"])
        self.assertEqual(segment_ranges(colors), [(0, 2, "up"), (2, 5, "down"), (5, 6, "up")])


class TestProjection(unittest.TestCase):
    def test_extend_future_places_raw_spans_ahead(self) -> None:
        df = synthetic_ohlcv(200)
        series = ind.compute(df)
        df_ext, ext = extend_future(df, series, 25)
        self.assertEqual(len(df_ext), len(df) + 25)
        # Uzatilan bolgede fiyat yok, bulut var
        self.assertTrue(df_ext["Close"].iloc[-1] != df_ext["Close"].iloc[-1])  # NaN
        self.assertFalse(pd.isna(ext["ICH_span_a"].iloc[-1]))
        self.assertAlmostEqual(
            float(ext["ICH_span_a"].iloc[len(df)]), float(series["ICH_span_a_raw"].iloc[-25])
        )

    def test_extend_future_is_noop_without_ichimoku(self) -> None:
        df = synthetic_ohlcv(120)
        series = ind.compute(df, keys=("ma", "rsi"))
        df_ext, ext = extend_future(df, series, 25)
        self.assertEqual(len(df_ext), len(df))


class TestViews(unittest.TestCase):
    def test_every_view_has_valid_keys(self) -> None:
        from src.plotspec import _OVERLAY_BUILDERS, _PANEL_BUILDERS
        from src.views import VIEWS

        valid = set(_OVERLAY_BUILDERS) | set(_PANEL_BUILDERS)
        for view in VIEWS:
            self.assertTrue(set(view.keys) <= valid, f"{view.key}: {set(view.keys) - valid}")
            self.assertTrue(set(view.compute_keys) <= set(ind.ALL_INDICATORS), view.key)

    def test_grid_views_take_one_indicator_per_category(self) -> None:
        """Her kare dort kategoriden BIRER gosterge tasimali."""
        from src.views import GRID_SET, VIEWS_BY_KEY

        for key in GRID_SET:
            view = VIEWS_BY_KEY[key]
            categories = [ind.CATEGORY[k] for k in view.compute_keys]
            self.assertEqual(sorted(categories),
                             ["hacim", "momentum", "trend", "volatilite"], key)

    def test_grid_views_do_not_repeat_a_display(self) -> None:
        from src.views import GRID_SET, VIEWS_BY_KEY

        used = [k for key in GRID_SET for k in VIEWS_BY_KEY[key].keys]
        self.assertEqual(len(used), len(set(used)), "ayni gosterim birden fazla karede")

    def test_grid_views_have_one_overlay_and_three_panels(self) -> None:
        """Izgaranin temel kurali: mum grafiginde TEK gosterge, altinda UC panel.

        Fiyat panelinde birden fazla katman ust uste binince grafik okunmaz
        hale geliyordu; bu test o duzenin bozulmasini engeller.
        """
        from src.plotspec import _OVERLAY_BUILDERS, _PANEL_BUILDERS
        from src.views import GRID_SET, VIEWS_BY_KEY

        for key in GRID_SET:
            view = VIEWS_BY_KEY[key]
            overlays = [k for k in view.keys if k in _OVERLAY_BUILDERS]
            panels = [k for k in view.keys if k in _PANEL_BUILDERS]
            self.assertEqual(len(overlays), 1, f"{key}: fiyat ustunde {overlays}")
            self.assertEqual(len(panels), 3, f"{key}: paneller {panels}")

    def test_grid_tiles_have_equal_height(self) -> None:
        """Ayni panel sayisi -> ayni yukseklik -> izgarada hizali karolar."""
        from src.views import GRID_SET, VIEWS_BY_KEY

        heights = {
            (VIEWS_BY_KEY[k].price_height, len(VIEWS_BY_KEY[k].keys)) for k in GRID_SET
        }
        self.assertEqual(len(heights), 1, "karolar farkli yukseklikte")

    def test_resolve_views(self) -> None:
        from src.views import DEFAULT_SET, VIEWS, resolve_views

        self.assertEqual(len(resolve_views("all")), len(VIEWS))
        self.assertEqual(len(resolve_views("set")), len(DEFAULT_SET))
        self.assertEqual([v.key for v in resolve_views("klasik,trend")],
                         ["klasik", "trend"])
        with self.assertRaises(KeyError):
            resolve_views("yok")

    def test_compute_keys_deduplicated(self) -> None:
        from src.plotspec import compute_keys_for

        self.assertEqual(compute_keys_for(("bbands", "bbstate", "bbwidth")), ("bbands",))
        self.assertEqual(compute_keys_for(("volume", "rvol")), ("volume",))


class TestRenderers(unittest.TestCase):
    def setUp(self) -> None:
        self.keys = ("ma", "bbands", "supertrend", "ichimoku", "vwap",
                     "volume", "rsi", "macd", "stochrsi", "adx")
        self.df = synthetic_ohlcv(320)
        series = ind.compute(self.df, keys=self.keys)
        df, series = extend_future(self.df, series, 25)
        self.spec = build_spec(df, series, self.keys, "TEST", "sentetik veri",
                               note="genel bakis")

    def test_spec_panels_follow_key_order(self) -> None:
        self.assertEqual([p.key for p in self.spec.panels],
                         ["volume", "rsi", "macd", "stochrsi", "adx"])
        self.assertGreaterEqual(len(self.spec.overlays), 8)
        self.assertGreaterEqual(len(self.spec.snapshot), 6)

    def test_png_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = render_png(self.spec, get_theme("ink"), Path(tmp) / "t.png", width_px=1400)
            self.assertGreater(path.stat().st_size, 50_000)

    def test_html_single_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = render_html(
                [("tumu", "Tümü", "not", self.spec)], get_theme("ink"),
                Path(tmp) / "t.html", ticker="TEST", subtitle="sentetik",
                source="test", generated="now",
            )
            body = path.read_text(encoding="utf-8")
            self.assertIn("plotly", body.lower())
            self.assertIn("TEST", body)
            self.assertGreater(len(body), 100_000)

    def test_html_tabs_load_plotly_once(self) -> None:
        """Cok kareli sayfada plotly.js tek kez yuklenmeli, aksi halde dosya sisiyor."""
        frames = [(f"k{i}", f"Kare {i}", "not", self.spec) for i in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            path = render_html(
                frames, get_theme("ink"), Path(tmp) / "t.html", ticker="TEST",
                subtitle="sentetik", source="test", generated="now",
            )
            body = path.read_text(encoding="utf-8")
            self.assertEqual(body.count("cdn.plot.ly"), 1)
            self.assertEqual(body.count('role="tab"'), 3)
            self.assertEqual(body.count('class="frame"'), 3)

    def test_html_rejects_empty_frames(self) -> None:
        with self.assertRaises(ValueError):
            render_html([], get_theme("ink"), "x.html", ticker="T", subtitle="",
                        source="", generated="")

    def test_paper_theme_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            render_png(self.spec, get_theme("paper"), Path(tmp) / "p.png", width_px=1200)


if __name__ == "__main__":
    unittest.main()


class TestCLIArgs(unittest.TestCase):
    def test_resolve_keys_all(self) -> None:
        from src.cli import resolve_keys

        self.assertEqual(resolve_keys("all"), ind.ALL_INDICATORS)
        self.assertEqual(resolve_keys(" MA , rsi "), ("ma", "rsi"))

    def test_resolve_keys_rejects_unknown(self) -> None:
        from src.cli import resolve_keys

        with self.assertRaises(SystemExit):
            resolve_keys("ma,bogus")

    def test_parse_args_defaults(self) -> None:
        from src.cli import parse_args

        args = parse_args(["--symbol", "THYAO"])
        self.assertEqual((args.interval, args.bars, args.theme), ("1d", 250, "tv"))
        self.assertEqual(args.grid, 2)


class TestPipelineViews(unittest.TestCase):
    """Veri kaynagini sahte veriyle degistirip uctan uca akisi dogrular."""

    def setUp(self) -> None:
        import src.pipeline as pipeline
        from src.data_sources import SymbolSpec

        self._original = pipeline.fetch_ohlcv
        pipeline.fetch_ohlcv = lambda symbol, period="1y", interval="1d", bars=None: (
            synthetic_ohlcv(520, seed=3),
            SymbolSpec(symbol, "borsapy", "TEST", "bist", "TEST"),
        )
        self.pipeline = pipeline

    def tearDown(self) -> None:
        self.pipeline.fetch_ohlcv = self._original

    def test_build_views_produces_one_spec_per_view(self) -> None:
        from src.views import resolve_views

        views = resolve_views("set")
        result = self.pipeline.build_views("TEST", views, bars=200)
        self.assertEqual(len(result), len(views))
        self.assertEqual([r.key for r in result], [v.key for v in views])

    def test_all_views_share_one_x_range(self) -> None:
        """Izgarada karolarin x eksenleri hizali olmali."""
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("grid"), bars=200)
        lengths = {len(r.spec.df) for r in result}
        self.assertEqual(len(lengths), 1, "kareler farkli x araligina sahip")
        # Ichimoku iceren set 25 bar ileri uzatilir
        self.assertEqual(lengths.pop(), 225)

    def test_set_without_cloud_is_not_extended(self) -> None:
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("klasik,trend"), bars=200)
        self.assertEqual({len(r.spec.df) for r in result}, {200})

    def test_snapshot_identical_across_views(self) -> None:
        """Ayni bar, ayni ozet: kareler arasinda tutarsiz rakam gorunmemeli."""
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("set"), bars=200)
        first = dict((label, value) for label, value, _ in result.results[0].spec.snapshot)
        for other in result.results[1:]:
            values = dict((label, value) for label, value, _ in other.spec.snapshot)
            self.assertEqual(first["Son"], values["Son"], other.key)



class TestCompose(unittest.TestCase):
    def test_grid_dimensions_and_row_alignment(self) -> None:
        """Farkli yukseklikteki karolar satir bazinda hizalanmali."""
        from PIL import Image

        from src.compose import compose_grid

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, height in enumerate((400, 500, 420, 420)):
                path = Path(tmp) / f"t{i}.png"
                Image.new("RGB", (600, height), "#101010").save(path)
                paths.append(path)

            out = compose_grid(paths, Path(tmp) / "grid.png", get_theme("tv"),
                               columns=2, title="TEST", subtitle="alt")
            with Image.open(out) as im:
                # 2 sutun x 600 + bosluklar + kenar paylari
                self.assertEqual(im.width, 22 * 2 + 600 * 2 + 18)
                # satir yukseklikleri: max(400,500)=500, max(420,420)=420
                self.assertEqual(im.height, 22 * 2 + 78 + 500 + 420 + 18)

    def test_grid_rejects_empty_input(self) -> None:
        from src.compose import compose_grid

        with self.assertRaises(ValueError):
            compose_grid([], "x.png", get_theme("tv"))


class TestFrameShape(unittest.TestCase):
    """Izgara karelerinin yapisal kurali: mum panelinde TEK gosterge."""

    def test_one_overlay_and_three_panels(self) -> None:
        from src.plotspec import _OVERLAY_BUILDERS, _PANEL_BUILDERS
        from src.views import GRID_SET, VIEWS_BY_KEY

        for key in GRID_SET:
            view = VIEWS_BY_KEY[key]
            overlays = [k for k in view.keys if k in _OVERLAY_BUILDERS]
            panels = [k for k in view.keys if k in _PANEL_BUILDERS]
            self.assertEqual(len(overlays), 1, f"{key}: mum panelinde {len(overlays)} gosterge")
            self.assertEqual(len(panels), 3, f"{key}: {len(panels)} alt panel")

    def test_rendered_spec_matches_the_rule(self) -> None:
        """Kural tanimda degil, uretilen ChartSpec'te de gecerli olmali."""
        import src.pipeline as pipeline
        from src.data_sources import SymbolSpec
        from src.views import resolve_views

        original = pipeline.fetch_ohlcv
        pipeline.fetch_ohlcv = lambda symbol, period="1y", interval="1d", bars=None: (
            synthetic_ohlcv(520, seed=5),
            SymbolSpec(symbol, "borsapy", "TEST", "bist", "TEST"),
        )
        try:
            result = pipeline.build_views("TEST", resolve_views("grid"), bars=150)
            for item in result:
                self.assertEqual(len(item.spec.panels), 3, item.key)
        finally:
            pipeline.fetch_ohlcv = original


class TestTelegramPayload(unittest.TestCase):
    """Istek govdesini agsiz dogrular: requests.post yakalanir."""

    def _capture(self, env: dict) -> dict:
        import os
        from unittest import mock

        from src import telegram

        captured: dict = {}

        class FakeResponse:
            status_code = 200
            content = b"{}"

            @staticmethod
            def json() -> dict:
                return {"ok": True, "result": {}}

        def fake_post(url, data=None, files=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["files"] = files
            return FakeResponse()

        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(telegram.requests, "post", fake_post), \
                tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.png"
            path.write_bytes(b"\x89PNG\r\n")
            telegram.send_document(path, "başlık")
        return captured

    def test_topic_id_is_sent_as_message_thread_id(self) -> None:
        captured = self._capture({
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-1003502567927",
            "TELEGRAM_TOPIC_ID": "18",
        })
        self.assertEqual(captured["data"]["chat_id"], "-1003502567927")
        self.assertEqual(captured["data"]["message_thread_id"], "18")
        self.assertIn("sendDocument", captured["url"])

    def test_topic_id_omitted_when_unset(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"TELEGRAM_TOPIC_ID": ""}, clear=False):
            captured = self._capture({
                "TELEGRAM_BOT_TOKEN": "123:ABC",
                "TELEGRAM_CHAT_ID": "-100999",
                "TELEGRAM_TOPIC_ID": "",
            })
        self.assertNotIn("message_thread_id", captured["data"])

    def test_missing_credentials_raise(self) -> None:
        import os
        from unittest import mock

        from src.telegram import TelegramError, send_photo

        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                          "TELEGRAM_CHAT_ID": ""}, clear=False):
            with self.assertRaises(TelegramError):
                send_photo("yok.png")


class TestOpenBarAndScale(unittest.TestCase):
    def test_open_bar_detection(self) -> None:
        from src.pipeline import last_bar_is_open

        idx = pd.bdate_range("2026-08-10", periods=9)  # son bar 20.08 00:00
        self.assertTrue(last_bar_is_open(idx, pd.Timestamp("2026-08-20 12:27")))
        self.assertFalse(last_bar_is_open(idx, pd.Timestamp("2026-08-21 09:00")))
        # Hafta sonu: cuma bari kapanmis sayilir
        self.assertFalse(last_bar_is_open(pd.bdate_range("2026-08-10", periods=5),
                                          pd.Timestamp("2026-08-16 12:00")))

    def test_open_bar_needs_enough_history(self) -> None:
        from src.pipeline import last_bar_is_open

        self.assertFalse(last_bar_is_open(pd.DatetimeIndex(["2026-08-20"])))

    def test_log_scale_triggers_on_wide_range(self) -> None:
        from src.plotspec import needs_log_scale

        narrow = synthetic_ohlcv(200, seed=4)
        self.assertFalse(needs_log_scale(narrow))

        wide = narrow.copy()
        wide[["Open", "High", "Low", "Close"]] *= np.exp(
            np.linspace(0, 2.5, len(wide))
        )[:, None]
        self.assertTrue(needs_log_scale(wide))

    def test_explicit_scale_overrides_auto(self) -> None:
        from src.plotspec import build_spec

        df = synthetic_ohlcv(200, seed=4)
        series = ind.compute(df, keys=("ma",))
        self.assertTrue(build_spec(df, series, ("ma",), "T", "s", log_price=True).log_price)
        self.assertFalse(build_spec(df, series, ("ma",), "T", "s", log_price=False).log_price)

    def test_scale_flag_mapping(self) -> None:
        from src.cli import _scale

        self.assertIsNone(_scale("auto"))
        self.assertTrue(_scale("log"))
        self.assertFalse(_scale("linear"))


class TestOutlierClipping(unittest.TestCase):
    def test_single_spike_sets_a_cap(self) -> None:
        from src.plotspec import clip_outliers

        rng = np.random.default_rng(1)
        series = pd.Series(list(rng.lognormal(13, 0.3, 200)) + [5e8])
        cap, exceeding = clip_outliers(series)
        self.assertTrue(np.isfinite(cap))
        self.assertGreaterEqual(exceeding, 1)
        self.assertLess(cap, float(series.max()))

    def test_even_series_is_not_clipped(self) -> None:
        from src.plotspec import clip_outliers

        series = pd.Series(np.random.default_rng(2).normal(100, 3, 200))
        cap, exceeding = clip_outliers(series)
        self.assertTrue(np.isnan(cap))
        self.assertEqual(exceeding, 0)

    def test_short_series_is_not_clipped(self) -> None:
        from src.plotspec import clip_outliers

        self.assertEqual(clip_outliers(pd.Series([1.0, 2.0, 900.0]))[1], 0)

    def test_volume_panel_reports_clipping(self) -> None:
        from src.plotspec import _volume_panel

        df = synthetic_ohlcv(200, seed=6)
        df.iloc[-3, df.columns.get_loc("Volume")] = float(df["Volume"].max()) * 60
        series = ind.compute(df, keys=("volume",))
        panel = _volume_panel(df, series)
        self.assertIn("kırpıldı", panel.params)
        self.assertIsNotNone(panel.yrange)
        # Kirpilan bar farkli renkte isaretlenmeli
        self.assertIn("accent2", list(panel.traces[0].colors))


class TestPanelClippingApplied(unittest.TestCase):
    """Kirpma mantigi panellere GERCEKTEN baglanmis mi.

    clip_outliers dogru calisip panel onu kullanmazsa kirpma sessizce
    devre disi kalir; bu test o durumu yakalar.
    """

    def setUp(self) -> None:
        df = synthetic_ohlcv(300, seed=17)
        df.iloc[-120, df.columns.get_loc("Volume")] *= 45
        self.df = df
        self.series = ind.compute(df, keys=("volume",))

    def test_rvol_panel_uses_cap(self) -> None:
        from src.plotspec import _rvol_panel

        panel = _rvol_panel(self.series)
        self.assertIsNotNone(panel.yrange, "RVOL paneli kirpma uygulamiyor")
        self.assertLess(panel.yrange[1], float(self.series["RVOL"].max()))
        self.assertIn("kırpıldı", panel.params)

    def test_volume_panel_uses_cap(self) -> None:
        from src.plotspec import _volume_panel

        panel = _volume_panel(self.df, self.series)
        self.assertIsNotNone(panel.yrange, "Hacim paneli kirpma uygulamiyor")
        self.assertLess(panel.yrange[1], float(self.series["VOL"].max()))


class TestResampling(unittest.TestCase):
    """4 saatlik barlar saatlikten turetilir; gun sinirlari korunmali."""

    def _hourly(self, days: int = 3, per_day: int = 8) -> pd.DataFrame:
        stamps = [
            pd.Timestamp("2026-08-17 10:00") + pd.Timedelta(days=d, hours=h)
            for d in range(days) for h in range(per_day)
        ]
        n = len(stamps)
        return pd.DataFrame(
            {"Open": np.arange(n, dtype=float) + 1,
             "High": np.arange(n, dtype=float) + 2,
             "Low": np.arange(n, dtype=float),
             "Close": np.arange(n, dtype=float) + 1.5,
             "Volume": np.full(n, 10.0)},
            index=pd.DatetimeIndex(stamps),
        )

    def test_ohlc_aggregation(self) -> None:
        from src.data_sources import resample_bars

        out = resample_bars(self._hourly(days=1), 4)
        self.assertEqual(len(out), 2)
        first = out.iloc[0]
        self.assertEqual(first["Open"], 1.0)      # ilk barin acilisi
        self.assertEqual(first["Close"], 4.5)     # dorduncu barin kapanisi
        self.assertEqual(first["High"], 5.0)      # en yuksek
        self.assertEqual(first["Low"], 0.0)       # en dusuk
        self.assertEqual(first["Volume"], 40.0)   # toplam

    def test_days_never_merge(self) -> None:
        """Kritik: bir gunun son bari ertesi gunun ilkiyle birlesmemeli."""
        from src.data_sources import resample_bars

        out = resample_bars(self._hourly(days=3), 4)
        self.assertEqual(len(out), 6)  # gunde 2, uc gun
        self.assertEqual(sorted(out.index.normalize().unique().tolist()),
                         sorted(pd.DatetimeIndex([
                             "2026-08-17", "2026-08-18", "2026-08-19"]).tolist()))

    def test_partial_last_bucket_is_kept(self) -> None:
        """Seans 4'e tam bolunmuyorsa artik bar yine de olusmali."""
        from src.data_sources import resample_bars

        out = resample_bars(self._hourly(days=1, per_day=6), 4)
        self.assertEqual(len(out), 2)
        self.assertEqual(out.iloc[1]["Volume"], 20.0)  # kalan iki bar

    def test_factor_one_is_identity(self) -> None:
        from src.data_sources import resample_bars

        df = self._hourly(days=1)
        pd.testing.assert_frame_equal(resample_bars(df, 1), df)


class TestMultiInterval(unittest.TestCase):
    def test_interval_list_parsing(self) -> None:
        from src.cli import _intervals

        self.assertEqual(_intervals("4h,1d,1wk"), ["4h", "1d", "1wk"])
        self.assertEqual(_intervals(" 1d , 1d ,1wk "), ["1d", "1wk"])

    def test_unknown_interval_rejected(self) -> None:
        from src.cli import _intervals

        with self.assertRaises(SystemExit):
            _intervals("7h")
        with self.assertRaises(SystemExit):
            _intervals("  ")

    def test_synthetic_intervals_declared(self) -> None:
        from src.data_sources import SYNTHETIC_INTERVALS
        from src.pipeline import DEFAULT_PERIODS, INTERVAL_LABELS

        for key in SYNTHETIC_INTERVALS:
            self.assertIn(key, DEFAULT_PERIODS, key)
            self.assertIn(key, INTERVAL_LABELS, key)
