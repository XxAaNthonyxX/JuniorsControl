"""Construye una copia del EXE de Windows en work para probarla antes de distribuirla."""
from pathlib import Path
import os
import subprocess
import sys

work = Path(__file__).resolve().parent
app = work.parent
src = app / 'escritorio'
csc = Path(sys.argv[1]) if len(sys.argv)>1 else Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
target = src / 'Juniors.exe'
options = ['/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',
           '/out:'+str(target), '/win32manifest:'+str(src/'Juniors.manifest'), '/win32icon:'+str(app/'web'/'juniors.ico')]
references = ['System.dll','System.Core.dll','System.Windows.Forms.dll','System.Drawing.dll',
              src/'Microsoft.Web.WebView2.Core.dll',src/'Microsoft.Web.WebView2.WinForms.dll']
subprocess.run([str(csc),*options,*['/reference:'+str(r) for r in references],str(src/'Juniors.cs'),str(src/'Conexion.cs')],check=True)
print('Compilado:',target)
