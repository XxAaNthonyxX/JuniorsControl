"""Verifica la hoja exacta del servidor antes de abrir la ventana del equipo principal."""
import base64
import hmac
import socket
import ssl
import sys


def main(host, port, encoded):
    if host not in ("127.0.0.1", "localhost"):
        return 1
    expected = base64.b64decode(encoded, validate=True)
    ctx = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(expected))
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    with socket.create_connection((host, int(port)), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as channel:
            return 0 if hmac.compare_digest(channel.getpeercert(binary_form=True), expected) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(*sys.argv[1:]))
    except (TypeError, ValueError, OSError):
        raise SystemExit(1)
