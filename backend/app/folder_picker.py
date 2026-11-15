"""Native local directory chooser; never invokes a shell or scans folders."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ZENITY = Path("/usr/bin/zenity")


def choose_project_folder() -> Path | None:
    if not ZENITY.is_file():
        raise RuntimeError("Yerel klasör seçici (zenity) bu bilgisayarda bulunamadı.")
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        raise RuntimeError("Grafik oturumu bulunamadı; klasör yolunu elle girebilirsiniz.")
    start = Path.home()
    try:
        result = subprocess.run(
            [
                str(ZENITY), "--file-selection", "--directory",
                "--title=Proje klasörünü seçin", f"--filename={start}/",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "GTK_USE_PORTAL": "1"},
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Klasör seçme penceresi zaman aşımına uğradı.") from error
    except OSError as error:
        raise RuntimeError("Yerel klasör seçme penceresi açılamadı.") from error
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise RuntimeError("Klasör seçme penceresi hata verdi.")
    selected = result.stdout.rstrip("\n")
    if not selected or "\x00" in selected:
        raise RuntimeError("Klasör seçici geçersiz bir sonuç verdi.")
    path = Path(selected)
    if not path.is_absolute() or not path.is_dir():
        raise RuntimeError("Seçilen klasör artık erişilebilir değil.")
    return path.resolve(strict=True)
