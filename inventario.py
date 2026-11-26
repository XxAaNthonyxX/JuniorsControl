"""Inventario por lotes y comandas. El llamador abre una transacción de escritura.

Las cantidades persistidas son milésimas de unidad y los precios son céntimos.
Una reserva sólo inmoviliza un lote; el movimiento físico corresponde al cobro.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import pyodbc


LIMA = timezone(timedelta(hours=-5))
SYSTEM = {"id": 0, "name": "Sistema", "role": "admin", "area": ""}
DEFAULT_AREAS = ["Cocina", "Barra", "Parrilla", "Limpieza", "Atención"]


def now():
    return datetime.now(LIMA).isoformat(sep=" ", timespec="seconds")[:19]


def today():
    return datetime.now(LIMA).date().isoformat()


def public(prefix, number):
    return f"{prefix}{number:04d}"


def _order_ref(row):
    return f"{public('C', row['number'])} · {row['day']}"


def _next_order_number(db, day):
    return db.execute("SELECT COALESCE(MAX(number),0)+1 FROM inv_orders WHERE day=?", (day,)).fetchone()[0]


def _scaled(value, scale, label, low=1, high=1_000_000_000):
    try:
        d = Decimal(str(value).strip().replace(",", "."))
        if not d.is_finite() or not Decimal(low) / scale <= d <= Decimal(high) / scale:
            raise ValueError
        n = d * scale
        if n != n.to_integral_value() or not low <= n <= high:
            raise ValueError
        return int(n)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ValueError(f"{label}: ingresa una cantidad válida con la precisión indicada.") from None


def qty(x):
    return _scaled(x, 1000, "Cantidad")


def num(x):
    return x / 1000


def _id(x):
    return _scaled(x, 1, "Identificador", high=2_147_483_647)


def _text(value, name, maximum=120):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f"Revisa el campo {name} (máximo {maximum} caracteres).")
    return value.strip()


def _bool(x):
    if x in (True, 1, "1", "true", "on"):
        return 1
    if x in (False, 0, "0", "false", "", None):
        return 0
    raise ValueError("Opción de catálogo inválida.")


def _date(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError("Ingresa una fecha válida.") from None


def _role(user, *roles):
    if user["role"] not in roles:
        raise PermissionError("Tu rol no tiene permiso para realizar esta operación.")


def _area(user):
    return user.get("area") or {"recepcion": "Limpieza", "atencion": "Atención"}.get(user["role"], "")


def _can_prepare(user):
    return user["role"] in ("admin", "area") or (
        user["role"] == "recepcion" and _area(user).casefold() in {"cocina", "parrilla", "horno"}
    )


def _in_area(user, area):
    if user["role"] != "admin" and _area(user).casefold() != area.casefold():
        raise PermissionError("El insumo pertenece a otra área.")


def _item(db, item_id):
    row = db.execute("SELECT * FROM inv_items WHERE id=?", (_id(item_id),)).fetchone()
    if row is None:
        raise ValueError("No se encontró el insumo.")
    return row


def _move(db, user, lot, delta, reason, ref):
    if not delta:
        return
    ok = db.execute("UPDATE inv_lots SET physical=physical+? WHERE id=? AND physical+?>=reserved",
                    (delta, lot, delta)).rowcount
    if not ok:
        raise ValueError("El lote ya no tiene suficientes existencias libres.")
    movement = db.execute("INSERT INTO inv_moves(at,lot_id,delta,reason,ref,operator,user_id) OUTPUT INSERTED.id VALUES(?,?,?,?,?,?,?)",
                          (now(), lot, delta, reason, str(ref), user["name"], user["id"])).lastrowid
    db.execute("""INSERT INTO inv_move_context(move_id,area,item_name)
                  SELECT ?,i.area,i.name FROM inv_lots l JOIN inv_items i ON i.id=l.item_id WHERE l.id=?""",
               (movement,lot))


def receive(db, user, item_id, qty_milli, expiry, reason, ref):
    item = _item(db, item_id)
    if not isinstance(qty_milli, int) or qty_milli <= 0:
        raise ValueError("La entrada debe ser mayor que cero.")
    expiry = _date(expiry) if expiry else None
    if (item["perishable"] and not expiry) or (expiry and expiry < today()):
        raise ValueError("El lote requiere una fecha de vencimiento vigente.")
    lot = db.execute("INSERT INTO inv_lots(item_id,expiry) OUTPUT INSERTED.id VALUES(?,?)", (item["id"], expiry)).lastrowid
    _move(db, user, lot, qty_milli, reason, ref)
    return lot


def _plan(db, item_id, amount, lot_id=None):
    item = _item(db, item_id)
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("La salida debe ser mayor que cero.")
    query = """SELECT *,physical-reserved AS free FROM inv_lots
               WHERE item_id=? AND physical>reserved AND (expiry IS NULL OR expiry>=?)"""
    args = [item["id"], today()]
    if lot_id is not None:
        query += " AND id=?"
        args.append(_id(lot_id))
    query += " ORDER BY CASE WHEN expiry IS NULL THEN 1 ELSE 0 END,expiry,id"
    left = amount
    result = []
    for lot in db.execute(query, args):
        take = min(left, lot["free"])
        result.append((lot["id"], take, lot["expiry"]))
        left -= take
        if not left:
            return result
    raise ValueError(f"Stock insuficiente de {item['name']}. Faltan {num(left):g} {item['unit']}.")


def withdraw(db, user, item_id, qty_milli, reason, ref, lot_id=None):
    plan = _plan(db, item_id, qty_milli, lot_id)
    for lot, amount, _ in plan:
        _move(db, user, lot, -amount, reason, ref)
    return plan


def _event(db, user, order_id, action, reason=""):
    db.execute("INSERT INTO inv_events(order_id,at,action,reason,user_id,operator) VALUES(?,?,?,?,?,?)",
               (order_id, now(), action, reason, user["id"], user["name"]))


def _release(db, order_id, product_id=None):
    predicate="order_id=?"
    args=(order_id,)
    if product_id is not None:
        predicate+=" AND product_id=?"
        args+=(product_id,)
    rows=db.execute("SELECT lot_id,SUM(amount) FROM inv_alloc WHERE "+predicate+" GROUP BY lot_id",args).fetchall()
    for lot, n in rows:
        db.execute("UPDATE inv_lots SET reserved=reserved-? WHERE id=?", (n, lot))
    db.execute("DELETE FROM inv_alloc WHERE "+predicate,args)


def expire(db):
    day = today()
    affected = db.execute("""SELECT DISTINCT a.order_id FROM inv_alloc a JOIN inv_lots l ON a.lot_id=l.id
                             JOIN inv_orders o ON o.id=a.order_id WHERE o.status='Reservado' AND l.expiry<?""", (day,)).fetchall()
    for (order,) in affected:
        _release(db, order)
        db.execute("UPDATE inv_orders SET status='Por revisar',version=version+1 WHERE id=?", (order,))
        _event(db, SYSTEM, order, "Por revisar", "Se liberó la reserva por vencimiento de un lote.")
    expired = db.execute("SELECT id,physical FROM inv_lots WHERE expiry<? AND physical>0", (day,)).fetchall()
    for lot, balance in expired:
        _move(db, SYSTEM, lot, -balance, "Caducidad", public("LT",lot))


def stock(db):
    result = []
    rows = db.execute("""SELECT i.*,COALESCE(SUM(l.physical),0) AS physical,COALESCE(SUM(l.reserved),0) AS reserved,
                         COALESCE(SUM(CASE WHEN l.expiry IS NULL OR l.expiry>=? THEN l.physical-l.reserved ELSE 0 END),0) AS available
                         FROM inv_items i LEFT JOIN inv_lots l ON l.item_id=i.id GROUP BY i.id,i.code,i.name,i.category,i.area,i.unit,i.min_qty,i.warn_days,i.perishable,i.transformable ORDER BY i.name""",
                      (today(),))
    for row in rows:
        item = dict(row)
        for k in ("min_qty", "physical", "reserved", "available"):
            item[k] = num(item[k])
        result.append(item)
    return result


def batches(db):
    data = []
    for row in db.execute("SELECT * FROM inv_lots WHERE physical>0 ORDER BY CASE WHEN expiry IS NULL THEN 1 ELSE 0 END,expiry,id"):
        lot = dict(row)
        lot["code"]=public("LT",row["id"])
        lot["available"] = num(row["physical"]-row["reserved"]) if not row["expiry"] or row["expiry"]>=today() else 0
        lot["physical"], lot["reserved"] = num(row["physical"]), num(row["reserved"])
        data.append(lot)
    return data


def net_sales(db):
    return db.execute("""SELECT COALESCE(SUM(l.price*(l.qty-l.refunded)),0) FROM inv_lines l
                        JOIN inv_orders o ON o.id=l.order_id WHERE o.paid_at IS NOT NULL""").fetchone()[0]


def _save_item(db, user, p):
    _role(user, "admin")
    fields = [_text(p.get(k), k, limit) for k, limit in
              (("name",100),("category",60),("area",60),("unit",20))]
    fields += [_scaled(p.get("min_qty",0),1000,"Stock mínimo",0),
               _scaled(p.get("warn_days",3),1,"Días de aviso",0,3650),
               _bool(p.get("perishable")), _bool(p.get("transformable"))]
    if p.get("id"):
        item = _item(db,p["id"])
        if (fields[3] != item["unit"] or fields[6] != item["perishable"]) and db.execute(
            "SELECT 1 FROM inv_lots WHERE item_id=? UNION SELECT 1 FROM inv_recipes WHERE item_id=? UNION SELECT 1 FROM inv_rules WHERE source_id=? OR target_id=?",
            (item["id"],)*4).fetchone():
            raise ValueError("El insumo tiene lotes o recetas. Conserva su unidad y tipo de vencimiento.")
        db.execute("UPDATE inv_items SET name=?,category=?,area=?,unit=?,min_qty=?,warn_days=?,perishable=?,transformable=? WHERE id=?",
                   (*fields,item["id"]))
        return {"id":item["id"],"code":item["code"]}
    next_id=db.execute("SELECT COALESCE(MAX(id),0)+1 FROM inv_items").fetchone()[0]
    code=public("INS",next_id)
    db.execute("""INSERT INTO inv_items(id,code,name,category,area,unit,min_qty,warn_days,perishable,transformable)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""", (next_id,code,*fields))
    return {"id":next_id,"code":code}


def _save_product(db, user, p):
    _role(user, "admin")
    name = _text(p.get("name"), "nombre")
    cat = _text(p.get("category"), "categoría")
    price = _scaled(p.get("price"), 100, "Precio", high=100_000_000)
    area = _prep_area(p.get("prep_area") or ("Barra" if "bebid" in cat.casefold() else "Parrilla" if "brasa" in cat.casefold() or "parrill" in cat.casefold() else "Cocina"))
    recipe = p.get("recipe")
    if not isinstance(recipe,list) or not 1<=len(recipe)<=100:
        raise ValueError("Agrega entre uno y cien insumos a la receta.")
    if p.get("id"):
        prod = _id(p["id"])
        if not db.execute("UPDATE inv_products SET name=?,category=?,price=?,prep_area=? WHERE id=?", (name,cat,price,area,prod)).rowcount:
            raise ValueError("El producto no existe.")
        db.execute("DELETE FROM inv_recipes WHERE product_id=?", (prod,))
    else:
        prod = db.execute("INSERT INTO inv_products(name,category,price,prep_area) OUTPUT INSERTED.id VALUES(?,?,?,?)", (name,cat,price,area)).lastrowid
    added = set()
    for row in recipe:
        if not isinstance(row,dict):
            raise ValueError("Revisa los insumos de la receta.")
        item = _item(db,row.get("item_id"))["id"]
        if item in added:
            raise ValueError("Agrupa las cantidades del mismo insumo en una línea de receta.")
        added.add(item)
        db.execute("INSERT INTO inv_recipes VALUES(?,?,?)",(prod,item,qty(row.get("qty"))))
    return {"id":prod,"code":public("PR",prod)}


def _rule(db,user,p):
    _role(user,"admin")
    source = _item(db,p.get("source_id"))
    target = _item(db,p.get("target_id"))
    if source["id"]==target["id"] or not source["transformable"]:
        raise ValueError("Selecciona un insumo transformable y un producto de destino diferente.")
    values=(qty(p.get("source_qty")),qty(p.get("target_qty")),source["id"],target["id"])
    if not db.execute("UPDATE inv_rules SET source_qty=?,target_qty=? WHERE source_id=? AND target_id=?",values).rowcount:
        db.execute("INSERT INTO inv_rules(source_qty,target_qty,source_id,target_id) VALUES(?,?,?,?)",values)
    key=db.execute("SELECT id FROM inv_rules WHERE source_id=? AND target_id=?",(source["id"],target["id"])).fetchone()[0]
    return {"id":key,"code":public("EQ",key)}


def _transform(db,user,p):
    if not _can_prepare(user):
        raise PermissionError("Tu cuenta no tiene permiso de preparación.")
    r=db.execute("SELECT * FROM inv_rules WHERE id=?",(_id(p.get("rule_id")),)).fetchone()
    if r is None:
        raise ValueError("Selecciona una equivalencia de preparación.")
    source,target = _item(db,r["source_id"]),_item(db,r["target_id"])
    _in_area(user,source["area"])
    _in_area(user,target["area"])
    if not source["transformable"]:
        raise ValueError("Este insumo ya no está habilitado para transformación.")
    times = _scaled(p.get("qty"),1,"Número de preparaciones",high=10000)
    ref = f"{source['name']} → {target['name']} · {public('EQ',r['id'])}"
    plan = withdraw(db,user,source["id"],r["source_qty"]*times,"Transformación · materia prima",ref)
    dates = [lot_date for _, _, lot_date in plan if lot_date]
    if p.get("expiry"):
        dates.append(_date(p["expiry"]))
    expiry = min(dates) if dates else None
    dest = receive(db,user,target["id"],r["target_qty"]*times,expiry,"Transformación · preparado",ref)
    return {"lot_id":dest}



def _table_number(value):
    """Solo números 1 a 20; el piso se deriva del número de mesa."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Selecciona una mesa entre 1 y 20.")
    raw = str(value).strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 20:
        raise ValueError("Selecciona una mesa entre 1 y 20.")
    return int(raw)


