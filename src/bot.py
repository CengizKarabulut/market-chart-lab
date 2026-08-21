"""Telegram botu: gruptan komutla grafik uretir.

Calisma bicimleri:

    python -m src.bot                 suresiz dinler (Ctrl+C ile durur)
    python -m src.bot --minutes 50    50 dakika dinler, sonra cikar
    python -m src.bot --once          bekleyenleri isler ve cikar

--minutes GitHub Actions icin: tek kosu boyunca surekli dinlenir, sure dolunca
bot_runner kendini yeniden tetikleyip zinciri surdurur. Sik cron'lara guvenmek
yerine bu yontem tercih edilir; GitHub'in 5 dakikalik programlari pratikte
cogu zaman atlanir ve komutlar cevapsiz kalir.

Offset (islenen son guncelleme) diske yazilir. Kosular arasinda komut kaybolmaz
ve ayni komut iki kez islenmez.

Komutlar:
    /grafik TMPOL                 varsayilan araliklar (4h, 1d, 1wk, 1mo)
    /grafik TMPOL 1d              tek aralik
    /grafik ASELS 4h,1d           birden fazla aralik
    /grafik BTC-USD 1d            kripto ve yabanci hisse de calisir
    /kareler                      hangi karelerin uretildigini yazar
    /yardim                       komut listesi

Guvenlik ve kapsam:

- Yalnizca TELEGRAM_CHAT_ID ile eslesen sohbetten gelen komutlar islenir.
  Botun token'ini bilen biri onu kendi grubuna ekleyebilir; orada sessiz kalir.
- TELEGRAM_TOPIC_ID tanimliysa yalnizca O KONUDAN gelen komutlar islenir.
  Forum modundaki gruplarda bot her konuda cevap vermesin diye.
- Komut adlari benzersizdir (/grafik, /kareler, /grafikyardim). Ayni gruptaki
  baska bir bot da /yardim gibi genel adlar kullaniyorsa ikisi birden cevap
  verirdi. Genel adlar yalnizca "@BotAdi" ile acikca adreslendiginde islenir.

Bot uzun yoklama (long polling) kullanir; acik bir port ya da web kancasi
gerektirmez, ev bilgisayarinda calisir.
"""

from __future__ import annotations

import json
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
#: Telegram baglantiyi bu kadar saniye acik tutar; mesaj gelince hemen doner
LONG_POLL_SECONDS = 25
STATE_FILE = Path(os.environ.get("BOT_STATE_FILE", "state/telegram_offset.json"))
#: Ayni anda tek is calissin; art arda gelen komutlar sirayla islenir
BUSY_MESSAGE = "Şu anda başka bir grafik hazırlanıyor, birazdan tekrar deneyin."


def load_offset() -> int | None:
    """Islenen son guncellemenin sirasini diskten okur."""
    try:
        return int(json.loads(STATE_FILE.read_text(encoding="utf-8"))["offset"])
    except Exception:  # noqa: BLE001 - dosya yoksa ya da bozuksa bastan basla
        return None


def save_offset(offset: int) -> None:
    """Offset'i diske yazar; kosular arasinda komut kaybolmasin diye."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    except OSError as exc:
        print(f"offset yazilamadi: {exc}")


#: Bu bota ait, baska botlarla cakismasi beklenmeyen komutlar
OWN_COMMANDS = {"grafik", "kareler", "grafikyardim"}
#: Yalnizca "@BotAdi" ile adreslendiginde islenen genel komutlar
SHARED_COMMANDS = {"yardim", "help", "start"}


def _allowed(message: dict) -> bool:
    """Komut, yapilandirilan sohbetten VE konudan mi geliyor?"""
    expected = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not expected or str(message.get("chat", {}).get("id")) != expected:
        return False

    topic = os.environ.get("TELEGRAM_TOPIC_ID", "").strip()
    if not topic:
        return True  # konu kisiti yok

    # Forum grubunda baska konulardan gelen komutlar islenmez
    thread = message.get("message_thread_id")
    return thread is not None and str(thread) == topic


def _parse(text: str, username: str = "") -> tuple[str, list[str]]:
    """'/grafik TMPOL 4h,1d' -> ('grafik', ['TMPOL', '4h,1d']).

    Adresleme kurallari (grupta birden fazla bot olabilir):
      /grafik            -> islenir (bize ozgu ad)
      /grafik@BizimBot   -> islenir
      /grafik@BaskaBot   -> islenmez
      /yardim            -> islenmez (baska botta da var, ikisi birden cevap verirdi)
      /yardim@BizimBot   -> islenir
    """
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return "", []

    head = parts[0][1:]
    command, _, target = head.partition("@")
    command, target = command.lower(), target.lower()

    if target:
        if username and target != username:
            return "", []  # baska bota yazilmis
    elif command in SHARED_COMMANDS:
        return "", []  # adressiz genel komut: cakismayi onlemek icin atlanir

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
    command, args = _parse(text, tg.get_me())

    if command in SHARED_COMMANDS | {"grafikyardim"}:
        tg.send_message(
            "<b>Komutlar</b>\n"
            "/grafik SEMBOL [aralık] — gösterge ızgarası üretir\n"
            "   örn: <code>/grafik TMPOL</code>\n"
            "   örn: <code>/grafik ASELS 1d</code>\n"
            "   örn: <code>/grafik BTC-USD 4h,1d</code>\n"
            f"   varsayılan aralıklar: {', '.join(DEFAULT_INTERVALS)}\n"
            "/kareler — hangi karelerin üretildiğini gösterir\n"
            "/grafikyardim — bu mesaj",
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
    updates = tg.get_updates(offset=load_offset(), timeout=timeout)
    if not updates:
        return 0

    handled = 0
    last_id = updates[-1]["update_id"]
    save_offset(last_id + 1)
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


def run(minutes: float | None = None, poll_timeout: int = LONG_POLL_SECONDS) -> int:
    """Uzun baglanti ile dinler. minutes verilirse o sure sonunda cikar.

    Telegram baglantiyi poll_timeout saniye acik tutar ve mesaj gelir gelmez
    doner; bu yuzden dongu bos yere donmez ve komutlara saniyeler icinde cevap
    verilir.
    """
    tg._credentials()
    offset = load_offset()
    deadline = time.monotonic() + minutes * 60 if minutes else None

    print("Bot dinliyor. Komutlar: /grafik SEMBOL [aralik] · /kareler · /yardim")
    if deadline:
        print(f"Calisma suresi: {minutes:.0f} dakika")

    handled = 0
    while deadline is None or time.monotonic() < deadline:
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
            save_offset(offset)
            message = update.get("message")
            if not message or not _allowed(message):
                continue
            try:
                handle(message)
                handled += 1
            except Exception:  # noqa: BLE001 - tek komut hatasi botu durdurmasin
                traceback.print_exc()
                try:
                    tg.send_message(
                        "❌ Beklenmeyen hata; günlüğe yazıldı.",
                        str(message.get("message_thread_id") or "") or None)
                except Exception:  # noqa: BLE001
                    pass
    return handled


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="market-chart-lab bot")
    parser.add_argument("--once", action="store_true",
                        help="Bekleyen komutlari isle ve cik")
    parser.add_argument("--minutes", type=float, default=None,
                        help="Kac dakika dinlensin (bos: suresiz)")
    options = parser.parse_args()

    if options.once:
        print(f"{poll_once()} komut islendi")
    else:
        try:
            print(f"{run(minutes=options.minutes)} komut islendi")
        except KeyboardInterrupt:
            print("\nBot durduruldu.")
