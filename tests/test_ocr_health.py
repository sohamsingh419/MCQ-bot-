from types import SimpleNamespace

from bot.services.ocr_health import check_ocr_environment


def test_ocr_check_is_disabled_without_blocking(caplog) -> None:
    health = check_ocr_environment(False)
    assert health.enabled is False
    assert health.ready is True
    assert "OCR check: disabled" in caplog.text


def test_ocr_check_reports_tesseract_hindi_and_poppler(monkeypatch, caplog) -> None:
    paths = {
        "tesseract": "/usr/bin/tesseract",
        "pdftoppm": "/usr/bin/pdftoppm",
        "pdfinfo": "/usr/bin/pdfinfo",
    }
    monkeypatch.setattr("bot.services.ocr_health.shutil.which", lambda name: paths.get(name))
    monkeypatch.setattr(
        "bot.services.ocr_health.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="List of available languages in /usr/share/tessdata:\neng\nhin\n",
            stderr="",
        ),
    )
    health = check_ocr_environment(True)
    assert health.ready is True
    assert health.hindi_language_available is True
    assert health.languages == ("eng", "hin")
    assert "OCR health: READY" in caplog.text


def test_ocr_check_reports_missing_dependencies(monkeypatch, caplog) -> None:
    monkeypatch.setattr("bot.services.ocr_health.shutil.which", lambda name: None)
    health = check_ocr_environment(True)
    assert health.ready is False
    assert health.tesseract_available is False
    assert "tesseract was not found" in caplog.text
    assert "pdftoppm/pdfinfo not found" in caplog.text
