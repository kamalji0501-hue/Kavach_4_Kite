"""Phase-1 alive menu branding — per-bot logo on top, HTML caption below.

Used by DRISHTI / KAVACH / KAVACH2 / JAGRAN / SARANSH start pages (hi /start).
Robot avatars live under ``image/robot/<bot>.png``.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from telegram import InputFile, Message
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

_CAPTION_LIMIT = 1024
# Keep uploads small — Telegram media uploads often time out above ~50KB here.
_MAX_SIDE = 512
_JPEG_QUALITY = 75
_PHOTO_TIMEOUT = 90.0
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".PNG", ".JPG", ".JPEG", ".WEBP")

_PKG_ROOT = Path(__file__).resolve().parent
_WORKSPACE = _PKG_ROOT.parent
_LOGO_SEARCH_DIRS = (
    _WORKSPACE / "image" / "logo",
    _WORKSPACE.parent / "image" / "logo" if _WORKSPACE.name == "kavach-2.0" else _WORKSPACE / "image" / "logo",
    Path("/home/kamalji0501e/Batman Algo Files/LOGO"),
)
_ROBOT_IMAGE_ROOTS = (
    _WORKSPACE / "image" / "robot",
    _WORKSPACE.parent / "image" / "robot" if _WORKSPACE.name == "kavach-2.0" else _WORKSPACE / "image" / "robot",
    Path("/home/kamalji0501e/Batman Algo Files/Robot Images"),
)
_BOT_LOGO_ALIASES: dict[str, tuple[str, ...]] = {
    "drishti": ("drishti", "Drishti"),
    "jagran": ("jagran", "Jagran"),
    "kavach": ("kavach2", "kavach", "Kavach"),
    "kavach2": ("kavach2", "kavach", "Kavach"),
    "ratripal": ("ratripal", "kavach2", "kavach", "Kavach"),
}

_prepared_logo: dict[str, bytes] = {}  # source path → jpeg bytes


def _robot_search_dirs() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for folder in _ROBOT_IMAGE_ROOTS:
        folder = folder.resolve() if folder.exists() else folder
        if folder in seen or not folder.is_dir():
            continue
        seen.add(folder)
        out.append(folder)
    return out


def _match_image_file(folder: Path, stem: str) -> Path | None:
    for ext in _IMAGE_EXTS:
        candidate = folder / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    sub = folder / stem
    if sub.is_dir():
        hits = sorted(p for p in sub.iterdir() if p.is_file() and p.suffix in _IMAGE_EXTS)
        if hits:
            return hits[0]
    return None


def find_brand_logo(bot_name: str | None = None) -> Path | None:
    """Return per-bot robot image, else legacy shared logo."""
    if bot_name:
        for folder in _robot_search_dirs():
            for stem in _BOT_LOGO_ALIASES.get(bot_name.lower(), (bot_name.lower(),)):
                hit = _match_image_file(folder, stem)
                if hit is not None:
                    return hit

    exts = _IMAGE_EXTS
    seen: set[Path] = set()
    for folder in _LOGO_SEARCH_DIRS:
        folder = folder.resolve() if folder.exists() else folder
        if folder in seen or not folder.is_dir():
            continue
        seen.add(folder)
        preferred = folder / "kavach_logo.png"
        if preferred.is_file():
            return preferred
        hits = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in exts)
        if hits:
            return hits[0]
    return None


def prepare_logo_jpeg(logo_path: Path) -> bytes:
    """Resize/compress logo for Telegram photo/profile uploads."""
    key = str(logo_path.resolve())
    cached = _prepared_logo.get(key)
    if cached is not None:
        return cached

    raw = logo_path.read_bytes()
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            w, h = im.size
            longest = max(w, h)
            if longest > _MAX_SIDE:
                scale = _MAX_SIDE / float(longest)
                im = im.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
            payload = buf.getvalue()
    except Exception as exc:
        logger.warning("Logo prepare failed (%s); using original bytes", exc)
        payload = raw

    _prepared_logo[key] = payload
    logger.info("Alive logo prepared — %s bytes from %s", len(payload), logo_path.name)
    return payload


def logo_photo_input(logo_path: Path) -> InputFile:
    """Clear logo for sendPhoto — no blur/watermark; compressed for upload speed."""
    payload = prepare_logo_jpeg(logo_path)
    return InputFile(io.BytesIO(payload), filename="brand_logo.jpg")


async def reply_alive_card(
    message: Message,
    caption_html: str,
    *,
    reply_markup: Any = None,
    bot_name: str | None = None,
) -> None:
    """Send the shared brand logo on top, then alive content.

    The top-of-card image is intentionally the shared KDFINSCHOOL brand logo for
    every bot. Per-bot robot images are used only as Telegram profile pictures
    (see scripts/set_bot_profile_photos.py), not on the alive card.
    """
    del bot_name  # alive card always uses the shared brand logo
    logo = find_brand_logo()
    if logo is not None:
        photo = logo_photo_input(logo)
        send_kwargs: dict[str, Any] = {
            "photo": photo,
            "read_timeout": _PHOTO_TIMEOUT,
            "write_timeout": _PHOTO_TIMEOUT,
            "connect_timeout": 30.0,
            "pool_timeout": 10.0,
        }
        try:
            if len(caption_html) <= _CAPTION_LIMIT:
                await message.reply_photo(
                    caption=caption_html,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                    **send_kwargs,
                )
                return
            await message.reply_photo(**send_kwargs)
        except Exception as exc:
            logger.warning("Alive logo send failed (%s); falling back to text", exc)

    await message.reply_text(
        caption_html,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )
