"""Prueba copia, restauración y, si se indica un respaldo anterior, importación."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sys
import subprocess
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parent))
from probar_sqlserver import APP, escenario, run, sqlserver


def recuperar(folder):
    import servidor
    with closing(sqlserver.raw(True)) as db:
        account=db.execute("SELECT service_account FROM sys.dm_server_services WHERE process_id=CONVERT(int,SERVERPROPERTY('ProcessID'))").fetchone()[0]
    subprocess.run(["icacls",str(folder),"/grant",account+":(OI)(CI)M"],check=True)
    os.environ["JUNIORS_SQL_BACKUP_DIR"]=str(folder)
    path=servidor.backup()
    assert servidor.backup()==path
    target="JuniorsQA_"+uuid4().hex
    with closing(sqlserver.raw(True,"master")) as master:
        from restaurar_sqlserver import restaurar
        try:
            restaurar(path,target)
            with closing(sqlserver.raw(True,target)) as restored:
                assert restored.execute("SELECT count(*) FROM dbo.users").fetchone()[0]==2
                assert restored.execute("SELECT count(*) FROM dbo.inv_sales").fetchone()[0]==1
                assert restored.execute("SELECT count(*) FROM dbo.auth_sessions").fetchone()[0]==0
            print("OK: .bak diario, VERIFYONLY, restauración independiente, CHECKDB, cuentas, ventas y cierre de sesiones.")
        finally:
            if master.execute("SELECT DB_ID(?)",target).fetchone()[0]:
                master.execute(f"ALTER DATABASE [{target}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
                master.execute(f"DROP DATABASE [{target}]")


def importar(path):
    from migrar_sqlite import validated_snapshot, copy_tables
    with validated_snapshot(path) as source, closing(sqlserver.connect()) as db, db:
        sqlserver.preparar(db)
        counts=copy_tables(source,db)
    with closing(sqlserver.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0]==counts["users"]
    print("OK: migración y recuentos por tabla.",sum(counts.values()),"filas confirmadas.")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origen",type=Path)
    args=parser.parse_args()
    with escenario() as folder:
        run()
        recuperar(folder)
    if args.origen:
        with escenario():
            importar(args.origen)
