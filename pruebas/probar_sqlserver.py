"""Ensayo con una base efímera exclusiva en la instancia configurada."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sys
import re
import time
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
import sqlserver


@contextmanager
def escenario():
    name = "JuniorsQA_" + uuid4().hex
    with closing(sqlserver.raw(autocommit=True,catalog="master")) as master:
        master.execute(f"CREATE DATABASE [{name}]")
        try:
            with TemporaryDirectory(dir=APP/"pruebas") as folder:
                os.environ.update(JUNIORS_SQL_DATABASE=name,JUNIORS_DATA=folder)
                yield Path(folder)
        finally:
            master.execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            master.execute(f"DROP DATABASE [{name}]")


def preparar_codigo_ui():
    """Prepara un código conocido exclusivamente en el catálogo temporal de la prueba de interfaz."""
    assert re.fullmatch(r"JuniorsQA_[a-f0-9]{32}", sqlserver.database())
    import acceso
    with closing(sqlserver.connect()) as db, db:
        sqlserver.preparar(db)
        acceso.act(db,None,"bootstrap_code",dict(email="qa@example.test",smtp_password="abcdefghijklmnop"))
        db.execute("DELETE FROM auth_invites")
        db.execute("INSERT INTO auth_invites(email,role,area,digest,expires_at) VALUES(?,?,?,?,?)",
                   ("qa@example.test","admin","",acceso._code_digest("012345"),int(time.time())+3600))


def rechazado(tipo, operation, *args):
    try:
        operation(*args)
    except tipo:
        return
    raise AssertionError("La operación debía rechazarse.")


def run():
    import servidor as app
    import inventario as inv
    import acceso
    import gestion
    app.prepare()
    app.prepare()
    with closing(app.connect()) as db, db:
        db.lock(write=True)
        admin = dict(name="Prueba",email="test@example.test",password="Prueba interna 1234")
        def enviar_codigo():
            delivery = acceso.act(db,None,"bootstrap_code",dict(admin,smtp_email="smtp@example.test",smtp_password="abcdefghijklmnop"))
            with patch.object(acceso.smtplib,"SMTP_SSL") as mail:
                delivery["_send_invite"]()
                smtp = mail.return_value.__enter__.return_value
                smtp.login.assert_called_once_with("smtp@example.test","abcdefghijklmnop")
                message = smtp.send_message.call_args.args[0]
                assert message["To"] == admin["email"]
                return re.search(r"registro es ([0-9]{6})\b", message.get_content()).group(1)
        first = enviar_codigo()
        code = enviar_codigo()
        rechazado(ValueError,acceso.act,db,None,"bootstrap",dict(admin,code=first))
        rechazado(PermissionError,acceso.act,db,None,"register",dict(admin,code=code))
        assert "_token" not in acceso.act(db,None,"bootstrap",dict(admin,code=code))
        token = acceso.act(db,None,"login",admin)["_token"]
        rechazado(PermissionError,acceso.act,db,None,"bootstrap",dict(admin,code=code))
        actor = acceso.current_user(db,token)
        inv.init(db,demo=True)
        gestion.tick(db)
    def act(module,action,payload):
        with closing(app.connect()) as db, db:
            db.lock(write=True)
            return module.act(db,actor,action,payload)
    def state():
        with closing(app.connect()) as db, db:
            db.lock(write=False)
            return app.snapshot(db,actor)
    def order(n):
        return act(inv,"pedidos.save",dict(table_name="Mesa 1",lines=[dict(product_id=6,qty=n)]))
    def stock():
        item = next(i for i in state()["items"] if i["id"]==9)
        return item["physical"],item["reserved"],item["available"]
    assert stock()==(10,0,10)
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(order,6) for _ in range(2)]
        won=[f.result() for f in futures if f.exception() is None]
        assert len(won)==1 and any(isinstance(f.exception(),ValueError) for f in futures)
    assert stock()==(10,6,4)
    record=won[0]
    for _ in range(2):
        assert act(inv,"pedidos.pay",record)["sale_code"]=="V0001"
    assert stock()==(4,0,4)
    act(inv,"pedidos.refund",dict(id=record["id"],product_id=6,qty=2,restock=[9],reason="Botellas selladas"))
    assert stock()==(6,0,6) and state()["net_sales"]==20
    rid=act(gestion,"gestion.receipt",dict(item_id=9,qty=8,supplier="Proveedor",unit_cents=125))["id"]
    act(gestion,"gestion.receive",dict(id=rid,received=7,approved=6,expiry="2099-12-31",reason="Una rechazada y una faltante"))
    assert stock()==(12,0,12) and len(state()["incidents"])==1
    act(inv,"inv.transform",dict(rule_id=1,qty=1))
    with closing(app.connect()) as db, db:
        db.lock(write=True)
        acceso.act(db,actor,"smtp_save",{"email":"smtp@example.test","password":"abcdefghijklmnop"})
        delivery=acceso.act(db,actor,"invite",{"email":"barra@example.test","role":"area","area":"Barra"})
    with patch.object(acceso,"_send_code") as sender:
        delivery["_send_invite"]()
        code=sender.call_args.args[-1]
    with closing(app.connect()) as db, db:
        db.lock(write=True)
        personal=dict(name="Barra",email="barra@example.test",password="Temporal prueba 123!",code=code)
        assert re.fullmatch(r"[0-9]{6}",code)
        rechazado(ValueError,acceso.act,db,None,"register",dict(personal,email="otra@example.test"))
        assert "_token" not in acceso.act(db,None,"register",personal)
        new=acceso.act(db,None,"login",personal)
        rechazado(ValueError,acceso.act,db,None,"register",personal)
        worker=acceso.current_user(db,new["_token"])
        assert worker["role"]=="area"
        login_result = acceso.act(db,None,"login",dict(personal,email="Barra@Example.Test"))
        assert acceso.current_user(db,login_result["_token"])["id"] == worker["id"]
        rechazado(ValueError,acceso.act,db,None,"login",dict(identifier="barra",password=personal["password"]))
        def solicitar():
            delivery=acceso.act(db,None,"reset_request",personal)
            with patch.object(acceso,"_send_code") as mail:
                delivery["_send_recovery"]()
                assert mail.call_args.kwargs["recovery"]
                return mail.call_args.args[-1]
        assert "_send_recovery" not in acceso.act(db,None,"reset_request",dict(email="ausente@example.test"))
        reset=solicitar()
        assert re.fullmatch(r"[0-9]{6}",reset)
        assert "_send_recovery" not in acceso.act(db,None,"reset_request",personal)
        reset_form=dict(personal,code=reset,password="Nueva temporal 123!")
        error_code="000001" if reset=="000000" else "000000"
        for _ in range(5):
            rechazado(acceso.InvalidCode,acceso.act,db,None,"reset_password",dict(reset_form,code=error_code))
        rechazado(acceso.InvalidCode,acceso.act,db,None,"reset_password",reset_form)
        db.execute("UPDATE auth_password_resets SET expires_at=0")
        reset_form["code"]=solicitar()
        db.execute("UPDATE auth_password_resets SET expires_at=0")
        rechazado(acceso.InvalidCode,acceso.act,db,None,"reset_password",reset_form)
        reset_form["code"]=solicitar()
        rechazado(acceso.InvalidCode,acceso.act,db,None,"reset_password",dict(reset_form,email=admin["email"]))
        acceso.act(db,None,"reset_password",reset_form)
        rechazado(acceso.InvalidCode,acceso.act,db,None,"reset_password",reset_form)
        assert acceso.current_user(db,new["_token"]) is None
        rechazado(ValueError,acceso.act,db,None,"login",personal)
        personal["password"]=reset_form["password"]
        new=acceso.act(db,None,"login",personal)
        try:
            inv.act(db,worker,"pedidos.pay",record)
        except PermissionError:
            pass
        else:
            raise AssertionError("Solo caja y administración pueden cobrar.")
        acceso.act(db,actor,"user_update",dict(id=worker["id"],role="area",area="Barra",active=False))
        assert acceso.current_user(db,new["_token"]) is None
        rechazado(ValueError,acceso.act,db,actor,"invite",dict(email="BARRA@example.test",role="admin"))
        rechazado(ValueError,acceso.act,db,None,"login",personal)
        assert "_send_recovery" not in acceso.act(db,None,"reset_request",personal)
    # Comprueba eliminación y reingreso sin cambiar el escenario usado por la prueba de respaldo.
    with closing(app.connect()) as db:
        db.lock(write=True)
        rechazado(ValueError,acceso.act,db,actor,"user_delete",dict(id=actor["id"]))
        rechazado(PermissionError,acceso.act,db,worker,"user_delete",dict(id=actor["id"]))
        acceso.act(db,actor,"user_delete",dict(id=worker["id"]))
        assert not any(row["id"]==worker["id"] for row in acceso.state(db,actor)["users"])
        invitation=acceso.act(db,actor,"invite",dict(email=personal["email"],role="caja"))
        with patch.object(acceso,"_send_code") as mail:
            invitation["_send_invite"]()
            personal["code"]=mail.call_args.args[-1]
        acceso.act(db,None,"register",personal)
        new_token=acceso.act(db,None,"login",personal)["_token"]
        replacement=acceso.current_user(db,new_token)
        assert replacement["role"]=="caja" and replacement["id"]!=worker["id"]
        rechazado(ValueError,acceso.act,db,None,"login",dict(identifier=replacement["code"],password=personal["password"]))
    with closing(app.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM inv_move_context").fetchone()[0]==db.execute("SELECT COUNT(*) FROM inv_moves").fetchone()[0]
    print("OK SQL Server: alta, sesiones, catálogo, concurrencia, cobro, devolución, recepción parcial, transformación, historial.")


if __name__=="__main__":
    with escenario():
        run()
