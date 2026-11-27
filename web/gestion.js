/* Compras, recepción y supervisión. */
(() => {
  const rows = key => S[key] || [];
  const e = value => h(value == null ? "" : String(value));
  const admin = () => S.user.role === "admin";
  const label = (prefix,id) => prefix + String(id).padStart(4, "0");
  const money = cents => cash(cents / 100);
  const cents = soles => Math.round(Number(soles) * 100);
  const date = value => value ? String(value).slice(0,10).split("-").reverse().join("/") : "—";
  const when = value => value ? date(value) + " " + String(value).slice(11,16) : "—";
  const muted = value => '<span class="muted">'+e(value)+'</span>';
  const sub = value => '<div class="muted">'+e(value)+'</div>';
  const actions = (...buttons) => '<div class="actions">'+buttons.filter(Boolean).join("")+'</div>';
  const qtyAttrs = 'required min="1" step="1"';
  const numberAttrs = 'min="0" step="0.01"';
  const stack = (...parts) => '<div class="stack">'+parts.filter(Boolean).join("")+'</div>';
  const item = id => rows("items").find(x=>x.id === id);
  const qtyText = (record,value) => formatStockQuantity(record.item_name||record.name,record.unit,value);
  const itemOptions = () => rows("items").map(x=>[x.id,`${x.code} · ${x.name} (${stockMeasure(x.name,x.unit).unit})`]);
  const note = value => '<p class="muted">'+e(value)+'</p>';
  const metric = (name,value) => '<div class="metric"><span class="muted">'+e(name)+'</span><div class="value">'+e(value)+'</div></div>';
  const group = (...metrics) => '<div class="metrics">'+metrics.join("")+'</div>';
  let preferredReceipt=null;

  function confirmAction(title, text, action, payload, submit, message) {
    modal(title,note(text),()=>run("gestion."+action,payload,message),submit);
  }

  function newReceipt() {
    const dialog=modal("Registrar entrega",select("item_id","Insumo",itemOptions())+
      input("supplier","Proveedor","text","","required maxlength=100")+
      input("qty","Cantidad prevista","number","",qtyAttrs)+
      input("cost","Costo unitario (S/)","number","",numberAttrs+" required")+
      note("La entrega quedará pendiente de revisión. El stock aumenta al aprobar las unidades recibidas."),
      v=>{
        const selected=item(Number(v.item_id));
        return run("gestion.receipt",{item_id:v.item_id,supplier:v.supplier,
          qty:stockQuantityPayload(selected?.name,selected?.unit,v.qty),unit_cents:cents(v.cost)},"Entrega registrada");
      },
      "Registrar entrega");
    const form=dialog.querySelector("form");
    const itemField=form.elements.namedItem("item_id");
    const update=()=>{
      const selected=item(Number(itemField.value));
      const field=form.elements.namedItem("qty");
      const displayUnit=stockMeasure(selected?.name,selected?.unit).unit;
      field.closest("label").querySelector("span").textContent=displayUnit?`Cantidad prevista (${displayUnit})`:"Cantidad prevista";
      form.elements.namedItem("cost").closest("label").querySelector("span").textContent=
        selected?`Costo por ${selected.unit} (S/)`:"Costo unitario (S/)";
      setItemQuantityStep(field,selected?.name);
    };
    itemField.addEventListener("change",update);
    update();
  }

  function reviewReceipt(r, approve) {
    const verb=approve?"Aprobar recepción":"Solicitar rechazo";
    const summary=[r.purchase_id?label("OC",r.purchase_id):r.code,r.supplier,
      r.item_code,r.item_name,`${qtyText(r,r.qty)} previstos`].filter(Boolean).join(" · ");
    const cost=r.unit_cents!=null?note(`Costo por ${r.unit} ${money(r.unit_cents)}`):"";
    const unit=stockMeasure(r.item_name,r.unit).unit;
    const value=stockInputValue(r.item_name,r.unit,r.qty);
    const step=itemQuantityStep(r.item_name,value);
    const received=input("received",`Cantidad entregada (${unit})`,"number",value,`required min="0" step="${step}"`);
    const approval=approve?input("approved",`Cantidad en buen estado (${unit})`,"number",value,
      `required min="${step}" max="${e(value)}" step="${step}"`)+
      input("expiry",r.perishable?"Vencimiento del lote aprobado":"Vencimiento, si corresponde","date","",r.perishable?"required":""):"";
    const dialog=modal(`${verb} · ${r.item_name}`,note(summary)+cost+received+approval+
      input("reason",approve?"Motivo si hay faltantes o unidades rechazadas":"Motivo del rechazo","text","",
        approve?"maxlength=500":"required maxlength=500")+
      note(approve?"Solo la cantidad aprobada ingresará al stock. Las diferencias quedarán como solicitudes pendientes.":
        "La solicitud quedará pendiente para que Administración gestione el rechazo con el proveedor."),
      v=>run("gestion.receive",{id:r.id,received:stockQuantityPayload(r.item_name,r.unit,v.received),
        approved:stockQuantityPayload(r.item_name,r.unit,approve?v.approved:"0"),expiry:v.expiry,reason:v.reason},
        approve?"Recepción aprobada · stock actualizado":"Solicitud de rechazo registrada"),verb);
    dialog.querySelector("form").addEventListener("input",event=>{
      const field=event.target;
      if(["received","approved"].includes(field.name)){
        setItemQuantityStep(field,r.item_name,field.name==="received",value);
      }
    });
  }

  function resolveIncident(x) {
    modal("Resolver "+x.code,note(x.supplier+" · "+x.item_name+" · "+qtyText(x,x.qty)+". "+x.reason)+
      input("resolution","Gestión con el proveedor","text","","required maxlength=500"),
      v=>run("gestion.resolve",{id:x.id,resolution:v.resolution},"Inconformidad resuelta"),"Resolver");
  }

  function receiptTable(deliveries) {
    return table(["Producto","Cantidad prevista","Revisión","Acciones"],deliveries.map(r=>[
      `<strong>${e(r.item_name)}</strong>`+sub([r.item_code,r.area,r.code,r.purchase_id?null:r.supplier].filter(Boolean).join(" · ")),
      e(qtyText(r,r.qty)),
      badge(r.status)+(r.approved!==null?sub((r.received!=null?qtyText(r,r.received)+" entregados · ":"")+
        qtyText(r,r.approved)+" aprobados")+sub(when(r.reviewed_at)+" · "+r.reviewer):""),
      r.status==="Pendiente"?actions(
        button("Aprobar recepción",()=>reviewReceipt(r,true),"primary"),
        button("Solicitar rechazo",()=>reviewReceipt(r,false))
      ):(r.lot_id?muted(label("LT",r.lot_id)+(r.expiry?" · Vence "+date(r.expiry):"")):""),
    ]),"Las entregas pendientes de validación aparecerán aquí.");
  }

  function receiptGroups(deliveries) {
    const groups=new Map();
    for(const receipt of deliveries){
      const id=receipt.purchase_id??null;
      if(!groups.has(id))groups.set(id,[]);
      groups.get(id).push(receipt);
    }
    const order=[...groups.keys()];
    if(preferredReceipt!=null&&groups.has(preferredReceipt)){
      order.splice(order.indexOf(preferredReceipt),1);
      order.unshift(preferredReceipt);
    }
    return order.map(id=>{
      const list=groups.get(id);
      const first=list[0];
      const done=list.filter(r=>r.status!=="Pendiente").length;
      const title=id?`Orden ${label("OC",id)} · ${first.supplier}`:"Entregas manuales";
      const subtitle=id?`Lote del ${date(first.purchase_day)} · ${done} de ${list.length} productos revisados`:
        `${done} de ${list.length} productos revisados`;
      return `<section><h3>${e(title)}</h3>${note(subtitle)}${receiptTable(list)}</section>`;
    }).join("");
  }

  pages.recepcion = () => {
    const deliveries = rows("receipts");
    const issues = rows("incidents");
    return stack(group(metric("Pendientes de revisión",deliveries.filter(x=>x.status==="Pendiente").length),
      metric("Solicitudes pendientes",issues.filter(x=>!x.closed).length)),
      panel("Entregas de proveedores",deliveries.length?stack(receiptGroups(deliveries)):receiptTable([]),
        button("Registrar entrega",newReceipt,"primary")),
      panel("Solicitudes de rechazo y diferencias",table(["Solicitud","Insumo y proveedor","Diferencia","Motivo y seguimiento","Estado"],issues.map(x=>[
        e(x.code)+sub(x.kind)+sub([x.purchase_id?label("OC",x.purchase_id):"",label("RC",x.receipt_id)].filter(Boolean).join(" · "))+
        sub(when(x.created)+" · "+x.actor),e(x.item_name)+sub(x.supplier),e(qtyText(x,x.qty))+
        (x.missing!=null?sub(qtyText(x,x.missing)+" faltantes · "+qtyText(x,x.rejected)+" rechazados"):""),e(x.reason)+
        (x.resolution?sub(x.resolution)+sub(when(x.closed)+" · "+x.closer):""),
        actions(badge(x.closed?"Resuelta":"Pendiente"),admin()&&!x.closed?button("Resolver solicitud",()=>resolveIncident(x)):"")
      ]),"Aún no se han registrado diferencias de recepción.")));
  };

  function newWaste() {
    const assigned=S.inventory_access_areas;
    const lots=rows("lots").filter(x=>{
      const i=item(x.item_id);
      return i && stockInputValue(i.name,i.unit,x.available)>=itemQuantityStep(i.name) && (admin() || assigned.includes(i.area));
    });
    if(!lots.length){
      toast("No hay lotes con existencias disponibles para reportar una merma.",true);
      return;
    }
    const options=lots.map(x=>[x.id,`${label("LT",x.id)} · ${item(x.item_id).name} · ${qtyText(item(x.item_id),x.available)} disponibles`]);
    const calendarToday=S.calendar_today||S.today;
    const activeDay=S.today;
    const latestDate=calendarToday>activeDay?calendarToday:activeDay;
    const todayButton=calendarToday!==activeDay?button(`Usar la fecha de hoy (${date(calendarToday)})`,()=>{
      dateField.value=calendarToday;
      dateField.setCustomValidity("");
    },"link"):"";
    const dialog=modal("Reportar merma",select("lot","Lote afectado",options)+
      input("qty","Cantidad afectada","number","",qtyAttrs)+
      input("occurred_on","Fecha de la merma","date",activeDay,'required max="'+e(latestDate)+'"')+todayButton+
      input("reason","Motivo y detalle del descarte","text","","required maxlength=500")+
      note("La cantidad quedará reservada hasta que Administración revise la solicitud."),
      v=>{
        const lot=lots.find(x=>x.id===Number(v.lot));
        if (!lot) throw Error("Selecciona un lote con existencias.");
        const selected=item(lot.item_id);
        const qty=stockQuantityPayload(selected.name,selected.unit,v.qty);
        return run("gestion.waste",{item_id:lot.item_id,lot_id:lot.id,qty,occurred_on:v.occurred_on,reason:v.reason},"Merma reportada");
      },"Enviar a revisión");
    const form=dialog.querySelector("form");
    const dateField=form.elements.namedItem("occurred_on");
    dateField.addEventListener("input",()=>{
      const future=dateField.value>calendarToday&&dateField.value!==activeDay;
      dateField.setCustomValidity(future?"Selecciona hoy, una fecha anterior o la fecha de la jornada activa.":"");
    });
    const lotField=form.elements.namedItem("lot");
    const quantityField=form.elements.namedItem("qty");
    const updateLimit=()=>{
      const lot=lots.find(x=>x.id===Number(lotField.value));
      const selected=item(lot.item_id);
      quantityField.max=stockInputValue(selected.name,selected.unit,lot.available);
      quantityField.closest("label").querySelector("span").textContent=
        `Cantidad afectada (${stockMeasure(selected.name,selected.unit).unit})`;
      setItemQuantityStep(quantityField,selected.name);
    };
    lotField.addEventListener("change",updateLimit);
    updateLimit();
  }

  function reviewWaste(x,approve) {
    const verb=approve?"Aprobar":"Rechazar";
    const effect=approve?"Se descontará la cantidad de la merma.":"Las reservas de esta merma se liberarán.";
    confirmAction(verb+" "+x.code,qtyText(x,x.qty)+" de "+x.item_name+". "+x.reason+". "+effect,
      "review_waste",{id:x.id,approve},verb,approve?"Merma aprobada":"Merma rechazada");
  }

  pages.mermas = () => {
    const data=rows("wastes");
    return panel("Reportes de merma",table(["Reporte","Lote e insumo","Cantidad","Motivo","Estado",""],data.map(x=>[
      e(x.code)+sub(date(x.occurred_on||x.created))+sub("Registro: "+when(x.created)),e(x.item_name)+sub(x.lot_id?label("LT",x.lot_id):x.area),
      e(qtyText(x,x.qty)),e(x.reason)+sub(x.actor),badge(x.status),
      admin()&&x.status==="Pendiente"?actions(button("Aprobar",()=>reviewWaste(x,true)),button("Rechazar",()=>reviewWaste(x,false))):muted(x.reviewer)
    ]),"Aún no se han reportado mermas."),button("Reportar merma",newWaste,"primary"));
  };

  const purchaseDayOf = purchase => purchase.purchase_day || purchase.created.slice(0,10);
  const purchaseLotCode = day => "LC-"+day.replaceAll("-","");
  let selectedPurchaseDay="";

  function purchaseForm(p, {day=S.calendar_today||S.today, source=null}={}) {
    const current=new Map((p?.lines||[]).map(x=>[x.item_id,x]));
    const options=admin()?rows("items").map(x=>({
      item_id:x.id,name:x.name,unit:x.unit,available:x.available,minimum:x.min_qty,
      critical:x.available<=x.min_qty,
    })).sort((a,b)=>Number(b.critical)-Number(a.critical)||a.name.localeCompare(b.name,"es")):
      p.lines.map(x=>({item_id:x.item_id,name:x.item_name,unit:x.unit}));
    const delegables=[["","Sin asignar"],...rows("users").filter(x=>x.active).map(x=>[x.id,x.name])];
    const assigned=admin()?select("assignee_id","Responsable delegado",delegables,p?.assignee_id||source?.assignee_id||""):"";
    const headers=admin()?["Insumo","Existencias","Cantidad","S/ por unidad"]:["Insumo","Cantidad","S/ por unidad"];
    const lines = table(headers,options.map(x=>{
      const line=current.get(x.item_id);
      const n=x.item_id;
      const unit=stockMeasure(x.name,x.unit).unit;
      const value=stockInputValue(x.name,x.unit,line?.qty);
      const step=itemQuantityStep(x.name,value||null);
      return [e(x.name)+sub(unit),
        ...(admin()?[badge(x.critical?"Crítico":"Normal")+sub(`${qtyText(x,x.available)} disponibles · mínimo ${qtyText(x,x.minimum)}`)]:[]),
        `<label><input aria-label="Cantidad de ${e(x.name)} (${e(unit)})" name="q${n}" data-purchase-qty="${n}" type="number" min="0" step="${step}" value="${e(value)}" style="width:7em"> ${e(unit)}</label>`,
        `<label><input aria-label="Costo de ${e(x.name)} por ${e(x.unit)}" name="c${n}" type="number" min="0" step="0.01" value="${e(line?line.unit_cents/100:"")}" style="width:7em"> / ${e(x.unit)}</label>`];
    }),"Agrega insumos al inventario para preparar la compra.");
    const lotDay=p?purchaseDayOf(p):source?purchaseDayOf(source):day;
    const dialog=modal(p?"Editar "+p.code:source?"Ampliar "+source.code:"Nueva hoja de compra",
      note(`Lote ${purchaseLotCode(lotDay)} · ${date(lotDay)}`)+
      input("supplier","Proveedor","text",p?.supplier||source?.supplier||"","maxlength=100")+assigned+
      '<div class="full">'+note("Completa la cantidad y el costo unitario de los insumos que deseas comprar.")+lines+'</div>',
      v=>{
        const details=options.filter(x=>Number(v["q"+x.item_id])>0).map(x=>({
          item_id:x.item_id,qty:stockQuantityPayload(x.name,x.unit,v["q"+x.item_id]),unit_cents:cents(v["c"+x.item_id]||0)
        }));
        const payload={supplier:v.supplier,lines:details};
        if (admin()) payload.assignee_id=v.assignee_id;
        if (p) { payload.id=p.id; payload.version=p.version; }
        else payload.purchase_day=lotDay;
        if (source) payload.source_purchase_id=source.id;
        return run(p?"gestion.edit_purchase":"gestion.purchase",payload,"Hoja de compra guardada");
      },"Guardar hoja");
    const byId=new Map(options.map(option=>[option.item_id,option]));
    dialog.querySelector("form").addEventListener("input",event=>{
      const field=event.target;
      if(!field.dataset.purchaseQty)return;
      const id=Number(field.dataset.purchaseQty);
      const selected=byId.get(id);
      const previous=stockInputValue(selected.name,selected.unit,current.get(id)?.qty);
      setItemQuantityStep(field,selected.name,true,previous||null);
    });
  }

  function purchaseDetails(p) {
    const details=table(["Insumo","Cantidad","Costo unitario","Importe"],p.lines.map(l=>[
      e(l.item_name),e(qtyText(l,l.qty)),e(money(l.unit_cents)+" / "+l.unit),e(money(l.total_cents))]),"Sin renglones.");
    modal("Detalle de "+p.code,'<div class="full">'+note((p.supplier||"Proveedor pendiente")+" · "+p.status)+
      details+note("Total "+money(p.total_cents))+
      actions(button("Exportar PDF",()=>printPurchases(purchaseDayOf(p),[p],p.code),"primary"),
        button("Exportar CSV",()=>downloadPurchase(p)))+'</div>',null);
  }

  function downloadPurchase(p) {
    const sheet = [
      ["Orden","Fecha","Proveedor","Estado"],[p.code,when(p.created),p.supplier,p.status],[],
      ["Insumo","Unidad","Cantidad","Unidad de cotización","Precio unitario (S/)","Importe (S/)"],
      ...p.lines.map(l=>[l.item_name,stockMeasure(l.item_name,l.unit).unit,stockInputValue(l.item_name,l.unit,l.qty),
        l.unit,(l.unit_cents/100).toFixed(2),(l.total_cents/100).toFixed(2)]),
      ["Total (S/)","","","","",(p.total_cents/100).toFixed(2)]
    ];
    exportCsv(p.code+".csv",sheet);
  }

  function printPurchases(day, purchases, code=purchaseLotCode(day)) {
    const output=document.createElement("section");
    output.id="purchase-print";
    const wholeLot=code===purchaseLotCode(day);
    const total=purchases.reduce((sum,p)=>sum+p.total_cents,0);
    const orders=purchases.map(p=>`<section class="purchase-print-order">
      ${wholeLot?`<h2>Hoja ${e(p.code)}</h2>`:""}
      <p>${e(p.supplier||"Proveedor por definir")} · ${e(p.status)} · Revisión ${e(p.version)}</p>
      ${table(["Insumo","Cantidad","Precio unitario","Importe"],p.lines.map(l=>[
        e(l.item_name),e(qtyText(l,l.qty)),e(money(l.unit_cents)+" / "+l.unit),e(money(l.total_cents)),
      ]),"Esta hoja no contiene insumos.")}
      ${purchases.length>1?`<p class="purchase-print-total">Subtotal <strong>${e(money(p.total_cents))}</strong></p>`:""}
    </section>`).join("");
    output.innerHTML=`<header class="purchase-print-heading">
      <p>Juniors · Pollos y parrillas</p>
      <h1>${wholeLot?"Lote de compras":"Hoja de compra"} ${e(code)}</h1>
      <p>${wholeLot?"":`Lote ${e(purchaseLotCode(day))} · `}${e(date(day))}</p>
    </header>${orders}<p class="purchase-print-total purchase-print-grand">Total <strong>${e(money(total))}</strong></p>`;
    const oldTitle=document.title;
    document.body.append(output);
    document.body.classList.add("printing-purchase");
    document.title=code;
    window.addEventListener("afterprint",()=>{
      output.remove();
      document.body.classList.remove("printing-purchase");
      document.title=oldTitle;
    },{once:true});
    window.print();
  }

  function confirmPurchase(purchase) {
    modal("Confirmar compra · "+purchase.code,
      note(`Se comprometerán ${money(purchase.total_cents)}. En Recepción aparecerá una fila por insumo de ${purchase.supplier}.`),
      async ()=>{
        await run("gestion.dispatch",{id:purchase.id,version:purchase.version},"Compra confirmada · recepción pendiente");
        preferredReceipt=purchase.id;
        go("recepcion");
      },"Confirmar compra");
  }

  function purchaseActions(p) {
    const draft=p.status==="Borrador";
    const info=button("Detalle",()=>purchaseDetails(p));
    const edit=draft?button("Editar",()=>purchaseForm(p)):"";
    const approval=approve=>confirmAction((approve?"Aprobar ":"Rechazar ")+p.code,
      (p.supplier||"Compra")+" · "+money(p.total_cents),"decide",{id:p.id,version:p.version,approve},
      approve?"Aprobar":"Rechazar","Compra evaluada");
    if (!admin()) return actions(info,edit);
    if (draft) return actions(info,edit,button("Aprobar",()=>approval(true)),button("Rechazar",()=>approval(false)));
    if (p.status==="Aprobada") return actions(info,button("Volver a borrador",()=>confirmAction("Revisar "+p.code,
      "Podrás corregir la cotización y aprobarla de nuevo antes de cursar la compra.",
      "reopen",{id:p.id,version:p.version},"Volver a borrador","Hoja de compra abierta para revisión")),
      button("Confirmar compra",()=>confirmPurchase(p),"primary"));
    const supplement=["Enviada","Recibida"].includes(p.status)?
      button("Agregar insumos",()=>purchaseForm(null,{source:p})):"";
    return actions(info,supplement);
  }

  function budgetCard(b) {
    return panel("Presupuesto de compras",stack(
      group(metric("Disponible",money(b.available_cents)), metric("Ventas netas",money(b.sales_cents)),
        metric("Compras recibidas",money(b.spent_cents)),metric("Por recibir",money(b.committed_cents))),
      note("Fondo inicial: "+money(b.opening_cents)+". Salidas de lotes con costo registrado: "+money(b.issues_cents)+". El costo se carga al recibir la compra.")),
      button("Editar fondo",()=>modal("Fondo inicial",
        input("soles","Fondo de apertura (S/)","number",b.opening_cents/100,numberAttrs+" required")+
        note("Se reemplazará el fondo de apertura utilizado para calcular el saldo."),
        v=>run("gestion.fund",{opening_cents:cents(v.soles)},"Fondo actualizado"))));
  }

  const reportSummary = r => {
    const items=table(["Insumo","Disponible","Mínimo","Compra sugerida"],r.lines.map(l=>[
      e(l.item_name),e(qtyText(l,l.available)),e(qtyText(l,l.minimum)),e(qtyText(l,l.suggested))
    ]),"Todos los insumos superaban el mínimo en el momento del informe.");
    modal("Faltantes · "+r.code,'<div class="full">'+note(when(r.created)+" · Hora de Lima")+
      items+'</div>',null);
  };

  pages.compras = () => {
    const purchases=rows("purchases");
    const today=S.calendar_today||S.today;
    const days=[...new Set([today,...purchases.map(purchaseDayOf)])].sort().reverse();
    const day=days.includes(selectedPurchaseDay)?selectedPurchaseDay:today;
    const lot=purchases.filter(p=>purchaseDayOf(p)===day);
    const period=`<div class="actions filters">${select("purchase_day","Lote diario",days.map(d=>[
      d,date(d)+" · "+purchaseLotCode(d),
    ]),day)}${lot.length?button("Exportar lote en PDF",()=>printPurchases(day,lot)):""}</div>`;
    const procurement=panel(admin()?"Hojas de compra":"Hojas de compra delegadas",
      period+table(["Orden","Proveedor","Responsable","Total","Estado",""],lot.map(p=>[
        e(p.code)+sub(when(p.created)),e(p.supplier||"Por definir")+sub(p.origin),e(p.assignee||"Administración"),
        e(money(p.total_cents)),badge(p.status),purchaseActions(p)
      ]),"Este lote todavía no tiene hojas de compra."),admin()?button("Nueva compra",()=>purchaseForm(null,{day}),"primary"):"");
    if (!admin()) return procurement;
    const reports=panel("Informes de faltantes",
      '<p class="muted">Conteo diario a las '+e(S.schedule)+' (Lima), mientras la aplicación esté en ejecución.</p>'+
      table(["Informe","Generación","Insumos críticos","Compra asociada",""],rows("reports").map(r=>[
        e(r.code)+sub(when(r.created)),e(r.scheduled?"Programada":"Manual"),e(r.count),e(r.purchase_id?label("OC",r.purchase_id):"—"),
        button("Ver faltantes",()=>reportSummary(r))
      ]),"El primer conteo aparecerá a la hora programada o al generar un informe."),
      actions(button("Cambiar hora",()=>modal("Horario del informe",
        input("time","Hora de Lima","time",S.schedule,"required"),
        v=>run("gestion.schedule",{time:v.time},"Horario guardado"))),
        button("Generar informe",()=>confirmAction("Generar informe de faltantes",
          "Se guardará el conteo actual. Si hay insumos críticos, se creará una hoja de compra editable.",
          "report",{},"Generar informe","Informe generado"))));
    return stack(budgetCard(S.budget),procurement,reports);
  };
  document.addEventListener("change",event=>{
    if(route==="compras"&&event.target.name==="purchase_day"){
      selectedPurchaseDay=event.target.value===(S.calendar_today||S.today)?"":event.target.value;
      render();
      document.querySelector('#view [name="purchase_day"]')?.focus();
    }
  });

  function configureAlerts() {
    const fields=select("item_id","Insumo",itemOptions())+
      input("min_qty","Cantidad mínima crítica","number","","required min=0 max=1000000 step=0.001")+
      '<div id="alert-expiry-fields">'+
      input("warn_days","Avisar antes del vencimiento (días)","number","","required min=0 max=3650 step=1")+
      '</div><p id="alert-expiry-preview" class="muted" aria-live="polite"></p>';
    const dialog=modal("Configurar alertas",fields,values=>{
      const selected=item(Number(values.item_id));
      values.min_qty=stockQuantityPayload(selected.name,selected.unit,values.min_qty);
      return run("gestion.configure_alerts",values,"Alertas del insumo actualizadas");
    },"Guardar alertas");
    const form=dialog.querySelector("form");
    const itemField=form.elements.namedItem("item_id");
    const minimum=form.elements.namedItem("min_qty");
    const days=form.elements.namedItem("warn_days");
    const expiryFields=dialog.querySelector("#alert-expiry-fields");
    const preview=dialog.querySelector("#alert-expiry-preview");

    function updatePreview() {
      const selected=item(Number(itemField.value));
      const source=item(selected.base_id)||selected;
      if(!source.perishable){
        preview.textContent="Este insumo se registra sin vencimiento.";
        return;
      }
      const lot=rows("lots").find(l=>l.item_id===source.id&&l.expiry&&l.expiry>=(S.calendar_today||S.today));
      const shared=source.id!==selected.id?`Se usan los lotes de ${source.name}. `:"";
      if(!lot){
        preview.textContent=shared+"El aviso se aplicará cuando ingresen lotes con fecha de vencimiento.";
        return;
      }
      const expiryText=`Próximo vencimiento: ${date(lot.expiry)} (${lot.code}).`;
      if(!days.value||!days.validity.valid){
        preview.textContent=shared+expiryText;
        return;
      }
      const alertDate=new Date(lot.expiry+"T00:00:00Z");
      alertDate.setUTCDate(alertDate.getUTCDate()-Number(days.value));
      preview.textContent=shared+expiryText+` Aviso desde el ${date(alertDate.toISOString())}.`;
    }

    function loadSettings() {
      const selected=item(Number(itemField.value));
      const source=item(selected.base_id)||selected;
      minimum.value=stockInputValue(selected.name,selected.unit,selected.min_qty);
      setItemQuantityStep(minimum,selected.name,true,minimum.value);
      minimum.max=stockInputValue(selected.name,selected.unit,1000000);
      minimum.closest("label").querySelector("span").textContent=
        `Cantidad mínima crítica (${stockMeasure(selected.name,selected.unit).unit})`;
      days.value=source.warn_days;
      days.disabled=!source.perishable;
      expiryFields.hidden=days.disabled;
      updatePreview();
    }
    itemField.addEventListener("change",loadSettings);
    minimum.addEventListener("input",()=>{
      const selected=item(Number(itemField.value));
      setItemQuantityStep(minimum,selected.name,true,stockInputValue(selected.name,selected.unit,selected.min_qty));
    });
    days.addEventListener("input",updatePreview);
    loadSettings();
  }

  pages.alertas = () => {
    const data=rows("alerts"), active=data.filter(x=>!x.closed);
    return stack(group(metric("Alertas activas",active.length),
      metric("En stock mínimo",active.filter(x=>x.kind==="Stock mínimo").length),
      metric("Próximos a vencer",active.filter(x=>x.kind==="Próximo a vencer").length)),
      panel("Seguimiento de alertas",table(["Alerta","Insumo","Detalle","Fecha","Estado"],data.map(x=>[
        e(x.code),e(x.item_name)+sub(x.area),e(x.message),e(when(x.created)),
        badge(x.closed?"Resuelta":"Activa")+(x.closed?sub(when(x.closed)):"")
      ]),"No se han detectado alertas en tu inventario."),
      admin()&&rows("items").length?button("Configurar alertas",configureAlerts,"primary"):""));
  };
})();
