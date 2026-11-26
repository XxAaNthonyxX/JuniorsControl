"""Cada interfaz usa un catálogo de prueba recién creado en SQL Server."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from probar_sqlserver import escenario, APP, preparar_codigo_ui

parser = argparse.ArgumentParser(description=__doc__)
casos = {"gestion":"prueba_gestion_ui.cjs", "tabletas":"prueba_tabletas.cjs", "escritorio":"prueba_webview2.cjs"}
parser.add_argument("caso",choices=casos)
args = parser.parse_args()
with escenario() as folder:
    preparar_codigo_ui()
    from contextlib import closing
    import sqlserver
    with closing(sqlserver.raw(True)) as db:
        account=db.execute("SELECT service_account FROM sys.dm_server_services WHERE process_id=CONVERT(int,SERVERPROPERTY('ProcessID'))").fetchone()[0]
    subprocess.run(["icacls",str(folder),"/grant",account+":(OI)(CI)M"],check=True)
    os.environ["JUNIORS_SQL_BACKUP_DIR"]=str(folder)
    subprocess.run(["node", str(APP/"pruebas"/casos[args.caso])],cwd=APP,check=True,timeout=190)
