"""Compras, recepciones, alertas y supervisión del inventario de Juniors.

El servidor abre una transacción de escritura por acción o ciclo de mantenimiento.
Las cantidades se almacenan en milésimas y los importes en céntimos de sol.
"""

from datetime import date, datetime, timedelta, timezone
from collections import defaultdict
from math import lcm
import re

import inventario as inv


LIMA = timezone(timedelta(hours=-5))
MAX_CENTS = 10**11


def stamp():
    return datetime.now(LIMA).isoformat(timespec="seconds")


def _text(value, label, limit=220, *, optional=False):
    if not isinstance(value, str) or len(value.strip()) > limit or (not value.strip() and not optional):
        raise ValueError(f"Comprueba el campo «{label}» (máximo {limit} caracteres).")
    return value.strip()


def _int(value, label, minimum=0, maximum=MAX_CENTS):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,15}", str(value)):
        raise ValueError(f"Introduce un número entero válido en «{label}».")
    n = int(value)
    if not minimum <= n <= maximum:
        raise ValueError(f"El valor de «{label}» está fuera del intervalo permitido.")
    return n


def _flag(p):
    if type(p.get("approve")) is not bool:
        raise ValueError("Selecciona aprobar o rechazar.")
    return p["approve"]


def _one(db, sql, *args):
    row = db.execute(sql, args).fetchone()
    if row is None:
        raise ValueError("No se encontró el registro solicitado.")
    return row


def _item(db, item_id):
    return _one(db, "SELECT * FROM inv_items WHERE id=?", _int(item_id, "insumo", 1))


def _require(user, *roles):
    if user["role"] not in roles:
        raise PermissionError("Tu rol no permite realizar esta operación.")


def _accessible(user, area):
    if user["role"] in ("area","atencion"):
        return area in inv.inventory_access_areas(user)
    return True


def _waste_accessible(user, area):
    if user["role"] == "recepcion":
        return area in inv.inventory_access_areas(user)
    return _accessible(user, area)


def _amount(qty_m, unit_cents):
    # Redondeo comercial al céntimo en cada renglón.
    return (qty_m * unit_cents + 500) // 1000


def _cap_line(qty_m, unit_cents):
    if _amount(qty_m, unit_cents) > MAX_CENTS:
        raise ValueError("El importe de la línea supera el máximo admitido.")


def _price(db, item_id):
    row = db.execute("""SELECT TOP (1) unit_cents FROM g_receipts WHERE item_id=? AND approved_m>0
                        ORDER BY reviewed_at DESC,id DESC""", (item_id,)).fetchone()
    return row[0] if row else 0


def _receipt_cost(receipt):
    if receipt["approved_m"] is None:
        return 0,_amount(receipt["qty_m"],receipt["unit_cents"]) if receipt["line_id"] is not None else 0
    spent=_amount(receipt["approved_m"],receipt["unit_cents"])
    pending=(receipt["qty_m"]-receipt["approved_m"]) if receipt["line_id"] is not None and receipt["pending_issue"] else 0
    return spent,_amount(pending,receipt["unit_cents"])


def budget(db):
    opening = _one(db, "SELECT opening_cents FROM g_settings WHERE id=1")[0]
    sales = inv.net_sales(db)
    spent = committed = issued = 0
    for r in db.execute("""SELECT r.qty_m,r.approved_m,r.unit_cents,r.line_id,l.physical,
                           CASE WHEN i.id IS NOT NULL AND i.closed IS NULL THEN 1 ELSE 0 END AS pending_issue
                           FROM g_receipts r LEFT JOIN inv_lots l ON r.lot_id=l.id
                           LEFT JOIN g_incidents i ON i.receipt_id=r.id"""):
        accepted,pending=_receipt_cost(r)
        spent+=accepted
        committed+=pending
        if r["approved_m"] is not None and r["physical"] is not None:
            issued+=_amount(r["approved_m"]-r["physical"],r["unit_cents"])
    other=_one(db,"SELECT COALESCE(SUM(cents),0) FROM cash_expenses WHERE purchase_id IS NULL AND void_at IS NULL")[0]
    return dict(opening_cents=opening, sales_cents=sales, spent_cents=spent,
                committed_cents=committed, other_expenses_cents=other, available_cents=opening+sales-spent-committed-other,
                issues_cents=issued)


def _receipt(db, user, p):
    _require(user, "admin", "recepcion")
    item = _item(db, p.get("item_id"))
    supplier = _text(p.get("supplier"), "proveedor", 100)
    quantity = inv.item_quantity(item["name"],p.get("qty"),unit=item["unit"],item=item)
    cost = _int(p.get("unit_cents", 0), "precio unitario")
    _cap_line(quantity, cost)
    cur = db.execute("""INSERT INTO g_receipts(item_id,supplier,qty_m,unit_cents,created,actor) OUTPUT INSERTED.id
                        VALUES(?,?,?,?,?,?)""", (item["id"], supplier, quantity, cost, stamp(), user["name"]))
    return cur.lastrowid


