"""Equivalencias de medios y enteros respaldadas por el mismo stock de cuartos."""


def resolve(db, item_id, amount):
    equivalent=db.execute("SELECT base_id,factor FROM inv_stock_equivalents WHERE item_id=?",(item_id,)).fetchone()
    if equivalent:
        return equivalent["base_id"],amount*equivalent["factor"]
    return item_id,amount


def project(db, items):
    from decimal import Decimal
    by_id={i["id"]:i for i in items}
    for row in db.execute("SELECT * FROM inv_stock_equivalents"):
        item,base=by_id[row["item_id"]],by_id[row["base_id"]]
        factor=row["factor"]
        physical=int(Decimal(str(base["physical"]))*1000)
        available=int(Decimal(str(base["available"]))*1000)
        # El pollo iniciado cuenta hasta consumir su última porción.
        item["physical"]=(physical+factor*1000-1)//(factor*1000)
        item["available"]=available//(factor*1000)
        item["reserved"]=item["physical"]-(available+factor*1000-1)//(factor*1000)
        item["base_id"]=base["id"]
        item["base_code"]=base["code"]
        item["factor"]=factor
        item["remaining_portions"]=base["physical"]


def setup(db,user,p):
    import inventario as inv
    inv._role(user,"admin")
    base=inv._item(db,p.get("base_id"))
    raw=inv._item(db,p.get("raw_id"))
    potato=inv._item(db,p.get("potato_id"))
    if len({base["id"],raw["id"],potato["id"]})!=3:
        raise ValueError("Selecciona insumos diferentes para pollo crudo, cuartos y papa.")
    if raw["unit"].strip().casefold() not in ("und","unidad","unidades","pollo","pollos"):
        raise ValueError("El pollo crudo debe registrarse en unidades.")
    if raw["area"]!=base["area"]:
        raise ValueError("El pollo crudo y cocido deben pertenecer a la misma área.")
    if potato["unit"].strip().casefold() not in ("kg","kilo","kilos","kilogramo","kilogramos"):
        raise ValueError("La unidad de la papa debe estar expresada en kg.")
    if db.execute("SELECT 1 FROM inv_stock_equivalents WHERE item_id IN (?,?,?)",(base["id"],raw["id"],potato["id"])).fetchone():
        raise ValueError("Selecciona los insumos de origen, sin equivalencias.")
    existing=db.execute("SELECT * FROM inv_portion_groups WHERE base_id=?",(base["id"],)).fetchone()
    if existing and (existing["raw_id"],existing["potato_id"])!=(raw["id"],potato["id"]):
        raise ValueError("Este grupo ya tiene pollo crudo y papa asociados.")
    if not existing:
        db.execute("INSERT inv_portion_groups(base_id,raw_id,potato_id) VALUES(?,?,?)",(base["id"],raw["id"],potato["id"]))
        for factor,name in ((2,"Medio pollo cocido"),(4,"Pollo entero cocido")):
            item=inv._save_item(db,user,dict(name=name,category=base["category"],area=base["area"],unit="und",
                perishable=base["perishable"],warn_days=base["warn_days"],min_qty=0))
            db.execute("INSERT inv_stock_equivalents(item_id,base_id,factor) VALUES(?,?,?)",(item["id"],base["id"],factor))
    whole=db.execute("SELECT item_id FROM inv_stock_equivalents WHERE base_id=? AND factor=4",(base["id"],)).fetchone()[0]
    db.execute("UPDATE inv_items SET transformable=1 WHERE id=?",(raw["id"],))
    # Sustituye la equivalencia anterior del mismo pollo, conservando otras preparaciones.
    db.execute("DELETE FROM inv_rules WHERE source_id=? AND target_id=?",(raw["id"],base["id"]))
    inv._rule(db,user,dict(source_id=raw["id"],target_id=whole,source_qty=1,target_qty=1))
    products=[p.get("quarter_product_id"),p.get("half_product_id"),p.get("whole_product_id")]
    selected=[inv._id(v) for v in products if v]
    if len(set(selected))!=len(selected):
        raise ValueError("Selecciona productos de carta diferentes para cada presentación.")
    for product,portions,potatoes in zip(products,(1,2,4),(500,1500,3000)):
        if not product:
            continue
        product=inv._id(product)
        if not db.execute("SELECT 1 FROM inv_products WHERE id=?",(product,)).fetchone():
            raise ValueError("No se encontró el producto de carta.")
        db.execute("DELETE FROM inv_recipes WHERE product_id=? AND item_id IN (?,?)",(product,base["id"],potato["id"]))
        db.execute("INSERT inv_recipes(product_id,item_id,amount) VALUES(?,?,?)",(product,base["id"],portions*1000))
        db.execute("INSERT inv_recipes(product_id,item_id,amount) VALUES(?,?,?)",(product,potato["id"],potatoes))
    return {"base_id":base["id"],"whole_id":whole}
