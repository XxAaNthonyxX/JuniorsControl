"""Mide el ciclo TLS, consulta y lectura JSON en una instalación de prueba nueva."""
from concurrent.futures import ThreadPoolExecutor
from math import ceil
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probar_sqlserver import escenario, APP, preparar_codigo_ui
from contextlib import contextmanager
from http.client import HTTPSConnection
from time import monotonic, sleep
from uuid import uuid4
import json, re, ssl, subprocess
ACCOUNT={"name":"Prueba local","email":"qa@example.test","password":"Prueba temporal 1234!"}
class Client:
    def __init__(self, host, port, ca):
        self.host, self.port = host, port
        self.tls = ssl.create_default_context(cafile=str(ca))
        self.cookie = ""

    def call(self, action=None, payload=None, request_id=None):
        conn = HTTPSConnection(self.host, self.port, context=self.tls, timeout=8)
        headers = {"Origin": f"https://{self.host}:{self.port}", "Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if action:
            content = json.dumps({"action": action, "payload": payload or {}, "request_id": request_id or str(uuid4())})
            conn.request("POST", "/api/action", content, headers)
        else:
            conn.request("GET", "/api/state", headers=headers)
        try:
            response = conn.getresponse()
            if response.getheader("Set-Cookie"):
                self.cookie = response.getheader("Set-Cookie").split(";", 1)[0]
            data = json.load(response)
            assert response.status == 200, (action, response.status, data.get("error"))
            return data
        finally:
            conn.close()



def bat_command(script, port):
    return [os.environ["ComSpec"], "/d", "/c", script.name,
            "--local", "--no-browser", "--port", str(port)]


def stop_test_process(process):
    if process.poll() is not None:
        return
    # El BAT de prueba tiene una consola exclusiva, oculta y distinta a la del usuario.
    send_break = ("import ctypes,sys,time; k=ctypes.WinDLL('kernel32',use_last_error=True); "
                  "k.FreeConsole(); assert k.AttachConsole(int(sys.argv[1])); "
                  "assert k.SetConsoleCtrlHandler(None,True); assert k.GenerateConsoleCtrlEvent(0,0); "
                  "time.sleep(.5); k.FreeConsole()")
    subprocess.run([sys.executable, "-c", send_break, str(process.pid)], capture_output=True,
                   timeout=7, creationflags=subprocess.CREATE_NO_WINDOW)
    if process.poll() is None:
        try:
            process.stdin.write(b"S\r\nY\r\n")
            process.stdin.close()
        except (BrokenPipeError,OSError):
            pass
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                       timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        process.wait(timeout=5)
        raise AssertionError("La consola de prueba no cerró tras Ctrl+C.")


@contextmanager
def running(script, log, env):
    start = subprocess.STARTUPINFO()
    start.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    start.wShowWindow = subprocess.SW_HIDE
    with open(log, "wb") as stream:
        proc = subprocess.Popen(bat_command(script, 0), cwd=script.parent, env=env,
                                stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=start)
    try:
        deadline = monotonic()+55
        while monotonic()<deadline:
            message = log.read_text(encoding="utf-8",errors="replace")
            port = re.search(r"https://127\.0\.0\.1:(\d+)", message)
            if port:
                yield int(port.group(1))
                break
            if proc.poll() is not None:
                raise RuntimeError(message)
            sleep(.2)
        else:
            raise TimeoutError(log.read_text(errors="replace"))
    finally:
        stop_test_process(proc)





def medir(servidor, entorno, temporal):
    with running(servidor, temporal / "inicio.log", entorno) as puerto:
        ca = Path(entorno["JUNIORS_DATA"]) / "https" / "ca.pem"
        clientes = [Client("127.0.0.1", puerto, ca) for _ in range(4)]
        assert clientes[0].call()["setup"], "El ensayo necesita una base nueva."
        clientes[0].call("bootstrap", dict(ACCOUNT, code="012345", demo=True))
        for cliente in clientes:
            cliente.call("login", ACCOUNT)
        for mesa in range(1, 11):
            pedido = clientes[0].call("pedidos.save", {"table_name":f"Mesa {mesa}", "lines":[{"product_id":1,"qty":1}]})
            clientes[0].call("pedidos.pay", {"id":pedido["id"]})

        def consultar(cliente):
            tiempos = []
            for _ in range(25):
                inicio = perf_counter()
                estado = cliente.call()
                tiempos.append(perf_counter() - inicio)
                assert len(estado["orders"]) == 10 and estado["net_sales"] > 0
            return tiempos

        with ThreadPoolExecutor(max_workers=4) as grupo:
            tiempos = sorted(t for bloque in grupo.map(consultar, clientes) for t in bloque)
        p95 = tiempos[ceil(0.95 * len(tiempos)) - 1]
        rapidas = sum(t <= 3 for t in tiempos)
        print(f"Estado por HTTPS local · 4 sesiones · {rapidas}/{len(tiempos)} en 3 s o menos · p95 {p95*1000:.1f} ms.")
        assert rapidas >= 95


if __name__ == "__main__":
    with escenario() as folder:
        preparar_codigo_ui()
        medir(APP/"iniciar_web.bat",dict(os.environ),folder)
