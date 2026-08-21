"""GitHub Actions icinde surekli dinleyen bot calistiricisi.

Neden bu tasarim: GitHub'in sik zamanlanmis kosulari (orn. "*/5 * * * *")
pratikte cogu zaman atlanir; belgelerde "yogun donemlerde gecikebilir" yazar
ama gercekte 5 dakikalik programlar tamamen calismayabilir. Komutlara dakikalar
sonra cevap vermek ya da hic vermemek kabul edilebilir degil.

Cozum: tek bir kosu icinde UZUN BAGLANTI ile surekli dinlemek. Telegram
baglantiyi 25 saniye acik tutar ve mesaj gelir gelmez doner, boylece komutlara
saniyeler icinde cevap verilir. Kosu suresi dolunca calistirici kendini
yeniden tetikler ve zincir devam eder. Cron yalnizca zincir koparsa (hata,
iptal, kota) devreye giren emniyet agidir.

Ortam degiskenleri:
    BOT_RUN_MINUTES   kosu suresi (varsayilan 50; Actions siniri 6 saat ama
                      kisa tutmak zinciri saglamlastirir)
    BOT_SELF_RESTART  "0" verilirse zincir surdurulmez (yerel calistirma)
    GH_PAT            zincir icin kisisel erisim jetonu (asagiya bakin)
    GITHUB_TOKEN      Actions'in verdigi jeton (yedek)
    GITHUB_REPOSITORY "kullanici/depo" (Actions otomatik verir)
    GITHUB_REF_NAME   dal adi (Actions otomatik verir)

JETON NOTU: GitHub, GITHUB_TOKEN ile tetiklenen olaylarin yeni kosu
baslatmamasi kuralini uygular (sonsuz dongu korumasi). Zincirin surmesi icin
`actions: write` yetkisi olan bir kisisel erisim jetonunu GH_PAT olarak
tanimlamak gerekir. Tanimli degilse calistirici bunu acikca bildirir ve kosu
biter; cron bir sonraki saat basinda yeniden baslatir.
"""

from __future__ import annotations

import os
import sys

import requests

from . import bot

WORKFLOW_FILE = os.environ.get("BOT_WORKFLOW_FILE", "telegram-bot.yml")


def _restart_token() -> tuple[str, str] | None:
    """(jeton, kaynak adi) dondurur; yoksa None."""
    pat = os.environ.get("GH_PAT", "").strip()
    if pat:
        return pat, "GH_PAT"
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token, "GITHUB_TOKEN"
    return None


def restart_self() -> bool:
    """Ayni workflow'u yeniden tetikler. Basarili olursa True."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    ref = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"
    credentials = _restart_token()

    if not repo or not credentials:
        print("Zincir surdurulemedi: GITHUB_REPOSITORY veya jeton yok. "
              "Cron bir sonraki saat basinda yeniden baslatacak.")
        return False

    token, source = credentials
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
           f"{WORKFLOW_FILE}/dispatches")
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            json={"ref": ref},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"Zincir istegi basarisiz: {exc}")
        return False

    if response.status_code == 204:
        print(f"Zincir surduruldu ({source} ile yeni kosu tetiklendi).")
        return True

    print(f"Zincir surdurulemedi: HTTP {response.status_code} {response.text[:200]}")
    if source == "GITHUB_TOKEN":
        # GitHub, GITHUB_TOKEN ile tetiklenen olaylarin yeni kosu baslatmasini
        # engeller. Bu durumda PAT gerekir.
        print("Not: GITHUB_TOKEN ile tetiklenen olaylar yeni kosu baslatmaz. "
              "actions:write yetkili bir PAT'i GH_PAT olarak tanimlayin.")
    return False


def main() -> int:
    minutes = float(os.environ.get("BOT_RUN_MINUTES", "50"))
    handled = bot.run(minutes=minutes)
    print(f"Kosu bitti, {handled} komut islendi.")

    if os.environ.get("BOT_SELF_RESTART", "1") != "0":
        restart_self()
    return 0


if __name__ == "__main__":
    sys.exit(main())
