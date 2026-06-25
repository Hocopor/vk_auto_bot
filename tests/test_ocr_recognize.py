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
