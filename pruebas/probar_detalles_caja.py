"""Ensayo de atención y caja en un catálogo temporal exclusivo de SQL Server."""
from contextlib import closing
from probar_sqlserver import escenario, rechazado, sqlserver
import inventario as inv
import gestion


def run():
    admin={"id":1,"name":"Admin QA","role":"admin","area":""}
    def action(module,name,payload):
        with closing(sqlserver.connect()) as db, db:
            db.lock(True)
            return module.act(db,admin,name,payload)

    def snapshot():
        with closing(sqlserver.connect()) as db, db:
            db.lock(False)
            return inv.state(db,admin,inv.today())

    with closing(sqlserver.connect()) as db, db:
        sqlserver.preparar(db)
        inv.init(db,demo=True)

    def details(*products):
        return [{"detail_no":i,"product_id":pid,"qty":1} for i,pid in enumerate(products,1)]

    def order():
        return snapshot()["orders"][0]

    def act(name,**fields):
        o=order()
        return action(inv,"pedidos."+name,dict(id=o["id"],version=o["version"],table_number=11,**fields))

    def deliver(job):
        return action(inv,"pedidos.prep",dict(id=job["order_id"],product_id=job["product_id"],
                            detail_no=job["detail_no"],revision=job["revision"],step="entregar"))

    action(inv,"pedidos.save",dict(table_number=11,lines=details(5)))
    assert not snapshot()["preparation"]
    act("send")
    stale=snapshot()["preparation"][0]
    act("save",lines=details(1))
    assert snapshot()["preparation"][0]["product_id"]==5
    act("send")
    rechazado(ValueError,deliver,stale)
    delivered=snapshot()["preparation"][0]
    assert delivered["product_id"]==1 and delivered["area"]=="Parrilla"
    deliver(delivered)
    rechazado(ValueError,lambda: act("save",lines=details(6)))
    act("save",lines=details(1,1))
    assert len(snapshot()["preparation"])==1
    rechazado(ValueError,lambda: act("pay",payment_method="Yape"))
    act("send")
    second=next(r for r in snapshot()["preparation"] if r["detail_no"]==2)
    act("save",lines=details(1,6))
    deliver(second)
    assert [d["product_id"] for d in order()["details"]]==[1,1]
    rechazado(ValueError,lambda: act("pay",payment_method="Yape",expected_cents=100))
    result=act("pay",payment_method="Yape",expected_cents=4400)
    assert act("pay",payment_method="Yape")==result
    assert order()["payment_method"]=="Yape" and order()["total"]==44
    rechazado(ValueError,lambda: act("save",lines=details(1,1,5)))
    gasto=dict(kind="Mercado",day=inv.today(),reference="QA-1",concept="Verduras",amount="3.25")
    action(gestion,"gestion.cash_expense",gasto)
    rechazado(ValueError,action,gestion,"gestion.cash_expense",gasto)
    with closing(sqlserver.connect()) as db, db:
        expenses=gestion.state(db,admin)["cash_expenses"]
        assert inv.net_sales(db)-expenses[0]["cents"]==4075
    action(gestion,"gestion.void_expense",dict(id=expenses[0]["id"],day=inv.today(),reason="Prueba"))
    with closing(sqlserver.connect()) as db, db:
        assert gestion.state(db,admin)["cash_expenses"][0]["void_at"]
    action(gestion,"gestion.cash_day",{"day":"2020-02-29"})
    action(inv,"pedidos.save",dict(table_number=11,lines=details(6)))
    assert order()["day"]=="2020-02-29" and order()["code"]=="C0001"
    act("request_cancel",reason="Prueba de bloqueo")
    rechazado(ValueError,lambda: act("save",lines=details(6,6)))
    rechazado(ValueError,lambda: act("send"))
    print("Detalles, envío, entrega, cobro único con Yape y arqueo verificados.")


if __name__=="__main__":
    with escenario():
        run()