def _receive(db, user, p):
    _require(user, "admin", "recepcion")
    r = _one(db, "SELECT * FROM g_receipts WHERE id=?", _int(p.get("id"), "recepción", 1))
    if r["approved_m"] is not None:
        raise ValueError("Esta recepción ya fue revisada.")
    if "version" in p and _int(p["version"],"versión",1)!=r["version"]:
        raise ValueError("La hoja de compra cambió. Actualiza la recepción antes de revisarla.")
    item = _item(db,r["item_id"])
    approved = inv.item_quantity(item["name"],p.get("approved"),"Cantidad aprobada",unit=item["unit"],item=item,
                                 minimum=0,previous=r["qty_m"])
    # En la interfaz anterior se conocía el total de la diferencia, sin su desglose.
    received = inv.item_quantity(item["name"],p["received"],"Cantidad entregada",unit=item["unit"],item=item,
                                 minimum=0,previous=r["qty_m"]) if "received" in p else None
    if received is not None and approved > received:
        raise ValueError("La cantidad aprobada supera la entregada por el proveedor.")
    if approved > r["qty_m"]:
        raise ValueError("La cantidad aprobada supera la cantidad prevista.")
    partial = approved < r["qty_m"] or (received is not None and received != approved)
    reason = _text(p.get("reason", ""), "motivo de inconformidad", 500, optional=not partial)
    lot_id = None
    if approved:
        lot_id = inv.receive(db,user,r["item_id"],approved,p.get("expiry") or None,
                             "Recepción aprobada", f"RC{r['id']:04d}")
    at = stamp()
    db.execute("""UPDATE g_receipts SET approved_m=?,received_m=?,reason=?,lot_id=?,reviewed_at=?,reviewer=?,
                  version=version+1 WHERE id=?""",
               (approved, received, reason, lot_id, at, user["name"], r["id"]))
    if partial:
        db.execute("INSERT INTO g_incidents(receipt_id,created) VALUES(?,?)", (r["id"], at))
    if r["line_id"]:
        purchase = _one(db, "SELECT purchase_id FROM g_lines WHERE id=?", r["line_id"])[0]
        _sync_purchase_receipt_state(db,purchase)
        _sync_purchase_expense(db,purchase,user["name"])
    return r["id"]


def _sync_purchase_receipt_state(db,purchase_id):
    db.execute("""UPDATE g_purchases SET version=version+1,status=CASE WHEN EXISTS (
                    SELECT 1 FROM g_receipts r JOIN g_lines l ON r.line_id=l.id
                    WHERE l.purchase_id=g_purchases.id AND r.approved_m IS NULL
                  ) THEN 'Enviada' ELSE 'Recibida' END WHERE id=?""",(purchase_id,))


def _resolve(db, user, p):
    _require(user, "admin","caja")
    issue = _one(db, "SELECT * FROM g_incidents WHERE id=?", _int(p.get("id"), "inconformidad", 1))
    if issue["closed"]:
        raise ValueError("La inconformidad ya está resuelta.")
    admit = _flag(p) if "approve" in p else True
    resolution = _text(p.get("resolution"), "motivo de la decisión", 500)
    at=stamp()
    receipt=_one(db,"SELECT * FROM g_receipts WHERE id=?",issue["receipt_id"])
    if not admit:
        remaining=receipt["qty_m"]-receipt["approved_m"]
        if remaining:
            db.execute("""INSERT INTO g_receipts(item_id,line_id,supplier,qty_m,unit_cents,created,actor)
                          VALUES(?,?,?,?,?,?,?)""",(receipt["item_id"],receipt["line_id"],receipt["supplier"],
                          remaining,receipt["unit_cents"],at,user["name"]))
    db.execute("UPDATE g_incidents SET decision=?,resolution=?,closed=?,closer=? WHERE id=?",
               (admit,resolution,at,user["name"],issue["id"]))
    if receipt["line_id"]:
        purchase=_one(db,"SELECT purchase_id FROM g_lines WHERE id=?",receipt["line_id"])[0]
        _sync_purchase_receipt_state(db,purchase)
        _sync_purchase_expense(db,purchase,user["name"])
    return issue["id"]


def _reserve_waste(db, waste_id, plan):
    for lot_id, amount, _ in plan:
        db.execute("UPDATE inv_lots SET reserved=reserved+? WHERE id=?", (amount,lot_id))
        db.execute("INSERT INTO g_waste_lots(waste_id,lot_id,amount) VALUES(?,?,?)", (waste_id,lot_id,amount))


def reserve_pending_wastes(db):
    pending=db.execute("SELECT id,item_id,qty_m,lot_id FROM g_wastes WHERE status='Pendiente' ORDER BY id").fetchall()
    for waste in pending:
        plan=inv._plan(db,waste["item_id"],waste["qty_m"],waste["lot_id"],allow_partial=True)
        _reserve_waste(db,waste["id"],plan)


def _waste(db, user, p):
    _require(user, "admin", "area", "recepcion")
    item = _item(db, p.get("item_id"))
    if not _waste_accessible(user, item["area"]):
        raise PermissionError("El insumo pertenece a otra área.")
    if p.get("lot_id") in (None,""):
        raise ValueError("Selecciona el lote afectado.")
    lot_id = _int(p["lot_id"], "lote", 1)
    amount=inv.item_quantity(item["name"],p.get("qty"),unit=item["unit"],item=item)
    source_id,quantity=inv.porciones.resolve(db,item["id"],amount)
    reason = _text(p.get("reason"), "motivo de la merma", 500)
    at = stamp()
    calendar_today = at[:10]
    try:
        occurred = date.fromisoformat(p.get("occurred_on",calendar_today)).isoformat()
    except (ValueError,TypeError):
        raise ValueError("Introduce una fecha válida para la merma.") from None
    if occurred > calendar_today and occurred != inv.business_day(db):
        raise ValueError("Selecciona hoy, una fecha anterior o la fecha de la jornada activa.")
    plan=inv._plan(db,source_id,quantity,lot_id)
    cur = db.execute("""INSERT INTO g_wastes(item_id,lot_id,qty_m,reason,created,actor,status,occurred_on) OUTPUT INSERTED.id
                        VALUES(?,?,?,?,?,?,'Pendiente',?)""", (source_id,lot_id,quantity,reason,at,user["name"],occurred))
    _reserve_waste(db,cur.lastrowid,plan)
    return cur.lastrowid


