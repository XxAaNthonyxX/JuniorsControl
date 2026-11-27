"""Cuentas, sesiones individuales e invitaciones de personal por Gmail."""
import logging
import ctypes
from ctypes import wintypes
from datetime import datetime
from email.message import EmailMessage
import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
import threading
import time

from inventario import responsible_area


ROLES = {"admin", "atencion", "caja", "area", "recepcion"}
ACTIONS = {"bootstrap_code", "bootstrap", "register", "login", "logout", "invite", "smtp_save", "user_update", "user_delete", "reset_request", "reset_password"}
PUBLIC_FIELDS = "id,name,email,username,role,area"
SESSION_LIFETIME = 12 * 60 * 60
INVITE_LIFETIME = 24 * 60 * 60
ROUNDS = 600_000
_login_failures = {}
_failure_lock = threading.Lock()


def state(db, user):
    result = {"setup": not bool(db.execute("SELECT TOP (1) 1 FROM users").fetchone())}
    if not user or user["role"] != "admin":
        return result
    smtp = db.execute("SELECT email FROM auth_smtp WHERE id=1").fetchone()
    result["smtp"] = {"email": smtp[0] if smtp else "", "configured": bool(smtp)}
    result["users"] = [dict(row, code=f"US{row['id']:04d}") for row in db.execute(
        f"SELECT {PUBLIC_FIELDS},active FROM users WHERE deleted=0 ORDER BY name,id"
    )]
    result["invitations"] = []
    for row in db.execute("SELECT email,role,area,expires_at FROM auth_invites "
                          "WHERE expires_at>? ORDER BY expires_at DESC", (int(time.time()),)):
        invite = dict(row)
        invite["expires"] = datetime.fromtimestamp(invite["expires_at"]).strftime("%d/%m/%Y %H:%M")
        result["invitations"].append(invite)
    return result


def _get_text(payload, key, maximum, error):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(error)
    return value.strip()


def _email(payload):
    value = _get_text(payload, "email", 254, "Escribe una dirección de correo válida.").casefold()
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
        raise ValueError("Escribe una dirección de correo válida.")
    return value


def _role_area(payload):
    role = payload.get("role")
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError("Selecciona un rol válido.")
    area = payload.get("area", "")
    if not isinstance(area, str) or len(area.strip()) > 80:
        raise ValueError("El área debe tener un máximo de 80 caracteres.")
    area = area.strip()
    if role == "area":
        area = responsible_area(area)
        if not area:
            raise ValueError("Selecciona el área a la que pertenece esta cuenta.")
    elif area.casefold() == "horno":
        area = "Brasas"
    return role, area


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).digest()


def _password_digest(password, salt, rounds):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)


def _session(db, user_id):
    now = int(time.time())
    db.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO auth_sessions(digest,user_id,expires_at) VALUES(?,?,?)",
               (_digest(token), user_id, now + SESSION_LIFETIME))
    return {"_token": token}


def current_user(db, token):
    if not isinstance(token, str) or not 1 <= len(token) <= 128:
        return None
    row = db.execute(
        f"SELECT {PUBLIC_FIELDS} FROM users WHERE active=1 AND id=("
        "SELECT user_id FROM auth_sessions WHERE digest=? AND expires_at>?)",
        (_digest(token), int(time.time()))
    ).fetchone()
    return dict(row, code=f"US{row['id']:04d}") if row else None


def _credentials(payload):
    password = payload.get("password")
    if not isinstance(password, str) or not 10 <= len(password) <= 128 or not password.strip():
        raise ValueError("Usa una contraseña de entre 10 y 128 caracteres.")
    salt = secrets.token_bytes(16)
    return salt, _password_digest(password, salt, ROUNDS), ROUNDS


def _create_user(db, payload, email, role, area):
    name = _get_text(payload, "name", 100, "Escribe tu nombre (hasta 100 caracteres).")
    db.execute("INSERT INTO users(name,email,role,area,salt,digest,rounds) VALUES(?,?,?,?,?,?,?)",
               (name, email, role, area, *_credentials(payload)))
    return {"message": "Cuenta verificada. Inicia sesión con tu correo y contraseña."}


