"""Compras, recepciones, alertas y supervisión del inventario de Juniors.

El servidor abre una transacción de escritura por acción o ciclo de mantenimiento.
Las cantidades se almacenan en milésimas y los importes en céntimos de sol.
"""

from datetime import date, datetime, timedelta, timezone
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
        assigned = user.get("area") or ("Atención" if user["role"]=="atencion" else "")
        return assigned.casefold() == area.casefold()
    return True


def _waste_accessible(user, area):
    if user["role"] == "recepcion":
        return (user.get("area") or "Limpieza").casefold() == area.casefold()
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


def budget(db):
    opening = _one(db, "SELECT opening_cents FROM g_settings WHERE id=1")[0]
    sales = inv.net_sales(db)
    spent = committed = issued = 0
    for r in db.execute("""SELECT r.qty_m,r.approved_m,r.unit_cents,r.line_id,l.physical
                           FROM g_receipts r LEFT JOIN inv_lots l ON r.lot_id=l.id"""):
        if r["approved_m"] is not None:
            spent += _amount(r["approved_m"], r["unit_cents"])
            if r["physical"] is not None:
                # Redondear el consumo neto de cada lote una sola vez, incluidas sus devoluciones.
                issued += _amount(r["approved_m"]-r["physical"],r["unit_cents"])
        elif r["line_id"] is not None:
            committed += _amount(r["qty_m"], r["unit_cents"])
    return dict(opening_cents=opening, sales_cents=sales, spent_cents=spent,
                committed_cents=committed, available_cents=opening+sales-spent-committed,
                issues_cents=issued)


def _receipt(db, user, p):
    _require(user, "admin", "recepcion")
    item_id = _item(db, p.get("item_id"))["id"]
    supplier = _text(p.get("supplier"), "proveedor", 100)
    quantity = inv.qty(p.get("qty"))
    cost = _int(p.get("unit_cents", 0), "precio unitario")
    _cap_line(quantity, cost)
    cur = db.execute("""INSERT INTO g_receipts(item_id,supplier,qty_m,unit_cents,created,actor) OUTPUT INSERTED.id
                        VALUES(?,?,?,?,?,?)""", (item_id, supplier, quantity, cost, stamp(), user["name"]))
    return cur.lastrowid


def _nonnegative_qty(value):
    return 0 if re.fullmatch(r"0+(?:[.,]0{1,3})?",str(value)) else inv.qty(value)


def _receive(db, user, p):
    _require(user, "admin", "recepcion")
    r = _one(db, "SELECT * FROM g_receipts WHERE id=?", _int(p.get("id"), "recepción", 1))
    if r["approved_m"] is not None:
        raise ValueError("Esta recepción ya fue revisada.")
    approved = _nonnegative_qty(p.get("approved"))
    # En la interfaz anterior se conocía el total de la diferencia, sin su desglose.
    received = _nonnegative_qty(p["received"]) if "received" in p else None
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
    db.execute("""UPDATE g_receipts SET approved_m=?,received_m=?,reason=?,lot_id=?,reviewed_at=?,reviewer=? WHERE id=?""",
               (approved, received, reason, lot_id, at, user["name"], r["id"]))
    if partial:
        db.execute("INSERT INTO g_incidents(receipt_id,created) VALUES(?,?)", (r["id"], at))
    if r["line_id"]:
        purchase = _one(db, "SELECT purchase_id FROM g_lines WHERE id=?", r["line_id"])[0]
        pending = db.execute("""SELECT 1 FROM g_receipts r JOIN g_lines l ON r.line_id=l.id
                               WHERE l.purchase_id=? AND r.approved_m IS NULL""", (purchase,)).fetchone()
        if not pending:
            db.execute("UPDATE g_purchases SET status='Recibida' WHERE id=?", (purchase,))
    return r["id"]


def _resolve(db, user, p):
    _require(user, "admin")
    issue = _one(db, "SELECT * FROM g_incidents WHERE id=?", _int(p.get("id"), "inconformidad", 1))
    if issue["closed"]:
        raise ValueError("La inconformidad ya está resuelta.")
    resolution = _text(p.get("resolution"), "gestión con el proveedor", 500)
    db.execute("UPDATE g_incidents SET resolution=?,closed=?,closer=? WHERE id=?",
               (resolution, stamp(), user["name"], issue["id"]))
    return issue["id"]