def _prep_area(value):
    if value not in ("Cocina", "Barra", "Parrilla"):
        raise ValueError("Selecciona Cocina, Barra o Parrilla para este producto.")
    return value


def _may_work(user, area):
    return user["role"] == "admin" or (user["role"] == "area" and
           (user.get("area") or "").casefold() == area.casefold())


def _pending_cancel(db, order_id):
    return db.execute("SELECT id FROM inv_cancel_requests WHERE order_id=? AND status='Pendiente'",(order_id,)).fetchone()


def _dispatch_exists(db, order_id):
    return db.execute("SELECT 1 FROM inv_dispatch WHERE order_id=?",(order_id,)).fetchone() is not None


def _order_lines_delivered(db, order_id):
    total = db.execute("SELECT COUNT(*) FROM inv_lines WHERE order_id=?",(order_id,)).fetchone()[0]
    delivered = db.execute("SELECT COUNT(*) FROM inv_dispatch WHERE order_id=? AND status=N'Entregado'",(order_id,)).fetchone()[0]
    return bool(total) and total == delivered

def _get_order(db,p):
    order = db.execute("SELECT * FROM inv_orders WHERE id=?",(_id(p.get("id")),)).fetchone()
    if not order:
        raise ValueError("El pedido no existe.")
    return order


