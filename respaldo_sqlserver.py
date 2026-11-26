"""Copia nativa diaria del catálogo activo. La instancia escribe el archivo .bak."""
import hashlib
import json
import ntpath
import os
import re
from uuid import uuid4


def copia_diaria(connection, folder, day):
    """Recibe una conexión ODBC en autocommit, fuera de la transacción de la aplicación."""
    cursor = connection.cursor()
    try:
        server, database, created, default_dir = cursor.execute("""
            SELECT CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')), DB_NAME(), create_date,
                   CONVERT(nvarchar(4000),SERVERPROPERTY('InstanceDefaultBackupPath'))
            FROM sys.databases WHERE database_id=DB_ID()
        """).fetchone()
        identity = json.dumps([server,database,str(created)],ensure_ascii=False)
        key = hashlib.sha256(identity.encode()).hexdigest()[:16]
        folder.mkdir(parents=True,exist_ok=True)
        record = folder / f"sqlserver-{key}-{day}.json"
        if record.exists():
            return json.loads(record.read_text(encoding="utf-8"))["archivo"]
        directory = os.environ.get("JUNIORS_SQL_BACKUP_DIR") or default_dir
        if not directory:
            raise ValueError("Configura JUNIORS_SQL_BACKUP_DIR con una carpeta del servidor SQL.")
        stem = re.sub(r"[^\w.-]", "_", database)[:100]
        name = f"{stem}-{day}-{uuid4().hex[:12]}.bak"
        # SQL Server también puede estar en otro equipo con rutas POSIX.
        path = directory.rstrip("/") + "/" + name if directory.startswith("/") else ntpath.join(directory,name)
        cursor.execute("""
            DECLARE @bd sysname=DB_NAME(), @archivo nvarchar(4000)=?;
            BACKUP DATABASE @bd TO DISK=@archivo WITH COPY_ONLY, CHECKSUM;
        """, path)
        while cursor.nextset():
            pass
        temp = record.with_suffix(".tmp")
        temp.write_text(json.dumps({"servidor":server,"base":database,"archivo":path,"fecha":day},
                                   ensure_ascii=False,indent=2),encoding="utf-8")
        temp.replace(record)
        return path
    finally:
        cursor.close()
