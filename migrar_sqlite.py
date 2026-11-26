"""Traslada un respaldo de Juniors a una base SQL Server nueva con su esquema instalado."""
import argparse
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import sys

import sqlserver


# Los padres preceden a los hijos para que todas las claves sigan activas al importar.
TABLES = (
    "users", "inv_items", "inv_lots", "inv_moves", "inv_move_context",
    "inv_products", "inv_recipes", "inv_rules", "inv_orders", "inv_lines",
    "inv_line_recipes", "inv_alloc", "inv_events", "inv_sales", "inv_returns",
    "inv_exchanges", "inv_seed", "g_settings", "g_purchases", "g_lines",
    "g_receipts", "g_incidents", "g_wastes", "g_alerts", "g_reports",
    "g_shortage", "operaciones",
)
EXCLUDED = ("auth_sessions", "auth_invites", "auth_smtp")


@contextmanager
def validated_snapshot(path):
    path = Path(path).expanduser().resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)) as source:
        source.execute("PRAGMA trusted_schema=OFF")
        source.execute("BEGIN")
        if source.execute("PRAGMA integrity_check").fetchall()!=[("ok",)] or source.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("La copia presenta errores de integridad.")
        names={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(TABLES+EXCLUDED)-{"inv_move_context"} <= names:
            raise ValueError("Selecciona una copia de la versión Avance de Juniors.")
        if not source.execute("SELECT 1 FROM users WHERE active=1 AND role='admin'").fetchone():
            raise ValueError("La copia necesita una cuenta administradora activa.")
        if "inv_move_context" not in names:
            source.execute("""CREATE TEMP VIEW inv_move_context AS
                SELECT m.id AS move_id,i.area,i.name AS item_name FROM inv_moves m
                JOIN inv_lots l ON l.id=m.lot_id JOIN inv_items i ON i.id=l.item_id""")
        yield source


def source_counts(source):
    return {name: source.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
            for name in TABLES}


def copy_tables(source, destination):
    """Requiere una transacción SQL Server abierta. El llamador confirma o revierte."""
    counts = source_counts(source)
    metadata = {}
    all_tables = TABLES + EXCLUDED
    if destination.execute("SELECT DB_ID()").fetchone()[0] <= 4:
        raise ValueError("Selecciona una base de Juniors creada para la migración.")
    for name in all_tables:
        columns = list(destination.execute("""
            SELECT c.name, c.is_identity
            FROM sys.columns AS c
            WHERE c.object_id=OBJECT_ID(?, 'U') ORDER BY c.column_id""", ("dbo." + name,)))
        if not columns:
            raise ValueError(f"Falta dbo.{name} en el destino. Instala primero el esquema de SQL Server.")
        local = [r[1] for r in source.execute(f"PRAGMA table_info([{name}])")]
        expected = {c[0] for c in columns}
        if name == "inv_sales":
            expected -= {"payment_method","cash_day"}
        if name=="inv_returns":
            expected.discard("cash_day")
        if name=="g_settings":
            expected.discard("work_day")
        if name == "users":
            expected -= {"username", "deleted"}
        if name == "auth_invites":
            expected.discard("attempts")
        if set(local) != expected:
            raise ValueError(f"Las columnas de {name} son distintas entre el respaldo y el destino.")
        metadata[name] = (local, any(c[1] for c in columns))
        # El bloqueo permanece hasta el fin de la transacción y evita carreras con otro proceso.
        total = destination.execute(
            f"SELECT COUNT_BIG(*) FROM dbo.[{name}] WITH (TABLOCKX, HOLDLOCK)").fetchone()[0]
        if total:
            if name == "g_settings" and total == 1:
                row = destination.execute("SELECT id,run_time,opening_cents FROM dbo.g_settings").fetchone()
                if tuple(row) == (1, "18:00", 0):
                    continue
            raise ValueError(f"El destino contiene datos en {name}. Selecciona una base nueva.")
    # La aplicación puede haber creado su configuración de apertura sin datos de operación.
    destination.execute("DELETE FROM dbo.g_settings WHERE id=1")
    for name in TABLES:
        if not counts[name]:
            continue
        columns, identity = metadata[name]
        # Los nombres proceden del catálogo verificado en ambos motores.
        fields = ", ".join("[" + c.replace("]", "]]") + "]" for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        query = f"INSERT INTO dbo.[{name}] ({fields}) VALUES ({placeholders})"
        if identity:
            destination.execute(f"SET IDENTITY_INSERT dbo.[{name}] ON")
        rows = source.execute(f"SELECT {fields} FROM [{name}]")
        while batch := rows.fetchmany(500):
            destination.executemany(query, batch)
        if identity:
            destination.execute(f"SET IDENTITY_INSERT dbo.[{name}] OFF")
            # Una importación fallida anterior puede haber avanzado la identidad pese al rollback.
            # Para tablas con datos, el próximo ID debe seguir al máximo que se conserva.
            maximum = source.execute(f"SELECT MAX(id) FROM [{name}]").fetchone()[0]
            destination.execute(f"DBCC CHECKIDENT ('dbo.{name}', RESEED, {int(maximum)}) WITH NO_INFOMSGS")
        verified = destination.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{name}]").fetchone()[0]
        if verified != counts[name]:
            raise ValueError(f"Recuento incorrecto en {name}. Se cancela la migración.")
    destination.execute("""INSERT inv_details(order_id,detail_no,product_id,qty) SELECT order_id,
        ROW_NUMBER() OVER(PARTITION BY order_id ORDER BY product_id),product_id,qty FROM inv_lines""")
    return counts

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("respaldo",type=Path)
    args=parser.parse_args()
    with validated_snapshot(args.respaldo) as source, closing(sqlserver.connect()) as destination, destination:
        sqlserver.preparar(destination)
        counts=copy_tables(source,destination)
    print("Migración confirmada.", sum(counts.values()), "filas de datos. Vuelve a configurar Gmail.")
