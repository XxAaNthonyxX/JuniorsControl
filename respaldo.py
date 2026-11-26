"""Bloqueo del servicio Windows asociado a la carpeta HTTPS."""
from contextlib import contextmanager
from pathlib import Path
import msvcrt

@contextmanager
def uso_exclusivo(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "instancia.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError("La base está en uso. Cierra Junior’s en su ventana de inicio "
                             "antes de abrir la restauración o de usar otro puerto.") from None
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