def _waste(db, user, p):
    _require(user, "admin", "area", "recepcion")
    item = _item(db, p.get("item_id"))
    if not _waste_accessible(user, item["area"]):
        raise PermissionError("El insumo pertenece a otra área.")
    source_id,quantity=inv.porciones.resolve(db,item["id"],inv.qty(p.get("qty")))
    item=_item(db,source_id)
    lot_id = p.get("lot_id")
    if lot_id not in (None,""):
        lot_id = _int(lot_id, "lote", 1)
        physical = _one(db,"SELECT physical FROM inv_lots WHERE id=? AND item_id=?",lot_id,item["id"])[0]
    else:
        lot_id = None
        physical = _one(db,"SELECT coalesce(sum(physical),0) FROM inv_lots WHERE item_id=?",item["id"])[0]
    if quantity > physical:
        raise ValueError("La cantidad reportada supera las existencias físicas.")
    reason = _text(p.get("reason"), "motivo de la merma", 500)
    at = stamp()
    try:
        occurred = date.fromisoformat(p.get("occurred_on",at[:10])).isoformat()
    except (ValueError,TypeError):
        raise ValueError("Introduce una fecha válida para la merma.") from None
    if occurred > at[:10]:
        raise ValueError("La fecha de la merma no puede ser posterior a hoy.")
    cur = db.execute("""INSERT INTO g_wastes(item_id,lot_id,qty_m,reason,created,actor,status,occurred_on) OUTPUT INSERTED.id
                        VALUES(?,?,?,?,?,?,'Pendiente',?)""", (item["id"],lot_id,quantity,reason,at,user["name"],occurred))
    return cur.lastrowid


def _review_waste(db, user, p):
    _require(user, "admin")
    waste = _one(db,"SELECT * FROM g_wastes WHERE id=?", _int(p.get("id"), "merma", 1))
    if waste["status"] != "Pendiente":
        raise ValueError("La merma ya fue revisada.")
    approve = _flag(p)
    if approve:
        if waste["lot_id"]:
            lot = _one(db,"SELECT physical,reserved FROM inv_lots WHERE id=?",waste["lot_id"])
            if lot["physical"]>=waste["qty_m"] and lot["physical"]-lot["reserved"]<waste["qty_m"]:
                raise ValueError("Parte del lote está reservada. Revisa las comandas afectadas y libera la cantidad necesaria antes de aprobar la merma.")
        inv.withdraw(db,user,waste["item_id"],waste["qty_m"],"Merma: "+waste["reason"],
                     f"ME{waste['id']:04d}",waste["lot_id"])
    db.execute("UPDATE g_wastes SET status=?,reviewed_at=?,reviewer=? WHERE id=?",
               ("Aprobada" if approve else "Rechazada",stamp(),user["name"],waste["id"]))
    return waste["id"]


