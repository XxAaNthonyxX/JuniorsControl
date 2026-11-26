"""Recupera una copia .bak a un catálogo nuevo de la misma instancia."""
from contextlib import closing
from pathlib import Path
import re
import sqlserver


def restaurar(archivo, nueva):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,119}", nueva):
        raise ValueError("Elige un nombre con letras, números y guion bajo.")
    with closing(sqlserver.raw(True,"master")) as db:
        if db.execute("SELECT DB_ID(?)",nueva).fetchone()[0] is not None:
            raise ValueError("Ya existe una base con ese nombre.")
        rows=db.execute("RESTORE FILELISTONLY FROM DISK=?",archivo).fetchall()
        logical={r.Type:r.LogicalName for r in rows}
        if len(rows)!=2 or set(logical)!={"D","L"}:
            raise ValueError("Para copias con varios archivos de datos, usa Restaurar en SSMS.")
        script=(Path(__file__).resolve().parent/"sql/recuperar_copia.sql").read_text(encoding="utf8").split("\nGO\n",1)[1]
        begin=script.index("IF @archivo")
        command="""DECLARE @archivo nvarchar(4000)=?, @nueva sysname=?, @datos sysname=?, @log sysname=?;
        """+script[begin:]
        cur=db.execute(command,archivo,nueva,logical["D"],logical["L"])
        while cur.nextset():
            pass


if __name__=="__main__":
    archivo=input("Ruta del .bak en el servidor SQL: ").strip().strip('"')
    nueva=input("Nombre NUEVO para la base recuperada: ").strip()
    try:
        restaurar(archivo,nueva)
    except (ValueError,sqlserver.pyodbc.Error) as exc:
        raise SystemExit(str(exc))
    print("Copia recuperada en",nueva,"· Para usarla, cierra Juniors, cambia database en sqlserver.json y vuelve a iniciar.")
