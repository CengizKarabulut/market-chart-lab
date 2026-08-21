"""Telegram botu: gruptan komutla grafik uretir.

Iki calisma bicimi:

    python -m src.bot            surekli dinler (bilgisayar acik kalmali)
    python -m src.bot --once     bekleyen komutlari isler ve cikar

Ikincisi GitHub Actions icin: zamanlanmis is her calistiginda birikmis
komutlari isler. Telegram guncellemeleri 24 saat sunucusunda tutar ve offset
ile onaylanana kadar tekrar tekrar dondurur; bu yuzden calismalar arasinda
durum saklamaya gerek yoktur. Isin sonunda offset onaylanir, ayni komut iki
kez islenmez.

Komutlar:
    /grafik TMPOL                 varsayilan araliklar (4h, 1d, 1wk, 1mo)
    /grafik TMPOL 1d              tek aralik
    /grafik ASELS 4h,1d           birden fazla aralik
    /grafik BTC-USD 1d            kripto ve yabanci hisse de calisir
    /kareler                      hangi karelerin uretildigini yazar
    /yardim                       komut listesi

Guvenlik: yalnizca TELEGRAM_CHAT_ID ile eslesen sohbetten gelen komutlar
islenir. Baska bir gruba eklenirse bot sessiz kalir. Bu onemli, cunku botun
token'i bilen biri onu kendi grubuna ekleyebilir.

Bot uzun yoklama (long polling) kullanir; acik bir port ya da web kancasi
gerektirmez, ev bilgisayarinda calisir.
"""

from __future__ import annotations

import os
import time
import traceback
from pathlib import Path

from . import telegram as tg
from .compose import compose_grid
from .pipeline import INTERVAL_LABELS, build_views, default_bars
from .render_png import render_png
from .theme import get_theme
from .views import resolve_views

DEFAULT_INTERVALS = ("4h", "1d", "1wk", "1mo")
#: Ayni anda tek is calissin; art arda gelen komutlar sirayla islenir
BUSY_MESSAGE = "Şu anda başka bir grafik hazırlanıyor, birazdan tekrar deneyin."


def _allowed(message: dict) -> bool:
    """Komut, yapilandirilan sohbetten mi geliyor?"""
    expected = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return bool(expected) and str(message.get("chat", {}).get("id")) == expected


def _parse(text: str) -> tuple[str, list[str]]:
    """'/grafik TMPOL 4h,1d' -> ('grafik', ['TMPOL', '4h,1d')]."""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return "", []
    command = parts[0][1:].split("@")[0].lower()  # /grafik@BotAdi -> grafik
    return command, parts[1:]


def _render_and_send(symbol: str, intervals: list[str], thread_id: str | None) -> None:
    theme = get_theme("tv")
    views = resolve_views("grid")
    outdir = Path(os.environ.get("BOT_OUTDIR", "out"))
    sent = 0

    for interval in intervals:
        try:
            view_set = build_views(
                symbol, views, interval=interval, bars=default_bars(interval),
            )
        except Exception as exc:  # noqa: BLE001
            tg.send_message(f"⚠️ <b>{symbol}</b> · {interval}: {exc}", thread_id)
            continue

        stem = f"{view_set.symbol.display.replace('-', '_')}_{interval}"
        tiles = []
        for i, result in enumerate(view_set, start=1):
            path = outdir / f"{stem}_{i:02d}_{result.key}.png"
            render_png(result.spec, theme, path, width_px=1500, compact=True)
            tiles.append(path)

        grid = outdir / f"{stem}_izgara.png"
        label = INTERVAL_LABELS.get(interval, interval)
        compose_grid(tiles, grid, theme, columns=2,
                     title=f"{view_set.symbol.display} · {label}",
                     subtitle=f"{view_set.subtitle} · {view_set.generated_at}")

        caption = tg.build_caption(
            f"{view_set.symbol.display} · {label}",
            view_set.subtitle, view_set.results[0].spec.snapshot,
        )
        # Izgara genis oldugu icin dosya olarak gonderilir; fotograf olarak
        # gonderilse Telegram uzun kenari ~1280'e indirir ve yazilar okunmaz olur.
        tg.send_document(grid, caption, thread_id)
        sent += 1

    if sent == 0:
        tg.send_message(f"❌ <b>{symbol}</b> için grafik üretilemedi.", thread_id)


