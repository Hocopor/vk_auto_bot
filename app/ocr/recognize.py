import asyncio

from PIL import Image, ImageOps

from app.core.config import settings

import pytesseract

if settings.tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

_PDF_RENDER_SCALE = 2.5


def _is_pdf(path: str) -> bool:
    """PDF по расширению ИЛИ по сигнатуре файла (%PDF- в первых байтах)."""
    if path.lower().endswith(".pdf"):
        return True
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def _render_pdf_first_page(path: str) -> Image.Image:
    """Рендер 1-й страницы PDF в PIL.Image через pypdfium2 (без системных зависимостей)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[0]
        bitmap = page.render(scale=_PDF_RENDER_SCALE)
        return bitmap.to_pil().convert("RGB")
    finally:
        pdf.close()


def _open_image(path: str) -> Image.Image:
    """Открыть чек как PIL.Image: PDF → рендер 1-й страницы, иначе обычная картинка."""
    if _is_pdf(path):
        return _render_pdf_first_page(path)
    return Image.open(path)


def _preprocess(img: Image.Image) -> Image.Image:
    """Подготовка изображения для OCR: grayscale, автоконтраст, апскейл мелких картинок."""
    img = ImageOps.exif_transpose(img)        # учесть EXIF-ориентацию фото
    img = img.convert("L")                    # grayscale
    img = ImageOps.autocontrast(img)
    w, h = img.size
    if max(w, h) < 1000:
        scale = 1000 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)))
    return img


def recognize_text_sync(path: str) -> str:
    """Синхронное распознавание (rus+eng). Может бросить pytesseract.TesseractNotFoundError."""
    img = _preprocess(_open_image(path))
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
