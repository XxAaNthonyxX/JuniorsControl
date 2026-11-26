using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("Juniors")]
[assembly: AssemblyDescription("Atención e inventario · Pollos y Parrillas Juniors")]
[assembly: AssemblyProduct("Juniors")]
[assembly: AssemblyVersion("1.0.0.0")]

namespace Juniors.Escritorio
{
    internal static class Programa
    {
        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            try
            {
                if (args.Length == 0)
                {
                    IniciarDesdeCarpeta();
                    return 0;
                }
                Opciones opciones = args.Length == 1 && args[0] == "--conectar"
                    ? Conexion.PedirServidor() : Opciones.Leer(args);
                if (opciones != null) Application.Run(new Ventana(opciones));
                return 0;
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "Inicio de Juniors", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }

        private static void IniciarDesdeCarpeta()
        {
            string carpeta = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
            string archivo = Path.Combine(carpeta, "iniciar_escritorio.bat");
            if (!File.Exists(archivo))
                throw new FileNotFoundException("Extrae la carpeta completa. Falta iniciar_escritorio.bat junto a los archivos del servidor.");
            Process.Start(new ProcessStartInfo(archivo) { WorkingDirectory = carpeta, UseShellExecute = true });
        }
    }

    internal sealed class Opciones
    {
        public Uri Inicio;
        public string Perfil;
        public byte[] Hoja;

        public static Opciones Leer(string[] args)
        {
            string url = null, perfil = null, cert = null;
            if (args.Length != 6)
                throw new ArgumentException("Abre iniciar_escritorio.bat para conectar la ventana al servidor.");
            for (int i = 0; i < args.Length; i += 2)
            {
                switch (args[i])
                {
                    case "--url": url = args[i + 1]; break;
                    case "--data-dir": perfil = args[i + 1]; break;
                    case "--cert": cert = args[i + 1]; break;
                    default: throw new ArgumentException("Parámetro de inicio desconocido.");
                }
            }
            Uri inicio;
            if (!Uri.TryCreate(url, UriKind.Absolute, out inicio) || inicio.Scheme != "https"
                || (inicio.Host != "127.0.0.1" && inicio.Host != "localhost")
                || inicio.UserInfo.Length != 0 || inicio.AbsolutePath != "/" || inicio.Query.Length != 0
                || inicio.Fragment.Length != 0 || inicio.Port < 1)
                throw new ArgumentException("El escritorio necesita la dirección HTTPS del servidor local.");
            if (String.IsNullOrWhiteSpace(perfil) || String.IsNullOrWhiteSpace(cert))
                throw new ArgumentException("Indica el perfil y el certificado de esta instalación.");
            string rutaPerfil = Path.GetFullPath(perfil);
            Directory.CreateDirectory(rutaPerfil);
            byte[] datos = File.ReadAllBytes(Path.GetFullPath(cert));
            if (datos.Length > 0 && datos[0] == '-')
                datos = DecodificarPem(Encoding.ASCII.GetString(datos));
            using (var x509 = new X509Certificate2(datos))
            {
                if (DateTime.Now < x509.NotBefore || DateTime.Now > x509.NotAfter)
                    throw new InvalidDataException("El certificado del servidor está fuera de su período de validez.");
                return new Opciones { Inicio = inicio, Perfil = rutaPerfil, Hoja = x509.RawData };
            }
        }

        public static byte[] DecodificarPem(string pem)
        {
            const string inicio = "-----BEGIN CERTIFICATE-----";
            const string fin = "-----END CERTIFICATE-----";
            int primero = pem.IndexOf(inicio, StringComparison.Ordinal);
            int ultimo = pem.IndexOf(fin, StringComparison.Ordinal);
            if (primero < 0 || ultimo < primero + inicio.Length)
                throw new InvalidDataException("El archivo de certificado está incompleto.");
            return Convert.FromBase64String(pem.Substring(primero + inicio.Length, ultimo - primero - inicio.Length));
        }