def handle(message: dict) -> None:
    """Tek bir mesaji isler."""
    text = message.get("text", "")
    thread_id = message.get("message_thread_id")
    thread_id = str(thread_id) if thread_id is not None else None
    command, args = _parse(text)

    if command in {"yardim", "help", "start"}:
        tg.send_message(
            "<b>Komutlar</b>\n"
            "/grafik SEMBOL [aralık] — gösterge ızgarası üretir\n"
            "   örn: <code>/grafik TMPOL</code>\n"
            "   örn: <code>/grafik ASELS 1d</code>\n"
            "   örn: <code>/grafik BTC-USD 4h,1d</code>\n"
            f"   varsayılan aralıklar: {', '.join(DEFAULT_INTERVALS)}\n"
            "/kareler — hangi karelerin üretildiğini gösterir\n"
            "/yardim — bu mesaj",
            thread_id,
        )
        return

    if command == "kareler":
        lines = ["<b>Her ızgarada dört kare</b>", ""]
        for view in resolve_views("grid"):
            lines.append(f"• <b>{view.title}</b> — {view.note}")
        lines.append("")
        lines.append("Mum panelinde tek gösterge, altında üç ayrı ölçekli panel.")
        tg.send_message("\n".join(lines), thread_id)
        return

    if command != "grafik":
        return  # tanimadigi komutlara sessiz kalir

    if not args:
        tg.send_message("Sembol gerekli. Örnek: <code>/grafik TMPOL</code>", thread_id)
        return

    symbol = args[0].upper()
    if len(args) > 1:
        intervals = [i for i in args[1].replace(",", " ").split() if i]
        unknown = [i for i in intervals if i not in INTERVAL_LABELS]
        if unknown:
            tg.send_message(
                f"Bilinmeyen aralık: {', '.join(unknown)}\n"
                f"Geçerli: {', '.join(INTERVAL_LABELS)}", thread_id)
            return
    else:
        intervals = list(DEFAULT_INTERVALS)

    tg.send_message(
        f"⏳ <b>{symbol}</b> hazırlanıyor · {', '.join(intervals)}", thread_id)
    _render_and_send(symbol, intervals, thread_id)


def poll_once(timeout: int = 0) -> int:
    """Bekleyen komutlari isler, onaylar ve islenen sayiyi dondurur.

    Zamanlanmis calistirmalar (GitHub Actions) icin. Durum dosyasina gerek
    yoktur: son adimda offset onaylanir, boylece ayni komut bir daha gelmez.
    """
    tg._credentials()
    updates = tg.get_updates(timeout=timeout)
    if not updates:
        return 0

    handled = 0
    last_id = updates[-1]["update_id"]
    for update in updates:
        message = update.get("message")
        if not message or not _allowed(message):
            continue
        try:
            handle(message)
            handled += 1
        except Exception:  # noqa: BLE001 - tek komut hatasi digerlerini engellemesin
            traceback.print_exc()

    # Onay: bu offset'ten oncekiler bir daha dondurulmez
    tg.get_updates(offset=last_id + 1, timeout=0)
    return handled


def run(poll_timeout: int = 30) -> None:
    """Bot dongusu. Ctrl+C ile durur."""
    tg._credentials()  # eksik yapilandirmayi hemen bildir
    print("Bot calisiyor. Komutlar: /grafik SEMBOL [aralik] · /kareler · /yardim")
    print("Durdurmak icin Ctrl+C")

    offset: int | None = None
    # Botu baslatmadan once biriken eski komutlar islenmesin
    for update in tg.get_updates(timeout=0):
        offset = update["update_id"] + 1

    while True:
        try:
            updates = tg.get_updates(offset=offset, timeout=poll_timeout)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - ag hatalarinda dongu surmeli
            print(f"getUpdates hatasi: {exc}")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message or not _allowed(message):
                continue
            try:
                handle(message)
            except Exception:  # noqa: BLE001 - tek komut hatasi botu durdurmasin
                traceback.print_exc()
                try:
                    tg.send_message("❌ Beklenmeyen hata; günlüğe yazıldı.",
                                    str(message.get("message_thread_id") or "") or None)
                except Exception:  # noqa: BLE001
                    pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="market-chart-lab bot")
    parser.add_argument("--once", action="store_true",
                        help="Bekleyen komutlari isle ve cik (zamanlanmis calistirma)")
    options = parser.parse_args()

    if options.once:
        count = poll_once()
        print(f"{count} komut islendi")
    else:
        try:
            run()
        except KeyboardInterrupt:
            print("\nBot durduruldu.")