def _login(db, payload):
    email = _email({"email": payload.get("email", payload.get("identifier"))})
    row = db.execute("SELECT id,salt,digest,rounds,active FROM users WHERE deleted=0 AND email=?", (email,)).fetchone()
    key = row["id"] if row else email
    now = time.monotonic()
    with _failure_lock:
        expired = [entry for entry, (_, until) in _login_failures.items() if until <= now]
        for entry in expired:
            del _login_failures[entry]
        attempts, until = _login_failures.get(key, (0, now + 300))
    if attempts >= 8:
        raise ValueError("Se alcanzó el límite de intentos. Vuelve a probar en cinco minutos.")
    password = payload.get("password")
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        raise ValueError("Revisa el correo y la contraseña.")
    check = _password_digest(password, row["salt"] if row else bytes(16), row["rounds"] if row else ROUNDS)
    if not row or not hmac.compare_digest(row["digest"], check) or not row["active"]:
        with _failure_lock:
            _login_failures[key] = (attempts + 1, until)
        raise ValueError("Revisa el correo y la contraseña, o consulta si tu cuenta está activa.")
    with _failure_lock:
        _login_failures.pop(key, None)
    return _session(db, row["id"])


class _Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _windows_secret(raw, *, protect):
    """DPAPI vincula el secreto al perfil de Windows que ejecuta la aplicación."""
    source_bytes = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = _Blob(len(raw), source_bytes)
    result = _Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptProtectData if protect else library.CryptUnprotectData
    ref = ctypes.byref
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    if not function(ref(source), None, None, None, None, 1, ref(result)):
        raise ValueError("Windows no pudo acceder a la clave de Gmail. Configura el remitente de nuevo.")
    local_free = ctypes.WinDLL("kernel32").LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        local_free(result.data)


def _smtp_save(db, payload):
    email = _email(payload)
    password = payload.get("password", "")
    if not isinstance(password, str):
        raise ValueError("Introduce la contraseña de aplicación de Google.")
    password = "".join(password.split())
    if not password:
        existing = db.execute("SELECT email FROM auth_smtp WHERE id=1").fetchone()
        if existing and existing[0] == email:
            return {"message": "Configuración de Gmail guardada."}
    if not re.fullmatch(r"[A-Za-z0-9]{16}", password):
        raise ValueError("Introduce la contraseña de aplicación de Google de 16 caracteres.")
    encrypted = _windows_secret(password.encode("ascii"), protect=True)
    if not db.execute("UPDATE auth_smtp SET email=?,protected=? WHERE id=1",(email,encrypted)).rowcount:
        db.execute("INSERT INTO auth_smtp(id,email,protected) VALUES(1,?,?)",(email,encrypted))
    return {"message": "Configuración de Gmail guardada."}


def _send_code(sender, protected, recipient, code, *, recovery=False, activation_url=None):
    password = _windows_secret(protected, protect=False).decode("ascii")
    message = EmailMessage()
    message["Subject"] = "Recuperar contraseña de JuniorsControl" if recovery else "Tu código de verificación de JuniorsControl"
    message["From"] = sender
    message["To"] = recipient
    if recovery:
        body = f"Tu código para cambiar la contraseña es {code}. Vence en 15 minutos. Si no lo solicitaste, puedes ignorar este correo."
    else:
        body = f"Tu código de registro es {code}. Es válido durante 24 horas."
        if activation_url:
            body += f"\n\nConéctate a la red indicada por Administración y abre este enlace para activar tu cuenta:\n{activation_url}"
        else:
            body += "\n\nIntroduce el código en la pantalla de creación de tu cuenta."
    message.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=12, context=ssl.create_default_context()) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise ValueError("Gmail rechazó las credenciales. Revisa la dirección y la contraseña de aplicación, "
                         "guarda los cambios y reenvía la invitación.") from None
    except (smtplib.SMTPException, OSError):
        raise ValueError("Gmail no confirmó el envío. Revisa la conexión, el remitente y el destinatario, "
                         "y vuelve a enviar la invitación.") from None


