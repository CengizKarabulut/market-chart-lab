"""Gorunumler: gostergeleri odakli karelere ayirir.

On gostergeyi tek bir grafige yigmak yerine, her biri 2-4 katman tasiyan
ayri kareler uretiriz. Boylece Bollinger'i incelerken MACD gurultusu,
momentuma bakarken bulut karmasasi ekrani mesgul etmez.

Her gorunum ayni sembol ve ayni bar araligindan cikar; tek veri cekimi ve
tek hesaplama turuyla hepsi uretilir (bkz. pipeline.build_views).

`keys` alani cizim sirasidir: once fiyat uzerine binen katmanlar, sonra alt
paneller. Hangi hesaplarin gerektigini plotspec.compute_keys_for cozer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .plotspec import compute_keys_for


@dataclass(frozen=True)
class View:
    key: str
    title: str
    keys: tuple[str, ...]
    note: str
    price_height: float = 3.2

    @property
    def compute_keys(self) -> tuple[str, ...]:
        return compute_keys_for(self.keys)


VIEWS: tuple[View, ...] = (
    View(
        key="ortalamalar",
        title="Ortalamalar",
        keys=("ma", "volume"),
        note="EMA 20/50 ve SMA 200 · hacim teyidi",
        price_height=3.6,
    ),
    View(
        key="bollinger",
        title="Bollinger",
        keys=("bbands", "bbstate", "bbwidth"),
        note="Bantlar · %B konumu · sıkışma ve genişleme",
    ),
    View(
        key="momentum",
        title="Momentum",
        keys=("ma", "rsi", "macd", "stochrsi"),
        note="RSI · MACD · Stochastic RSI aynı karede",
        price_height=2.8,
    ),
    View(
        key="supertrend",
        title="Supertrend",
        keys=("supertrend", "adx", "volume"),
        note="Yön ve trend gücü birlikte",
    ),
    View(
        key="ichimoku",
        title="Ichimoku",
        keys=("ichimoku", "adx"),
        note="Bulut 25 bar ileri taşınmış · ADX ile teyit",
        price_height=3.6,
    ),
    View(
        key="hacim",
        title="Hacim ve VWAP",
        keys=("vwap", "volume", "rvol"),
        note="Hacim ağırlıklı fiyat · bağıl hacim",
    ),
    View(
        key="tumu",
        title="Tüm göstergeler",
        keys=("ma", "bbands", "supertrend", "ichimoku", "vwap",
              "volume", "rsi", "macd", "stochrsi", "adx"),
        note="On göstergenin tamamı tek karede",
        price_height=3.4,
    ),
)

VIEWS_BY_KEY: dict[str, View] = {v.key: v for v in VIEWS}

#: Telegram'a seri halinde gonderilen varsayilan set (tumu haric alti kare)
DEFAULT_SET: tuple[str, ...] = tuple(v.key for v in VIEWS if v.key != "tumu")


def resolve_views(spec: str) -> tuple[View, ...]:
    """'all', 'set', virgullu liste veya tek anahtar cozer."""
    value = spec.strip().lower()
    if value in {"all", "hepsi"}:
        return VIEWS
    if value in {"set", "seri"}:
        return tuple(VIEWS_BY_KEY[k] for k in DEFAULT_SET)
    keys = [k.strip() for k in value.split(",") if k.strip()]
    unknown = [k for k in keys if k not in VIEWS_BY_KEY]
    if unknown:
        raise KeyError(
            f"Bilinmeyen gorunum: {', '.join(unknown)}. "
            f"Gecerli: {', '.join(VIEWS_BY_KEY)} (ya da 'all' / 'set')"
        )
    return tuple(VIEWS_BY_KEY[k] for k in keys)