def _check_version(order, p):
    if p.get("version") is not None and _id(p["version"]) != order["version"]:
        raise ValueError("El pedido cambió en otra sesión. Actualiza antes de continuar.")


def _save_order(db,user,p,*,exchange=False):
    _role(user,"atencion","caja","admin")
    number_table = None if exchange else _table_number(p.get("table_number", p.get("table_name")))
    table = _text(p.get("table_name"), "mesa o referencia", 60) if exchange else f"Mesa {number_table}"
    rows = p.get("lines")
    if not isinstance(rows,list) or not 1<=len(rows)<=100:
        raise ValueError("Selecciona al menos un producto y hasta cien líneas.")
    requested={}
    for line in rows:
        if not isinstance(line,dict):
            raise ValueError("Revisa las líneas del pedido.")
        product_id=_id(line.get("product_id"))
        if product_id in requested:
            raise ValueError("Agrupa los productos repetidos en una sola línea.")
        requested[product_id]=_scaled(line.get("qty"),1,"Unidades del plato",high=10000)
    old_lines = {}
    unchanged=set()
    if not exchange:
        day_check=today()
        conflict=db.execute("""SELECT TOP(1) number FROM inv_orders
                  WHERE day=? AND status IN ('Reservado','Por revisar')
                  AND (table_number=? OR (table_number IS NULL AND
                        (table_name IN (?,?) OR (table_name LIKE N'Mesa %' AND
                          TRY_CONVERT(int,SUBSTRING(table_name,6,100))=?))))
                  AND id<>? ORDER BY id""",
                  (day_check,number_table,f"Mesa {number_table}",str(number_table),number_table,_id(p["id"]) if p.get("id") else 0)).fetchone()
        if conflict:
            raise ValueError(f"La mesa {number_table} está OCUPADA por {public('C',conflict['number'])} en la jornada actual.")
    if p.get("id"):
        o = _get_order(db,p)
        if o["status"] not in ("Reservado","Por revisar"):
            raise ValueError("Este pedido ya se cerró.")
        if _pending_cancel(db,o["id"]):
            raise ValueError("La solicitud de cancelación está pendiente de aprobación.")
        if o["day"] != today():
            raise ValueError("Solo puedes modificar comandas de la jornada actual.")
        _check_version(o,p)
        order=o["id"]
        old_lines={l["product_id"]:l for l in db.execute("SELECT * FROM inv_lines WHERE order_id=?",(order,))}
        sent={r["product_id"] for r in db.execute("SELECT product_id FROM inv_dispatch WHERE order_id=?",(order,))}
        for pid in sent:
            if requested.get(pid) != old_lines[pid]["qty"]:
                raise ValueError("Un producto enviado a preparación ya no se puede modificar. Solicita asistencia para su anulación.")
        # Primero libera todas las líneas retiradas o editadas para que los cambios
        # puedan intercambiar insumos. Las demás conservan sus lotes originales.
        for product_id,line in old_lines.items():
            if o["status"]=="Reservado" and requested.get(product_id)==line["qty"]:
                unchanged.add(product_id)
                continue
            _release(db,order,product_id)
            if product_id not in requested:
                db.execute("DELETE FROM inv_lines WHERE order_id=? AND product_id=?",(order,product_id))
        db.execute("UPDATE inv_orders SET table_name=?,table_number=?,status='Reservado',version=version+1 WHERE id=?",(table,number_table,order))
    else:
        timestamp=now()
        day=timestamp[:10]
        number=_next_order_number(db,day)
        order=db.execute("""INSERT INTO inv_orders(table_name,table_number,status,created,operator,user_id,day,number) OUTPUT INSERTED.id
                            VALUES(?,?,'Reservado',?,?,?,?,?)""",(table,number_table,timestamp,user["name"],user["id"],day,number)).lastrowid
    for product_id,n in requested.items():
        if product_id in unchanged:
            continue
        if product_id in old_lines:
            db.execute("UPDATE inv_lines SET qty=? WHERE order_id=? AND product_id=?",(n,order,product_id))
        else:
            inserted=db.execute("""INSERT INTO inv_lines(order_id,product_id,name,qty,price)
                                   SELECT ?,id,name,?,price FROM inv_products WHERE id=?""",(order,n,product_id))
            if not inserted.rowcount:
                raise ValueError("No se encontró uno de los productos del pedido.")
            db.execute("""INSERT INTO inv_line_recipes(order_id,product_id,item_id,amount)
                          SELECT ?,product_id,item_id,amount FROM inv_recipes WHERE product_id=?""",(order,product_id))
        recipe=db.execute("SELECT item_id,amount FROM inv_line_recipes WHERE order_id=? AND product_id=?",(order,product_id)).fetchall()
        if not recipe:
            raise ValueError("Esta línea no tiene una receta registrada. Revisa el producto de la carta.")
        for item, amount in recipe:
            for lot,take,_ in _plan(db,item,amount*n):
                db.execute("UPDATE inv_lots SET reserved=reserved+? WHERE id=?", (take,lot))
                db.execute("INSERT INTO inv_alloc(order_id,product_id,lot_id,amount) VALUES(?,?,?,?)",(order,product_id,lot,take))
    _event(db,user,order,"Modificado" if old_lines else "Reservado")
    saved=db.execute("SELECT number,day FROM inv_orders WHERE id=?",(order,)).fetchone()
    return {"id":order,"code":public("C",saved["number"]),"day":saved["day"]}


