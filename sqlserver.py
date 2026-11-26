"""Conexiones ODBC a SQL Server y transacciones compartidas por ambas interfaces."""
from pathlib import Path
import json
import os
import re
import pyodbc


ROOT = Path(__file__).resolve().parent
SETTINGS = json.loads((ROOT / "sqlserver.json").read_text(encoding="utf-8-sig"))


def database():
    return os.environ.get("JUNIORS_SQL_DATABASE") or SETTINGS["database"]

def instance():
    return os.environ.get("JUNIORS_SQL_SERVER") or SETTINGS["server"]


def raw(autocommit=False, catalog=None):
    server = instance()
    name = catalog or database()
    def quote(value):
        return "{" + value.replace("}", "}}") + "}"
    local = server.lower().split("\\")[0] in {".","localhost","127.0.0.1","(localdb)","(local)"}
    connection = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER="+quote(server)+";DATABASE="+quote(name)
        +";Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate="+("yes" if local else "no")+";",
        timeout=8, autocommit=autocommit)
    connection.execute("SET ANSI_NULLS ON; SET ANSI_PADDING ON; SET ANSI_WARNINGS ON; SET ARITHABORT ON; "
                       "SET CONCAT_NULL_YIELDS_NULL ON; SET QUOTED_IDENTIFIER ON; SET NUMERIC_ROUNDABORT OFF; SET XACT_ABORT ON;")
    return connection


class Row:
    def __init__(self, columns, values):
        self.columns = columns
        self.values = values

    def keys(self):
        return self.columns.keys()

    def __getitem__(self, key):
        return self.values[self.columns[key] if isinstance(key,str) else key]

    def __iter__(self):
        return iter(self.values)


class Result:
    def __init__(self, cursor):
        self.rowcount = cursor.rowcount
        self.rows = []
        if cursor.description:
            columns = {column[0]:i for i,column in enumerate(cursor.description)}
            self.rows = [Row(columns,r) for r in cursor.fetchall()]
        self.remaining = iter(self.rows)

    def fetchone(self):
        return next(self.remaining, None)

    def fetchall(self):
        return list(self.remaining)

    def __iter__(self):
        return self.remaining

    @property
    def lastrowid(self):
        return self.rows[0][0]


class Connection:
    def __init__(self):
        self.connection = raw()

    def execute(self, sql, parameters=()):
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, tuple(parameters))
            result = Result(cursor)
            while cursor.nextset():
                pass
            return result
        finally:
            cursor.close()

    def executemany(self, sql, rows):
        rows = list(rows)
        if rows:
            cursor = self.connection.cursor()
            try:
                cursor.executemany(sql,rows)
            finally:
                cursor.close()

    def lock(self, write):
        mode = "Exclusive" if write else "Shared"
        self.execute("""IF @@TRANCOUNT=0 BEGIN TRANSACTION; DECLARE @r int;
            EXEC @r=sys.sp_getapplock @Resource=N'JuniorsControl.operaciones', @LockMode=?,
            @LockOwner='Transaction', @LockTimeout=12000;
            IF @r<0 THROW 51000, N'No se pudo reservar la transacción. Reintenta.', 1;""",(mode,))

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, trace):
        if kind is None:
            self.connection.commit()
        else:
            self.connection.rollback()


def connect():
    return Connection()


def _aplicar_v4(db):
    for batch in re.split(r"(?im)^GO\s*$", (ROOT/"sql/atencion_v4.sql").read_text(encoding="utf8")):
        if batch.strip():
            db.execute(batch)


def preparar(db):
    if db.execute("SELECT DB_ID()").fetchone()[0] <= 4:
        raise ValueError("Elige una base exclusiva de JuniorsControl.")
    db.lock(write=True)
    if db.execute("SELECT OBJECT_ID('dbo.juniors_version','U')").fetchone()[0]:
        version = db.execute("SELECT version FROM dbo.juniors_version").fetchone()[0]
        if version == 1:
            db.execute("ALTER TABLE dbo.users ADD username nvarchar(40) NULL, deleted bit NOT NULL DEFAULT 0")
            db.execute("CREATE UNIQUE INDEX ux_users_username ON dbo.users(username) WHERE username IS NOT NULL")
            db.execute("UPDATE dbo.juniors_version SET version=2 WHERE version=1")
            version = 2
        if version == 3:
            db.execute((ROOT/"sql/compatibilidad_codigos_v3.sql").read_text(encoding="utf8"))
            _aplicar_v4(db)
            version = 4
        if version == 4:
            db.execute((ROOT/"sql/detalles_v5.sql").read_text(encoding="utf8"))
            version = 5
        if version == 5:
            db.execute((ROOT/"sql/solicitudes_v6.sql").read_text(encoding="utf8"))
            return
        if version == 6:
            return
        if version != 2:
            raise ValueError("Versión de esquema incompatible.")
    else:
        if db.execute("SELECT TOP(1) name FROM sys.tables WHERE is_ms_shipped=0").fetchone():
            raise ValueError("La instalación inicial requiere una base vacía dedicada a JuniorsControl.")
        for batch in re.split(r"(?im)^GO\s*$", (ROOT/"esquema.sql").read_text(encoding="utf8")):
            if batch.strip():
                db.execute(batch)
    db.execute((ROOT/"sql/acceso_v3.sql").read_text(encoding="utf8"))
    db.execute((ROOT/"sql/compatibilidad_codigos_v3.sql").read_text(encoding="utf8"))
    _aplicar_v4(db)
    db.execute((ROOT/"sql/detalles_v5.sql").read_text(encoding="utf8"))
    db.execute((ROOT/"sql/solicitudes_v6.sql").read_text(encoding="utf8"))
