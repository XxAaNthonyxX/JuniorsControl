"""Inventario por lotes y comandas. El llamador abre una transacción de escritura.

Las cantidades persistidas son milésimas de unidad y los precios son céntimos.
Una reserva sólo inmoviliza un lote; el movimiento físico corresponde al cobro.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
import pyodbc
import porciones


LIMA = timezone(timedelta(hours=-5))
SYSTEM = {"id": 0, "name": "Sistema", "role": "admin", "area": ""}
INVENTORY_AREAS = ("Brasas", "Parrillas", "Barra", "Orientales", "Limpieza y Atención")
PAYMENT_METHODS = ("Efectivo", "Yape", "Tarjeta")
SMALL_STOCK_UNITS = (
    dict.fromkeys(("kg","kgs","kilo","kilos","kilogramo","kilogramos"),"g")
    | dict.fromkeys(("l","lt","lts","litro","litros"),"mL")
)
STAFF_AREAS = ("Cocina", "Barra", "Parrilla", "Limpieza", "Atención", "Horno")
STAFF_INVENTORY_AREAS = {
    "cocina": ("Orientales",),
    "parrilla": ("Brasas", "Parrillas"),
    "horno": ("Brasas",),
    "limpieza": ("Limpieza y Atención",),
    "atención": ("Limpieza y Atención",),
}


def now():
    return datetime.now(LIMA).isoformat(sep=" ", timespec="seconds")[:19]


def today():
    return datetime.now(LIMA).date().isoformat()


def business_day(db):
    row=db.execute("SELECT work_day FROM g_settings WHERE id=1").fetchone()
    return row[0] if row and row[0] else today()


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


def allows_decimal(name):
    return bool(re.search(r"\b(?:papas?|arroz)\b",name,re.IGNORECASE))


def potato_quantity_step(name, unit):
    if not re.search(r"\bpapas?\b", name, re.IGNORECASE):
        return 0
    key=unit.strip().casefold()
    if SMALL_STOCK_UNITS.get(key)=="g":
        return 500
    return 500_000 if key in ("g","gramo","gramos") else 0


def quantity_measure(item):
    if item is not None and "display_unit_milli" in item.keys() and item["display_unit_milli"]:
        return item["display_unit"],item["display_unit_milli"]
    return None,0


def check_item_quantity(name, amount, previous=None, *, unit="", item=None):
    if amount == previous:
        return amount
    potato_step=potato_quantity_step(name, unit)
    if potato_step and amount % potato_step:
        raise ValueError(f"{name}: ingresa una cantidad en incrementos de 0,5 kg.")
    display,size=quantity_measure(item)
    if size and amount % size:
        raise ValueError(f"{name}: ingresa una cantidad entera de {display}.")
    if not size and not potato_step and amount % 1000 and not allows_decimal(name):
        raise ValueError(f"{name}: ingresa una cantidad entera.")
    return amount


def item_quantity(name, value, label="Cantidad", *, unit="", minimum=1, previous=None, item=None):
    if isinstance(value,dict):
        display,size=quantity_measure(item)
        if not size and not allows_decimal(name):
            display=SMALL_STOCK_UNITS.get(unit.strip().casefold())
            size=1
        if not display or value.get("unit")!=display or value.get("unit_milli",1)!=size:
            raise ValueError(f"{name}: revisa la unidad de la cantidad indicada.")
        amount=_scaled(value.get("value"),1,label,minimum,1_000_000_000//size)*size
        if potato_quantity_step(name,unit):
            check_item_quantity(name,amount,unit=unit,item=item)
        return amount
    return check_item_quantity(name,_scaled(value,1000,label,minimum),previous,unit=unit,item=item)


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


def _item_area(value):
    area = _text(value, "área", 60)
    for name in INVENTORY_AREAS:
        if name.casefold() == area.casefold():
            return name
    raise ValueError("Selecciona un área de insumos del catálogo.")


def inventory_access_areas(user):
    assigned = _area(user).casefold()
    if assigned in STAFF_INVENTORY_AREAS:
        return STAFF_INVENTORY_AREAS[assigned]
    return tuple(area for area in INVENTORY_AREAS if area.casefold() == assigned)


def _can_prepare(user):
    return user["role"] in ("admin", "area") or (
        user["role"] == "recepcion" and any(
            area in ("Brasas", "Parrillas", "Orientales") for area in inventory_access_areas(user)
        )
    )


def _in_area(user, area):
    if user["role"] != "admin" and area not in inventory_access_areas(user):
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
    item_id,qty_milli=porciones.resolve(db,item_id,qty_milli)
    item = _item(db, item_id)
    if not isinstance(qty_milli, int) or qty_milli <= 0:
        raise ValueError("La entrada debe ser mayor que cero.")
    expiry = _date(expiry) if expiry else None
    if (item["perishable"] and not expiry) or (expiry and expiry < today()):
        raise ValueError("El lote requiere una fecha de vencimiento vigente.")
    lot = db.execute("INSERT INTO inv_lots(item_id,expiry) OUTPUT INSERTED.id VALUES(?,?)", (item["id"], expiry)).lastrowid
    _move(db, user, lot, qty_milli, reason, ref)
    return lot


def _plan(db, item_id, amount, lot_id=None, *, allow_partial=False):
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
    if allow_partial:
        return result
    raise ValueError(f"Stock insuficiente de {item['name']}. Faltan {num(left):g} {item['unit']}.")


def withdraw(db, user, item_id, qty_milli, reason, ref, lot_id=None):
    item_id,qty_milli=porciones.resolve(db,item_id,qty_milli)
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
    expired = db.execute("SELECT id,physical-reserved FROM inv_lots WHERE expiry<? AND physical>reserved", (day,)).fetchall()
    for lot, balance in expired:
        _move(db, SYSTEM, lot, -balance, "Caducidad", public("LT",lot))


def stock(db):
    result = []
    rows = db.execute("""SELECT i.id,i.code,i.name,i.area,i.unit,i.min_qty,i.warn_days,i.perishable,i.transformable,
                         i.display_unit,i.display_unit_milli,
                         COALESCE(SUM(l.physical),0) AS physical,COALESCE(SUM(l.reserved),0) AS reserved,
                         COALESCE(SUM(CASE WHEN l.expiry IS NULL OR l.expiry>=? THEN l.physical-l.reserved ELSE 0 END),0) AS available
                         FROM inv_items i LEFT JOIN inv_lots l ON l.item_id=i.id
                         GROUP BY i.id,i.code,i.name,i.area,i.unit,i.min_qty,i.warn_days,i.perishable,i.transformable,
                                  i.display_unit,i.display_unit_milli ORDER BY i.name""",
                      (today(),))
    for row in rows:
        item = dict(row)
        for k in ("min_qty", "physical", "reserved", "available"):
            item[k] = num(item[k])
        result.append(item)
    porciones.project(db,result)
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
                        JOIN inv_orders o ON o.id=l.order_id WHERE o.paid_at IS NOT NULL AND o.status<>'Anulada'""").fetchone()[0]


def _next_item_code(db,number):
    code=public("INS",number)
    while db.execute("SELECT 1 FROM inv_items WHERE code=?",(code,)).fetchone():
        number+=1
        code=public("INS",number)
    return code


def _set_item_area(db, item, area):
    if area == item["area"]:
        return
    base_id, _ = porciones.resolve(db, item["id"], 0)
    db.execute("""UPDATE inv_items SET area=? WHERE id=? OR id IN
                  (SELECT item_id FROM inv_stock_equivalents WHERE base_id=?)""",
               (area, base_id, base_id))


def _save_item(db, user, p):
    _role(user, "admin")
    name=_text(p.get("name"),"nombre",100)
    area=_item_area(p.get("area"))
    unit=_text(p.get("unit"),"unidad",20)
    item=_item(db,p["id"]) if p.get("id") else None
    min_qty=item_quantity(name,p.get("min_qty",0),"Stock mínimo",unit=unit,minimum=0,item=item,
                          previous=item["min_qty"] if item else None)
    warn_days=_scaled(p.get("warn_days",3),1,"Días de aviso",0,3650)
    perishable=_bool(p.get("perishable"))
    transformable=_bool(p.get("transformable"))
    if item and db.execute("SELECT 1 FROM inv_stock_equivalents WHERE item_id=? OR base_id=?",(item["id"],item["id"])).fetchone():
        if (unit,perishable)!=(item["unit"],item["perishable"]):
            raise ValueError("El stock compartido debe conservar su unidad y tipo de vencimiento.")
    code=p.get("code")
    if code:
        code=_text(code,"código",32)
        if not item or code!=item["code"]:
            code=code.upper()
        if len(code)>32:
            raise ValueError("El código admite hasta 32 caracteres.")
        if db.execute("SELECT 1 FROM inv_items WHERE code=? AND id<>?",(code,item["id"] if item else 0)).fetchone():
            raise ValueError("Ya existe un insumo con ese código.")
    if item:
        if unit!=item["unit"] and quantity_measure(item)[1]:
            raise ValueError("Cambia la presentación desde Cambiar unidad.")
        if (unit != item["unit"] or perishable != item["perishable"]) and db.execute(
            "SELECT 1 FROM inv_lots WHERE item_id=? UNION SELECT 1 FROM inv_recipes WHERE item_id=? UNION SELECT 1 FROM inv_rules WHERE source_id=? OR target_id=?",
            (item["id"],)*4).fetchone():
            raise ValueError("El insumo tiene lotes o recetas. Conserva su unidad y tipo de vencimiento.")
        code=code or item["code"]
        db.execute("UPDATE inv_items SET code=?,name=?,unit=?,min_qty=?,warn_days=?,perishable=?,transformable=? WHERE id=?",
                   (code,name,unit,min_qty,warn_days,perishable,transformable,item["id"]))
        _set_item_area(db, item, area)
        saved_id=item["id"]
    else:
        saved_id=db.execute("SELECT COALESCE(MAX(id),0)+1 FROM inv_items").fetchone()[0]
        code=code or _next_item_code(db,saved_id)
        # La columna histórica de SQL Server sigue siendo obligatoria.
        db.execute("""INSERT INTO inv_items(id,code,name,category,area,unit,min_qty,warn_days,perishable,transformable)
                      VALUES(?,?,?,N'',?,?,?,?,?,?)""",(saved_id,code,name,area,unit,min_qty,warn_days,perishable,transformable))
    transform_now=_bool(p.get("transform_now",False))
    if transform_now and not p.get("target_id"):
        raise ValueError("Selecciona el producto resultante antes de transformar.")
    result={"id":saved_id,"code":code}
    if p.get("target_id"):
        rule=_rule(db,user,{"source_id":saved_id,"target_id":p["target_id"],
                           "source_qty":p.get("source_qty"),"target_qty":p.get("target_qty")})
        if transform_now:
            transformed=_transform(db,user,{"rule_id":rule["id"],"qty":p.get("transform_qty"),
                                           "expiry":p.get("transform_expiry")})
            result.update(transformed,transformed=True)
    return result


