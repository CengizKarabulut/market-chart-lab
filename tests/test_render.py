"""Cizim katmani duman testleri (ag baglantisi gerektirmez)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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

    def test_views_cover_all_ten_indicators(self) -> None:
        from src.views import VIEWS

        covered = {k for v in VIEWS for k in v.compute_keys}
        self.assertEqual(covered, set(ind.ALL_INDICATORS))

    def test_resolve_views(self) -> None:
        from src.views import DEFAULT_SET, VIEWS, resolve_views

        self.assertEqual(len(resolve_views("all")), len(VIEWS))
        self.assertEqual(len(resolve_views("set")), len(DEFAULT_SET))
        self.assertEqual([v.key for v in resolve_views("momentum,bollinger")],
                         ["momentum", "bollinger"])
        with self.assertRaises(KeyError):
            resolve_views("yok")

    def test_compute_keys_deduplicated(self) -> None:
        from src.plotspec import compute_keys_for

        self.assertEqual(compute_keys_for(("bbands", "bbstate", "bbwidth")), ("bbands",))
        self.assertEqual(compute_keys_for(("volume", "rvol")), ("volume",))


class TestRenderers(unittest.TestCase):
    def setUp(self) -> None:
        self.df = synthetic_ohlcv(320)
        series = ind.compute(self.df)
        df, series = extend_future(self.df, series, 25)
        self.spec = build_spec(df, series, ind.ALL_INDICATORS, "TEST", "sentetik veri",
                               note="tum gostergeler")

    def test_spec_has_five_panels_and_overlays(self) -> None:
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
        self.assertEqual((args.interval, args.bars, args.theme), ("1d", 250, "ink"))


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

    def test_only_ichimoku_views_are_extended(self) -> None:
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("momentum,ichimoku"), bars=200)
        momentum, ichimoku = result.results
        self.assertEqual(len(momentum.spec.df), 200)
        self.assertEqual(len(ichimoku.spec.df), 225)

    def test_snapshot_identical_across_views(self) -> None:
        """Ayni bar, ayni ozet: kareler arasinda tutarsiz rakam gorunmemeli."""
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("set"), bars=200)
        first = dict((label, value) for label, value, _ in result.results[0].spec.snapshot)
        for other in result.results[1:]:
            values = dict((label, value) for label, value, _ in other.spec.snapshot)
            self.assertEqual(first["Son"], values["Son"], other.key)
