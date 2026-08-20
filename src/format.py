"""Turkce sayi ve tarih bicimleme.

Neden elle: locale ayari sunucudan sunucuya degisir ve Windows'ta Turkce
locale adlari farklidir ("Turkish_Turkey" vs "tr_TR"). GitHub Actions'ta
locale hic kurulu olmayabilir. Bu yuzden bicimleme locale'den bagimsiz
yapilir; ayni girdi her ortamda ayni ciktiyi verir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: strftime %b yerine kullanilir
AYLAR = ("Oca", "Şub", "Mar", "Nis", "May", "Haz",
         "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")


def sayi(value: float, digits: int = 2) -> str:
    """1234.5 -> '1.234,50' (binlik nokta, ondalik virgul)."""
    if value is None or not np.isfinite(value):
        return "—"
    text = f"{value:,.{digits}f}"
    # once ayiricilari takas et, sonra yerlerine koy
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fiyat(value: float) -> str:
    """Buyuklugune gore basamak sayisi secer."""
    if value is None or not np.isfinite(value):
        return "—"
    if abs(value) >= 1000:
        return sayi(value, 0)
    if abs(value) >= 10:
        return sayi(value, 2)
    if abs(value) >= 1:
        return sayi(value, 3)
    return sayi(value, 4)


def kisa(value: float) -> str:
    """Buyuk sayilari kisaltir: 1250000 -> '1,25M'."""
    if value is None or not np.isfinite(value):
        return "—"
    for limit, suffix in ((1e12, "T"), (1e9, "Mr"), (1e6, "M"), (1e3, "B")):
        if abs(value) >= limit:
            return sayi(value / limit, 2).rstrip("0").rstrip(",") + suffix
    return sayi(value, 0)


def tarih(ts: pd.Timestamp, fmt: str = "gun") -> str:
    """fmt: 'gun' -> '14 Ağu', 'ay' -> 'Ağu 26', 'saat' -> '14 Ağu 09:45'."""
    ay = AYLAR[ts.month - 1]
    if fmt == "ay":
        return f"{ay} {ts.year % 100:02d}"
    if fmt == "saat":
        return f"{ts.day} {ay} {ts.hour:02d}:{ts.minute:02d}"
    if fmt == "dakika":
        return f"{ts.hour:02d}:{ts.minute:02d}"
    return f"{ts.day} {ay}"


def tam_tarih(ts: pd.Timestamp) -> str:
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year} {ts.hour:02d}:{ts.minute:02d}"
