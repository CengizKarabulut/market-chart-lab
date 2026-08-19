"""Telegram teslimati.

PNG fotograf olarak, etkilesimli HTML ise dosya (document) olarak gonderilir.
Token ve chat id ortam degiskenlerinden okunur:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024


class TelegramError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise TelegramError(
            "TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID ortam degiskenleri tanimli degil"
        )
    return token, chat_id


def _post(method: str, files: dict, data: dict, timeout: int = 60) -> dict:
    token, chat_id = _credentials()
    data = {"chat_id": chat_id, **data}
    response = requests.post(
        API.format(token=token, method=method), data=data, files=files, timeout=timeout
    )
    payload = response.json() if response.content else {}
    if not payload.get("ok"):
        raise TelegramError(f"{method} basarisiz: {response.status_code} {payload}")
    return payload


def send_photo(path: str | Path, caption: str = "") -> dict:
    path = Path(path)
    with path.open("rb") as handle:
        return _post(
            "sendPhoto",
            files={"photo": (path.name, handle, "image/png")},
            data={"caption": caption[:CAPTION_LIMIT], "parse_mode": "HTML"},
        )


def send_document(path: str | Path, caption: str = "") -> dict:
    path = Path(path)
    with path.open("rb") as handle:
        return _post(
            "sendDocument",
            files={"document": (path.name, handle, "text/html")},
            data={"caption": caption[:CAPTION_LIMIT], "parse_mode": "HTML"},
        )


def send_media_group(paths: list[str | Path], caption: str = "") -> dict:
    """Birden fazla PNG'yi tek albüm olarak gonderir (Telegram siniri 10).

    Seri halinde gonderilen kareler boylece sohbette dagilmaz; basligi yalnizca
    ilk gorsel tasir.
    """
    paths = [Path(p) for p in paths]
    if not paths:
        raise TelegramError("Gonderilecek gorsel yok")
    if len(paths) > 10:
        raise TelegramError(f"Albume en fazla 10 gorsel konabilir ({len(paths)} verildi)")

    handles, files, media = [], {}, []
    try:
        for i, path in enumerate(paths):
            handle = path.open("rb")
            handles.append(handle)
            tag = f"file{i}"
            files[tag] = (path.name, handle, "image/png")
            item = {"type": "photo", "media": f"attach://{tag}"}
            if i == 0 and caption:
                item["caption"] = caption[:CAPTION_LIMIT]
                item["parse_mode"] = "HTML"
            media.append(item)
        return _post("sendMediaGroup", files=files,
                     data={"media": json.dumps(media)}, timeout=120)
    finally:
        for handle in handles:
            handle.close()


def build_caption(symbol: str, subtitle: str, chips: list[tuple[str, str, str]]) -> str:
    """PNG altinda gorunecek kisa ozet."""
    head = f"<b>{symbol}</b>\n<i>{subtitle}</i>"
    body = " · ".join(f"{label}: {value}" for label, value, _ in chips)
    return f"{head}\n{body}"