        public bool MismaHoja(byte[] otra)
        {
            if (otra == null || Hoja.Length != otra.Length)
                return false;
            for (int i = 0; i < Hoja.Length; i++)
                if (Hoja[i] != otra[i]) return false;
            return true;
        }

        public bool MismoOrigen(Uri destino)
        {
            return destino != null && destino.IsAbsoluteUri && destino.Scheme == Inicio.Scheme
                && destino.IdnHost == Inicio.IdnHost && destino.Port == Inicio.Port && destino.UserInfo.Length == 0;
        }

        public void ComprobarServidor()
        {
            if (Hoja != null)
            {
                string carpeta = AppDomain.CurrentDomain.BaseDirectory;
                string python = Path.GetFullPath(Path.Combine(carpeta, "..", "runtime", "python.exe"));
                string parametros = "-B verificar_certificado.py " + Inicio.DnsSafeHost + " " + Inicio.Port
                    + " " + Convert.ToBase64String(Hoja);
                var info = new ProcessStartInfo(python, parametros) { WorkingDirectory = carpeta,
                    UseShellExecute = false, CreateNoWindow = true };
                using (var prueba = Process.Start(info))
                {
                    if (!prueba.WaitForExit(10000))
                    {
                        prueba.Kill();
                        throw new IOException("El servidor de Juniors no respondió a tiempo.");
                    }
                    if (prueba.ExitCode != 0)
                        throw new AuthenticationException("No se pudo verificar el certificado local.");
                }
                return;
            }
            // En el segundo equipo, WebView2 aplica la confianza normal de Windows.
            using (var tcp = new TcpClient())
            {
                var conexion = tcp.BeginConnect(Inicio.DnsSafeHost, Inicio.Port, null, null);
                using (var espera = conexion.AsyncWaitHandle)
                    if (!espera.WaitOne(TimeSpan.FromSeconds(6)))
                        throw new IOException("El servidor de Juniors no responde. Vuelve a abrir iniciar_escritorio.bat.");
                tcp.EndConnect(conexion);
            }
        }
    }

    internal sealed class Ventana : Form
    {
        private readonly Opciones opciones;
        private readonly WebView2 vista = new WebView2();
        private readonly Label aviso = new Label();
        private bool certificadoRechazado;

        public Ventana(Opciones opciones)
        {
            this.opciones = opciones;
            Text = "Juniors · Atención e inventario";
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1280, 840);
            MinimumSize = new Size(560, 440);
            WindowState = FormWindowState.Maximized;
            AutoScaleMode = AutoScaleMode.Dpi;
            BackColor = Color.FromArgb(246, 245, 239);
            vista.Dock = DockStyle.Fill;
            vista.DefaultBackgroundColor = BackColor;
            aviso.Dock = DockStyle.Fill;
            aviso.TextAlign = ContentAlignment.MiddleCenter;
            aviso.Font = new Font("Segoe UI", 12F);
            aviso.Padding = new Padding(28);
            aviso.Text = "Conectando con Juniors…";
            var contenido = new Panel { Dock = DockStyle.Fill };
            contenido.Controls.Add(vista);
            contenido.Controls.Add(aviso);
            Controls.Add(contenido);
            aviso.BringToFront();
            var menu = new MenuStrip();
            var archivo = new ToolStripMenuItem("&Archivo");
            archivo.DropDownItems.Add("Cerrar ventana", null, (s, e) => Close());
            var ver = new ToolStripMenuItem("&Ver");
            ver.DropDownItems.Add("Aumentar zoom", null, (s, e) => vista.ZoomFactor = Math.Min(2.5, vista.ZoomFactor + 0.1));
            ver.DropDownItems.Add("Reducir zoom", null, (s, e) => vista.ZoomFactor = Math.Max(0.5, vista.ZoomFactor - 0.1));
            ver.DropDownItems.Add("Restablecer zoom", null, (s, e) => vista.ZoomFactor = 1);
            var ayuda = new ToolStripMenuItem("A&yuda");
            ayuda.DropDownItems.Add("Guía de inicio", null, (s, e) => AbrirGuia("LEEME.txt"));
            ayuda.DropDownItems.Add("Conexión al local", null, (s, e) => AbrirGuia("CONEXION.txt"));
            menu.Items.AddRange(new ToolStripItem[] { archivo, ver, ayuda });
            Controls.Add(menu);
            MainMenuStrip = menu;
            Shown += Conectar;
        }