def _review_waste(db, user, p):
    _require(user, "admin")
    waste = _one(db,"SELECT * FROM g_wastes WHERE id=?", _int(p.get("id"), "merma", 1))
    if waste["status"] != "Pendiente":
        raise ValueError("La merma ya fue revisada.")
    approve = _flag(p)
    reserved=db.execute("SELECT lot_id,amount FROM g_waste_lots WHERE waste_id=?", (waste["id"],)).fetchall()
    reason="Merma: "+waste["reason"]
    ref=f"ME{waste['id']:04d}"
    remaining=waste["qty_m"]-sum(part["amount"] for part in reserved)
    if approve and remaining:
        inv.withdraw(db,user,waste["item_id"],remaining,reason,ref,waste["lot_id"])
    for part in reserved:
        lot_id,amount=part["lot_id"],part["amount"]
        db.execute("UPDATE inv_lots SET reserved=reserved-? WHERE id=?", (amount,lot_id))
        if approve:
            inv._move(db,user,lot_id,-amount,reason,ref)
    db.execute("DELETE FROM g_waste_lots WHERE waste_id=?", (waste["id"],))
    db.execute("UPDATE g_wastes SET status=?,reviewed_at=?,reviewer=? WHERE id=?",
               ("Aprobada" if approve else "Rechazada",stamp(),user["name"],waste["id"]))
    return waste["id"]


def _lines(db, rows, previous=None):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Incluye al menos un insumo en la compra.")
    checked, seen = [], set()
    previous = previous or {}
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("Comprueba los datos de cada línea.")
        item = _item(db,r.get("item_id"))
        item_id = item["id"]
        if item_id in seen:
            raise ValueError("Agrupa la cantidad del mismo insumo en una sola línea.")
        seen.add(item_id)
        quantity = inv.item_quantity(item["name"],r.get("qty"),unit=item["unit"],item=item,previous=previous.get(item_id))
        cost = _int(r.get("unit_cents"), "precio unitario")
        _cap_line(quantity, cost)
        checked.append((item_id, quantity, cost))
    return checked


def _put_lines(db, purchase_id, lines):
    db.executemany("INSERT INTO g_lines(purchase_id,item_id,qty_m,unit_cents) VALUES(?,?,?,?)",
                   ((purchase_id, *line) for line in lines))


def _assignee(db, value):
    if value in (None,"",0,"0"):
        return None
    return _one(db,"SELECT id FROM users WHERE id=? AND active=1",
                _int(value, "responsable", 1))[0]

def _purchase_day(purchase):
    return purchase["purchase_day"] or purchase["created"][:10]


def _require_current_lot(day):
    if day!=inv.today():
        raise ValueError("El lote solo se puede modificar o enviar durante su día, hasta las 00:00 (Lima).")


def _purchase(db, user, p):
    _require(user, "admin")
    lines = _lines(db,p.get("lines"))
    supplier = _text(p.get("supplier",""), "proveedor", 100, optional=True)
    delegate = _assignee(db,p.get("assignee_id"))
    created = stamp()
    origin = "Manual"
    if p.get("source_purchase_id"):
        source = _one(db,"SELECT * FROM g_purchases WHERE id=?",
                      _int(p["source_purchase_id"],"compra de origen",1))
        if source["status"] not in ("Enviada","Recibida"):
            raise ValueError("La hoja de origen debe estar cursada o recibida.")
        day = _purchase_day(source)
        origin = "Ampliación de " + inv.public("OC",source["id"])
    else:
        day = inv._date(p.get("purchase_day",created[:10]))
    _require_current_lot(day)
    cur = db.execute("""INSERT INTO g_purchases(origin,created,actor,supplier,assignee_id,status,purchase_day) OUTPUT INSERTED.id
                        VALUES(?,?,?,?,?,'Borrador',?)""",(origin,created,user["name"],supplier,delegate,day))
    _put_lines(db,cur.lastrowid,lines)
    return cur.lastrowid


def _check_purchase_version(purchase, payload):
    if "version" in payload and _int(payload["version"],"versión",1) != purchase["version"]:
        raise ValueError("La hoja de compra cambió desde que la abriste. Cierra el formulario, actualiza y revisa la cotización.")


def _edit_purchase(db, user, p):
    purchase = _one(db,"SELECT * FROM g_purchases WHERE id=?",_int(p.get("id"), "compra", 1))
    if user["role"] != "admin" and purchase["assignee_id"] != user["id"]:
        raise PermissionError("Solo administración o el responsable delegado puede editar la compra.")
    sent=purchase["status"] in ("Enviada","Recibida")
    if not sent and purchase["status"]!="Borrador":
        raise ValueError("Abre la hoja aprobada como borrador para corregirla.")
    _require_current_lot(_purchase_day(purchase))
    _check_purchase_version(purchase,p)
    supplier = _text(p.get("supplier",purchase["supplier"]),"proveedor",100,optional=True)
    delegate = purchase["assignee_id"]
    if "assignee_id" in p and user["role"] == "admin":
        delegate = _assignee(db,p["assignee_id"])
    if sent:
        _edit_sent_purchase(db,user,purchase,p,supplier)
    elif "lines" in p:
        previous = dict(db.execute("SELECT item_id,qty_m FROM g_lines WHERE purchase_id=?",(purchase["id"],)))
        lines = _lines(db,p["lines"],previous)
        if user["role"] != "admin":
            # La delegación permite cotizar la hoja asignada, no consultar otros insumos.
            if any(item_id not in previous for item_id,_,_ in lines):
                raise PermissionError("La delegación solo permite editar los insumos de la hoja asignada.")
        db.execute("DELETE FROM g_lines WHERE purchase_id=?",(purchase["id"],))
        _put_lines(db,purchase["id"],lines)
    db.execute("UPDATE g_purchases SET supplier=?,assignee_id=?,version=version+1 WHERE id=?",(supplier,delegate,purchase["id"]))
    return purchase["id"]


