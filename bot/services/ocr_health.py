"""Startup diagnostics for PDF text extraction and OCR dependencies."""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class OCRHealth:
    enabled: bool
    tesseract_available: bool
    hindi_language_available: bool
    poppler_available: bool
    languages: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return (
            not self.enabled
            or (
                self.tesseract_available
                and self.hindi_language_available
                and self.poppler_available
            )
        )


def _run_command(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return result.returncode, (result.stdout or result.stderr or "")


def check_ocr_environment(enabled: bool, logger: logging.Logger | None = None) -> OCRHealth:
    """Log OCR dependency status without preventing the bot from starting."""
    log = logger or logging.getLogger(__name__)
    if not enabled:
        log.info("OCR check: disabled (SOURCE_OCR_ENABLED=false)")
        return OCRHealth(False, False, False, False)

    tesseract_path = shutil.which("tesseract")
    pdftoppm_path = shutil.which("pdftoppm")
    pdfinfo_path = shutil.which("pdfinfo")
    tesseract_available = bool(tesseract_path)
    poppler_available = bool(pdftoppm_path and pdfinfo_path)
    languages: tuple[str, ...] = ()
    hindi_available = False

    if tesseract_available:
        return_code, raw_languages = _run_command([tesseract_path, "--list-langs"])
        if return_code == 0:
            parsed = {
                line.strip()
                for line in raw_languages.splitlines()
                if line.strip() and not line.lower().startswith("list of available")
            }
            languages = tuple(sorted(parsed))
            hindi_available = "hin" in parsed

    health = OCRHealth(
        enabled=True,
        tesseract_available=tesseract_available,
        hindi_language_available=hindi_available,
        poppler_available=poppler_available,
        languages=languages,
    )
    if not tesseract_available:
        log.error("OCR check failed: tesseract was not found on PATH")
    else:
        log.info("OCR check: Tesseract available (%s)", tesseract_path)
        log.info("OCR languages detected: %s", ", ".join(languages) or "none")
        if hindi_available:
            log.info("OCR language validation: Hindi (hin) available")
        else:
            log.error("OCR language validation failed: Hindi (hin) is missing")
    if poppler_available:
        log.info("PDF tools check: Poppler available (pdftoppm, pdfinfo)")
    else:
        log.error("PDF tools check failed: pdftoppm/pdfinfo not found on PATH")
    if health.ready:
        log.info("OCR health: READY for scanned PDF indexing")
    else:
        log.error("OCR health: NOT READY; scanned PDFs may fail until dependencies are installed")
    return health
