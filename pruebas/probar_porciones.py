"""Verifica equivalencias, ventas y devoluciones en un catálogo SQL Server temporal."""
from contextlib import closing
from probar_sqlserver import escenario, sqlserver
import inventario as inv

ADMIN={"id":1,"name":"QA","role":"admin","area":""}


def action(name,payload):
    with closing(sqlserver.connect()) as db,db:
        db.lock(True)
        return inv.act(db,ADMIN,name,payload)


def snapshot():
    with closing(sqlserver.connect()) as db,db:
        db.lock(False)
        return inv.state(db,ADMIN,inv.today())


def run():
    with closing(sqlserver.connect()) as db,db:
        sqlserver.preparar(db)
        sqlserver.preparar(db)
        inv.init(db,True)
    config=dict(raw_id=1,base_id=2,potato_id=3,quarter_product_id=1,half_product_id=2)
    group=action("inv.portions",config)
    action("inv.portions",config)
    whole_id=group["whole_id"]
    half_id=next(i["id"] for i in snapshot()["items"] if i.get("factor")==2)
    whole=action("inv.product",dict(name="Pollo entero QA",category="Brasas",price=70,
        recipe=[dict(item_id=whole_id,qty=1),dict(item_id=3,qty=3)]))["id"]
    with closing(sqlserver.connect()) as db,db:
        db.lock(True)
        inv.receive(db,ADMIN,1,50000,inv.today(),"QA","")
        rule=db.execute("SELECT id FROM inv_rules WHERE source_id=1 AND target_id=?",(whole_id,)).fetchone()[0]
    action("inv.transform",dict(rule_id=rule,qty=50))

    def amounts():
        items={i["id"]:i for i in snapshot()["items"]}
        return tuple(items[i]["physical"] for i in (2,half_id,whole_id,3))

    def sell(*products):
        saved=action("pedidos.save",dict(table_number=1,lines=[dict(detail_no=n,product_id=p,qty=1) for n,p in enumerate(products,1)]))
        def current():
            return next(o for o in snapshot()["orders"] if o["id"]==saved["id"])
        o=current()
        action("pedidos.send",dict(id=o["id"],version=o["version"]))
        for job in snapshot()["preparation"]:
            if job["order_id"]==o["id"]:
                action("pedidos.prep",dict(id=o["id"],detail_no=job["detail_no"],product_id=job["product_id"],revision=job["revision"],step="entregar"))
        o=current()
        payload=dict(id=o["id"],version=o["version"],payment_method="Efectivo")
        action("pedidos.pay",payload)
        before=amounts()
        action("pedidos.pay",payload)
        assert amounts()==before
        return current()

    assert amounts()==(236,118,59,32)
    for expected in ((235,118,59,31.5),(234,117,59,31),(233,117,59,30.5),(232,116,58,30)):
        sell(1)
        assert amounts()==expected,amounts()
    sell(2)
    assert amounts()==(230,115,58,28.5)
    sell(1,1,2)
    assert amounts()==(226,113,57,26)
    sale=sell(whole)
    assert amounts()==(222,111,56,23)
    action("pedidos.refund",dict(id=sale["id"],version=sale["version"],product_id=whole,qty=1,reason="QA",restock=[2,3]))
    assert amounts()==(226,113,57,26)
    sale=sell(1)
    before=amounts()
    action("pedidos.refund",dict(id=sale["id"],version=sale["version"],product_id=1,qty=1,reason="QA",restock=[]))
    assert amounts()==before
    saved=action("pedidos.save",dict(table_number=1,lines=[dict(detail_no=1,product_id=2,qty=1)]))
    o=next(o for o in snapshot()["orders"] if o["id"]==saved["id"])
    action("pedidos.cancel",dict(id=o["id"],version=o["version"]))
    assert amounts()==before
    print("OK: 50 pollos transformados, ventas acumuladas y mixtas, papa, doble cobro, cancelación y reposición opcional.")


if __name__=="__main__":
    with escenario():
        run()