def _edit_sent_purchase(db,user,purchase,p,supplier):
    pid=purchase["id"]
    existing={r["item_id"]:r for r in db.execute("SELECT * FROM g_lines WHERE purchase_id=?",(pid,))}
    previous={item_id:r["qty_m"] for item_id,r in existing.items()}
    lines=_lines(db,p["lines"],previous) if "lines" in p else [
        (item_id,r["qty_m"],r["unit_cents"]) for item_id,r in existing.items()]
    if not supplier or any(not cost for _,_,cost in lines):
        raise ValueError("Indica el proveedor y cotiza todos los insumos de la lista enviada.")
    if user["role"]!="admin" and any(item_id not in existing for item_id,_,_ in lines):
        raise PermissionError("La delegación solo permite editar los insumos de la hoja asignada.")
    receipts=defaultdict(list)
    for receipt in db.execute("""SELECT r.*,i.decision FROM g_receipts r JOIN g_lines l ON l.id=r.line_id
          LEFT JOIN g_incidents i ON i.receipt_id=r.id WHERE l.purchase_id=? ORDER BY r.id""",(pid,)):
        receipts[receipt["item_id"]].append(receipt)
    proposed={item_id:(qty,cost) for item_id,qty,cost in lines}
    pending_lines=[]
    old_cost=new_cost=0
    for item_id in existing.keys()|proposed.keys():
        old=existing.get(item_id)
        qty,cost=proposed.get(item_id,(0,0))
        reviewed=[r for r in receipts[item_id] if r["approved_m"] is not None]
        pending=[r for r in receipts[item_id] if r["approved_m"] is None]
        fixed=sum(r["approved_m"] if r["decision"]==0 else r["qty_m"] for r in reviewed)
        if reviewed and (not qty or qty<fixed or cost!=old["unit_cents"] or supplier!=purchase["supplier"]):
            raise ValueError("Conserva los insumos ya revisados, su cantidad tramitada, su costo y su proveedor.")
        remaining=qty-fixed
        committed=sum(_amount(r["qty_m"],r["unit_cents"]) for r in pending)
        old_cost+=committed
        new_cost+=committed if old and (qty,cost)==(old["qty_m"],old["unit_cents"]) else _amount(remaining,cost)
        pending_lines.append((item_id,old,qty,cost,remaining,pending))
    if new_cost>old_cost and new_cost-old_cost>budget(db)["available_cents"]:
        raise ValueError("Saldo insuficiente para aumentar el importe pendiente de recepción.")
    at=stamp()
    for item_id,old,qty,cost,remaining,pending in pending_lines:
        if old and (qty,cost)==(old["qty_m"],old["unit_cents"]) and supplier==purchase["supplier"]:
            continue
        for r in pending:
            db.execute("DELETE FROM g_receipts WHERE id=?",(r["id"],))
        if not qty:
            db.execute("DELETE FROM g_lines WHERE id=?",(old["id"],))
            continue
        if old:
            line_id=old["id"]
            db.execute("UPDATE g_lines SET qty_m=?,unit_cents=? WHERE id=?",(qty,cost,line_id))
        else:
            line_id=db.execute("""INSERT INTO g_lines(purchase_id,item_id,qty_m,unit_cents) OUTPUT INSERTED.id
                                  VALUES(?,?,?,?)""",(pid,item_id,qty,cost)).lastrowid
        if remaining:
            db.execute("""INSERT INTO g_receipts(item_id,line_id,supplier,qty_m,unit_cents,created,actor)
                          VALUES(?,?,?,?,?,?,?)""",(item_id,line_id,supplier,remaining,cost,at,user["name"]))
    _sync_purchase_receipt_state(db,pid)
    _sync_purchase_expense(db,pid,user["name"])


def _decide(db, user, p):
    _require(user,"admin")
    purchase = _one(db,"SELECT * FROM g_purchases WHERE id=?",_int(p.get("id"),"compra",1))
    if purchase["status"] != "Borrador":
        raise ValueError("La compra ya fue evaluada.")
    _require_current_lot(_purchase_day(purchase))
    _check_purchase_version(purchase,p)
    approve = _flag(p)
    if approve:
        _check_purchase_funds(db,_quoted_purchase(db,purchase))
    db.execute("UPDATE g_purchases SET status=?,reviewed_at=?,reviewer=?,version=version+1 WHERE id=?",
               ("Aprobada" if approve else "Rechazada",stamp(),user["name"],purchase["id"]))
    return purchase["id"]


def _reopen_purchase(db, user, p):
    _require(user,"admin")
    purchase = _one(db,"SELECT * FROM g_purchases WHERE id=?",_int(p.get("id"),"compra",1))
    if purchase["status"] != "Aprobada":
        raise ValueError("Solo se puede revisar una compra aprobada que todavía no se ha cursado.")
    _require_current_lot(_purchase_day(purchase))
    _check_purchase_version(purchase,p)
    db.execute("""UPDATE g_purchases SET status='Borrador',version=version+1,
                  reviewed_at=NULL,reviewer=NULL WHERE id=?""",(purchase["id"],))
    return purchase["id"]


def _dispatch(db, user, p):
    _require(user,"admin")
    purchase = _one(db,"SELECT * FROM g_purchases WHERE id=?",_int(p.get("id"),"compra",1))
    if purchase["status"] != "Aprobada":
        raise ValueError("Solo se puede cursar una compra aprobada y pendiente de envío.")
    _check_purchase_version(purchase,p)
    _require_current_lot(_purchase_day(purchase))
    _dispatch_purchase(db,user,purchase)
    return purchase["id"]