        private void AbrirGuia(string nombre)
        {
            string ruta = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", nombre));
            try { Process.Start(new ProcessStartInfo(ruta) { UseShellExecute = true }); }
            catch (Exception err) { MessageBox.Show(this, err.Message, "Abrir guía"); }
        }

        private async void Conectar(object sender, EventArgs e)
        {
            try
            {
                await Task.Run((Action)opciones.ComprobarServidor);
                if (IsDisposed) return;
                Task inicio = PrepararWebView();
                if (await Task.WhenAny(inicio, Task.Delay(35000)) != inicio)
                {
                    if (!IsDisposed)
                    {
                        vista.Dispose();
                        MostrarAviso("WebView2 no terminó de iniciar. Vuelve a abrir Juniors o usa iniciar_web.bat para continuar en el navegador.");
                    }
                    return;
                }
                await inicio;
                if (IsDisposed) return;
                var web = vista.CoreWebView2;
                string descargas = Environment.GetEnvironmentVariable("JUNIORS_DESCARGAS");
                if (!String.IsNullOrWhiteSpace(descargas))
                {
                    Directory.CreateDirectory(descargas);
                    web.Profile.DefaultDownloadFolderPath = Path.GetFullPath(descargas);
                }
                web.Settings.AreDevToolsEnabled = false;
                web.Settings.AreHostObjectsAllowed = false;
                web.Settings.IsWebMessageEnabled = false;
                web.Settings.IsPasswordAutosaveEnabled = false;
                web.Settings.IsGeneralAutofillEnabled = false;
                web.Settings.IsZoomControlEnabled = true;
                await web.ClearServerCertificateErrorActionsAsync();
                web.ServerCertificateErrorDetected += ValidarCertificado;
                web.NavigationStarting += Navegar;
                web.NewWindowRequested += AbrirEnlace;
                web.DownloadStarting += IniciarDescarga;
                web.ProcessFailed += (s, fallo) =>
                {
                    if (fallo.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited
                        || fallo.ProcessFailedKind == CoreWebView2ProcessFailedKind.RenderProcessExited)
                        MostrarAviso("WebView2 dejó de responder. Cierra esta ventana y vuelve a abrir Juniors o usa iniciar_web.bat.");
                };
                web.PermissionRequested += (s, permiso) => permiso.State = CoreWebView2PermissionState.Deny;
                web.NavigationCompleted += (s, nav) =>
                {
                    if (nav.IsSuccess) aviso.Visible = false;
                    else if (certificadoRechazado)
                        MostrarAviso("Windows no pudo verificar el certificado del local. Consulta CONEXION.txt e importa el certificado público de la instalación en este equipo.");
                    else if (nav.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled)
                        MostrarAviso("No se pudo cargar la aplicación. Comprueba que la ventana del servidor esté abierta y vuelve a iniciar el escritorio.");
                };
                web.Navigate(opciones.Inicio.AbsoluteUri);
            }
            catch (WebView2RuntimeNotFoundException)
            {
                MostrarAviso("Este equipo necesita Microsoft Edge WebView2 Runtime (Evergreen). "
                    + "Instálalo desde la página oficial de Microsoft Edge o abre iniciar_web.bat para usar tu navegador.");
            }
            catch (AuthenticationException)
            {
                MostrarAviso(opciones.Hoja == null
                    ? "Windows no pudo verificar el certificado del local. Sigue las instrucciones de CONEXION.txt para confiar en Juniors-CA.cer en este equipo y comprueba la dirección de Dispositivos."
                    : "El certificado del servidor local no coincide. Cierra la ventana y vuelve a abrir iniciar_escritorio.bat.");
            }
            catch (Exception err)
            {
                if (!IsDisposed)
                    MostrarAviso("No se pudo abrir Juniors.\r\n\r\n" + err.Message);
            }
        }

