"""Aplicación local de Junior's. Ejecutar con iniciar.bat."""
import argparse
from contextlib import closing
import hashlib
from ipaddress import IPv4Address, IPv4Network
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import pyodbc
import sqlserver
import respaldo_sqlserver
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from urllib.parse import parse_qs, urlsplit

import acceso
import gestion
import inventario
import respaldo
import red
import seguridad_local
from ubicacion import carpeta_datos

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = carpeta_datos()
DATABASE = sqlserver.database()
APP_ID = "juniors-sqlserver-" + hashlib.sha256(
    json.dumps([sqlserver.instance().casefold(),DATABASE.casefold()]).encode()
).hexdigest()[:20]
PRIVATE_NETS = tuple(IPv4Network(net) for net in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"))


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    # Varios navegadores pueden abrir sus recursos en paralelo al comenzar el turno.
    request_queue_size = 64

    def verify_request(self, request, client_address):
        source = IPv4Address(client_address[0])
        return (request.getsockname()[0] in self.accepted_ips and
                (source.is_loopback or any(source in network for network in PRIVATE_NETS)))

    def finish_request(self, request, client_address):
        # El handshake se hace en el hilo del cliente. Una tableta dormida no bloquea la caja.
        request.settimeout(10)
        try:
            with self.tls.wrap_socket(request,server_side=True) as secure:
                secure.settimeout(30)
                self.RequestHandlerClass(secure,client_address,self)
        except (ssl.SSLError, ConnectionError, TimeoutError):
            pass

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def connect():
    return sqlserver.connect()


def prepare():
    DATA.mkdir(exist_ok=True, parents=True)
    with closing(connect()) as db, db:
        sqlserver.preparar(db)
        if db.execute("SELECT TOP (1) 1 FROM users").fetchone():
            gestion.tick(db)


def backup():
    with closing(sqlserver.raw(autocommit=True)) as db:
        return respaldo_sqlserver.copia_diaria(db, DATA / "respaldos", inventario.today())


def maintain(stop):
    while not stop.is_set():
        try:
            with closing(connect()) as db, db:
                db.lock(write=True)
                installed = db.execute("SELECT TOP (1) 1 FROM users").fetchone()
                if installed:
                    gestion.tick(db)
            if installed:
                backup()
        except Exception:
            traceback.print_exc()
        stop.wait(30)


def snapshot(db, user):
    day = inventario.business_day(db)
    result = dict(user=user, today=day, calendar_today=inventario.today(), **acceso.state(db,user))
    if user:
        result.update(inventario.state(db,user,day))
        result.update(gestion.state(db,user))
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "Juniors"

    def log_message(self, *args):
        pass

    def send_content(self, code, body, content_type, token=None):
        self.send_response(code)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if token is not None:
            age = acceso.SESSION_LIFETIME if token else 0
            self.send_header("Set-Cookie",f"__Host-juniors={token}; Path=/; Max-Age={age}; Secure; HttpOnly; SameSite=Strict")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, ssl.SSLError):
            pass

    def reply(self, obj, code=200, token=None):
        self.send_content(code,json.dumps(obj,ensure_ascii=False).encode(),"application/json; charset=utf-8",token)

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie",""))
        except CookieError:
            return ""
        return cookie["__Host-juniors"].value if "__Host-juniors" in cookie else ""

    def valid_host(self):
        return self.headers.get("Host","").lower() in self.server.allowed_hosts

    def from_primary(self):
        return IPv4Address(self.client_address[0]).is_loopback

    def do_GET(self):
        if not self.valid_host():
            return self.reply({"error":"Dirección local no válida."},403)
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self.reply({"app":APP_ID})
        if path in {"/Juniors-CA.cer","/api/qr"}:
            with closing(connect()) as db:
                user = acceso.current_user(db,self.token())
                if not user or user["role"] != "admin":
                    return self.reply({"error":"Acceso reservado a administración."},403)
            if path == "/Juniors-CA.cer":
                return self.send_content(200,self.server.ca_der,"application/x-x509-ca-cert")
            ip = parse_qs(urlsplit(self.path).query).get("ip",[""])[0]
            if ip not in self.server.lan_addresses:
                return self.reply({"error":"Elige una dirección de este local."},400)
            return self.send_content(200,red.qr_png(f"https://{ip}:{self.server.server_port}"),"image/png")
        if path == "/api/state":
            try:
                with closing(connect()) as db:
                    db.lock(write=False)
                    state = snapshot(db,acceso.current_user(db,self.token()))
                    if state["user"] and state["user"]["role"] == "admin":
                        state["network"] = self.server.network_info
                    if state["setup"] and not self.from_primary():
                        state.update(setup=False,awaiting_setup=True)
                return self.reply(state)
            except Exception:
                traceback.print_exc()
                return self.reply({"error":"No se pudo consultar la base de datos."},500)
        name = "index.html" if path == "/" else path.removeprefix("/")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.(?:html|css|js|jpg|ico|woff2)",name) or not (WEB / name).is_file():
            return self.reply({"error":"Recurso no encontrado."},404)
        return self.send_content(200,(WEB / name).read_bytes(),mimetypes.guess_type(name)[0] or "application/octet-stream")

    def do_POST(self):
        if self.path != "/api/action":
            return self.reply({"error":"Ruta desconocida."},404)
        if not self.valid_host() or self.headers.get("Origin") != "https://" + self.headers.get("Host",""):
            return self.reply({"error":"Solicitud ajena a esta aplicación."},403)
        token = None
        try:
            length = int(self.headers.get("Content-Length",0))
            if not 0 < length <= 256_000 or self.headers.get_content_type() != "application/json":
                raise ValueError("Envía datos válidos en formato JSON.")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request,dict):
                raise ValueError("Solicitud inválida.")
            action, p = request.get("action"), request.get("payload")
            if not isinstance(action,str) or not isinstance(p,dict):
                raise ValueError("Operación inválida.")
            if action in {"bootstrap", "bootstrap_code"} and not self.from_primary():
                raise PermissionError("Crea la primera cuenta desde iniciar.bat en la computadora principal.")
            send_mail = send_recovery = None
            with closing(connect()) as db, db:
                db.lock(write=True)
                session = self.token()
                user = acceso.current_user(db,session)
                if not user and action not in {"bootstrap","bootstrap_code","login","register","reset_request","reset_password"}:
                    return self.reply({"error":"Inicia sesión para continuar."},401)
                if action in acceso.ACTIONS:
                    links = self.server.network_info["urls"]
                    origin = links[0] if links else "https://" + self.headers["Host"]
                    try:
                        result = acceso.act(db,user,action,{**p,"_token":session,"_activation_url":origin+"/#activar"})
                    except acceso.InvalidCode as exc:
                        # Confirmar el contador de intentos también cuando se rechaza el código.
                        result = {"error": str(exc)}
                    if action == "bootstrap" and "error" not in result:
                        inventario.init(db,demo=p.get("demo",True) is True)
                        gestion.tick(db)
                    token = result.pop("_token",None)
                    send_mail = result.pop("_send_invite",None)
                    send_recovery = result.pop("_send_recovery",None)
                else:
                    key = request.get("request_id")
                    if not isinstance(key,str) or not re.fullmatch("[a-zA-Z0-9-]{16,80}",key):
                        raise ValueError("Falta el identificador de la operación.")
                    fingerprint = hashlib.sha256(json.dumps([action,p],sort_keys=True).encode()).hexdigest()
                    cached = db.execute("SELECT huella,resultado FROM operaciones WHERE usuario=? AND clave=?",
                                        (user["id"],key)).fetchone()
                    if cached:
                        if cached["huella"] != fingerprint:
                            raise ValueError("Este identificador ya corresponde a otra operación.")
                        result = json.loads(cached["resultado"])
                    elif action == "inv.history":
                        result = inventario.act(db,user,action,p)
                    else:
                        # Se comprueban vencimientos antes de usar existencias, incluso tras suspensión del PC.
                        gestion.tick(db)
                        module = gestion if action.startswith("gestion.") else inventario
                        result = module.act(db,user,action,p)
                        gestion.tick(db)
                        db.execute("INSERT INTO operaciones VALUES(?,?,?,?)",
                                   (user["id"],key,fingerprint,json.dumps(result)))
            if send_mail:
                send_mail()
            if send_recovery:
                threading.Thread(target=send_recovery, daemon=True).start()
            self.reply(result,code=400 if "error" in result else 200,token=token)
        except PermissionError as exc:
            self.reply({"error":str(exc)},403)
        except (ValueError, UnicodeError) as exc:
            self.reply({"error":str(exc)},400)
        except pyodbc.IntegrityError:
            self.reply({"error":"Los datos entran en conflicto con otro registro. Actualiza la pantalla."},409)
        except pyodbc.OperationalError as exc:
            print("SQL Server:",exc)
            self.reply({"error":"La base de datos no está disponible. Reintenta la operación."},503)
        except Exception:
            traceback.print_exc()
            self.reply({"error":"Ocurrió un error interno. Revisa la ventana de inicio."},500)


