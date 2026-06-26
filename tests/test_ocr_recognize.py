import pytest

from app.ocr import recognize


def test_recognize_import():
    assert isinstance(recognize.tesseract_available(), bool)


def test_recognize_real(tmp_path):
    if not recognize.tesseract_available():
        pytest.skip("tesseract not installed")

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "Итого 1000 руб", fill="black")

    img_path = tmp_path / "receipt.png"
    img.save(img_path)

    text = recognize.recognize_text_sync(str(img_path))
    assert isinstance(text, str)
    assert text.strip() != ""


def _make_pdf(tmp_path, text="Итого 1000 руб"):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), text, fill="black")
    pdf_path = tmp_path / "receipt.pdf"
    img.save(str(pdf_path), "PDF", resolution=150.0)
    return pdf_path


def test_is_pdf_by_extension(tmp_path):
    p = _make_pdf(tmp_path)
    assert recognize._is_pdf(str(p))


def test_is_pdf_by_signature(tmp_path):
    p = _make_pdf(tmp_path)
    renamed = tmp_path / "receipt.bin"   # без .pdf — ловим по сигнатуре %PDF-
    p.rename(renamed)
    assert recognize._is_pdf(str(renamed))


def test_open_image_renders_pdf(tmp_path):
    from PIL import Image
    p = _make_pdf(tmp_path)
    img = recognize._open_image(str(p))
    assert isinstance(img, Image.Image)
    assert img.size[0] > 0 and img.size[1] > 0


def test_recognize_pdf_real(tmp_path):
    if not recognize.tesseract_available():
        pytest.skip("tesseract not installed")
    p = _make_pdf(tmp_path)
    text = recognize.recognize_text_sync(str(p))
    assert isinstance(text, str)
    assert text.strip() != ""
