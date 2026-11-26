"""Enlace QR de acceso, generado en el servidor para la dirección de esta red."""
from functools import lru_cache
import struct
import zlib
from runtime.qrencoder import QRCode, QRErrorCorrectLevel, QR8bitByte


def _chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


@lru_cache(maxsize=16)
def qr_png(url):
    code = QRCode(None, QRErrorCorrectLevel.M)
    code.addData(QR8bitByte(url))
    code.make()
    margin, scale = 4, 6
    size = (code.getModuleCount() + 2 * margin) * scale
    rows = []
    for y in range(-margin, code.getModuleCount() + margin):
        pixels = bytearray()
        for x in range(-margin, code.getModuleCount() + margin):
            dark = (0 <= x < code.getModuleCount() and 0 <= y < code.getModuleCount() and code.isDark(y, x))
            pixels.extend(bytes([0 if dark else 255]) * scale)
        rows.append((b"\x00" + pixels) * scale)
    header = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows))) + _chunk(b"IEND", b""))