        private async Task PrepararWebView()
        {
            var entorno = await CoreWebView2Environment.CreateAsync(null, opciones.Perfil);
            if (!IsDisposed && !vista.IsDisposed) await vista.EnsureCoreWebView2Async(entorno);
        }

        private void MostrarAviso(string texto)
        {
            aviso.Text = texto;
            aviso.Visible = true;
            aviso.BringToFront();
        }

        private void ValidarCertificado(object sender, CoreWebView2ServerCertificateErrorDetectedEventArgs e)
        {
            e.Action = CoreWebView2ServerCertificateErrorAction.Cancel;
            if (opciones.Hoja == null)
            {
                certificadoRechazado = true;
                MostrarAviso("Windows no pudo verificar el certificado del local. Consulta CONEXION.txt e importa el certificado público de la instalación en este equipo.");
                return;
            }
            Uri uri;
            if (!Uri.TryCreate(e.RequestUri, UriKind.Absolute, out uri) || !opciones.MismoOrigen(uri)
                || e.ErrorStatus != CoreWebView2WebErrorStatus.CertificateIsInvalid) return;
            using (var hoja = e.ServerCertificate.ToX509Certificate2())
                if (opciones.MismaHoja(hoja.RawData))
                    e.Action = CoreWebView2ServerCertificateErrorAction.AlwaysAllow;
        }

        private void Navegar(object sender, CoreWebView2NavigationStartingEventArgs e)
        {
            Uri uri;
            if (Uri.TryCreate(e.Uri, UriKind.Absolute, out uri) && opciones.MismoOrigen(uri)) return;
            e.Cancel = true;
            if (e.IsUserInitiated) AbrirExterno(uri);
        }

        private void AbrirEnlace(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        {
            e.Handled = true;
            Uri uri;
            if (!e.IsUserInitiated || !Uri.TryCreate(e.Uri, UriKind.Absolute, out uri)) return;
            if (opciones.MismoOrigen(uri)) vista.CoreWebView2.Navigate(uri.AbsoluteUri);
            else AbrirExterno(uri);
        }

        private void AbrirExterno(Uri uri)
        {
            if (uri == null || (uri.Scheme != "https" && uri.Scheme != "http") || uri.UserInfo.Length != 0) return;
            try { Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true }); }
            catch (Exception err) { MessageBox.Show(this, err.Message, "Abrir enlace"); }
        }

        private void IniciarDescarga(object sender, CoreWebView2DownloadStartingEventArgs e)
        {
            string recurso = e.DownloadOperation.Uri;
            if (recurso.StartsWith("blob:", StringComparison.OrdinalIgnoreCase)) recurso = recurso.Substring(5);
            Uri uri;
            if (!Uri.TryCreate(recurso, UriKind.Absolute, out uri) || !opciones.MismoOrigen(uri))
            {
                e.Cancel = true;
                return;
            }
            string carpeta = Environment.GetEnvironmentVariable("JUNIORS_DESCARGAS");
            if (!String.IsNullOrWhiteSpace(carpeta))
            {
                string nombre = Path.GetFileName(e.ResultFilePath);
                string destino = Path.Combine(Path.GetFullPath(carpeta), nombre);
                if (!File.Exists(destino))
                {
                    e.ResultFilePath = destino;
                    e.Handled = true;
                }
            }
        }
    }
}