def _pay(db,user,p,*,exchange=False):
    _role(user,"caja","admin")
    o=_get_order(db,p)
    if o["paid_at"]:
        sale_id=db.execute("SELECT id FROM inv_sales WHERE order_id=?",(o["id"],)).fetchone()[0]
        return {"id":o["id"],"sale_code":public("V",sale_id)}
    if o["status"]!="Reservado":
        raise ValueError("El pedido debe tener una reserva vigente antes del cobro.")
    if not exchange:
        if _pending_cancel(db,o["id"]):
            raise ValueError("La comanda tiene una cancelación pendiente; primero debe resolverse.")
        if not _order_lines_delivered(db,o["id"]):
            raise ValueError("Antes de cobrar, Cocina, Barra o Parrilla deben marcar todos los productos como entregados.")
    _check_version(o,p)
    parts=db.execute("""SELECT a.lot_id,SUM(a.amount),l.expiry FROM inv_alloc a JOIN inv_lots l ON l.id=a.lot_id
                        WHERE a.order_id=? GROUP BY a.lot_id,l.expiry""",(o["id"],)).fetchall()
    if not parts or any(expiry and expiry<today() for _,_,expiry in parts):
        raise ValueError("La reserva venció. Revisa los insumos y vuelve a guardar el pedido.")
    sale_id=db.execute("INSERT INTO inv_sales(order_id) OUTPUT INSERTED.id VALUES(?)",(o["id"],)).lastrowid
    sale_code=public("V",sale_id)
    for lot,amount,_ in parts:
        db.execute("UPDATE inv_lots SET reserved=reserved-? WHERE id=?",(amount,lot))
        _move(db,user,lot,-amount,"Venta",f"{sale_code} · {_order_ref(o)}")
    db.execute("UPDATE inv_orders SET status='Cobrado',paid_at=?,cashier=?,version=version+1 WHERE id=?",
               (now(),user["name"],o["id"]))
    _event(db,user,o["id"],"Cobrado")
    return {"id":o["id"],"sale_code":sale_code}


def _cancel(db,user,p):
    _role(user,"caja","admin")
    o=_get_order(db,p)
    if _pending_cancel(db,o["id"]):
        raise ValueError("La cancelación pendiente debe aprobarse o rechazarse primero.")
    if db.execute("SELECT 1 FROM inv_dispatch WHERE order_id=? AND status=N'Entregado'",(o["id"],)).fetchone():
        raise ValueError("La comanda tiene productos entregados. Solicita una devolución o ajuste supervisado.")
    if o["status"]=="Cancelado":
        return {"id":o["id"]}
    if o["status"] not in ("Por revisar","Reservado"):
        raise ValueError("Para corregir una venta cobrada, registra una devolución.")
    _check_version(o,p)
    _release(db,o["id"])
    db.execute("UPDATE inv_orders SET status='Cancelado',version=version+1 WHERE id=?",(o["id"],))
    _event(db,user,o["id"],"Cancelado")
    return {"id":o["id"]}