def abrir_vista(vista,url,pin):
    if vista == "web":
        seguridad_local.browser(url,pin,DATA)
        return
    executable = ROOT / "escritorio" / "Juniors.exe"
    if not executable.is_file():
        raise SystemExit("Usa la descarga de escritorio para abrir la ventana Windows, o abre iniciar_web.bat.")
    subprocess.Popen([str(executable),"--url",url,"--data-dir",str(DATA / "navegador-escritorio"),
                      "--cert",str(DATA / "https" / "cert.pem")],cwd=executable.parent)


def instancia_disponible(url):
    # La otra edición puede estar creando los certificados y la base por primera vez.
    limite = time.monotonic() + 20
    while time.monotonic() < limite:
        try:
            ctx = ssl.create_default_context(cafile=str(DATA / "https" / "ca.pem"))
            with urllib.request.urlopen(url + "/api/health",context=ctx,timeout=2) as response:
                return json.load(response).get("app") == APP_ID
        except (OSError, ValueError):
            time.sleep(0.3)
    return False


def main():
    seguridad_local.habilitar_cierre()
    parser = argparse.ArgumentParser(description="Junior’s • Atención e inventario")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--no-browser",action="store_true")
    parser.add_argument("--local",action="store_true",help="Permitir acceso sólo desde la computadora principal")
    parser.add_argument("--vista",choices=("web","escritorio"),help="Abrir en el navegador o en la ventana de Windows")
    args = parser.parse_args()
    edition = ROOT / "edicion.txt"
    vista = args.vista or (edition.read_text(encoding="utf-8-sig").strip() if edition.exists() else "web")
    DATA.mkdir(parents=True,exist_ok=True)
    addresses = [] if args.local else seguridad_local.enlaces_locales()
    launch = not args.no_browser and not os.environ.get("JUNIORS_NO_BROWSER")
    try:
        server = LocalServer(("0.0.0.0" if addresses else "127.0.0.1",args.port),Handler)
    except OSError:
        url = f"https://127.0.0.1:{args.port}"
        if not instancia_disponible(url):
            raise SystemExit(f"El puerto {args.port} está ocupado. Cierra el otro servicio o usa iniciar.bat --port 8766.")
        if launch:
            abrir_vista(vista,url,(DATA / "https" / "pin.txt").read_text(encoding="ascii"))
        return
    with server, respaldo.uso_exclusivo(DATA):
        ctx,pin = seguridad_local.certificate(DATA,addresses)
        prepare()
        server.tls = ctx
        server.lan_addresses = addresses
        server.accepted_ips = {"127.0.0.1",*addresses}
        server.allowed_hosts = {f"{host}:{server.server_port}" for host in (*server.accepted_ips,"localhost")}
        server.ca_der = (DATA / "https" / "Juniors-CA.cer").read_bytes()
        server.network_info = {
            "urls":[f"https://{ip}:{server.server_port}" for ip in addresses],
            "fingerprint":hashlib.sha256(server.ca_der).hexdigest().upper(),
            "cert_url":"/Juniors-CA.cer","local_only":not bool(addresses)
        }
        url = f"https://127.0.0.1:{server.server_port}"
        print(f"Junior's disponible en {url}\nBase de datos: {DATABASE}\nMantén abierta esta consola durante el turno. Para apagar el servidor, pulsa Ctrl+C.",flush=True)
        stop = threading.Event()
        worker = threading.Thread(target=maintain,args=(stop,),daemon=True)
        worker.start()
        try:
            if launch:
                abrir_vista(vista,url,pin)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            worker.join(timeout=5)


if __name__ == "__main__":
    main()