def _quoted_purchase(db,purchase):
    lines = list(db.execute("SELECT * FROM g_lines WHERE purchase_id=?",(purchase["id"],)))
    if not purchase["supplier"] or not lines or any(not r["unit_cents"] for r in lines):
        raise ValueError(f"Completa el proveedor y la cotización en {inv.public('OC',purchase['id'])}.")
    return lines


def _check_purchase_funds(db,lines):
    cost = sum(_amount(r["qty_m"],r["unit_cents"]) for r in lines)
    if cost > budget(db)["available_cents"]:
        raise ValueError("Saldo insuficiente para esta compra. Revisa el presupuesto disponible.")


def _dispatch_purchase(db,user,purchase):
    lines=_quoted_purchase(db,purchase)
    _check_purchase_funds(db,lines)
    at = stamp()
    db.executemany("""INSERT INTO g_receipts(item_id,line_id,supplier,qty_m,unit_cents,created,actor)
                      VALUES(?,?,?,?,?,?,?)""",
                   ((r["item_id"],r["id"],purchase["supplier"],r["qty_m"],r["unit_cents"],at,user["name"]) for r in lines))
    db.execute("""UPDATE g_purchases SET status='Enviada',sent_at=?,sender=?,version=version+1,
                  reviewed_at=COALESCE(reviewed_at,?),reviewer=COALESCE(reviewer,?) WHERE id=?""",
               (at,user["name"],at,user["name"],purchase["id"]))
    _sync_purchase_expense(db,purchase["id"],user["name"],day=inv.business_day(db))


def _send_purchase_list(db,user,p):
    _require(user,"admin")
    day=inv._date(p.get("day"))
    _require_current_lot(day)
    expected=p.get("orders")
    if not isinstance(expected,list) or not expected or any(not isinstance(r,dict) for r in expected):
        raise ValueError("Selecciona un lote con hojas de compra pendientes de envío.")
    versions={_int(r.get("id"),"compra",1):_int(r.get("version"),"versión",1) for r in expected}
    purchases=list(db.execute("""SELECT * FROM g_purchases
                WHERE COALESCE(purchase_day,LEFT(created,10))=? AND status IN ('Borrador','Aprobada') ORDER BY id""",(day,)))
    if versions!={r["id"]:r["version"] for r in purchases}:
        raise ValueError("La lista del día cambió. Actualiza antes de enviarla.")
    for purchase in purchases:
        _dispatch_purchase(db,user,purchase)
    return {"day":day,"sent":len(purchases)}


def _configure(db, user, p, *, funds):
    _require(user,"admin")
    if funds:
        opening = _int(p.get("opening_cents"),"fondo inicial")
        db.execute("UPDATE g_settings SET opening_cents=? WHERE id=1",(opening,))
    else:
        time = p.get("time")
        if not isinstance(time,str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]",time):
            raise ValueError("Introduce la hora en el formato de 24 horas HH:MM.")
        db.execute("UPDATE g_settings SET run_time=? WHERE id=1",(time,))
    return 1


