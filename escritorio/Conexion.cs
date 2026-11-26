using System;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace Juniors.Escritorio
{
    internal static class Conexion
    {
        public static bool DireccionPrivada(string texto, out Uri direccion)
        {
            direccion = null;
            Match m = Regex.Match(texto.Trim(), @"\Ahttps://(?<ip>(?:[0-9]{1,3}\.){3}[0-9]{1,3}):(?<puerto>[0-9]{1,5})/?\z",
                                  RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
            IPAddress ip;
            if (!m.Success || !IPAddress.TryParse(m.Groups["ip"].Value, out ip)
                || ip.ToString() != m.Groups["ip"].Value) return false;
            byte[] octetos = ip.GetAddressBytes();
            if (!(octetos[0] == 10 || (octetos[0] == 172 && octetos[1] >= 16 && octetos[1] <= 31)
                || (octetos[0] == 192 && octetos[1] == 168))) return false;
            int puerto;
            if (!Int32.TryParse(m.Groups["puerto"].Value, out puerto) || puerto < 1 || puerto > 65535) return false;
            direccion = new UriBuilder("https", ip.ToString(), puerto).Uri;
            return true;
        }

        public static Opciones PedirServidor()
        {
            string appData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            if (String.IsNullOrWhiteSpace(appData)) appData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string carpeta = Path.Combine(appData, "Juniors");
            string ultima = Path.Combine(carpeta, "ultima-url.txt");
            using (var dialogo = new Form())
            {
                dialogo.Text = "Juniors · Conectar al local";
                dialogo.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
                dialogo.Font = new Font("Segoe UI", 10F);
                dialogo.ClientSize = new Size(484, 245);
                dialogo.FormBorderStyle = FormBorderStyle.FixedDialog;
                dialogo.StartPosition = FormStartPosition.CenterScreen;
                dialogo.MaximizeBox = false;
                dialogo.MinimizeBox = false;
                dialogo.AutoScaleMode = AutoScaleMode.Dpi;
                var titulo = new Label { Text = "Conectar al local", Location = new Point(20,17), AutoSize = true,
                                         Font = new Font("Segoe UI", 16F, FontStyle.Bold) };
                var instrucciones = new Label { Text = "Pega la dirección HTTPS que muestra Dispositivos en el equipo principal.",
                                                 Location = new Point(22,63), Size = new Size(438,42) };
                var campo = new TextBox { Location = new Point(22,111), Width = 438, TabIndex = 0, MaxLength = 80,
                                          AccessibleName = "Dirección HTTPS del local" };
                if (File.Exists(ultima)) campo.Text = File.ReadAllText(ultima).Trim();
                var ayuda = new Label { Text = "Ejemplo: https://192.168.1.20:8765", Location = new Point(22,145),
                                        Size = new Size(438,43), ForeColor = Color.DimGray };
                var conectar = new Button { Text = "Conectar", Location = new Point(350,195),
                                            Size = new Size(110,33), TabIndex = 1 };
                var cancelar = new Button { Text = "Cancelar", Location = new Point(231,195),
                                            Size = new Size(110,33), TabIndex = 2, DialogResult = DialogResult.Cancel };
                Uri servidor = null;
                conectar.Click += (s, e) =>
                {
                    if (DireccionPrivada(campo.Text, out servidor)) dialogo.DialogResult = DialogResult.OK;
                    else
                    {
                        ayuda.ForeColor = Color.Firebrick;
                        ayuda.Text = "Escribe una dirección HTTPS con la IPv4 privada del local y su puerto.";
                        campo.Focus();
                        campo.SelectAll();
                    }
                };
                dialogo.Controls.AddRange(new Control[] { titulo, instrucciones, campo, ayuda, conectar, cancelar });
                dialogo.AcceptButton = conectar;
                dialogo.CancelButton = cancelar;
                dialogo.Shown += (s, e) => campo.Focus();
                if (dialogo.ShowDialog() != DialogResult.OK) return null;
                Directory.CreateDirectory(carpeta);
                File.WriteAllText(ultima, servidor.GetLeftPart(UriPartial.Authority));
                return new Opciones { Inicio = servidor, Perfil = Path.Combine(carpeta, "perfil-cliente") };
            }
        }
    }
}