def _change_item_area(db,user,p):
    _role(user,"admin")
    item=_item(db,p.get("id"))
    area=_item_area(p.get("area"))
    _set_item_area(db, item, area)
    return {"id":item["id"],"area":area}


def _configure_item_unit(db,user,p):
    _role(user,"admin")
    item=_item(db,p.get("id"))
    unit=_text(p.get("display_unit"),"unidad de medida",20)
    size=_scaled(p.get("base_per_unit"),1000,"Equivalencia",high=1_000_000_000)
    if p.get("expected_unit_milli",quantity_measure(item)[1])!=quantity_measure(item)[1]:
        raise ValueError("La unidad del insumo cambió. Actualiza antes de continuar.")
    if unit.casefold()==item["unit"].casefold() and size!=1000:
        raise ValueError("Usa un nombre diferente si la nueva unidad tiene otra equivalencia.")
    canonical_potato=potato_quantity_step(item["name"],item["unit"]) and unit.casefold()==item["unit"].casefold()
    measure=(None,None) if canonical_potato else (unit,size)
    db.execute("UPDATE inv_items SET display_unit=?,display_unit_milli=? WHERE id=?",(*measure,item["id"]))
    return {"id":item["id"],"unit":unit}


def _menu_category(db,user,p):
    _role(user,"admin")
    name=_text(p.get("name"),"categoría",120)
    old=p.get("previous")
    if db.execute("SELECT name FROM menu_categories WHERE name=? UNION SELECT category FROM inv_products WHERE category=?",(name,name)).fetchone():
        raise ValueError("Ya existe esa categoría.")
    if old:
        if not db.execute("SELECT name FROM menu_categories WHERE name=? UNION SELECT category FROM inv_products WHERE category=?",(old,old)).fetchone():
            raise ValueError("La categoría cambió. Actualiza la carta.")
        db.execute("UPDATE inv_products SET category=? WHERE category=?",(name,old))
        db.execute("DELETE FROM menu_categories WHERE name=?",(old,))
    db.execute("INSERT INTO menu_categories(name) VALUES(?)",(name,))
    return {}


def _save_product(db, user, p, *, demo=False):
    _role(user, "admin")
    name = _text(p.get("name"), "nombre")
    cat = _text(p.get("category"), "categoría")
    if not db.execute("SELECT name FROM menu_categories WHERE name=?",(cat,)).fetchone():
        db.execute("INSERT INTO menu_categories(name) VALUES(?)",(cat,))
    price = _scaled(p.get("price"), 100, "Precio", high=100_000_000)
    category_key = cat.casefold()
    if category_key == "barra" or "bebid" in category_key:
        default_area = "Barra"
    elif "brasa" in category_key or "parrill" in category_key:
        default_area = "Parrilla"
    else:
        default_area = "Cocina"
    area = _prep_area(p.get("prep_area") or default_area)
    recipe = p.get("recipe")
    if not isinstance(recipe,list) or not 1<=len(recipe)<=100:
        raise ValueError("Agrega entre uno y cien insumos a la receta.")
    previous={}
    if p.get("id"):
        prod = _id(p["id"])
        previous=dict(db.execute("SELECT item_id,amount FROM inv_recipes WHERE product_id=?",(prod,)))
        if not db.execute("UPDATE inv_products SET name=?,category=?,price=?,prep_area=? WHERE id=?", (name,cat,price,area,prod)).rowcount:
            raise ValueError("El producto no existe.")
        db.execute("DELETE FROM inv_recipes WHERE product_id=?", (prod,))
    else:
        prod = db.execute("INSERT INTO inv_products(name,category,price,prep_area) OUTPUT INSERTED.id VALUES(?,?,?,?)", (name,cat,price,area)).lastrowid
    added = set()
    for row in recipe:
        if not isinstance(row,dict):
            raise ValueError("Revisa los insumos de la receta.")
        ingredient = _item(db,row.get("item_id"))
        quantity=row.get("qty")
        measured=isinstance(quantity,dict)
        requested=item_quantity(ingredient["name"],quantity,unit=ingredient["unit"],item=ingredient) if measured else qty(quantity)
        item,amount=porciones.resolve(db,ingredient["id"],requested)
        if not measured and not demo and previous.get(item)!=amount:
            check_item_quantity(ingredient["name"],requested,unit=ingredient["unit"],item=ingredient)
        if item in added:
            raise ValueError("Agrupa las cantidades del mismo insumo en una línea de receta.")
        added.add(item)
        db.execute("INSERT INTO inv_recipes VALUES(?,?,?)",(prod,item,amount))
    return {"id":prod,"code":public("PR",prod)}


def _rule(db,user,p):
    _role(user,"admin")
    source = _item(db,p.get("source_id"))
    target = _item(db,p.get("target_id"))
    if source["id"]==target["id"] or not source["transformable"]:
        raise ValueError("Selecciona un insumo transformable y un producto de destino diferente.")
    existing=db.execute("SELECT source_qty,target_qty FROM inv_rules WHERE source_id=? AND target_id=?",
                        (source["id"],target["id"])).fetchone()
    source_qty=item_quantity(source["name"],p.get("source_qty"),"Cantidad consumida",unit=source["unit"],item=source,
                             previous=existing[0] if existing else None)
    target_qty=item_quantity(target["name"],p.get("target_qty"),"Cantidad producida",unit=target["unit"],item=target,
                             previous=existing[1] if existing else None)
    values=(source_qty,target_qty,source["id"],target["id"])
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
    return db.execute("""SELECT id,revision,reason,request_day FROM inv_cancel_requests
                         WHERE order_id=? AND status='Pendiente'""",(order_id,)).fetchone()


def _has_delivered_details(db, order_id):
    return db.execute("SELECT 1 FROM inv_details WHERE order_id=? AND status='Entregado'",(order_id,)).fetchone() is not None


def _get_order(db,p):
    order = db.execute("SELECT * FROM inv_orders WHERE id=?",(_id(p.get("id")),)).fetchone()
    if not order:
        raise ValueError("El pedido no existe.")
    return order


def _check_version(order, p):
    if p.get("version") is not None and _id(p["version"]) != order["version"]:
        raise ValueError("El pedido cambió en otra sesión. Actualiza antes de continuar.")


def _validate_details(rows,existing):
    seen=set()
    for index,line in enumerate(rows,1):
        number=_id(line.get("detail_no",index))
        if number in seen:
            raise ValueError("Número de detalle repetido.")
        seen.add(number)
        prior=existing.get(number)
        if prior and (prior["status"]=="Cancelado" or prior["remove_pending"]):
            raise ValueError("Añade un detalle nuevo para reemplazar uno retirado.")
        if prior and prior["status"]=="Entregado" and (prior["product_id"],prior["qty"])!=(_id(line["product_id"]),int(line["qty"])):
            raise ValueError("Un detalle entregado no se puede modificar.")
    removed=[detail for number,detail in existing.items() if number not in seen and detail["status"]!="Cancelado"]
    if any(detail["status"]=="Entregado" for detail in removed):
        raise ValueError("Un detalle entregado no se puede eliminar.")
    return removed


def _reserved_quantities(rows,existing,removed):
    totals=defaultdict(int)
    for line in rows:
        prior=existing.get(line["detail_no"])
        if prior and prior["sent_at"]:
            totals[prior["sent_product"]]+=prior["sent_qty"]
        else:
            totals[_id(line["product_id"])]+=int(line["qty"])
    # El área conserva el envío y sus insumos hasta que Atención confirme el retiro.
    for detail in removed:
        if detail["sent_at"]:
            totals[detail["sent_product"]]+=detail["sent_qty"]
    return totals


def _retire_detail(db,order,number):
    db.execute("""UPDATE d SET status='Cancelado',remove_pending=0,revision=revision+1,
                  closed_name=COALESCE(l.name,p.name),closed_price=COALESCE(l.price,p.price)
                  FROM inv_details d JOIN inv_products p ON p.id=d.product_id
                  LEFT JOIN inv_lines l ON l.order_id=d.order_id AND l.product_id=d.product_id
                  WHERE d.order_id=? AND d.detail_no=?""",(order,number))


