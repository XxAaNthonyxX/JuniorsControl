"""Certificado HTTPS por instalación, sin modificar el almacén de confianza."""
import base64
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import msvcrt
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import time


def habilitar_cierre():
    # Un lanzador puede heredar CTRL_C_EVENT desactivado en Windows.
    if os.name == "nt":
        import ctypes
        import signal
        ctypes.WinDLL("kernel32").SetConsoleCtrlHandler(None, False)
        signal.signal(signal.SIGINT, signal.default_int_handler)


def der(tag, data):
    length = len(data)
    raw = length.to_bytes((length.bit_length() + 7) // 8 or 1, "big")
    size = bytes([length]) if length < 128 else bytes([128 + len(raw)]) + raw
    return bytes([tag]) + size + data


def integer(data):
    data = data.lstrip(b"\0") or b"\0"
    return der(2, (b"\0" if data[0] >= 128 else b"") + data)


def pem(label, data):
    return f"-----BEGIN {label}-----\n{base64.encodebytes(data).decode()}-----END {label}-----\n"


_RFC1918 = tuple(ipaddress.IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def _powershell(script, settings=None):
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env = os.environ.copy()
    if settings is not None:
        env["JUNIORS_CERT_PARAMS"] = json.dumps(settings, ensure_ascii=True)
    return subprocess.run([str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, check=True, timeout=50, env=env,
                          creationflags=subprocess.CREATE_NO_WINDOW).stdout


def _private_v4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        return None
    return str(address) if any(address in net for net in _RFC1918) else None


def enlaces_locales():
    """IPv4 RFC1918 asignadas a interfaces activas. Prioriza interfaces con puerta de enlace."""
    script = r"""
$ErrorActionPreference='Stop'
$rows = foreach ($nic in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
  if ($nic.OperationalStatus -ne 'Up' -or $nic.NetworkInterfaceType -eq 'Loopback') { continue }
  $props = $nic.GetIPProperties()
  $gateway = @($props.GatewayAddresses | Where-Object {$_.Address.AddressFamily -eq 'InterNetwork'}).Count -gt 0
  foreach ($entry in $props.UnicastAddresses) {
    if ($entry.Address.AddressFamily -eq 'InterNetwork' -and $entry.DuplicateAddressDetectionState -eq 'Preferred') {
      [pscustomobject]@{Gateway=[int]$gateway; Address=$entry.Address.ToString()}
    }
  }
}
$rows | Sort-Object Gateway -Descending | ForEach-Object {$_.Address}
"""
    try:
        lines = _powershell(script).decode("ascii").splitlines()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return []
    return list(dict.fromkeys(ip for line in lines if (ip := _private_v4(line.strip()))))


@contextmanager
def _cert_lock(target):
    with (target / "certificado.lock").open("a+b") as lock:
        until = time.monotonic() + 60
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= until:
                    raise RuntimeError("Otra ventana está preparando el certificado HTTPS. Reintenta el inicio.")
                time.sleep(0.15)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


_ISSUE = r"""
using namespace System.Security.Cryptography
using namespace System.Security.Cryptography.X509Certificates
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$cfg = $env:JUNIORS_CERT_PARAMS | ConvertFrom-Json
$now = [DateTimeOffset]::UtcNow
$hash = [HashAlgorithmName]::SHA256
$padding = [RSASignaturePadding]::Pkcs1
$scope = [DataProtectionScope]::CurrentUser
$flags = [X509KeyStorageFlags]::EphemeralKeySet -bor [X509KeyStorageFlags]::Exportable
if ([IO.File]::Exists($cfg.seed)) {
  $pfx = [ProtectedData]::Unprotect([IO.File]::ReadAllBytes($cfg.seed), $null, $scope)
  $root = [X509Certificate2]::new($pfx, [string]::Empty, $flags)
  [Array]::Clear($pfx,0,$pfx.Length)
} else {
  $issuerKey = [RSA]::Create(3072)
  $request = [CertificateRequest]::new("CN=Juniors - CA local", $issuerKey, $hash, $padding)
  $request.CertificateExtensions.Add([X509BasicConstraintsExtension]::new($true,$true,0,$true))
  $uses = [X509KeyUsageFlags]::KeyCertSign -bor [X509KeyUsageFlags]::CrlSign
  $request.CertificateExtensions.Add([X509KeyUsageExtension]::new($uses,$true))
  $request.CertificateExtensions.Add([X509SubjectKeyIdentifierExtension]::new($request.PublicKey,$false))
  $root = $request.CreateSelfSigned($now.AddDays(-2),$now.AddYears(15))
  $pfx = $root.Export([X509ContentType]::Pfx,[string]::Empty)
  $protected = [ProtectedData]::Protect($pfx, $null, $scope)
  [IO.File]::WriteAllBytes($cfg.newSeed, $protected)
  [Array]::Clear($pfx,0,$pfx.Length)
}
$leafKey = [RSA]::Create(2048)
$leafRequest = [CertificateRequest]::new("CN=Juniors local", $leafKey, $hash, $padding)
$leafRequest.CertificateExtensions.Add([X509BasicConstraintsExtension]::new($false,$false,0,$true))
$leafUses = [X509KeyUsageFlags]::DigitalSignature -bor [X509KeyUsageFlags]::KeyEncipherment
$leafRequest.CertificateExtensions.Add([X509KeyUsageExtension]::new($leafUses,$true))
$eku = [OidCollection]::new()
[void]$eku.Add([Oid]::new("1.3.6.1.5.5.7.3.1"))
$leafRequest.CertificateExtensions.Add([X509EnhancedKeyUsageExtension]::new($eku,$false))
$leafRequest.CertificateExtensions.Add([X509SubjectKeyIdentifierExtension]::new($leafRequest.PublicKey,$false))
$ski = ($root.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.14'}).SubjectKeyIdentifier
$aki = [byte[]]::new(24)
$aki[0]=0x30; $aki[1]=0x16; $aki[2]=0x80; $aki[3]=0x14
for($i=0; $i -lt 20; $i++) { $aki[$i+4]=[Convert]::ToByte($ski.Substring($i*2,2),16) }
$leafRequest.CertificateExtensions.Add([X509Extension]::new("2.5.29.35", $aki, $false))
$san = [SubjectAlternativeNameBuilder]::new()
foreach ($name in $cfg.names) { $san.AddDnsName($name) }
foreach ($ip in $cfg.addresses) { $san.AddIpAddress([Net.IPAddress]::Parse($ip)) }
$leafRequest.CertificateExtensions.Add($san.Build())
$serial = [byte[]]::new(16)
$random = [RandomNumberGenerator]::Create()
$random.GetBytes($serial)
$serial[0] = ($serial[0] -band 0x7f) -bor 1
$leaf = $leafRequest.Create($root,$now.AddDays(-1),$now.AddDays(180),$serial)
$p = $leafKey.ExportParameters($true)
$x = @{cert=[Convert]::ToBase64String($leaf.RawData); root=[Convert]::ToBase64String($root.RawData)}
foreach($n in 'Modulus','Exponent','D','P','Q','DP','DQ','InverseQ'){$x[$n]=[Convert]::ToBase64String($p.$n)}
$x | ConvertTo-Json -Compress
"""


def _server_context(folder):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(folder / "cert.pem", folder / "key.pem")
    return ctx


def certificate(folder, addresses=None):
    """Emite o reutiliza la hoja de esta instalación, con una raíz pública estable."""
    target = Path(folder).resolve() / "https"
    target.mkdir(parents=True, exist_ok=True)
    addresses = enlaces_locales() if addresses is None else addresses
    private = sorted({ip for value in addresses if (ip := _private_v4(value))}, key=ipaddress.IPv4Address)
    names = sorted({"localhost", socket.gethostname().rstrip(".").encode("idna").decode("ascii").lower()} - {""})
    identity = {"names": names, "addresses": ["127.0.0.1", *private]}
    seed = target / "raiz.dpapi"
    with _cert_lock(target):
        marker = target / "identidad.json"
        public_root = target / "Juniors-CA.cer"
        if not seed.exists() and (public_root.exists() or marker.exists() or (target / "ca.pem").exists()):
            raise RuntimeError("Falta la clave protegida de la CA. Recupera la carpeta https de esta instalación.")
        try:
            saved = json.loads(marker.read_text(encoding="ascii"))
            same_root = hashlib.sha256(public_root.read_bytes()).hexdigest() == saved["root"]
            if same_root and identity == saved["identity"] and time.time() < saved["renew"]:
                if (target / "ca.pem").read_text("ascii") == pem("CERTIFICATE", public_root.read_bytes()):
                    return _server_context(target), (target / "pin.txt").read_text("ascii")
        except (KeyError, TypeError, ValueError, OSError):
            pass
        with tempfile.TemporaryDirectory(dir=target) as tmp:
            stage = Path(tmp)
            new_seed = stage / "raiz.dpapi"
            try:
                output = _powershell(_ISSUE, dict(identity, seed=str(seed), newSeed=str(new_seed)))
            except (OSError, subprocess.SubprocessError) as exc:
                detail = ("Usa el perfil de Windows que creó la CA; su clave está protegida por Windows."
                          if seed.exists() else "Comprueba que Windows PowerShell y el perfil de usuario estén disponibles.")
                raise RuntimeError("No se pudo emitir el certificado HTTPS. " + detail) from exc
            parts = {key: base64.b64decode(value, validate=True) for key, value in json.loads(output).items()}
            if public_root.exists() and public_root.read_bytes() != parts["root"]:
                raise RuntimeError("La CA pública no coincide con su clave. Recupera la carpeta https original.")
            key = der(48, integer(b"\0") + b"".join(integer(parts[n]) for n in
                      ("Modulus", "Exponent", "D", "P", "Q", "DP", "DQ", "InverseQ")))
            public = der(48, integer(parts["Modulus"]) + integer(parts["Exponent"]))
            spki = der(48, bytes.fromhex("300d06092a864886f70d0101010500") + der(3, b"\0" + public))
            pin = base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")
            ca = pem("CERTIFICATE", parts["root"])
            (stage / "Juniors-CA.cer").write_bytes(parts["root"])
            (stage / "ca.pem").write_text(ca, encoding="ascii")
            (stage / "cert.pem").write_text(pem("CERTIFICATE", parts["cert"]) + ca, encoding="ascii")
            (stage / "key.pem").write_text(pem("RSA PRIVATE KEY", key), encoding="ascii")
            (stage / "pin.txt").write_text(pin, encoding="ascii")
            metadata = dict(identity=identity, root=hashlib.sha256(parts["root"]).hexdigest(),
                            renew=int(time.time()) + 150 * 86400)
            (stage / marker.name).write_text(json.dumps(metadata), encoding="ascii")
            ctx = _server_context(stage)
            if new_seed.exists():
                os.replace(new_seed, seed)
            for name in ("Juniors-CA.cer", "ca.pem", "cert.pem", "key.pem", "pin.txt", marker.name):
                os.replace(stage / name, target / name)
            return ctx, pin


def browser(url, pin, folder):
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for path in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for root in filter(None, roots):
            exe = Path(root) / path
            if exe.is_file():
                subprocess.Popen([str(exe), "--new-tab", "--no-first-run", "--disable-sync",
                                  "--user-data-dir=" + str(folder / "navegador"),
                                  "--ignore-certificate-errors-spki-list=" + pin,url],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    import webbrowser
    print("Para abrir la aplicación con su certificado local se recomienda Microsoft Edge o Google Chrome.")
    webbrowser.open(url)