class InvalidCode(ValueError):
    """El servidor confirma el intento fallido antes de contestar al cliente."""


def _new_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def _code_digest(code, salt=None):
    salt = secrets.token_bytes(12) if salt is None else salt
    return salt + hashlib.pbkdf2_hmac("sha256", code.encode("ascii"), salt, 100_000, dklen=20)


def _valid_code(record, payload):
    code = payload.get("code")
    return (record and record["attempts"] < 5 and isinstance(code, str)
            and re.fullmatch(r"[0-9]{6}", code)
            and hmac.compare_digest(record["digest"], _code_digest(code, record["digest"][:12])))


def _reset_request(db, payload):
    email = _email(payload)
    result = {"message": "Si el correo tiene una cuenta activa, recibirás un código válido durante 15 minutos."}
    now = int(time.time())
    account = db.execute("SELECT id FROM users WHERE email=? AND active=1 AND deleted=0", (email,)).fetchone()
    smtp = db.execute("SELECT email,protected FROM auth_smtp WHERE id=1").fetchone()
    if not account or not smtp:
        return result
    uid = account["id"]
    if db.execute("SELECT 1 FROM auth_password_resets WHERE user_id=? AND expires_at>?", (uid,now+840)).fetchone():
        return result
    code = _new_code()
    db.execute("DELETE FROM auth_password_resets WHERE user_id=? OR expires_at<=?", (uid,now))
    db.execute("INSERT INTO auth_password_resets(user_id,digest,expires_at) VALUES(?,?,?)", (uid,_code_digest(code),now+900))

    def deliver():
        try:
            _send_code(smtp["email"], smtp["protected"], email, code, recovery=True)
        except ValueError as exc:
            logging.warning("Correo de recuperación: %s", exc)
    result["_send_recovery"] = deliver
    return result


def _reset_password(db, payload):
    email = _email(payload)
    record = db.execute("SELECT r.user_id,r.digest,r.attempts FROM auth_password_resets r "
                        "JOIN users u ON r.user_id=u.id WHERE u.email=? AND u.active=1 AND u.deleted=0 AND r.expires_at>?",
                        (email,int(time.time()))).fetchone()
    if not _valid_code(record, payload):
        if record and record["attempts"] < 5:
            db.execute("UPDATE auth_password_resets SET attempts=attempts+1 WHERE user_id=?", (record["user_id"],))
        raise InvalidCode("Código incorrecto o vencido. Revisa el último correo o solicita otro código.")
    uid = record["user_id"]
    db.execute("UPDATE users SET salt=?,digest=?,rounds=? WHERE id=?", (*_credentials(payload),uid))
    db.execute("DELETE FROM auth_password_resets WHERE user_id=?", (uid,))
    db.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))
    with _failure_lock:
        _login_failures.pop(uid, None)
    return {"message": "Contraseña actualizada. Inicia sesión con tu nueva contraseña."}


def _invite(db, payload):
    email = _email(payload)
    role, area = _role_area(payload)
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise ValueError("Ya existe una cuenta con este correo.")
    smtp = db.execute("SELECT email,protected FROM auth_smtp WHERE id=1").fetchone()
    if not smtp:
        raise ValueError("Configura primero el remitente de Gmail.")
    code = _new_code()
    db.execute("DELETE FROM auth_invites WHERE email=?", (email,))
    db.execute("INSERT INTO auth_invites(email,role,area,digest,expires_at) VALUES(?,?,?,?,?)",
               (email,role,area,_code_digest(code),int(time.time())+INVITE_LIFETIME))
    return {"message": "Invitación enviada. El código es válido durante 24 horas.",
            "_send_invite": lambda: _send_code(smtp["email"], smtp["protected"], email, code, activation_url=payload.get("_activation_url"))}


