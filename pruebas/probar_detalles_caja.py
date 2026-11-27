"""Ensayo de atención y caja en un catálogo temporal exclusivo de SQL Server."""
from contextlib import closing
from probar_sqlserver import escenario, rechazado, sqlserver
import inventario as inv
import gestion


def run():
    admin={"id":1,"name":"Admin QA","role":"admin","area":""}
    def action(module,name,payload,user=admin):
        with closing(sqlserver.connect()) as db, db:
            db.lock(True)
            return module.act(db,user,name,payload)

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
    rechazado(ValueError,lambda: act("pay",payment_method="Yape",expected_cents=4400))
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
    waiter=dict(admin,role="atencion")
    bar=dict(admin,role="area",area="Barra")
    request=dict(id=order()["id"],product_id=1,qty=2,reason="Pedido devuelto")
    action(inv,"pedidos.request_refund",request,waiter)
    rechazado(ValueError,action,inv,"pedidos.request_refund",request,waiter)
    rejected=snapshot()["service_requests"]["refunds"][0]["id"]
    rechazado(PermissionError,action,inv,"pedidos.resolve_refund",dict(id=rejected,approve=True),waiter)
    action(inv,"pedidos.resolve_refund",dict(id=rejected,approve=False,reason="Revisar cantidad"))
    action(inv,"pedidos.request_refund",dict(request,qty=1),waiter)
    key=snapshot()["service_requests"]["refunds"][0]["id"]
    lot_balances=lambda: {l["id"]:l["physical"] for l in snapshot()["lots"]}
    before_refund=lot_balances()
    action(inv,"pedidos.resolve_refund",dict(id=key,approve=True))
    with closing(sqlserver.connect()) as db, db:
        parts=db.execute("""SELECT amount,restocked FROM refund_parts p JOIN refund_requests r
                            ON r.return_id=p.return_id WHERE r.id=?""",(key,)).fetchall()
        assert parts and all(amount==restocked for amount,restocked in parts)
    assert lot_balances()!=before_refund
    rechazado(ValueError,action,inv,"pedidos.resolve_refund",dict(id=key,approve=True))
    assert order()["total"]==22 and len(order()["returns"])==1
    undo=dict(id=key,kind="refund",revision=1)
    rechazado(PermissionError,action,inv,"pedidos.undo_request",undo,waiter)
    action(inv,"pedidos.undo_request",undo)
    assert order()["total"]==44 and order()["returns"][0]["undone_at"]
    assert lot_balances()==before_refund
    rechazado(ValueError,action,inv,"pedidos.undo_request",undo)
    action(inv,"pedidos.resolve_refund",dict(id=key,approve=False,revision=2,reason="Prueba"))
    action(inv,"pedidos.undo_request",dict(undo,revision=3))
    action(inv,"pedidos.resolve_refund",dict(id=key,approve=True,revision=4,restock=[]))
    assert order()["total"]==22
    action(inv,"inv.menu_category",dict(name="Jugos"))
    action(inv,"inv.product",dict(name="Jugo QA",category="Jugos",prep_area="Barra",price=8,recipe=[dict(item_id=1,qty=1)]))
    action(inv,"inv.menu_category",dict(previous="Jugos",name="Jugos naturales"))
    for area in ("Barra","Cocina","Parrilla"):
        with closing(sqlserver.connect()) as db, db:
            scoped=inv.state(db,dict(bar,area=area),inv.today())
        assert not scoped["orders"] and "service_requests" not in scoped
        assert any(p["name"]=="Jugo QA" and p["category"]=="Jugos naturales" for p in scoped["area_menu"])==(area=="Barra")
        assert all(job["area"]==area for job in scoped["preparation"])
    action(gestion,"gestion.cash_day",{"day":"2020-02-29"})
    action(inv,"pedidos.save",dict(table_number=11,lines=details(6)))
    assert order()["day"]=="2020-02-29" and order()["code"]=="C0001"
    rechazado(ValueError,lambda: act("request_cancel",reason="Sin entregas"))
    act("send")
    deliver(next(r for r in snapshot()["preparation"] if r["order_id"]==order()["id"]))
    act("request_cancel",reason="Prueba de bloqueo")
    rechazado(ValueError,lambda: act("save",lines=details(6,6)))
    rechazado(ValueError,lambda: act("send"))
    act("decide_cancel",approve=True,restock_details=[1])
    assert order()["status"]=="Cancelado"
    requests=snapshot()["service_requests"]
    assert not requests["refunds"] and not requests["refundable"]
    req=requests["cancellations"][0]
    undo=dict(id=req["id"],kind="cancel",revision=req["revision"])
    action(inv,"pedidos.undo_request",undo)
    assert order()["status"]=="Reservado" and order()["cancel_request"]
    act("decide_cancel",approve=False)
    action(inv,"pedidos.undo_request",dict(undo,revision=3))
    act("decide_cancel",approve=True,restock_details=[1])
    empty="2020-03-01"
    action(gestion,"gestion.cash_day",dict(day=empty,expected_day="2020-02-29"))
    assert not snapshot()["service_requests"]["cancellations"]
    rechazado(ValueError,action,gestion,"gestion.cash_day",dict(day="2020-03-02",expected_day="2020-02-29"))
    rechazado(PermissionError,action,gestion,"gestion.cash_day",dict(day=empty),waiter)
    action(gestion,"gestion.cash_day",dict(day="2020-02-29",expected_day=empty))
    with closing(sqlserver.connect()) as db, db:
        registry={r["day"]:r for r in gestion.state(db,admin)["registered_days"]}
        assert empty in registry and registry[empty]["opened_by"]==admin["name"]
        assert inv.today() in registry and inv.business_day(db)=="2020-02-29"
        assert "registered_days" not in gestion.state(db,waiter)
        assert db.execute("SELECT COUNT(*) FROM cash_days WHERE day=?",("2020-02-29",)).fetchone()[0]==1
    # Dos unidades iguales, una entregada y una pendiente: sólo se factura la primera.
    action(inv,"pedidos.save",dict(table_number=11,lines=details(6,6)))
    rechazado(ValueError,lambda: act("void_sale",reason="Sin entregas"))
    act("send")
    deliver(next(r for r in snapshot()["preparation"] if r["order_id"]==order()["id"]))
    before=lot_balances()
    act("pay",expected_cents=500)
    sold=order()
    assert sold["total"]==5 and len(sold["details"])==2 and sold["lines"][0]["qty"]==1
    assert sorted(d["status"] for d in sold["details"])==["Cancelado","Entregado"]
    assert sum(d["price"]*d["qty"] for d in sold["details"])==10
    after=lot_balances()
    assert before!=after
    rechazado(ValueError,lambda: act("void_sale",reason="Venta incorrecta"))
    act("request_cancel",reason="Venta incorrecta")
    assert order()["status"]=="Cobrado" and order()["cancel_request"]
    assert act("decide_cancel",approve=True,restock_details=[])["void_cents"]==500
    assert lot_balances()==after and order()["status"]=="Anulada"
    rechazado(ValueError,lambda: act("void_sale",reason="Duplicada"))
    action(inv,"pedidos.save",dict(table_number=11,lines=details(6,6)))
    act("send")
    deliver(next(r for r in snapshot()["preparation"] if r["order_id"]==order()["id"]))
    rechazado(ValueError,lambda: act("void_sale",reason="Anular antes del cobro"))
    act("request_cancel",reason="Anular antes del cobro")
    act("decide_cancel",approve=True,restock_details=[])
    assert order()["status"]=="Cancelado" and not order()["paid_at"]
    action(inv,"pedidos.save",dict(table_number=11,lines=details(6)))
    act("send")
    deliver(next(r for r in snapshot()["preparation"] if r["order_id"]==order()["id"]))
    act("pay",expected_cents=500)
    before=lot_balances()
    act("refund_order",whole=True,expected_day="2020-02-29",reason="Sin reposición",
        details=[dict(detail_no=1,qty=1,restock=False)])
    assert lot_balances()==before and order()["status"]=="Devuelto"
    print("Cobro parcial con cierre, anulación antes y después del pago y devolución directa verificados.")
    print("Registro persistente, reapertura, permisos y conflicto entre jornadas verificados.")
    print("Detalles, envío, entrega, cobro único con Yape y arqueo verificados.")


if __name__=="__main__":
    with escenario():
        run()
