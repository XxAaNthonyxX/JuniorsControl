"""Carpeta del certificado HTTPS y perfiles de esta instalación."""
import os
from pathlib import Path


def carpeta_datos():
    return Path(os.environ.get("JUNIORS_DATA") or Path(os.environ["LOCALAPPDATA"]) / "Juniors Restaurante" / "datos").expanduser().resolve()