def _reserve_lines(db,order,requested,old_lines,status):
    unchanged=set()
    # Primero libera todas las líneas retiradas o editadas para que los cambios
    # puedan intercambiar insumos. Las demás conservan sus lotes originales.
    for product_id,line in old_lines.items():
        if status=="Reservado" and requested.get(product_id)==line["qty"]:
            unchanged.add(product_id)
            continue
        _release(db,order,product_id)
        if product_id not in requested:
            db.execute("DELETE FROM inv_lines WHERE order_id=? AND product_id=?",(order,product_id))
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


def _save_order(db,user,p,*,exchange=False):
    _role(user,"atencion","caja","admin")
    confirm_changes=p.get("confirm_changes") is True
    if confirm_changes and (exchange or not p.get("id")):
        raise ValueError("Registra la comanda antes de enviarla a preparación.")
    number_table = None if exchange else _table_number(p.get("table_number", p.get("table_name")))
    table = _text(p.get("table_name"), "mesa o referencia", 60) if exchange else f"Mesa {number_table}"
    rows = p.get("lines")
    if not isinstance(rows,list) or (not rows and (not p.get("id") or exchange)):
        raise ValueError("Selecciona al menos un producto.")
    requested={}
    for line in rows:
        if not isinstance(line,dict):
            raise ValueError("Revisa las líneas del pedido.")
        product_id=_id(line.get("product_id"))
        line["qty"]=_scaled(line.get("qty"),1,"Unidades del plato",high=10000)
        if "detail_no" in line:
            line["detail_no"]=_id(line["detail_no"])
        requested[product_id]=requested.get(product_id,0)+line["qty"]
    old_lines = {}
    closed = False
    if not exchange:
        day_check=_get_order(db,p)["day"] if p.get("id") else business_day(db)
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
        _check_version(o,p)
        order=o["id"]
        old_lines={l["product_id"]:l for l in db.execute("SELECT * FROM inv_lines WHERE order_id=?",(order,))}
        details={r["detail_no"]:dict(r) for r in db.execute("SELECT * FROM inv_details WHERE order_id=?",(order,))}
        if details and p.get("version") is None:
            raise ValueError("Actualiza la comanda antes de editarla.")
        if details and not all("detail_no" in line for line in rows):
            raise ValueError("Actualiza la aplicación antes de editar los detalles.")
        take_away=_bool(p.get("take_away",o["take_away"]))
        active=[d for d in details.values() if d["status"]!="Cancelado"]
        if take_away!=o["take_away"] and active and all(d["status"]=="Entregado" for d in active):
            raise ValueError("El pedido ya fue entregado. La modalidad de consumo está bloqueada.")
        removed=_validate_details(rows,details)
        was_sent=any(detail["sent_at"] for detail in details.values())
        if confirm_changes and not was_sent:
            raise ValueError("Envía la comanda a preparación después de guardar los cambios.")
        if not rows and not was_sent:
            raise ValueError("Usa Anular comanda para cerrar un pedido que aún no se envió.")
        if not confirm_changes:
            requested=_reserved_quantities(rows,details,removed)
        for detail in removed:
            number=detail["detail_no"]
            if confirm_changes or not detail["sent_at"]:
                _retire_detail(db,order,number)
            elif not detail["remove_pending"]:
                db.execute("""UPDATE inv_details SET remove_pending=1,product_id=sent_product,qty=sent_qty
                              WHERE order_id=? AND detail_no=?""",(order,number))
        closed=not requested
        db.execute("UPDATE inv_orders SET table_name=?,table_number=?,take_away=?,status=?,version=version+1 WHERE id=?",
                   (table,number_table,take_away,"Cancelado" if closed else "Reservado",order))
    else:
        timestamp=now()
        day=business_day(db)
        if p.get("expected_day",day)!=day:
            raise ValueError("Cambió la jornada. Actualiza la comanda antes de registrarla.")
        number=_next_order_number(db,day)
        order=db.execute("""INSERT INTO inv_orders(table_name,table_number,status,created,operator,user_id,day,number,take_away) OUTPUT INSERTED.id
                            VALUES(?,?,'Reservado',?,?,?,?,?,?)""",(table,number_table,timestamp,user["name"],user["id"],day,number,_bool(p.get("take_away",False)))).lastrowid
    if not p.get("id"):
        details={}
        _validate_details(rows,details)
    _reserve_lines(db,order,requested,old_lines,o["status"] if p.get("id") else "Reservado")
    for index,line in enumerate(rows,1):
        number=_id(line.get("detail_no",index))
        args=(_id(line["product_id"]),int(line["qty"]),order,number)
        if number in details:
            db.execute("UPDATE inv_details SET product_id=?,qty=? WHERE order_id=? AND detail_no=?",args)
        else:
            db.execute("INSERT INTO inv_details(product_id,qty,order_id,detail_no) VALUES(?,?,?,?)",args)
    if confirm_changes:
        if not closed:
            _dispatch_details(db,user,order,_pending_dispatch(_preparation_details(db,order)))
        _record_retired_details(db,user,order,[d for d in removed if d["sent_at"]])
    _event(db,user,order,"Cancelado" if closed else "Modificado" if old_lines else "Reservado")
    saved=db.execute("SELECT number,day FROM inv_orders WHERE id=?",(order,)).fetchone()
    return {"id":order,"code":public("C",saved["number"]),"day":saved["day"],"cerrada":closed}


def _close_details(db,order):
    delivered={pid:qty for pid,qty in db.execute("""SELECT sent_product,SUM(sent_qty) FROM inv_details
                  WHERE order_id=? AND status='Entregado' GROUP BY sent_product""",(order,))}
    if not delivered:
        raise ValueError("Debe haber productos entregados antes de cerrar la venta.")
    db.execute("""UPDATE d SET closed_name=COALESCE(d.closed_name,l.name,p.name),closed_price=COALESCE(d.closed_price,l.price,p.price),remove_pending=0,
                  status=CASE WHEN d.status='Entregado' THEN d.status ELSE 'Cancelado' END
                  FROM inv_details d JOIN inv_products p ON p.id=d.product_id
                  LEFT JOIN inv_lines l ON l.order_id=d.order_id AND l.product_id=d.product_id WHERE d.order_id=?""",(order,))
    return delivered