def _report(db, actor, scheduled, stocks=None, at=None):
    created = at or stamp()
    day = created[:10]
    if scheduled:
        previous = db.execute("SELECT id FROM g_reports WHERE day=? AND scheduled=1",(day,)).fetchone()
        if previous:
            return previous[0]
    stocks = inv.stock(db) if stocks is None else stocks
    shortages, lines = [], []
    for item in stocks:
        minimum = round(item["min_qty"]*1000)
        available = round(item["available"]*1000)
        if available > minimum:
            continue
        # Restablecer un objetivo de dos mínimos; en un mínimo cero proponemos una unidad.
        suggested = max(1000 if minimum == 0 else 1, minimum*2-available)
        _, size = inv.quantity_measure(item)
        potato_step = inv.potato_quantity_step(item["name"],item["unit"])
        if potato_step:
            size = lcm(size or 1,potato_step)
        if not size and not inv.allows_decimal(item["name"]) and item["unit"].strip().casefold() not in inv.SMALL_STOCK_UNITS:
            size = 1000
        if size:
            suggested = ((suggested+size-1)//size)*size
        shortages.append((item["id"],available,minimum,suggested))
        lines.append((item["id"],suggested,_price(db,item["id"])))
    purchase_id = None
    if lines:
        purchase_id = db.execute("""INSERT INTO g_purchases(origin,created,actor,supplier,status,purchase_day) OUTPUT INSERTED.id
                                    VALUES('Faltantes',?,?,'','Borrador',?)""",(created,actor,day)).lastrowid
        _put_lines(db,purchase_id,lines)
    report_id = db.execute("INSERT INTO g_reports(day,created,scheduled,purchase_id) OUTPUT INSERTED.id VALUES(?,?,?,?)",
                           (day,created,int(scheduled),purchase_id)).lastrowid
    db.executemany("INSERT INTO g_shortage VALUES(?,?,?,?,?)",((report_id,*s) for s in shortages))
    return report_id


def _configure_alerts(db, user, payload):
    _require(user, "admin")
    item = inv._item(db, payload.get("item_id"))
    minimum = inv.item_quantity(item["name"],payload.get("min_qty"),"Cantidad mínima crítica",unit=item["unit"],item=item,
                                minimum=0,previous=item["min_qty"])

    if "warn_days" in payload:
        source_id, _ = inv.porciones.resolve(db, item["id"], 0)
        source = item if source_id == item["id"] else inv._item(db, source_id)
        if not source["perishable"]:
            raise ValueError("Selecciona un insumo que requiera vencimiento para configurar el aviso.")
        days = inv._scaled(payload["warn_days"], 1, "Días de aviso", 0, 3650)
        db.execute("""UPDATE inv_items SET warn_days=? WHERE id=? OR id IN
                      (SELECT item_id FROM inv_stock_equivalents WHERE base_id=?)""",
                   (days, source_id, source_id))

    db.execute("UPDATE inv_items SET min_qty=? WHERE id=?", (minimum, item["id"]))
    return item["id"]


def _alerts(db, stocks):
    now = date.fromisoformat(inv.today())
    by_id = {i["id"]:i for i in stocks}
    active = {}
    for i in stocks:
        if i["available"] <= i["min_qty"]:
            unit,size=inv.quantity_measure(i)
            if not unit and not inv.allows_decimal(i["name"]):
                unit=inv.SMALL_STOCK_UNITS.get(i["unit"].strip().casefold())
                size=1
            available=str(round(i["available"]*1000)//size) if unit else f"{i['available']:g}"
            active[f"min.{i['id']}"] = ("Stock mínimo",i["id"],
                f"{i['name']} alcanzó el mínimo. Disponible al activar la alerta: {available} {unit or i['unit']}.")
    for lot in inv.batches(db):
        if lot["physical"] <= 0 or not lot["expiry"]:
            continue
        i = by_id[lot["item_id"]]
        days = (date.fromisoformat(lot["expiry"]) - now).days
        if i["perishable"] and 0 <= days <= i["warn_days"]:
            active[f"vence.{lot['id']}"] = ("Próximo a vencer", i["id"],
                f"{i['name']}: el lote LT{lot['id']:04d} vence el {lot['expiry']}.")
    existing = {r["event_key"]:r["id"] for r in db.execute("SELECT id,event_key FROM g_alerts WHERE closed IS NULL")}
    at = stamp()
    db.executemany("UPDATE g_alerts SET closed=? WHERE id=?",
                   ((at,existing[k]) for k in existing.keys()-active.keys()))
    db.executemany("INSERT INTO g_alerts(event_key,kind,item_id,message,created) VALUES(?,?,?,?,?)",
                   ((k,*active[k],at) for k in active.keys()-existing.keys()))


def tick(db):
    inv.expire(db)
    stocks = inv.stock(db)
    _alerts(db,stocks)
    run_time = _one(db,"SELECT run_time FROM g_settings WHERE id=1")[0]
    at = stamp()
    if at[11:16] >= run_time:
        _report(db,"Sistema",True,stocks,at)


def _next_cash_expense_number(db,day):
    return db.execute("SELECT COALESCE(MAX(receipt_no),0)+1 FROM cash_expenses WHERE day=?",(day,)).fetchone()[0]


def _insert_cash_expense(db,day,kind,reference,concept,amount,actor,*,purchase_id=None):
    number=_next_cash_expense_number(db,day)
    receipt=db.execute("""INSERT INTO cash_expenses(day,receipt_no,kind,reference,concept,cents,actor,purchase_id)
                         OUTPUT INSERTED.id VALUES(?,?,?,?,?,?,?,?)""",
                       (day,number,kind,reference,concept,amount,actor,purchase_id)).lastrowid
    return {"id":receipt,"code":inv.public("BL",number)}


def _sync_purchase_expense(db,purchase_id,actor,*,day=None,reconcile=False):
    linked=db.execute("SELECT id,cents,void_at FROM cash_expenses WHERE purchase_id=?",(purchase_id,)).fetchone()
    receipts=db.execute("""SELECT r.qty_m,r.approved_m,r.unit_cents,r.line_id,
                           CASE WHEN i.id IS NOT NULL AND i.closed IS NULL THEN 1 ELSE 0 END AS pending_issue
                           FROM g_receipts r JOIN g_lines l ON l.id=r.line_id
                           LEFT JOIN g_incidents i ON i.receipt_id=r.id WHERE l.purchase_id=?""",(purchase_id,))
    amount=sum(sum(_receipt_cost(r)) for r in receipts)
    if linked:
        if not amount and not linked["void_at"]:
            db.execute("""UPDATE cash_expenses SET void_at=?,void_reason=?,void_by=? WHERE id=?""",
                       (inv.now(),"Compra sin importe recibido ni pendiente",actor,linked["id"]))
        elif amount and (linked["cents"]!=amount or linked["void_at"]):
            db.execute("""UPDATE cash_expenses SET cents=?,void_at=NULL,void_reason=NULL,void_by=NULL WHERE id=?""",
                       (amount,linked["id"]))
    elif amount:
        if day is None:
            purchase=_one(db,"SELECT sent_at FROM g_purchases WHERE id=?",purchase_id)
            day=purchase["sent_at"][:10]
        code=inv.public("OC",purchase_id)
        if reconcile:
            manual=db.execute("""UPDATE cash_expenses SET purchase_id=?
                                 WHERE purchase_id IS NULL AND day=? AND kind='Mercado'
                                   AND reference=? AND cents=? AND void_at IS NULL""",
                              (purchase_id,day,code,amount))
            if manual.rowcount:
                return
        _insert_cash_expense(db,day,"Mercado","","Compra enviada · "+code,amount,actor,purchase_id=purchase_id)


def register_existing_purchase_expenses(db):
    for r in db.execute("""SELECT id,sent_at,COALESCE(sender,actor) AS actor FROM g_purchases
                           WHERE sent_at IS NOT NULL AND status IN ('Enviada','Recibida') ORDER BY sent_at,id"""):
        _sync_purchase_expense(db,r["id"],r["actor"],day=r["sent_at"][:10],reconcile=True)


def _record_cash_expense(db,user,payload,day):
    kind=payload.get("kind")
    if kind not in ("Personal","Mercado"):
        raise ValueError("Tipo de gasto inválido.")
    reference=_text(payload.get("reference",""),"referencia externa",100,optional=True)
    if reference and db.execute("SELECT id FROM cash_expenses WHERE day=? AND kind=? AND reference=? AND void_at IS NULL",
                                (day,kind,reference)).fetchone():
        raise ValueError("La referencia ya está registrada para esta jornada.")
    concept=inv._text(payload.get("concept"),"concepto",300)
    amount=inv._scaled(payload.get("amount"),100,"Importe")
    return _insert_cash_expense(db,day,kind,reference,concept,amount,user["name"])


def act(db, user, action, payload):
    if action=="gestion.send_purchase_list":
        return _send_purchase_list(db,user,payload)
    handlers = {
        "gestion.configure_alerts":_configure_alerts,
        "gestion.receipt":_receipt, "gestion.receive":_receive, "gestion.resolve":_resolve,
        "gestion.waste":_waste, "gestion.review_waste":_review_waste,
        "gestion.purchase":_purchase, "gestion.edit_purchase":_edit_purchase,
        "gestion.decide":_decide, "gestion.reopen":_reopen_purchase, "gestion.dispatch":_dispatch,
    }
    if action in handlers:
        result = handlers[action](db,user,payload)
    elif action=="gestion.cash_day":
        inv._role(user,"admin","caja")
        day=date.fromisoformat(payload["day"]).isoformat() if payload.get("day") else None
        previous=inv.business_day(db)
        if payload.get("expected_day",previous)!=previous:
            raise ValueError("La jornada cambió en otro equipo. Actualiza antes de abrir otra fecha.")
        active=day or inv.today()
        if previous!=active:
            db.execute("IF NOT EXISTS(SELECT 1 FROM cash_days WHERE day=?) INSERT cash_days(day) VALUES(?)",(previous,previous))
        db.execute("""IF NOT EXISTS(SELECT 1 FROM cash_days WHERE day=?)
                      INSERT cash_days(day,opened_at,opened_by) VALUES(?,?,?)""",(active,active,inv.now(),user["name"]))
        db.execute("UPDATE g_settings SET work_day=? WHERE id=1",(day,))
        return {"day":active}
    elif action in {"gestion.cash_expense","gestion.void_expense"}:
        inv._role(user,"admin","caja")
        day=inv.business_day(db)
        if payload.get("day")!=day:
            raise ValueError("La jornada cambió. Actualiza Caja antes de continuar.")
        if action=="gestion.void_expense":
            reason=inv._text(payload.get("reason"),"motivo",300)
            if not db.execute("""UPDATE cash_expenses SET void_reason=?,void_by=?,void_at=?
                                  WHERE id=? AND day=? AND void_at IS NULL AND purchase_id IS NULL""",
                              (reason,user["name"],inv.now(),inv._id(payload.get("id")),day)).rowcount:
                raise ValueError("El gasto no se puede anular aquí. Los gastos de compra se ajustan en Compras y Recepción.")
            return {}
        return _record_cash_expense(db,user,payload,day)
    elif action in {"gestion.fund","gestion.schedule"}:
        result = _configure(db,user,payload,funds=action=="gestion.fund")
    elif action == "gestion.report":
        _require(user,"admin")
        result = _report(db,user["name"],False)
    else:
        raise ValueError("Operación de gestión desconocida.")
    prefixes = {"receipt":"RC","receive":"RC","resolve":"INC","waste":"ME",
                "review_waste":"ME","purchase":"OC","edit_purchase":"OC","decide":"OC",
                "reopen":"OC","dispatch":"OC","report":"INF"}
    prefix = prefixes.get(action.split(".")[-1])
    return {"id":result, "code":f"{prefix}{result:04d}"} if prefix else {"id":result}


def _with_code(row, prefix):
    return dict(row, code=f"{prefix}{row['id']:04d}")


def state(db, user):
    admin = user["role"] == "admin"
    receiving = user["role"] in {"admin","recepcion","caja"}
    result = {"receipts":[], "wastes":[], "incidents":[], "alerts":[], "purchases":[],
              "reports":[], "budget":None, "schedule":None}
    if user["role"] in ("admin","caja"):
        active_day=inv.business_day(db)
        result["registered_days"]=[dict(r) for r in db.execute("""WITH days(day) AS (
            SELECT day FROM cash_days UNION SELECT day FROM inv_orders UNION SELECT day FROM cash_expenses
            UNION SELECT COALESCE(s.cash_day,LEFT(o.paid_at,10)) FROM inv_sales s JOIN inv_orders o ON o.id=s.order_id
            UNION SELECT COALESCE(cash_day,LEFT(at,10)) FROM inv_returns UNION SELECT cash_day FROM sale_voids UNION SELECT cash_day FROM refund_reversals UNION SELECT CAST(? AS nvarchar(10)))
            SELECT days.day,d.opened_at,d.opened_by FROM days LEFT JOIN cash_days d ON days.day=d.day
            WHERE days.day IS NOT NULL ORDER BY days.day DESC""",(active_day,))]
        result["cash_expenses"]=[dict(r,code=inv.public("BL",r["receipt_no"])) for r in
                                 db.execute("SELECT * FROM cash_expenses ORDER BY day DESC,receipt_no DESC")]
        result["next_cash_expense_code"]=inv.public("BL",_next_cash_expense_number(db,active_day))
    if receiving:
        for r in db.execute("""SELECT r.id,r.item_id,i.code item_code,i.name item_name,i.unit,i.display_unit,i.display_unit_milli,i.area,i.perishable,r.supplier,r.qty_m,
                r.approved_m,r.received_m,r.reason,r.created,r.actor,r.reviewed_at,r.reviewer,r.unit_cents,r.version,
                r.lot_id,l.expiry,k.purchase_id,COALESCE(p.purchase_day,LEFT(p.created,10)) purchase_day
                FROM g_receipts r JOIN inv_items i ON i.id=r.item_id
                LEFT JOIN g_lines k ON k.id=r.line_id LEFT JOIN inv_lots l ON l.id=r.lot_id
                LEFT JOIN g_purchases p ON p.id=k.purchase_id
                ORDER BY CASE WHEN r.approved_m IS NULL THEN 0 ELSE 1 END,r.id DESC"""):
            receipt = _with_code(r, "RC")
            expected, accepted = receipt.pop("qty_m"),receipt.pop("approved_m")
            received = receipt.pop("received_m")
            receipt["qty"] = inv.num(expected)
            receipt["approved"] = None if accepted is None else inv.num(accepted)
            receipt["received"] = None if received is None else inv.num(received)
            receipt["status"] = ("Pendiente" if accepted is None else "No entregada" if received == 0 else "Rechazada" if accepted == 0
                                 else "Aprobada" if accepted == expected and received in (None,expected) else "Parcial")
            if not admin:
                receipt.pop("unit_cents")
            result["receipts"].append(receipt)
        for r in db.execute("""SELECT p.id,p.receipt_id,r.item_id,k.purchase_id,COALESCE(c.purchase_day,LEFT(c.created,10)) purchase_day,
                i.name item_name,i.unit,i.display_unit,i.display_unit_milli,r.supplier,
                r.qty_m,r.received_m,r.approved_m,r.reason,p.created,r.reviewer AS actor,
                p.resolution,p.closed,p.closer,p.decision FROM g_incidents p JOIN g_receipts r ON r.id=p.receipt_id
                JOIN inv_items i ON i.id=r.item_id LEFT JOIN g_lines k ON k.id=r.line_id
                LEFT JOIN g_purchases c ON c.id=k.purchase_id
                ORDER BY CASE WHEN p.closed IS NULL THEN 0 ELSE 1 END,p.id DESC"""):
            issue = _with_code(r,"INC")
            expected,received,approved = issue.pop("qty_m"),issue.pop("received_m"),issue.pop("approved_m")
            issue["missing"] = None if received is None else inv.num(max(0,expected-received))
            issue["rejected"] = None if received is None else inv.num(received-approved)
            issue["kind"] = "Rechazo" if (received or 0) > approved or (received is None and approved == 0) else "Faltante"
            issue["qty"] = inv.num(max(expected,received or 0)-approved)
            issue["status"] = ("Admitida" if issue["decision"] else "Denegada" if issue["decision"]==0
                               else "Resuelta" if issue["closed"] else "Pendiente")
            result["incidents"].append(issue)
    if user["role"] in {"admin","recepcion","area"}:
        for r in db.execute("""SELECT w.*,i.name item_name,i.unit,i.display_unit,i.display_unit_milli,i.area FROM g_wastes w
                  JOIN inv_items i ON i.id=w.item_id ORDER BY CASE WHEN w.status='Pendiente' THEN 0 ELSE 1 END,w.id DESC"""):
            if _waste_accessible(user,r["area"]):
                waste = _with_code(r,"ME")
                waste["qty"] = inv.num(waste.pop("qty_m"))
                result["wastes"].append(waste)
    for r in db.execute("""SELECT a.id,a.kind,a.item_id,i.name item_name,i.area,a.message,a.created,a.closed
            FROM g_alerts a JOIN inv_items i ON i.id=a.item_id ORDER BY CASE WHEN a.closed IS NULL THEN 0 ELSE 1 END,a.id DESC"""):
        if _accessible(user,r["area"]):
            result["alerts"].append(_with_code(r,"AL"))
    query = """SELECT p.*,u.name assignee FROM g_purchases p LEFT JOIN users u ON p.assignee_id=u.id"""
    args = ()
    if not admin:
        query += " WHERE p.assignee_id=?"
        args = (user["id"],)
    purchases = {}
    for r in db.execute(query+" ORDER BY p.id DESC",args):
        purchase = _with_code(r,"OC")
        purchase["purchase_day"] = purchase["purchase_day"] or purchase["created"][:10]
        purchase.update(lines=[], total_cents=0)
        purchases[r["id"]] = purchase
    if purchases:
        line_query = """SELECT l.purchase_id,l.item_id,i.name item_name,i.unit,i.display_unit,i.display_unit_milli,l.qty_m,l.unit_cents
                        FROM g_lines l JOIN inv_items i ON i.id=l.item_id"""
        if not admin:
            line_query += " JOIN g_purchases p ON p.id=l.purchase_id WHERE p.assignee_id=?"
        for r in db.execute(line_query+" ORDER BY l.id",args):
            purchase = purchases[r["purchase_id"]]
            line = dict(r)
            line["qty"] = inv.num(line.pop("qty_m"))
            line["total_cents"] = _amount(r["qty_m"],r["unit_cents"])
            purchase["lines"].append(line)
            purchase["total_cents"] += line["total_cents"]
    result["purchases"] = list(purchases.values())
    if admin:
        result["budget"] = budget(db)
        result["schedule"] = _one(db,"SELECT run_time FROM g_settings WHERE id=1")[0]
        reports = {r["id"]:dict(_with_code(r,"INF"),count=0,lines=[]) for r in db.execute(
            "SELECT id,day,created,scheduled,purchase_id FROM g_reports ORDER BY id DESC")}
        for r in db.execute("""SELECT s.*,i.name item_name,i.unit,i.display_unit,i.display_unit_milli FROM g_shortage s
                               JOIN inv_items i ON i.id=s.item_id ORDER BY i.name"""):
            report = reports[r["report_id"]]
            report["lines"].append({"item_id":r["item_id"],"item_name":r["item_name"],"unit":r["unit"],
                                    "display_unit":r["display_unit"], "display_unit_milli":r["display_unit_milli"],
                                    "available":inv.num(r["available_m"]),"minimum":inv.num(r["minimum_m"]),
                                    "suggested":inv.num(r["suggested_m"])})
            report["count"] += 1
        result["reports"] = list(reports.values())
    return result
