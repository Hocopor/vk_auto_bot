import asyncio

from PIL import Image, ImageOps

from app.core.config import settings

import pytesseract

if settings.tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


def _preprocess(path: str) -> Image.Image:
    """Подготовка изображения для OCR: grayscale, автоконтраст, апскейл мелких картинок."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)        # учесть EXIF-ориентацию фото
    img = img.convert("L")                    # grayscale
    img = ImageOps.autocontrast(img)
    # апскейл, если картинка маленькая (Tesseract любит ~300 DPI)
    w, h = img.size
    if max(w, h) < 1000:
        scale = 1000 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)))
    return img


def recognize_text_sync(path: str) -> str:
    """Синхронное распознавание (rus+eng). Может бросить pytesseract.TesseractNotFoundError."""
    img = _preprocess(path)
    return pytesseract.image_to_string(img, lang="rus+eng")


async def recognize_text(path: str) -> str:
    """Асинхронная обёртка — Tesseract блокирующий, уносим в поток."""
    return await asyncio.to_thread(recognize_text_sync, path)


def tesseract_available() -> bool:
    """Доступен ли бинарь Tesseract (для условного запуска/тестов)."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