def _payment_breakdown(payload, total):
    if "payments" not in payload:
        method = payload.get("payment_method", "Efectivo")
        if method not in PAYMENT_METHODS:
            raise ValueError("Selecciona un medio de pago válido.")
        return [(method, total)]

    entries = payload["payments"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= len(PAYMENT_METHODS):
        raise ValueError("Indica los medios de pago y sus importes.")

    payments = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Revisa el detalle del pago.")
        method, cents = entry.get("method"), entry.get("cents")
        if method not in PAYMENT_METHODS or method in payments:
            raise ValueError("Selecciona medios de pago válidos y distintos.")
        if type(cents) is not int or cents <= 0:
            raise ValueError("Cada medio utilizado debe tener un importe mayor que cero.")
        payments[method] = cents
    if sum(payments.values()) != total:
        raise ValueError("Los importes por medio deben sumar el total a cobrar.")
    return list(payments.items())


def _pay(db,user,p,*,exchange=False):
    _role(user,"caja","admin")
    o=_get_order(db,p)
    if o["status"]=="Anulada":
        raise ValueError("La venta está anulada.")
    if o["paid_at"]:
        sale_id=db.execute("SELECT id FROM inv_sales WHERE order_id=?",(o["id"],)).fetchone()[0]
        return {"id":o["id"],"sale_code":public("V",sale_id)}
    if o["status"] not in ("Reservado","Por revisar"):
        raise ValueError("La comanda debe estar abierta antes del cobro.")
    _check_version(o,p)
    if not exchange:
        if _pending_cancel(db,o["id"]):
            raise ValueError("La comanda tiene una cancelación pendiente; primero debe resolverse.")
        delivered=_close_details(db,o["id"])
        lines={l["product_id"]:l for l in db.execute("SELECT * FROM inv_lines WHERE order_id=?",(o["id"],))}
        _reserve_lines(db,o["id"],delivered,lines,o["status"])
    parts=db.execute("""SELECT a.lot_id,SUM(a.amount),l.expiry FROM inv_alloc a JOIN inv_lots l ON l.id=a.lot_id
                        WHERE a.order_id=? GROUP BY a.lot_id,l.expiry""",(o["id"],)).fetchall()
    if not parts or any(expiry and expiry<today() for _,_,expiry in parts):
        raise ValueError("La reserva venció. Revisa los insumos y vuelve a guardar el pedido.")
    day=business_day(db)
    if p.get("expected_day",day)!=day:
        raise ValueError("Cambió la jornada de caja. Actualiza antes de cobrar.")
    amount=db.execute("SELECT SUM(qty*price) FROM inv_lines WHERE order_id=?",(o["id"],)).fetchone()[0]
    if p.get("expected_cents",amount)!=amount:
        raise ValueError("Cambió el importe. Revisa el total antes de cobrar.")
    payments = [] if exchange else _payment_breakdown(p, amount)
    method = "Cambio" if exchange else payments[0][0] if len(payments)==1 else "Mixto"
    sale_id=db.execute("INSERT INTO inv_sales(order_id,payment_method,cash_day) OUTPUT INSERTED.id VALUES(?,?,?)",(o["id"],method,day)).lastrowid
    if payments:
        db.executemany("INSERT INTO inv_sale_payments(sale_id,method,cents) VALUES(?,?,?)",
                       ((sale_id, method, cents) for method,cents in payments))
    sale_code=public("V",sale_id)
    for lot,amount,_ in parts:
        db.execute("UPDATE inv_lots SET reserved=reserved-? WHERE id=?",(amount,lot))
        _move(db,user,lot,-amount,"Venta",f"{sale_code} · {_order_ref(o)}")
    db.execute("UPDATE inv_orders SET status='Cobrado',paid_at=?,cashier=?,version=version+1 WHERE id=?",
               (now(),user["name"],o["id"]))
    _event(db,user,o["id"],"Cobrado")
    return {"id":o["id"],"sale_code":sale_code}


def _void_sale(db,user,p):
    _role(user,"caja","admin")
    raise ValueError("Envía una solicitud y resuélvela desde Solicitudes y devoluciones.")


def _paid_order_lines(db,order_id):
    return {r["product_id"]:r for r in db.execute("""SELECT l.* FROM inv_lines l
                     JOIN inv_sales s ON s.order_id=l.order_id WHERE l.order_id=? AND l.qty>0""",(order_id,))}


def _approve_paid_cancel(db,user,order,request,restock,day):
    oid=order["id"]
    lines=_paid_order_lines(db,oid)
    if order["status"] not in ("Cobrado","Devuelto") or not lines:
        raise ValueError("La comanda no tiene un cobro registrado que se pueda anular.")
    cents=sum(line["price"]*(line["qty"]-line["refunded"]) for line in lines.values())
    at=now()
    db.execute("INSERT sale_voids(order_id,cash_day,at,actor,reason,cents,cancel_request_id) VALUES(?,?,?,?,?,?,?)",
               (oid,day,at,user["name"],request["reason"],cents,request["id"]))
    if restock:
        _restore_paid_cancel_stock(db,user,order,lines,restock)
    db.execute("""UPDATE refund_requests SET status='Rechazada',decision_reason='Venta anulada',
                  decided_by=?,decided_at=?,voided_by_cancel_id=?,revision=revision+1 WHERE order_id=? AND status='Pendiente'""",
               (user["name"],at,request["id"],oid))
    db.execute("UPDATE inv_orders SET status='Anulada',version=version+1 WHERE id=?",(oid,))
    _event(db,user,oid,"Venta anulada",request["reason"])
    return cents


def _cancel(db,user,p):
    _role(user,"caja","admin","atencion")
    o=_get_order(db,p)
    if _pending_cancel(db,o["id"]):
        raise ValueError("La cancelación pendiente debe aprobarse o rechazarse primero.")
    if o["status"]=="Cancelado":
        return {"id":o["id"]}
    if o["status"] not in ("Por revisar","Reservado"):
        raise ValueError("Para anular una venta cobrada, envía una solicitud de anulación.")
    _check_version(o,p)
    if _has_delivered_details(db,o["id"]):
        raise ValueError("La comanda tiene productos entregados. Solicita la anulación para que Caja la revise.")
    _release(db,o["id"])
    db.execute("""UPDATE inv_details SET status='Cancelado',remove_pending=0,revision=revision+1
                  WHERE order_id=? AND ISNULL(status,'')<>'Cancelado'""",(o["id"],))
    db.execute("UPDATE inv_orders SET status='Cancelado',version=version+1 WHERE id=?",(o["id"],))
    _event(db,user,o["id"],"Cancelado")
    return {"id":o["id"]}


def _returned_detail_totals(db,order_id=None):
    query="""SELECT d.order_id,d.detail_no,SUM(d.qty) FROM inv_return_details d
             LEFT JOIN refund_reversals r ON r.return_id=d.return_id WHERE r.return_id IS NULL"""
    args=()
    if order_id is not None:
        query+=" AND d.order_id=?"
        args=(order_id,)
    return {(oid,number):qty for oid,number,qty in db.execute(query+" GROUP BY d.order_id,d.detail_no",args)}


def _detail_refundable(details,returned,refunded):
    available={}
    legacy=refunded-sum(returned.get(d["detail_no"],0) for d in details)
    for d in sorted(details,key=lambda d:d["detail_no"]):
        number=d["detail_no"]
        remaining=d["qty"]-returned.get(number,0)
        already_returned=min(remaining,legacy)
        available[number]=remaining-already_returned
        legacy-=already_returned
    return available


def _sold_lots(db,order_id,product_id):
    grouped=defaultdict(list)
    for r in db.execute("""SELECT a.*,l.item_id,l.expiry FROM inv_alloc a JOIN inv_lots l ON l.id=a.lot_id
                           WHERE a.order_id=? AND a.product_id=?
                           ORDER BY CASE WHEN l.expiry IS NULL THEN 1 ELSE 0 END,l.expiry,l.id""",(order_id,product_id)):
        grouped[r["item_id"]].append(r)
    return grouped


def _restore_paid_cancel_stock(db,user,order,lines,selected):
    oid=order["id"]
    details=defaultdict(list)
    for d in db.execute("""SELECT detail_no,product_id,qty FROM inv_details
                           WHERE order_id=? AND (status='Entregado' OR status IS NULL)""",(oid,)):
        details[d["product_id"]].append(d)
    returned={number:qty for (_,number),qty in _returned_detail_totals(db,oid).items()}
    units=defaultdict(int)
    unmatched=set(selected)
    for pid,line in lines.items():
        for number,remaining in _detail_refundable(details[pid],returned,line["refunded"]).items():
            if number in selected and remaining>0:
                units[pid]+=remaining
                unmatched.discard(number)
    if unmatched:
        raise ValueError("Selecciona únicamente detalles cobrados con unidades pendientes de reposición.")
    restored=defaultdict(int)
    for pid,qty in units.items():
        line=lines[pid]
        lots=_sold_lots(db,oid,pid)
        if not lots:
            raise ValueError("El detalle no tiene lotes registrados para reponer.")
        for parts in lots.values():
            needed=sum(r["amount"] for r in parts)//line["qty"]*qty
            for r in parts:
                take=min(needed,r["amount"]-r["processed"])
                if take:
                    if r["expiry"] and r["expiry"]<today():
                        raise ValueError("El lote original venció. Revisa qué detalles pueden volver al inventario.")
                    _move(db,user,r["lot_id"],take,"Reposición por anulación de venta",_order_ref(order))
                    restored[r["lot_id"]]+=take
                    needed-=take
                if not needed:
                    break
            if needed:
                raise ValueError("No se pudo calcular la reposición del detalle.")
    db.executemany("INSERT INTO sale_void_stock(order_id,lot_id,amount) VALUES(?,?,?)",
                   ((oid,lot,amount) for lot,amount in restored.items()))


def _refund(db,user,p,*,resolving=0):
    _role(user,"caja","admin")
    o=_get_order(db,p)
    if o["status"]!="Cobrado":
        raise ValueError("Selecciona una venta cobrada con unidades pendientes de devolución.")
    _check_version(o,p)
    if _pending_cancel(db,o["id"]):
        raise ValueError("Resuelve la solicitud de anulación antes de registrar una devolución.")
    pid=_id(p.get("product_id"))
    n=_scaled(p.get("qty"),1,"Unidades a devolver",high=1_000_000_000 if p.get("details") is not None else 10000)
    reason=_text(p.get("reason"),"motivo",300)
    line=db.execute("SELECT * FROM inv_lines WHERE order_id=? AND product_id=?",(o["id"],pid)).fetchone()
    if not line or n>line["qty"]-line["refunded"]:
        raise ValueError("La cantidad excede las unidades cobradas pendientes de devolución.")
    held=db.execute("""SELECT COALESCE(SUM(qty),0) FROM refund_requests
                       WHERE order_id=? AND product_id=? AND status='Pendiente' AND id<>?""",(o["id"],pid,resolving)).fetchone()[0]
    if n>line["qty"]-line["refunded"]-held:
        raise ValueError("Hay unidades con una solicitud pendiente. Resuélvela desde Solicitudes y devoluciones.")
    details=p.get("details")
    restock_units=None
    if details is not None:
        if not isinstance(details,list) or not details:
            raise ValueError("Selecciona los detalles de la comanda que deseas devolver.")
        original=list(db.execute("""SELECT detail_no,qty FROM inv_details WHERE order_id=? AND product_id=?
                                   AND (status='Entregado' OR status IS NULL)""",(o["id"],pid)))
        returned={number:units for (_,number),units in _returned_detail_totals(db,o["id"]).items()}
        available=_detail_refundable(original,returned,line["refunded"])
        picked={}
        for d in details:
            if not isinstance(d,dict):
                raise ValueError("Revisa los detalles de la devolución.")
            number=_id(d.get("detail_no"))
            units=_scaled(d.get("qty"),1,"Unidades a devolver",high=10000)
            if number in picked or units>available.get(number,0) or type(d.get("restock")) is not bool:
                raise ValueError("Revisa las unidades y la reposición de cada detalle.")
            picked[number]=(units,d["restock"])
        if sum(units for units,_ in picked.values())!=n:
            raise ValueError("La cantidad no coincide con los detalles seleccionados.")
        restock_units=sum(units for units,restore in picked.values() if restore)
    restock=p.get("restock",[])
    if not isinstance(restock,list):
        raise ValueError("Revisa la selección de insumos recuperables.")
    restock={_id(v) for v in restock}
    grouped=_sold_lots(db,o["id"],pid)
    if resolving and details is None and "restock" not in p:
        restock=set(grouped)
    if not restock.issubset(grouped):
        raise ValueError("Solo se pueden devolver insumos de esta venta.")
    return_id=db.execute("""INSERT INTO inv_returns(order_id,product_id,qty,reason,at,operator,cash_day) OUTPUT INSERTED.id
                            VALUES(?,?,?,?,?,?,?)""",(o["id"],pid,n,reason,now(),user["name"],business_day(db))).lastrowid
    if details is not None:
        db.executemany("INSERT INTO inv_return_details(return_id,order_id,detail_no,qty,restock) VALUES(?,?,?,?,?)",
                       ((return_id,o["id"],number,units,restore) for number,(units,restore) in picked.items()))
    return_code=public("DV",return_id)
    for item,parts in grouped.items():
        per_unit=sum(r["amount"] for r in parts)//line["qty"]
        needed=per_unit*n
        restore=per_unit*(restock_units if restock_units is not None else n if item in restock else 0)
        for r in parts:
            take=min(needed,r["amount"]-r["processed"])
            if not take:
                continue
            restocked=min(take,restore)
            if restocked:
                if (not resolving or details is not None) and r["expiry"] and r["expiry"]<today():
                    raise ValueError("El lote original venció. Revisa los detalles marcados para volver al inventario.")
                _move(db,user,r["lot_id"],restocked,"Devolución · "+reason,f"{return_code} · {_order_ref(o)}")
                restore-=restocked
            if resolving:
                db.execute("INSERT refund_parts(return_id,lot_id,amount,restocked) VALUES(?,?,?,?)",
                           (return_id,r["lot_id"],take,restocked))
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


def _refund_order(db,user,p):
    _role(user,"caja","admin")
    order=_get_order(db,p)
    _check_version(order,p)
    if order["status"]!="Cobrado":
        raise ValueError("Selecciona una venta cobrada con unidades pendientes de devolución.")
    if p.get("expected_day")!=business_day(db):
        raise ValueError("Cambió la jornada de caja. Actualiza antes de devolver.")
    entries=p.get("details")
    if not isinstance(entries,list) or not entries:
        raise ValueError("Selecciona al menos un detalle para devolver.")
    reason=_text(p.get("reason"),"motivo",300)
    products=dict(db.execute("""SELECT detail_no,product_id FROM inv_details
                               WHERE order_id=? AND (status='Entregado' OR status IS NULL)""",(order["id"],)))
    grouped=defaultdict(list)
    for d in entries:
        number=_id(d.get("detail_no")) if isinstance(d,dict) else None
        if number not in products:
            raise ValueError("Selecciona detalles cobrados de esta comanda.")
        grouped[products[number]].append(d)
    quantities={pid:sum(_scaled(d.get("qty"),1,"Unidades a devolver",high=10000) for d in details)
                for pid,details in grouped.items()}
    if p.get("whole") is True:
        remaining=dict(db.execute("""SELECT product_id,qty-refunded FROM inv_lines
                                    WHERE order_id=? AND qty>refunded""",(order["id"],)))
        if quantities!=remaining:
            raise ValueError("La selección debe cubrir todos los detalles pendientes de devolución.")
    codes=[]
    for pid,details in grouped.items():
        result=_refund(db,user,{"id":order["id"],"product_id":pid,"qty":quantities[pid],"reason":reason,"details":details})
        codes.append(result["return_code"])
    return {"id":order["id"],"return_codes":codes}


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



def _preparation_details(db,order):
    return [dict(r) for r in db.execute("""SELECT d.*,p.prep_area FROM inv_details d JOIN inv_products p
                   ON p.id=d.product_id WHERE d.order_id=? AND ISNULL(d.status,'')<>'Cancelado'""",(order,))]


def _pending_dispatch(details):
    return [d for d in details if d.get("status")!="Entregado" and not d["remove_pending"]
            and (d["product_id"],d["qty"])!=(d["sent_product"],d["sent_qty"])]


def _dispatch_details(db,user,order,details):
    if not details:
        return
    at=now()
    for d in details:
        db.execute("""UPDATE inv_details SET sent_product=product_id,sent_qty=qty,area=?,status='En cola',
                   sent_at=?,started_at=NULL,ready_at=NULL,revision=revision+1 WHERE order_id=? AND detail_no=?""",
                   (_prep_area(d["prep_area"]),at,order,d["detail_no"]))
    _event(db,user,order,"Enviado a preparación",f"{len(details)} productos")


def _record_retired_details(db,user,order,details):
    if details:
        _event(db,user,order,"Retirado de preparación",f"{len(details)} detalles")


def _send_to_areas(db,user,p):
    _role(user,"admin","caja","atencion")
    o=_get_order(db,p)
    _check_version(o,p)
    if o["status"] != "Reservado" or _pending_cancel(db,o["id"]):
        raise ValueError("La comanda debe estar abierta, sin solicitud de cancelación.")
    details=_preparation_details(db,o["id"])
    removed=[d for d in details if d["remove_pending"]]
    active=[d for d in details if not d["remove_pending"]]
    lines=_pending_dispatch(active)
    if not lines and not removed:
        raise ValueError("No hay detalles pendientes de envío.")
    totals=defaultdict(int)
    for d in active:
        totals[d["product_id"]]+=d["qty"]
    for detail in removed:
        _retire_detail(db,o["id"],detail["detail_no"])
    old={l["product_id"]:l for l in db.execute("SELECT * FROM inv_lines WHERE order_id=?",(o["id"],))}
    _reserve_lines(db,o["id"],totals,old,o["status"])
    _dispatch_details(db,user,o["id"],lines)
    db.execute("UPDATE inv_orders SET status=?,version=version+1 WHERE id=?",
               ("Reservado" if active else "Cancelado",o["id"]))
    _record_retired_details(db,user,o["id"],removed)
    return {"id":o["id"],"enviados":len(lines),"retirados":len(removed),"cerrada":not active}


def _advance_preparation(db,user,p):
    _role(user,"admin","area")
    o=_get_order(db,p)
    pid=_id(p.get("product_id"))
    number=_id(p.get("detail_no"))
    task=db.execute("SELECT * FROM inv_details WHERE order_id=? AND detail_no=? AND sent_product=?",(o["id"],number,pid)).fetchone()
    if not task:
        raise ValueError("El producto no fue enviado a preparación.")
    if not _may_work(user,task["area"]):
        raise PermissionError("No puedes consultar ni entregar pedidos de otra área.")
    if task["revision"]!=p.get("revision"):
        raise ValueError("Este envío cambió. Actualiza la cola antes de continuar.")
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
    changed=db.execute(f"UPDATE inv_details SET status=?,{column}=?,delivered_by=CASE WHEN ?='entregar' THEN ? ELSE delivered_by END WHERE order_id=? AND detail_no=? AND status=?",
               (after,now(),action,user["name"],o["id"],number,before)).rowcount
    if not changed:
        raise ValueError("Otro empleado ya actualizó el estado.")
    db.execute("UPDATE inv_orders SET version=version+1 WHERE id=?",(o["id"],))
    if action=="entregar":
        # La entrega confirma exactamente lo que recibió el área, incluso si existe un cambio sin enviar.
        db.execute("UPDATE inv_details SET product_id=sent_product,qty=sent_qty,remove_pending=0 WHERE order_id=? AND detail_no=?",(o["id"],number))
    _event(db,user,o["id"],after,f"{task['area']} · producto {pid}")
    return {"id":o["id"],"estado":after}


def _ask_cancel(db,user,p):
    _role(user,"admin","caja","atencion")
    o=_get_order(db,p)
    _check_version(o,p)
    if o["paid_at"] and o["status"] in ("Cobrado","Devuelto"):
        if user["role"]=="atencion" and o["user_id"]!=user["id"]:
            raise PermissionError("Solo puedes solicitar la anulación de tus comandas cobradas.")
        if not _paid_order_lines(db,o["id"]):
            raise ValueError("La comanda debe tener al menos un detalle cobrado.")
    elif o["status"] not in ("Reservado","Por revisar"):
        raise ValueError("La comanda ya está anulada o cerrada.")
    elif not _has_delivered_details(db,o["id"]):
        raise ValueError("La solicitud requiere un producto entregado. Anula la comanda directamente desde Comandas.")
    if _pending_cancel(db,o["id"]):
        raise ValueError("Ya existe una solicitud de cancelación pendiente.")
    reason=_text(p.get("reason"),"motivo",500)
    cid=db.execute("""INSERT INTO inv_cancel_requests(order_id,status,reason,requester,requested_at,requester_id,request_day)
                       OUTPUT INSERTED.id VALUES(?,'Pendiente',?,?,?,?,?)""",(o["id"],reason,user["name"],now(),user["id"],business_day(db))).lastrowid
    _event(db,user,o["id"],"Cancelación solicitada",reason)
    return {"id":o["id"],"solicitud_id":cid}


def _consume_cancelled_deliveries(db,user,order,request_id,details,restock):
    units=defaultdict(int)
    for detail in details:
        if detail["detail_no"] not in restock:
            units[detail["sent_product"]]+=detail["sent_qty"]
    consumed=defaultdict(int)
    for pid,n in units.items():
        recipe=db.execute("SELECT item_id,amount FROM inv_line_recipes WHERE order_id=? AND product_id=?",
                          (order["id"],pid)).fetchall()
        if not recipe:
            raise ValueError("Falta la receta de un detalle entregado.")
        for item,amount in recipe:
            for lot,take,_ in withdraw(db,user,item,amount*n,"Entrega en comanda anulada",_order_ref(order)):
                consumed[lot]+=take
    db.executemany("INSERT INTO cancel_consumption(request_id,lot_id,amount) VALUES(?,?,?)",
                   ((request_id,lot,amount) for lot,amount in consumed.items()))


def _decide_cancel(db,user,p):
    _role(user,"admin","caja")
    o=_get_order(db,p)
    r=_pending_cancel(db,o["id"])
    if not r or p.get("request_id",r["id"])!=r["id"]:
        raise ValueError("Actualiza la solicitud de cancelación antes de resolverla.")
    if p.get("revision",r["revision"])!=r["revision"]:
        raise ValueError("La solicitud cambió. Actualiza antes de resolverla.")
    approved=p.get("approve")
    if type(approved) is not bool:
        raise ValueError("Indica si apruebas o rechazas la solicitud.")
    day=business_day(db)
    if p.get("expected_day",day)!=day or (r["request_day"] and day!=r["request_day"]):
        raise ValueError("Abre la jornada de la solicitud antes de resolverla.")
    cents=None
    if approved and o["paid_at"]:
        selected=p.get("restock_details",[])
        if not isinstance(selected,list):
            raise ValueError("Indica cuáles detalles cobrados regresan al inventario.")
        cents=_approve_paid_cancel(db,user,o,r,{_id(number) for number in selected},day)
    elif approved:
        delivered=list(db.execute("""SELECT detail_no,sent_product,sent_qty FROM inv_details
                                    WHERE order_id=? AND status='Entregado'""",(o["id"],)))
        selected=p.get("restock_details",[] if not delivered else None)
        if not isinstance(selected,list):
            raise ValueError("Indica qué detalles entregados regresan al inventario.")
        restock={_id(number) for number in selected}
        if not restock.issubset(d["detail_no"] for d in delivered):
            raise ValueError("Selecciona únicamente detalles entregados de esta comanda.")
        _release(db,o["id"])
        if delivered:
            _consume_cancelled_deliveries(db,user,o,r["id"],delivered,restock)
        db.execute("UPDATE inv_orders SET status='Cancelado',version=version+1 WHERE id=?",(o["id"],))
    db.execute("UPDATE inv_cancel_requests SET status=?,decided_at=?,decided_by=?,decision_reason=?,prior_status=?,revision=revision+1 WHERE id=?",
               ("Aprobada" if approved else "Rechazada",now(),user["name"],
                _text(p["reason"],"observación",300) if p.get("reason") else None,o["status"],r["id"]))
    _event(db,user,o["id"],"Cancelación aprobada" if approved else "Cancelación rechazada")
    result={"id":o["id"],"aprobada":approved}
    if cents is not None:
        result["void_cents"]=cents
    return result


def _preparation(db,user):
    if user["role"] not in ("admin","area"):
        return []
    query="""SELECT d.order_id,d.detail_no,d.revision,d.sent_product AS product_id,d.area,d.status,d.sent_at,d.started_at,d.ready_at,
            d.delivered_at,d.delivered_by,o.number,o.day,o.table_number,o.take_away,l.name,d.sent_qty AS qty,
            CASE WHEN EXISTS (SELECT 1 FROM inv_cancel_requests cr WHERE cr.order_id=o.id AND cr.status='Pendiente')
                 THEN 1 ELSE 0 END AS cancel_pending
            FROM inv_details d JOIN inv_orders o ON o.id=d.order_id
            JOIN inv_lines l ON l.order_id=d.order_id AND l.product_id=d.sent_product
            WHERE o.status='Reservado' AND d.status<>'Cancelado'"""
    params=[]
    if user["role"]=="area":
        query+=" AND d.area=?"
        params.append(_area(user))
    query+=" ORDER BY d.sent_at,d.order_id,d.detail_no"
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
    restricted=user["role"] not in ("admin","caja","recepcion")
    if restricted:
        history_areas={name.casefold() for name in (*inventory_access_areas(user),_area(user)) if name}
        if area and area.casefold() not in history_areas:
            raise PermissionError("El insumo pertenece a otra área.")
        area_keys=sorted(history_areas) if not area else [area.casefold()]
        if not area_keys:
            return []
        placeholders=",".join("?" for _ in area_keys)
        area_filter=f"LOWER(c.area) IN ({placeholders})"
        conditions.append(area_filter)
        args.extend(area_keys)
    elif area:
        conditions.append("c.area=?")
        args.append(area)
    if p.get("item_id"):
        source_id,_=porciones.resolve(db,_id(p["item_id"]),0)
        item=_item(db,source_id)
        if restricted and item["area"].casefold() not in area_keys:
            previous=db.execute("""SELECT 1 FROM inv_move_context c JOIN inv_moves m ON m.id=c.move_id
                                   JOIN inv_lots l ON l.id=m.lot_id WHERE """+area_filter+" AND l.item_id=?",
                                (*area_keys,item["id"])).fetchone()
            if not previous:
                raise PermissionError("El insumo pertenece a otra área.")
        conditions.append("i.id=?")
        args.append(item["id"])
    query="""SELECT m.id,m.at,m.lot_id,m.delta AS qty,m.reason,m.ref,m.operator,
             c.item_name AS item,i.id AS item_id,c.area,i.unit,i.display_unit,i.display_unit_milli FROM inv_moves m JOIN inv_lots l ON l.id=m.lot_id
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


def _products(db,balances,all_items):
    items={item["id"]:item for item in all_items}
    shared_items={item["base_id"] for item in all_items if "base_id" in item}
    recipes=defaultdict(list)
    for p,i,n in db.execute("SELECT product_id,item_id,amount FROM inv_recipes ORDER BY product_id,item_id"):
        recipes[p].append((i,n))
    products=[]
    for row in db.execute("SELECT * FROM inv_products ORDER BY id"):
        prod=dict(row)
        prod["code"]=public("PR",row["id"])
        raw=recipes[prod["id"]]
        prod["available"]=min((balances[i]//n for i,n in raw),default=0)
        prod["recipe"]=[{
            "item_id":i, "qty":num(n), "available":items[i]["available"],
            "name":items[i]["name"], "unit":items[i]["unit"], "shared_stock":i in shared_items,
            "display_unit":items[i].get("display_unit"), "display_unit_milli":items[i].get("display_unit_milli"),
        } for i,n in raw]
        prod["price"]/=100
        products.append(prod)
    return products


def _orders(db,user,balances):
    if user["role"] not in ("admin","caja","atencion"):
        return []
    attending=user["role"]=="atencion"
    sql="SELECT o.* FROM inv_orders o"
    scope=""
    scope_args=()
    if attending:
        scope=""" WHERE o.status IN ('Reservado','Por revisar')
                    OR (o.user_id=? AND o.paid_at IS NOT NULL AND o.status IN ('Cobrado','Devuelto'))"""
        scope_args=(user["id"],)
    rows={r["id"]:dict(r) for r in db.execute(sql+scope+" ORDER BY o.id DESC",scope_args)}
    if not rows:
        return []
    returned_details={} if attending else _returned_detail_totals(db)
    for r in rows.values():
        r["code"]=public("C",r["number"])
        r.update(lines=[],total=0,gross=0)
        if not attending:
            r.update(sale_code=None,returns=[])
    if not attending:
        payments=defaultdict(list)
        for sale_id,method,cents in db.execute("SELECT sale_id,method,cents FROM inv_sale_payments ORDER BY sale_id,method"):
            payments[sale_id].append({"method":method,"cents":cents})
        for sale_id,order_id,method,day in db.execute("SELECT id,order_id,payment_method,cash_day FROM inv_sales"):
            rows[order_id]["cash_day"]=day
            rows[order_id]["payment_method"]=method or "Sin especificar"
            rows[order_id]["payments"]=payments[sale_id]
            rows[order_id]["sale_code"]=public("V",sale_id)
        for v in db.execute("SELECT * FROM sale_voids"):
            rows[v["order_id"]]["sale_void"]=dict(v)
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
        credits=db.execute("""SELECT r.id,r.order_id,r.product_id,r.qty,r.reason,r.at,r.cash_day,r.operator,l.name,v.at AS undone_at,v.cash_day AS undone_day,v.actor AS undone_by
                              FROM inv_returns r JOIN inv_lines l ON l.order_id=r.order_id AND l.product_id=r.product_id
                              LEFT JOIN refund_reversals v ON v.return_id=r.id ORDER BY r.id""")
        for credit in credits:
            detail=dict(credit)
            detail.update(linked.get(credit["id"],{}))
            detail["code"]=public("DV",detail.pop("id"))
            rows[detail.pop("order_id")]["returns"].append(detail)
    for order in rows.values():
        order["details"]=[]
    for row in db.execute("""SELECT d.*,COALESCE(d.closed_name,l.name,p.name) AS name,COALESCE(d.closed_price,l.price,p.price) AS price FROM inv_details d
          JOIN inv_products p ON p.id=d.product_id LEFT JOIN inv_lines l ON l.order_id=d.order_id
          AND l.product_id=d.product_id ORDER BY d.order_id,d.detail_no"""):
        if row["order_id"] in rows:
            d=dict(row)
            d["price"]/=100
            d["pending"]=d["status"]!="Cancelado" and (d["remove_pending"] or (d["product_id"],d["qty"])!=(d["sent_product"],d["sent_qty"]))
            rows[d["order_id"]]["details"].append(d)
    pending={r["order_id"]:dict(r) for r in db.execute("SELECT order_id,id,revision,reason,requested_at FROM inv_cancel_requests WHERE status='Pendiente'")}
    for o in rows.values():
        o["cancel_request"]=pending.get(o["id"])
        o["table_number"]=o.get("table_number")
        o["floor"]=(1 if o["table_number"]<=10 else 2) if o["table_number"] else None
    line_sql="SELECT l.* FROM inv_lines l JOIN inv_orders o ON l.order_id=o.id"
    part_sql="""SELECT a.order_id,a.product_id,l.item_id,i.name,i.unit,SUM(a.amount) AS n FROM inv_alloc a
                JOIN inv_lots l ON l.id=a.lot_id JOIN inv_items i ON i.id=l.item_id JOIN inv_orders o ON o.id=a.order_id"""
    if attending:
        part_sql+=" WHERE o.status IN ('Reservado','Por revisar')"
    ingredients=defaultdict(list)
    for row in db.execute(part_sql+" GROUP BY a.order_id,a.product_id,l.item_id,i.name,i.unit"):
        ingredients[(row["order_id"],row["product_id"])].append(
            {"item_id":row["item_id"],"name":row["name"],"unit":row["unit"],"qty":num(row["n"])})
    capacity={}
    saved_recipes=defaultdict(list)
    for oid,pid,item_id,unit_amount in db.execute("""SELECT r.order_id,r.product_id,r.item_id,r.amount
            FROM inv_line_recipes r JOIN inv_orders o ON o.id=r.order_id WHERE o.status IN ('Reservado','Por revisar')"""):
        key=(oid,pid)
        units=balances[item_id]//unit_amount
        capacity[key]=min(units,capacity.get(key,units))
        saved_recipes[key].append({"item_id":item_id,"qty":num(unit_amount),"available":num(balances[item_id])})
    detail_groups=defaultdict(list)
    for order in rows.values():
        for d in order["details"]:
            if d["status"]!="Cancelado":
                detail_groups[(order["id"],d["product_id"])].append(d)
    for row in db.execute(line_sql+scope+" ORDER BY l.order_id,l.product_id",scope_args):
        line=dict(row)
        order=rows[line.pop("order_id")]
        order["gross"]+=line["price"]*line["qty"]
        order["total"]+=line["price"]*(line["qty"]-line["refunded"])
        line["price"]/=100
        key=(order["id"],line["product_id"])
        line["ingredients"]=ingredients[key]
        group=detail_groups[key]
        line["prep_status"]="Entregado" if group and all(d["status"]=="Entregado" for d in group) else "Pendiente"
        if not attending and order["status"]=="Cobrado":
            candidates=[d for d in group if d["status"] in ("Entregado",None)]
            returned={d["detail_no"]:returned_details.get((order["id"],d["detail_no"]),0) for d in candidates}
            available=_detail_refundable(candidates,returned,line["refunded"])
            for d in candidates:
                d["refundable_qty"]=available[d["detail_no"]]
        if key in capacity:
            line["max_qty"]=capacity[key]+(line["qty"] if order["status"]=="Reservado" else 0)
            line["recipe"]=saved_recipes[key]
        order["lines"].append(line)
    for r in rows.values():
        r["gross"]/=100
        r["total"]/=100
        if r["status"]=="Anulada":
            r["total"]=0
        if r["status"] in ("Reservado","Por revisar"):
            r["total"]=sum(round(d["price"]*100)*d["qty"] for d in r["details"]
                           if d["status"]!="Cancelado" and not d["remove_pending"])/100
    return list(rows.values())


def state(db,user,day):
    _role(user,"admin","caja","atencion","area","recepcion")
    all_items=stock(db)
    balances={i["id"]:int(Decimal(str(i["available"]))*1000) for i in all_items}
    wide=user["role"] in ("admin","caja","recepcion")
    assigned_areas=inventory_access_areas(user)
    items=all_items if wide else [i for i in all_items if i["area"] in assigned_areas]
    allowed={i["id"] for i in items}
    can_order=user["role"] in ("admin","caja","atencion")
    can_prepare = _can_prepare(user)
    recipe_items = allowed
    if user["role"] == "recepcion" and can_prepare:
        recipe_items = {i["id"] for i in items if i["area"] in assigned_areas}
    rules=[]
    for row in db.execute("SELECT * FROM inv_rules ORDER BY id"):
        if row["source_id"] in recipe_items and row["target_id"] in recipe_items:
            rule=dict(row)
            rule["code"]=public("EQ",row["id"])
            for key in ("source_qty","target_qty"):
                rule[key]=num(rule[key])
            rules.append(rule)
    result={"items":items,"lots":[r for r in batches(db) if r["item_id"] in allowed],
            "areas":INVENTORY_AREAS if wide else assigned_areas,
            "inventory_access_areas":assigned_areas,
            "products":_products(db,balances,all_items) if can_order else [],
            "orders":_orders(db,user,balances),"preparation":_preparation(db,user),"rules":rules,"can_prepare":can_prepare,
            "movements":_history(db,user,{},recent=True)}
    if user["role"]=="admin":
        result["staff_areas"]=STAFF_AREAS
        result["portion_groups"]=[dict(r) for r in db.execute("SELECT * FROM inv_portion_groups")]
        result["next_item_code"]=_next_item_code(db,1+max((i["id"] for i in all_items),default=0))
    if user["role"]=="area":
        result["area_menu"]=[dict(r) for r in db.execute("SELECT name,category FROM inv_products WHERE prep_area=? ORDER BY category,name",(_area(user),))]
    if can_order:
        result["menu_categories"]=[r[0] for r in db.execute("SELECT name FROM menu_categories UNION SELECT category FROM inv_products ORDER BY 1")]
        result["service_requests"]=_service_requests(db,user)
        result["next_order_code"]=public("C",_next_order_number(db,day))
    if user["role"] in ("admin","caja"):
        result["net_sales"]=net_sales(db)/100
    return result


def _request_refund(db,user,p):
    _role(user,"atencion","admin","caja")
    order=_get_order(db,p)
    if order["status"]!="Cobrado" or (user["role"]=="atencion" and order["user_id"]!=user["id"]):
        raise ValueError("Selecciona una venta cobrada que puedas gestionar.")
    if _pending_cancel(db,order["id"]):
        raise ValueError("Resuelve la solicitud de anulación antes de solicitar devoluciones.")
    pid=_id(p.get("product_id"))
    qty=_scaled(p.get("qty"),1,"Unidades",high=10000)
    reason=_text(p.get("reason"),"motivo",300)
    line=db.execute("""SELECT qty-refunded-COALESCE((SELECT SUM(r.qty) FROM refund_requests r
            WHERE r.order_id=l.order_id AND r.product_id=l.product_id AND r.status='Pendiente'),0)
            FROM inv_lines l WHERE order_id=? AND product_id=?""",(order["id"],pid)).fetchone()
    if not line or qty>line[0]:
        raise ValueError("La cantidad supera las unidades disponibles para solicitar.")
    db.execute("""INSERT refund_requests(order_id,product_id,qty,reason,requester_id,requester,requested_at,status,request_day)
                  VALUES(?,?,?,?,?,?,?,'Pendiente',?)""",(order["id"],pid,qty,reason,user["id"],user["name"],now(),business_day(db)))
    return {}


def _resolve_refund(db,user,p):
    _role(user,"admin","caja")
    req=db.execute("SELECT * FROM refund_requests WHERE id=? AND status='Pendiente'",(_id(p.get("id")),)).fetchone()
    if not req:
        raise ValueError("La solicitud ya fue resuelta o no existe.")
    approved=p.get("approve") is True
    if p.get("revision",req["revision"])!=req["revision"]:
        raise ValueError("La solicitud cambió. Actualiza antes de resolverla.")
    reason=None if approved else _text(p.get("reason"),"motivo del rechazo",300)
    credit=None
    if approved:
        selection={key:p[key] for key in ("details","restock") if key in p}
        credit=_refund(db,user,dict(id=req["order_id"],product_id=req["product_id"],qty=req["qty"],
                       reason=req["reason"],**selection),resolving=req["id"])["return_id"]
    db.execute("UPDATE refund_requests SET status=?,decided_by=?,decided_at=?,decision_reason=?,return_id=?,revision=revision+1 WHERE id=?",
               ("Aprobada" if approved else "Rechazada",user["name"],now(),reason,credit,req["id"]))
    return {}


def _undo_paid_cancel(db,user,order,request,day):
    oid=order["id"]
    if request["prior_status"] not in ("Cobrado","Devuelto"):
        raise ValueError("La comanda se cobró después de resolver la solicitud.")
    if request["status"]=="Rechazada":
        if order["status"] not in ("Cobrado","Devuelto"):
            raise ValueError("La venta ya cambió de estado.")
        return
    void=db.execute("SELECT cash_day FROM sale_voids WHERE order_id=? AND cancel_request_id=?",
                    (oid,request["id"])).fetchone()
    if order["status"]!="Anulada" or not void or void["cash_day"]!=day:
        raise ValueError("La anulación de venta ya cambió o corresponde a otra jornada.")
    for lot,amount in db.execute("SELECT lot_id,amount FROM sale_void_stock WHERE order_id=?",(oid,)):
        _move(db,user,lot,-amount,"Reversión de reposición por anulación de venta",_order_ref(order))
    db.execute("DELETE FROM sale_void_stock WHERE order_id=?",(oid,))
    db.execute("DELETE FROM sale_voids WHERE order_id=?",(oid,))
    db.execute("""UPDATE refund_requests SET status='Pendiente',decided_by=NULL,decided_at=NULL,
                  decision_reason=NULL,voided_by_cancel_id=NULL,revision=revision+1 WHERE voided_by_cancel_id=?""",
               (request["id"],))
    db.execute("UPDATE inv_orders SET status=? WHERE id=?",(request["prior_status"],oid))


def _undo_request(db,user,p):
    _role(user,"admin","caja")
    kind=p.get("kind")
    if kind not in ("cancel","refund"):
        raise ValueError("Tipo de solicitud desconocido.")
    cancellation=kind=="cancel"
    table="inv_cancel_requests" if cancellation else "refund_requests"
    req=db.execute("SELECT * FROM "+table+" WHERE id=?",(_id(p.get("id")),)).fetchone()
    if not req or req["status"] not in ("Aprobada","Rechazada") or req["revision"]!=p.get("revision"):
        raise ValueError("La decisión cambió. Actualiza la página.")
    order=_get_order(db,{"id":req["order_id"]})
    if not cancellation and order["status"]=="Anulada":
        raise ValueError("La venta está anulada.")
    day=business_day(db)
    request_day=req["request_day"] or order["day"]
    if day!=request_day:
        raise ValueError("Abre la jornada de la solicitud antes de deshacer.")
    oid=order["id"]
    approved=req["status"]=="Aprobada"
    if _pending_cancel(db,oid):
        raise ValueError("Resuelve la solicitud de anulación pendiente antes de deshacer otra decisión.")
    if cancellation and order["paid_at"]:
        _undo_paid_cancel(db,user,order,req,day)
    elif cancellation:
        if approved:
            if order["status"]!="Cancelado":
                raise ValueError("La comanda ya cambió de estado.")
            if db.execute("""SELECT 1 FROM inv_orders WHERE day=? AND id<>? AND status IN ('Reservado','Por revisar')
                      AND (table_number=? OR table_name=?)""",(order["day"],oid,order["table_number"],order["table_name"])).fetchone():
                raise ValueError("La mesa está ocupada por otra comanda.")
            status=req["prior_status"] or "Reservado"
            for lot,amount in db.execute("SELECT lot_id,amount FROM cancel_consumption WHERE request_id=?",(req["id"],)):
                _move(db,user,lot,amount,"Reversión de anulación de comanda",_order_ref(order))
            db.execute("DELETE FROM cancel_consumption WHERE request_id=?",(req["id"],))
            if status=="Reservado":
                lines={r["product_id"]:r for r in db.execute("SELECT * FROM inv_lines WHERE order_id=?",(oid,))}
                _reserve_lines(db,oid,{k:r["qty"] for k,r in lines.items()},lines,"Por revisar")
            db.execute("UPDATE inv_orders SET status=? WHERE id=?",(status,oid))
        elif order["status"] not in ("Reservado","Por revisar"):
            raise ValueError("La comanda ya está cerrada.")
    else:
        pid=req["product_id"]
        if approved:
            credit=req["return_id"]
            ref=public("DV",credit)
            for part in db.execute("SELECT * FROM refund_parts WHERE return_id=?",(credit,)):
                if part["restocked"]:
                    _move(db,user,part["lot_id"],-part["restocked"],"Reversión de devolución",ref)
                db.execute("UPDATE inv_alloc SET processed=processed-? WHERE order_id=? AND product_id=? AND lot_id=?",
                           (part["amount"],oid,pid,part["lot_id"]))
            db.execute("INSERT refund_reversals(return_id,at,cash_day,actor) VALUES(?,?,?,?)",(credit,now(),day,user["name"]))
            db.execute("UPDATE inv_lines SET refunded=refunded-? WHERE order_id=? AND product_id=?",(req["qty"],oid,pid))
            db.execute("UPDATE inv_orders SET status='Cobrado' WHERE id=?",(oid,))
        free=db.execute("""SELECT qty-refunded-COALESCE((SELECT SUM(qty) FROM refund_requests WHERE
            order_id=? AND product_id=? AND status='Pendiente'),0) FROM inv_lines WHERE order_id=? AND product_id=?""",
            (oid,pid,oid,pid)).fetchone()[0]
        if req["qty"]>free:
            raise ValueError("Las unidades ya se devolvieron o figuran en otra solicitud pendiente.")
    extra="" if cancellation else ",return_id=NULL"
    db.execute("UPDATE "+table+" SET status='Pendiente',decided_by=NULL,decided_at=NULL,decision_reason=NULL,revision=revision+1"+extra+" WHERE id=?",(req["id"],))
    db.execute("UPDATE inv_orders SET version=version+1 WHERE id=?",(oid,))
    _event(db,user,oid,"Decisión deshecha",f"{kind} #{req['id']} · {req['status']} · {req['decided_by']} · {req['decided_at']} · {req['decision_reason'] or ''}")
    return {}


def _service_requests(db,user):
    manager=user["role"] in ("admin","caja")
    day=business_day(db)
    def records(query):
        predicate=" WHERE COALESCE(r.request_day,o.day)=?"
        values=(day,)
        if not manager:
            predicate+=" AND (o.user_id=? OR r.requester_id=?)"
            values+=(user["id"],user["id"])
        return [dict(r) for r in db.execute(query+predicate+" ORDER BY r.id DESC",values)]
    orders=" JOIN inv_orders o ON o.id=r.order_id"
    return dict(
        cancellations=records("SELECT r.*,o.number,o.day,o.table_name,o.paid_at FROM inv_cancel_requests r"+orders),
        refunds=records("SELECT r.*,o.number,o.day,o.table_name,l.name FROM refund_requests r"+orders+
                        " JOIN inv_lines l ON l.order_id=r.order_id AND l.product_id=r.product_id"),
        refundable=[dict(r) for r in db.execute("""SELECT o.id,o.number,o.day,o.table_name,l.product_id,l.name,
                    l.qty-l.refunded-COALESCE((SELECT SUM(qty) FROM refund_requests rr WHERE rr.order_id=o.id AND rr.product_id=l.product_id AND rr.status='Pendiente'),0) AS remaining FROM inv_orders o JOIN inv_lines l ON l.order_id=o.id
                    JOIN inv_sales sale ON sale.order_id=o.id WHERE COALESCE(sale.cash_day,LEFT(o.paid_at,10))=? AND o.status='Cobrado' AND l.qty>l.refunded
                    AND NOT EXISTS (SELECT 1 FROM inv_cancel_requests cr WHERE cr.order_id=o.id AND cr.status='Pendiente')"""+("" if manager else " AND o.user_id=?")+
                    " ORDER BY o.id DESC,l.product_id",(day,) if manager else (day,user["id"]))])


def act(db,user,action,payload):
    if not isinstance(payload,dict):
        raise ValueError("Los datos de la operación son inválidos.")
    routes={"inv.portions":porciones.setup,"pedidos.void_sale":_void_sale,"pedidos.undo_request":_undo_request,"inv.menu_category":_menu_category,"pedidos.request_refund":_request_refund,"pedidos.resolve_refund":_resolve_refund,
            "inv.item":_save_item,"inv.item_area":_change_item_area,"inv.item_category":_change_item_area,
            "inv.item_unit":_configure_item_unit,
            "inv.product":_save_product,"inv.rule":_rule,"inv.transform":_transform,
            "pedidos.save":_save_order,"pedidos.cancel":_cancel,"pedidos.pay":_pay,"pedidos.refund":_refund,
            "pedidos.refund_order":_refund_order,
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
        amount=item_quantity(item["name"],payload.get("qty"),unit=item["unit"],item=item)
        withdraw(db,user,item["id"],amount,"Consumo · "+detail,item["area"])
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
    # código, nombre, área, unidad, mínimo, aviso, vida inicial, transformable, cantidad
    sample=[
        ("POL-01","Pollo entero crudo","Brasas","und",6,2,5,1,18),
        ("POL-02","Cuarto de pollo asado","Brasas","porc",10,1,2,0,36),
        ("PAP-01","Papa para freír","Orientales","kg",8,3,12,0,32),
        ("ENS-01","Ensalada de la casa","Orientales","porc",8,1,2,0,40),
        ("RES-01","Bistec de res","Parrillas","kg",3,2,5,0,9),
        ("ARR-01","Arroz cocido","Orientales","kg",4,1,2,0,12),
        ("POL-03","Pollo trozado","Orientales","kg",3,2,3,0,8),
        ("BEB-01","Chicha morada preparada","Barra","L",3,1,3,0,15),
        ("BEB-02","Gaseosa personal sellada","Barra","bot",12,10,90,0,10),
        ("LIM-01","Detergente lavavajillas","Limpieza y Atención","L",2,0,None,0,6),
        ("ATE-01","Servilletas","Limpieza y Atención","und",100,0,None,0,500),
    ]
    first_day=date.fromisoformat(today())
    ids={}
    for code,name,area,unit,minimum,warn,life,transformable,opening in sample:
        item=_save_item(db,SYSTEM,{"name":name,"area":area,"unit":unit,
                        "min_qty":minimum,"warn_days":warn,"perishable":life is not None,"transformable":transformable})["id"]
        ids[code]=item
        expiry=(first_day+timedelta(days=life)).isoformat() if life is not None else None
        receive(db,SYSTEM,item,qty(opening),expiry,"Apertura de demostración","Inventario inicial")
    _configure_item_unit(db,SYSTEM,{"id":ids["RES-01"],"display_unit":"filetes","base_per_unit":"0.28"})
    _configure_item_unit(db,SYSTEM,{"id":ids["ARR-01"],"display_unit":"porciones","base_per_unit":"0.5"})
    dishes=[
        ("Cuarto de pollo a la brasa","Brasas",22,[("POL-02",1),("PAP-01",0.5),("ENS-01",1)]),
        ("Medio pollo a la brasa","Brasas",41,[("POL-02",2),("PAP-01",1.5),("ENS-01",2)]),
        ("Parrilla personal","Parrillas",34,[("RES-01",0.28),("PAP-01",0.5),("ENS-01",1)]),
        ("Chaufa de pollo","Orientales",19,[("ARR-01",0.5),("POL-03",0.12)]),
        ("Chicha morada","Barra",7,[("BEB-01",0.4)]),
        ("Gaseosa personal","Barra",5,[("BEB-02",1)]),
        ("Pollo entero a la brasa","Brasas",68,[("POL-02",4),("PAP-01",3),("ENS-01",4)]),
    ]
    products={}
    for name,cat,price,recipe in dishes:
        products[name]=_save_product(db,SYSTEM,{"name":name,"category":cat,"price":price,
                      "recipe":[{"item_id":ids[code],"qty":amount} for code,amount in recipe]},demo=True)["id"]
    porciones.setup(db,SYSTEM,dict(raw_id=ids["POL-01"],base_id=ids["POL-02"],potato_id=ids["PAP-01"],
        quarter_product_id=products["Cuarto de pollo a la brasa"],half_product_id=products["Medio pollo a la brasa"],
        whole_product_id=products["Pollo entero a la brasa"]))
    db.execute("INSERT INTO inv_seed VALUES(1)")