def _refund(db,user,p):
    _role(user,"caja","admin")
    o=_get_order(db,p)
    if o["status"]!="Cobrado":
        raise ValueError("Selecciona una venta cobrada con unidades pendientes de devolución.")
    _check_version(o,p)
    pid=_id(p.get("product_id"))
    n=_scaled(p.get("qty"),1,"Unidades a devolver",high=10000)
    reason=_text(p.get("reason"),"motivo",300)
    line=db.execute("SELECT * FROM inv_lines WHERE order_id=? AND product_id=?",(o["id"],pid)).fetchone()
    if not line or n>line["qty"]-line["refunded"]:
        raise ValueError("La cantidad excede las unidades cobradas pendientes de devolución.")
    restock=p.get("restock",[])
    if not isinstance(restock,list):
        raise ValueError("Revisa la selección de insumos recuperables.")
    restock={_id(v) for v in restock}
    rows=db.execute("""SELECT a.*,l.item_id,l.expiry FROM inv_alloc a JOIN inv_lots l ON l.id=a.lot_id
                       WHERE a.order_id=? AND a.product_id=? ORDER BY CASE WHEN l.expiry IS NULL THEN 1 ELSE 0 END,l.expiry,l.id""",(o["id"],pid))
    grouped=defaultdict(list)
    for r in rows:
        grouped[r["item_id"]].append(r)
    if not restock.issubset(grouped):
        raise ValueError("Solo se pueden devolver insumos de esta venta.")
    return_id=db.execute("""INSERT INTO inv_returns(order_id,product_id,qty,reason,at,operator) OUTPUT INSERTED.id
                            VALUES(?,?,?,?,?,?)""",(o["id"],pid,n,reason,now(),user["name"])).lastrowid
    return_code=public("DV",return_id)
    for item,parts in grouped.items():
        needed=(sum(r["amount"] for r in parts)//line["qty"])*n
        for r in parts:
            take=min(needed,r["amount"]-r["processed"])
            if not take:
                continue
            if item in restock:
                if r["expiry"] and r["expiry"]<today():
                    raise ValueError("El lote original venció. Desmarca ese insumo para continuar.")
                _move(db,user,r["lot_id"],take,"Devolución · "+reason,f"{return_code} · {_order_ref(o)}")
            db.execute("UPDATE inv_alloc SET processed=processed+? WHERE order_id=? AND product_id=? AND lot_id=?",
                       (take,o["id"],pid,r["lot_id"]))
            needed-=take
            if not needed:
                break
    db.execute("UPDATE inv_lines SET refunded=refunded+? WHERE order_id=? AND product_id=?",(n,o["id"],pid))
    remains=db.execute("SELECT 1 FROM inv_lines WHERE order_id=? AND qty>refunded",(o["id"],)).fetchone()
    db.execute("UPDATE inv_orders SET status=?,version=version+1 WHERE id=?",("Cobrado" if remains else "Devuelto",o["id"]))
    _event(db,user,o["id"],"Devolución",f"{n} × {line['name']}. {reason}")
    return {"id":o["id"],"return_id":return_id,"return_code":return_code}


def _exchange(db,user,p):
    _role(user,"admin","caja")
    origin=_get_order(db,p)
    _id(p.get("version"))
    _check_version(origin,p)
    original_product=_id(p.get("product_id"))
    new_product=_id(p.get("replacement_id"))
    if original_product==new_product:
        raise ValueError("Elige un producto diferente como reemplazo.")
    units_back=_scaled(p.get("qty"),1,"Unidades a devolver",high=10000)
    units_out=_scaled(p.get("replacement_qty"),1,"Unidades de reemplazo",high=10000)
    expected=_scaled(p.get("expected_difference_cents"),1,"Diferencia confirmada",-(10**12),10**12)
    prices=db.execute("""SELECT l.price,p.price FROM inv_lines l JOIN inv_products p ON p.id=?
                         WHERE l.order_id=? AND l.product_id=?""",(new_product,origin["id"],original_product)).fetchone()
    if not prices:
        raise ValueError("Revisa el producto cobrado y el producto de reemplazo.")
    difference=units_out*prices[1]-units_back*prices[0]
    if expected!=difference:
        raise ValueError("La diferencia de precio cambió. Actualiza la carta y vuelve a confirmar el importe.")

    # La transacción del servicio abarca el abono, la reserva y el cobro.
    # Un error de existencias revierte también la devolución y sus movimientos.
    credit=_refund(db,user,p)
    replacement=_save_order(db,user,{"table_name":origin["table_name"],
                                     "lines":[{"product_id":new_product,"qty":units_out}]},exchange=True)
    paid=_pay(db,user,replacement,exchange=True)
    sale_id=db.execute("SELECT id FROM inv_sales WHERE order_id=?",(replacement["id"],)).fetchone()[0]
    exchange_id=db.execute("""INSERT INTO inv_exchanges(return_id,replacement_sale_id,difference_cents) OUTPUT INSERTED.id
                              VALUES(?,?,?)""",(credit["return_id"],sale_id,difference)).lastrowid
    return {"id":origin["id"],"exchange_code":public("CB",exchange_id),"return_code":credit["return_code"],
            "replacement_id":replacement["id"],"replacement_code":replacement["code"],"replacement_day":replacement["day"],
            "replacement_sale_code":paid["sale_code"],"difference_cents":difference,"difference":difference/100}



def _send_to_areas(db,user,p):
    _role(user,"admin","caja","atencion")
    o=_get_order(db,p)
    _check_version(o,p)
    if o["status"] != "Reservado" or o["day"] != today() or _pending_cancel(db,o["id"]):
        raise ValueError("La comanda debe estar abierta, sin solicitud de cancelación y en la jornada actual.")
    lines=db.execute("""SELECT l.product_id,p.prep_area FROM inv_lines l
                        JOIN inv_products p ON p.id=l.product_id
                        LEFT JOIN inv_dispatch d ON d.order_id=l.order_id AND d.product_id=l.product_id
                        WHERE l.order_id=? AND d.order_id IS NULL""",(o["id"],)).fetchall()
    if not lines:
        raise ValueError("Esta comanda no tiene productos nuevos por enviar a preparación.")
    at=now()
    for line in lines:
        db.execute("""INSERT INTO inv_dispatch(order_id,product_id,area,status,sent_at)
                      VALUES(?,?,?,N'En cola',?)""",(o["id"],line["product_id"],_prep_area(line["prep_area"]),at))
    db.execute("UPDATE inv_orders SET version=version+1 WHERE id=?",(o["id"],))
    _event(db,user,o["id"],"Enviado a preparación",f"{len(lines)} productos")
    return {"id":o["id"],"enviados":len(lines)}


def _advance_preparation(db,user,p):
    _role(user,"admin","area")
    o=_get_order(db,p)
    pid=_id(p.get("product_id"))
    task=db.execute("SELECT * FROM inv_dispatch WHERE order_id=? AND product_id=?",(o["id"],pid)).fetchone()
    if not task:
        raise ValueError("El producto no fue enviado a preparación.")
    if not _may_work(user,task["area"]):
        raise PermissionError("No puedes consultar ni entregar pedidos de otra área.")
    action=p.get("step")
    transitions={"preparar":("En cola","Preparando","started_at"),
                 "listo":("Preparando","Listo","ready_at"),
                 "entregar":("Listo","Entregado","delivered_at")}
    if action not in transitions:
        raise ValueError("Etapa de preparación inválida.")
    before,after,column=transitions[action]
    if action=="entregar" and task["status"] in ("En cola","Preparando","Listo"):
        before=task["status"]
    if task["status"]!=before:
        raise ValueError(f"Este producto debe estar en estado {before} antes de avanzar.")
    if o["status"]!="Reservado" or _pending_cancel(db,o["id"]):
        raise ValueError("La comanda no permite acciones de preparación.")
    # column derives from a constant server-side mapping, never from the request.
    changed=db.execute(f"UPDATE inv_dispatch SET status=?,{column}=?,delivered_by=CASE WHEN ?='entregar' THEN ? ELSE delivered_by END WHERE order_id=? AND product_id=? AND status=?",
               (after,now(),action,user["name"],o["id"],pid,before)).rowcount
    if not changed:
        raise ValueError("Otro empleado ya actualizó el estado.")
    db.execute("UPDATE inv_orders SET version=version+1 WHERE id=?",(o["id"],))
    _event(db,user,o["id"],after,f"{task['area']} · producto {pid}")
    return {"id":o["id"],"estado":after}


def _ask_cancel(db,user,p):
    _role(user,"admin","caja","atencion")
    o=_get_order(db,p)
    _check_version(o,p)
    if o["status"] not in ("Reservado","Por revisar"):
        raise ValueError("La comanda ya está cerrada; utiliza devoluciones para ventas cobradas.")
    if _pending_cancel(db,o["id"]):
        raise ValueError("Ya existe una solicitud de cancelación pendiente.")
    reason=_text(p.get("reason"),"motivo",500)
    if db.execute("SELECT 1 FROM inv_dispatch WHERE order_id=? AND status=N'Entregado'",(o["id"],)).fetchone():
        raise ValueError("Hay productos entregados; consulta con Caja para el ajuste correspondiente.")
    cid=db.execute("""INSERT INTO inv_cancel_requests(order_id,status,reason,requester,requested_at)
                       OUTPUT INSERTED.id VALUES(?,'Pendiente',?,?,?)""",(o["id"],reason,user["name"],now())).lastrowid
    _event(db,user,o["id"],"Cancelación solicitada",reason)
    return {"id":o["id"],"solicitud_id":cid}


def _decide_cancel(db,user,p):
    _role(user,"admin","caja")
    o=_get_order(db,p)
    r=_pending_cancel(db,o["id"])
    if not r:
        raise ValueError("No hay una solicitud de cancelación pendiente.")
    approved=p.get("approve") is True
    if approved:
        # Una entrega física exige devolución supervisada, no liberar reservas ficticiamente.
        if db.execute("SELECT 1 FROM inv_dispatch WHERE order_id=? AND status=N'Entregado'",(o["id"],)).fetchone():
            raise ValueError("No se puede cancelar: existen productos entregados.")
        _release(db,o["id"])
        db.execute("UPDATE inv_orders SET status='Cancelado',version=version+1 WHERE id=?",(o["id"],))
    db.execute("UPDATE inv_cancel_requests SET status=?,decided_at=?,decided_by=? WHERE id=?",
               ("Aprobada" if approved else "Rechazada",now(),user["name"],r["id"]))
    _event(db,user,o["id"],"Cancelación aprobada" if approved else "Cancelación rechazada")
    return {"id":o["id"],"aprobada":approved}


def _preparation(db,user):
    if user["role"] not in ("admin","area"):
        return []
    query="""SELECT d.order_id,d.product_id,d.area,d.status,d.sent_at,d.started_at,d.ready_at,
            d.delivered_at,d.delivered_by,o.number,o.day,o.table_number,l.name,l.qty,
            CASE WHEN EXISTS (SELECT 1 FROM inv_cancel_requests cr WHERE cr.order_id=o.id AND cr.status='Pendiente')
                 THEN 1 ELSE 0 END AS cancel_pending
            FROM inv_dispatch d JOIN inv_orders o ON o.id=d.order_id
            JOIN inv_lines l ON l.order_id=d.order_id AND l.product_id=d.product_id
            WHERE o.status='Reservado'"""
    params=[]
    if user["role"]=="area":
        query+=" AND d.area=?"
        params.append(_area(user))
    query+=" ORDER BY d.sent_at,d.order_id,d.product_id"
    result=[]
    for r in db.execute(query,params):
        x=dict(r);x["code"]=public("C",x["number"])
        result.append(x)
    return result

def _history(db,user,p,recent=False):
    _role(user,"admin","caja","area","recepcion","atencion")
    conditions=[]
    args=[]
    for field,op in (("start",">="),("end","<=")):
        if p.get(field):
            day=_date(p[field])
            conditions.append(f"m.at {op} ?")
            args.append(day + (" 23:59:59" if field=="end" else " 00:00:00"))
    if p.get("start") and p.get("end") and p["start"]>p["end"]:
        raise ValueError("La fecha inicial debe ser anterior a la final.")
    area=p.get("area")
    if user["role"] not in ("admin","caja","recepcion"):
        if area:
            _in_area(user,area)
        area=_area(user)
        if not area:
            return []
    if area:
        conditions.append("c.area=?")
        args.append(area)
    if p.get("item_id"):
        item=_item(db,p["item_id"])
        if user["role"] not in ("caja","admin","recepcion") and item["area"].casefold()!=area.casefold():
            previous=db.execute("""SELECT 1 FROM inv_move_context c JOIN inv_moves m ON m.id=c.move_id
                                   JOIN inv_lots l ON l.id=m.lot_id WHERE c.area=? AND l.item_id=?""",
                                (area,item["id"])).fetchone()
            if not previous:
                raise PermissionError("El insumo pertenece a otra área.")
        conditions.append("i.id=?")
        args.append(item["id"])
    query="""SELECT m.id,m.at,m.lot_id,m.delta AS qty,m.reason,m.ref,m.operator,
             c.item_name AS item,i.id AS item_id,c.area,i.unit FROM inv_moves m JOIN inv_lots l ON l.id=m.lot_id
             JOIN inv_items i ON i.id=l.item_id JOIN inv_move_context c ON c.move_id=m.id"""
    if conditions:
        query+=" WHERE "+" AND ".join(conditions)
    query+=" ORDER BY m.at DESC,m.id DESC"
    if recent:
        query+=" OFFSET 0 ROWS FETCH NEXT 100 ROWS ONLY"
    result=[]
    for row in db.execute(query,args):
        move=dict(row)
        move["code"]=public("MV",row["id"])
        move["lot_code"]=public("LT",row["lot_id"])
        move["qty"]=num(move["qty"])
        result.append(move)
    return result


def _products(db,balances):
    recipes=defaultdict(list)
    for p,i,n in db.execute("SELECT product_id,item_id,amount FROM inv_recipes ORDER BY product_id,item_id"):
        recipes[p].append((i,n))
    products=[]
    for row in db.execute("SELECT * FROM inv_products ORDER BY id"):
        prod=dict(row)
        prod["code"]=public("PR",row["id"])
        raw=recipes[prod["id"]]
        prod["available"]=min((balances[i]//n for i,n in raw),default=0)
        prod["recipe"]=[{"item_id":i,"qty":num(n)} for i,n in raw]
        prod["price"]/=100
        products.append(prod)
    return products


def _orders(db,user,balances):
    if user["role"] not in ("admin","caja","atencion"):
        return []
    attending=user["role"]=="atencion"
    sql="SELECT * FROM inv_orders"
    if attending:
        sql+=" WHERE status IN ('Reservado','Por revisar')"
    rows={r["id"]:dict(r) for r in db.execute(sql+" ORDER BY id DESC")}
    if not rows:
        return []
    for r in rows.values():
        r["code"]=public("C",r["number"])
        r.update(lines=[],total=0,gross=0)
        if not attending:
            r.update(sale_code=None,returns=[])
    if not attending:
        for sale_id,order_id in db.execute("SELECT id,order_id FROM inv_sales"):
            rows[order_id]["sale_code"]=public("V",sale_id)
        linked={}
        exchanges=db.execute("""SELECT x.id,x.return_id,x.difference_cents,s.id AS sale_id,s.order_id AS new_order,
                                r.order_id AS original_order FROM inv_exchanges x JOIN inv_sales s ON s.id=x.replacement_sale_id
                                JOIN inv_returns r ON r.id=x.return_id""")
        for e in exchanges:
            original=rows[e["original_order"]]
            replacement=rows[e["new_order"]]
            code=public("CB",e["id"])
            linked[e["return_id"]]={"exchange_code":code,"replacement_id":replacement["id"],
                "replacement_code":replacement["code"],"replacement_day":replacement["day"],
                "replacement_sale_code":public("V",e["sale_id"]),"difference_cents":e["difference_cents"],
                "difference":e["difference_cents"]/100}
            replacement["exchange_origin"]={"exchange_code":code,"return_code":public("DV",e["return_id"]),
                "id":original["id"],"code":original["code"],"day":original["day"],"sale_code":original["sale_code"]}
        credits=db.execute("""SELECT r.id,r.order_id,r.product_id,r.qty,r.reason,r.at,r.operator,l.name
                              FROM inv_returns r JOIN inv_lines l ON l.order_id=r.order_id AND l.product_id=r.product_id
                              ORDER BY r.id""")
        for credit in credits:
            detail=dict(credit)
            detail.update(linked.get(credit["id"],{}))
            detail["code"]=public("DV",detail.pop("id"))
            rows[detail.pop("order_id")]["returns"].append(detail)
    queue={}
    for d in db.execute("SELECT order_id,product_id,area,status,sent_at,started_at,ready_at,delivered_at,delivered_by FROM inv_dispatch"):
        if d["order_id"] in rows: queue[(d["order_id"],d["product_id"])]=dict(d)
    pending={r["order_id"]:dict(r) for r in db.execute("SELECT order_id,id,reason,requested_at FROM inv_cancel_requests WHERE status='Pendiente'")}
    for o in rows.values():
        o["cancel_request"]=pending.get(o["id"])
        o["table_number"]=o.get("table_number")
        o["floor"]=(1 if o["table_number"]<=10 else 2) if o["table_number"] else None
    line_sql="SELECT l.* FROM inv_lines l JOIN inv_orders o ON l.order_id=o.id"
    part_sql="""SELECT a.order_id,a.product_id,l.item_id,i.name,i.unit,SUM(a.amount) AS n FROM inv_alloc a
                JOIN inv_lots l ON l.id=a.lot_id JOIN inv_items i ON i.id=l.item_id JOIN inv_orders o ON o.id=a.order_id"""
    if attending:
        predicate=" WHERE o.status IN ('Reservado','Por revisar')"
        line_sql+=predicate
        part_sql+=predicate
    ingredients=defaultdict(list)
    for row in db.execute(part_sql+" GROUP BY a.order_id,a.product_id,l.item_id,i.name,i.unit"):
        ingredients[(row["order_id"],row["product_id"])].append(
            {"item_id":row["item_id"],"name":row["name"],"unit":row["unit"],"qty":num(row["n"])})
    capacity={}
    for oid,pid,item_id,unit_amount in db.execute("""SELECT r.order_id,r.product_id,r.item_id,r.amount
            FROM inv_line_recipes r JOIN inv_orders o ON o.id=r.order_id WHERE o.status IN ('Reservado','Por revisar')"""):
        key=(oid,pid)
        units=balances[item_id]//unit_amount
        capacity[key]=min(units,capacity.get(key,units))
    for row in db.execute(line_sql+" ORDER BY l.order_id,l.product_id"):
        line=dict(row)
        order=rows[line.pop("order_id")]
        order["gross"]+=line["price"]*line["qty"]
        order["total"]+=line["price"]*(line["qty"]-line["refunded"])
        line["price"]/=100
        key=(order["id"],line["product_id"])
        line["ingredients"]=ingredients[key]
        line["prep"]=queue.get(key)
        line["prep_status"]=line["prep"]["status"] if line["prep"] else "Sin enviar"
        if key in capacity:
            line["max_qty"]=capacity[key]+(line["qty"] if order["status"]=="Reservado" else 0)
        order["lines"].append(line)
    for r in rows.values():
        r["gross"]/=100
        r["total"]/=100
    return list(rows.values())


def state(db,user,day):
    _role(user,"admin","caja","atencion","area","recepcion")
    all_items=stock(db)
    balances={i["id"]:int(Decimal(str(i["available"]))*1000) for i in all_items}
    wide=user["role"] in ("admin","caja","recepcion")
    items=all_items if wide else [i for i in all_items if i["area"].casefold()==_area(user).casefold()]
    allowed={i["id"] for i in items}
    can_order=user["role"] in ("admin","caja","atencion")
    can_prepare = _can_prepare(user)
    recipe_items = allowed
    if user["role"] == "recepcion" and can_prepare:
        recipe_items = {i["id"] for i in items if i["area"].casefold() == _area(user).casefold()}
    rules=[]
    for row in db.execute("SELECT * FROM inv_rules ORDER BY id"):
        if row["source_id"] in recipe_items and row["target_id"] in recipe_items:
            rule=dict(row)
            rule["code"]=public("EQ",row["id"])
            for key in ("source_qty","target_qty"):
                rule[key]=num(rule[key])
            rules.append(rule)
    area_names={i["area"] for i in items}
    if wide:
        area_names.update(DEFAULT_AREAS)
    result={"items":items,"lots":[r for r in batches(db) if r["item_id"] in allowed],
            "areas":sorted(area_names),"categories":sorted({i["category"] for i in items}),
            "products":_products(db,balances) if can_order else [],
            "orders":_orders(db,user,balances),"preparation":_preparation(db,user),"rules":rules,"can_prepare":can_prepare,
            "movements":_history(db,user,{},recent=True)}
    if can_order:
        result["next_order_code"]=public("C",_next_order_number(db,day))
    if user["role"] in ("admin","caja"):
        result["net_sales"]=net_sales(db)/100
    return result


def act(db,user,action,payload):
    if not isinstance(payload,dict):
        raise ValueError("Los datos de la operación son inválidos.")
    routes={"inv.item":_save_item,"inv.product":_save_product,"inv.rule":_rule,"inv.transform":_transform,
            "pedidos.save":_save_order,"pedidos.cancel":_cancel,"pedidos.pay":_pay,"pedidos.refund":_refund,
            "pedidos.exchange":_exchange,
            "pedidos.send":_send_to_areas,"pedidos.prep":_advance_preparation,
            "pedidos.request_cancel":_ask_cancel,"pedidos.decide_cancel":_decide_cancel}
    if action=="inv.history":
        return {"movements":_history(db,user,payload)}
    if action=="inv.use":
        _role(user,"admin","area","recepcion","atencion")
        item=_item(db,payload.get("item_id"))
        _in_area(user,item["area"])
        detail=_text(payload.get("reason"),"motivo",300)
        withdraw(db,user,item["id"],qty(payload.get("qty")),"Consumo · "+detail,item["area"])
        return {}
    if action not in routes:
        raise ValueError("Operación de inventario desconocida.")
    try:
        return routes[action](db,user,payload)
    except pyodbc.IntegrityError as exc:
        if "ux_juniors_mesa_jornada_abierta" in str(exc):
            raise ValueError("La mesa ya está ocupada por otra comanda activa de esta fecha.") from None
        if "UNIQUE" in str(exc):
            raise ValueError("Ese código o nombre ya está registrado.") from None
        raise


def init(db,demo=True):
    if demo is None or db.execute("SELECT 1 FROM inv_seed").fetchone():
        return
    if not demo:
        db.execute("INSERT INTO inv_seed VALUES(1)")
        return
    # Datos ficticios de apertura. La fecha se fija una vez en la primera instalación.
    # código, nombre, área, familia, unidad, mínimo, aviso, vida inicial, transformable, cantidad
    sample=[
        ("POL-01","Pollo entero crudo","Parrilla","Aves","und",6,2,5,1,18),
        ("POL-02","Cuarto de pollo asado","Parrilla","Preparados","porc",10,1,2,0,36),
        ("PAP-01","Papa para freír","Cocina","Verduras","kg",8,3,12,0,32),
        ("ENS-01","Ensalada de la casa","Cocina","Preparados","porc",8,1,2,0,40),
        ("RES-01","Bistec de res","Parrilla","Carnes","kg",3,2,5,0,9),
        ("ARR-01","Arroz cocido","Cocina","Preparados","kg",4,1,2,0,12),
        ("POL-03","Pollo trozado","Cocina","Aves","kg",3,2,3,0,8),
        ("BEB-01","Chicha morada preparada","Barra","Bebidas","L",3,1,3,0,15),
        ("BEB-02","Gaseosa personal sellada","Barra","Bebidas","bot",12,10,90,0,10),
        ("LIM-01","Detergente lavavajillas","Limpieza","Limpieza","L",2,0,None,0,6),
        ("ATE-01","Servilletas","Atención","Servicio","und",100,0,None,0,500),
    ]
    first_day=date.fromisoformat(today())
    ids={}
    for code,name,area,cat,unit,minimum,warn,life,transformable,opening in sample:
        item=_save_item(db,SYSTEM,{"code":code,"name":name,"area":area,"category":cat,"unit":unit,
                        "min_qty":minimum,"warn_days":warn,"perishable":life is not None,"transformable":transformable})["id"]
        ids[code]=item
        expiry=(first_day+timedelta(days=life)).isoformat() if life is not None else None
        receive(db,SYSTEM,item,qty(opening),expiry,"Apertura de demostración","Inventario inicial")
    dishes=[
        ("Cuarto de pollo a la brasa","Brasas",22,[("POL-02",1),("PAP-01",0.22),("ENS-01",1)]),
        ("Medio pollo a la brasa","Brasas",41,[("POL-02",2),("PAP-01",0.44),("ENS-01",2)]),
        ("Parrilla personal","Parrillas",34,[("RES-01",0.28),("PAP-01",0.2),("ENS-01",1)]),
        ("Chaufa de pollo","Oriental",19,[("ARR-01",0.25),("POL-03",0.12)]),
        ("Chicha morada","Bebidas",7,[("BEB-01",0.4)]),
        ("Gaseosa personal","Bebidas",5,[("BEB-02",1)]),
    ]
    for name,cat,price,recipe in dishes:
        _save_product(db,SYSTEM,{"name":name,"category":cat,"price":price,
                      "recipe":[{"item_id":ids[code],"qty":amount} for code,amount in recipe]})
    _rule(db,SYSTEM,{"source_id":ids["POL-01"],"source_qty":1,"target_id":ids["POL-02"],"target_qty":4})
    db.execute("INSERT INTO inv_seed VALUES(1)")