def _register(db, payload, *, first_admin=False):
    email = _email(payload)
    invitation = db.execute("SELECT role,area,digest,attempts FROM auth_invites WHERE email=? AND expires_at>?",
                            (email, int(time.time()))).fetchone()
    if not _valid_code(invitation, payload) or (first_admin and invitation["role"] != "admin"):
        if invitation and invitation["attempts"] < 5:
            db.execute("UPDATE auth_invites SET attempts=attempts+1 WHERE email=?", (email,))
        raise InvalidCode("Código incorrecto o vencido. Revisa la última invitación o pide un código nuevo.")
    result = _create_user(db, payload, email, invitation["role"], invitation["area"])
    db.execute("DELETE FROM auth_invites WHERE email=?", (email,))
    return result


def _target_user(db, payload):
    try:
        user_id = int(payload.get("id"))
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Selecciona una cuenta válida.") from None
    if not 1 <= user_id <= 2**63 - 1:
        raise ValueError("Selecciona una cuenta válida.")
    target = db.execute("SELECT id,email FROM users WHERE id=? AND deleted=0", (user_id,)).fetchone()
    if not target:
        raise ValueError("Esa cuenta ya no existe.")
    return target


def _delete_user(db, user, payload):
    target = _target_user(db, payload)
    user_id = target["id"]
    if user_id == user["id"]:
        raise ValueError("Otra persona administradora debe eliminar tu cuenta.")
    db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM auth_password_resets WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM auth_invites WHERE email=?", (target["email"],))
    # Se conserva el ID histórico al que se refieren las compras y los movimientos.
    db.execute("UPDATE users SET active=0,deleted=1,username=NULL,email=?,salt=0x,digest=0x WHERE id=?",
               (f"eliminado:{user_id}", user_id))
    return {"message": "Cuenta eliminada."}


def _update_user(db, user, payload):
    user_id = _target_user(db, payload)["id"]
    role, area = _role_area(payload)
    active = payload.get("active")
    if active not in (True, False, "0", "1"):
        raise ValueError("Selecciona el estado de la cuenta.")
    active = int(active)
    if user_id == user["id"] and (not active or role != "admin"):
        raise ValueError("Otra persona administradora debe cambiar los permisos de tu propia cuenta.")
    db.execute("UPDATE users SET role=?,area=?,active=? WHERE id=?", (role, area, active, user_id))
    if not active:
        db.execute("DELETE FROM auth_password_resets WHERE user_id=?", (user_id,))
    if user_id != user["id"]:
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    return {"message": "Cuenta actualizada."}


def act(db, user, action, payload):
    if action in {"bootstrap_code", "bootstrap"}:
        if db.execute("SELECT TOP (1) 1 FROM users").fetchone():
            raise PermissionError("Ya existe una cuenta administradora.")
        if action == "bootstrap_code":
            email = _email(payload)
            _smtp_save(db, {"email": payload.get("smtp_email") or email, "password": payload.get("smtp_password")})
            db.execute("DELETE FROM auth_invites")
            return _invite(db, {"email": email, "role": "admin"})
        return _register(db, payload, first_admin=True)
    if action == "register":
        if not db.execute("SELECT TOP (1) 1 FROM users").fetchone():
            raise PermissionError("Crea la primera cuenta desde la computadora principal.")
        return _register(db, payload)
    if action == "reset_request":
        return _reset_request(db, payload)
    if action == "reset_password":
        return _reset_password(db, payload)
    if action == "login":
        return _login(db, payload)
    if action == "logout":
        token = payload.get("_token", "")
        db.execute("DELETE FROM auth_sessions WHERE digest=?", (_digest(token),))
        return {"_token": ""}
    if not user or user["role"] != "admin":
        raise PermissionError("Necesitas el rol de administración para realizar esta operación.")
    if action == "smtp_save":
        return _smtp_save(db, payload)
    if action == "invite":
        return _invite(db, payload)
    if action == "user_update":
        return _update_user(db, user, payload)
    if action == "user_delete":
        return _delete_user(db, user, payload)
    raise ValueError("Acción de acceso desconocida.")