def _lines(db, rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Incluye al menos un insumo en la compra.")
    checked, seen = [], set()
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("Comprueba los datos de cada línea.")
        item_id = _item(db,r.get("item_id"))["id"]
        if item_id in seen:
            raise ValueError("Agrupa la cantidad del mismo insumo en una sola línea.")
        seen.add(item_id)
        quantity = inv.qty(r.get("qty"))
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


def _purchase(db, user, p):
    _require(user, "admin")
    lines = _lines(db,p.get("lines"))
    supplier = _text(p.get("supplier",""), "proveedor", 100, optional=True)
    delegate = _assignee(db,p.get("assignee_id"))
    cur = db.execute("""INSERT INTO g_purchases(origin,created,actor,supplier,assignee_id,status) OUTPUT INSERTED.id
                        VALUES('Manual',?,?,?,?,'Borrador')""",(stamp(),user["name"],supplier,delegate))
    _put_lines(db,cur.lastrowid,lines)
    return cur.lastrowid


def _check_purchase_version(purchase, payload):
    if "version" in payload and _int(payload["version"],"versión",1) != purchase["version"]:
        raise ValueError("La hoja de compra cambió desde que la abriste. Cierra el formulario, actualiza y revisa la cotización.")


def _edit_purchase(db, user, p):
    purchase = _one(db,"SELECT * FROM g_purchases WHERE id=?",_int(p.get("id"), "compra", 1))
    if user["role"] != "admin" and purchase["assignee_id"] != user["id"]:
        raise PermissionError("Solo administración o el responsable delegado puede editar la compra.")
    if purchase["status"] != "Borrador":
        raise ValueError("Solo se pueden modificar compras en borrador.")
    _check_purchase_version(purchase,p)
    supplier = _text(p.get("supplier",purchase["supplier"]),"proveedor",100,optional=True)
    delegate = purchase["assignee_id"]
    if "assignee_id" in p and user["role"] == "admin":
        delegate = _assignee(db,p["assignee_id"])
    if "lines" in p:
        lines = _lines(db,p["lines"])
        if user["role"] != "admin":
            # La delegación permite cotizar la hoja asignada, no consultar otros insumos.
            permitted = {r[0] for r in db.execute("SELECT item_id FROM g_lines WHERE purchase_id=?",(purchase["id"],))}
            if any(item_id not in permitted for item_id,_,_ in lines):
                raise PermissionError("La delegación solo permite editar los insumos de la hoja asignada.")
        db.execute("DELETE FROM g_lines WHERE purchase_id=?",(purchase["id"],))
        _put_lines(db,purchase["id"],lines)
    db.execute("UPDATE g_purchases SET supplier=?,assignee_id=?,version=version+1 WHERE id=?",(supplier,delegate,purchase["id"]))
    return purchase["id"]


def _decide(db, user, p):
    _require(user,"admin")
    purchase = _one(db,"SELECT * FROM g_purchases WHERE id=?",_int(p.get("id"),"compra",1))
    if purchase["status"] != "Borrador":
        raise ValueError("La compra ya fue evaluada.")
    _check_purchase_version(purchase,p)
    approve = _flag(p)
    if approve:
        if not purchase["supplier"]:
            raise ValueError("Indica el proveedor antes de aprobar la compra.")
        if db.execute("SELECT 1 FROM g_lines WHERE purchase_id=? AND unit_cents=0",(purchase["id"],)).fetchone():
            raise ValueError("Completa la cotización de todos los insumos antes de aprobar.")
    db.execute("UPDATE g_purchases SET status=?,reviewed_at=?,reviewer=? WHERE id=?",
               ("Aprobada" if approve else "Rechazada",stamp(),user["name"],purchase["id"]))
    return purchase["id"]


def _reopen_purchase(db, user, p):
    _require(user,"admin")
    purchase = _one(db,"SELECT * FROM g_purchases WHERE id=?",_int(p.get("id"),"compra",1))
    if purchase["status"] != "Aprobada":
        raise ValueError("Solo se puede revisar una compra aprobada que todavía no se ha cursado.")
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
    lines = list(db.execute("SELECT * FROM g_lines WHERE purchase_id=?",(purchase["id"],)))
    cost = sum(_amount(r["qty_m"],r["unit_cents"]) for r in lines)
    if cost > budget(db)["available_cents"]:
        raise ValueError("Saldo insuficiente para cursar esta compra. Revisa el presupuesto disponible.")
    at = stamp()
    db.executemany("""INSERT INTO g_receipts(item_id,line_id,supplier,qty_m,unit_cents,created,actor)
                      VALUES(?,?,?,?,?,?,?)""",
                   ((r["item_id"],r["id"],purchase["supplier"],r["qty_m"],r["unit_cents"],at,user["name"]) for r in lines))
    db.execute("UPDATE g_purchases SET status='Enviada',sent_at=?,sender=? WHERE id=?",
               (at,user["name"],purchase["id"]))
    return purchase["id"]


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
        shortages.append((item["id"],available,minimum,suggested))
        lines.append((item["id"],suggested,_price(db,item["id"])))
    purchase_id = None
    if lines:
        purchase_id = db.execute("""INSERT INTO g_purchases(origin,created,actor,supplier,status) OUTPUT INSERTED.id
                                    VALUES('Faltantes',?,?,'','Borrador')""",(created,actor)).lastrowid
        _put_lines(db,purchase_id,lines)
    report_id = db.execute("INSERT INTO g_reports(day,created,scheduled,purchase_id) OUTPUT INSERTED.id VALUES(?,?,?,?)",
                           (day,created,int(scheduled),purchase_id)).lastrowid
    db.executemany("INSERT INTO g_shortage VALUES(?,?,?,?,?)",((report_id,*s) for s in shortages))
    return report_id


def _alerts(db, stocks):
    now = date.fromisoformat(inv.today())
    by_id = {i["id"]:i for i in stocks}
    active = {}
    for i in stocks:
        if i["available"] <= i["min_qty"]:
            active[f"min.{i['id']}"] = ("Stock mínimo",i["id"],
                f"{i['name']} alcanzó el mínimo. Disponible al activar la alerta: {i['available']:g} {i['unit']}.")
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


def act(db, user, action, payload):
    handlers = {
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
            if not db.execute("UPDATE cash_expenses SET void_reason=?,void_by=?,void_at=? WHERE id=? AND day=? AND void_at IS NULL",
                              (reason,user["name"],inv.now(),inv._id(payload.get("id")),day)).rowcount:
                raise ValueError("El gasto ya fue anulado o no existe.")
        else:
            kind=payload.get("kind")
            if kind not in ("Personal","Mercado"):
                raise ValueError("Tipo de gasto inválido.")
            day=date.fromisoformat(payload.get("day","")).isoformat()
            reference=inv._text(payload.get("reference"),"referencia",100)
            if db.execute("SELECT id FROM cash_expenses WHERE day=? AND kind=? AND reference=? AND void_at IS NULL",(day,kind,reference)).fetchone():
                raise ValueError("La referencia ya está registrada para esta jornada.")
            db.execute("INSERT INTO cash_expenses(day,kind,reference,concept,cents,actor) VALUES(?,?,?,?,?,?)",
                       (day,kind,reference,inv._text(payload.get("concept"),"concepto",300),
                        inv._scaled(payload.get("amount"),100,"Importe"),user["name"]))
        return {}
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
    receiving = user["role"] in {"admin","recepcion"}
    result = {"receipts":[], "wastes":[], "incidents":[], "alerts":[], "purchases":[],
              "reports":[], "budget":None, "schedule":None}
    if user["role"] in ("admin","caja"):
        result["registered_days"]=[dict(r) for r in db.execute("""WITH days(day) AS (
            SELECT day FROM cash_days UNION SELECT day FROM inv_orders UNION SELECT day FROM cash_expenses
            UNION SELECT COALESCE(s.cash_day,LEFT(o.paid_at,10)) FROM inv_sales s JOIN inv_orders o ON o.id=s.order_id
            UNION SELECT COALESCE(cash_day,LEFT(at,10)) FROM inv_returns UNION SELECT cash_day FROM sale_voids UNION SELECT cash_day FROM refund_reversals UNION SELECT CAST(? AS nvarchar(10)))
            SELECT days.day,d.opened_at,d.opened_by FROM days LEFT JOIN cash_days d ON days.day=d.day
            WHERE days.day IS NOT NULL ORDER BY days.day DESC""",(inv.business_day(db),))]
        result["cash_expenses"]=[dict(r) for r in db.execute("SELECT * FROM cash_expenses ORDER BY day DESC,id DESC")]
    if receiving:
        for r in db.execute("""SELECT r.id,r.item_id,i.name item_name,i.unit,r.supplier,r.qty_m,
                r.approved_m,r.received_m,r.reason,r.created,r.actor,r.reviewed_at,r.reviewer,r.unit_cents,
                r.lot_id,l.expiry,k.purchase_id FROM g_receipts r JOIN inv_items i ON i.id=r.item_id
                LEFT JOIN g_lines k ON k.id=r.line_id LEFT JOIN inv_lots l ON l.id=r.lot_id
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
        for r in db.execute("""SELECT p.id,p.receipt_id,r.item_id,i.name item_name,i.unit,r.supplier,
                r.qty_m,r.received_m,r.approved_m,r.reason,p.created,r.reviewer AS actor,
                p.resolution,p.closed,p.closer FROM g_incidents p JOIN g_receipts r ON r.id=p.receipt_id
                JOIN inv_items i ON i.id=r.item_id ORDER BY CASE WHEN p.closed IS NULL THEN 0 ELSE 1 END,p.id DESC"""):
            issue = _with_code(r,"INC")
            expected,received,approved = issue.pop("qty_m"),issue.pop("received_m"),issue.pop("approved_m")
            issue["missing"] = None if received is None else inv.num(max(0,expected-received))
            issue["rejected"] = None if received is None else inv.num(received-approved)
            issue["qty"] = inv.num(max(expected,received or 0)-approved)
            issue["status"] = "Resuelta" if issue["closed"] else "Abierta"
            result["incidents"].append(issue)
    if user["role"] in {"admin","recepcion","area"}:
        for r in db.execute("""SELECT w.*,i.name item_name,i.unit,i.area FROM g_wastes w
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
        purchase.update(lines=[], total_cents=0)
        purchases[r["id"]] = purchase
    if purchases:
        line_query = """SELECT l.purchase_id,l.item_id,i.name item_name,i.unit,l.qty_m,l.unit_cents
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
        for r in db.execute("""SELECT s.*,i.name item_name,i.unit FROM g_shortage s
                               JOIN inv_items i ON i.id=s.item_id ORDER BY i.name"""):
            report = reports[r["report_id"]]
            report["lines"].append({"item_id":r["item_id"],"item_name":r["item_name"],"unit":r["unit"],
                                    "available":inv.num(r["available_m"]),"minimum":inv.num(r["minimum_m"]),
                                    "suggested":inv.num(r["suggested_m"])})
            report["count"] += 1
        result["reports"] = list(reports.values())
    return result
