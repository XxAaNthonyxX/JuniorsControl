"""Prepara la base dedicada indicada en sqlserver.json usando la cuenta de Windows."""
from contextlib import closing
import re
import sqlserver


def instalar():
    name=sqlserver.database()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,119}",name):
        raise ValueError("El nombre de la base debe usar letras, dígitos y guion bajo.")
    with closing(sqlserver.raw(True,"master")) as master:
        if master.execute("SELECT DB_ID(?)",name).fetchone()[0] is None:
            master.execute(f"CREATE DATABASE [{name}] COLLATE Latin1_General_100_CI_AS")
    with closing(sqlserver.connect()) as db, db:
        sqlserver.preparar(db)
    print("Base lista:", name, "· Abre iniciar.bat.")


if __name__=="__main__":
    try:
        instalar()
    except (ValueError,sqlserver.pyodbc.Error) as exc:
        raise SystemExit("No se completó la configuración. Revisa sqlserver.json, ODBC 18 y los permisos de Windows.\n"+str(exc))
