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
  const qtyAttrs = 'required min="0.001" step="0.001"';
  const numberAttrs = 'min="0" step="0.01"';
  const stack = (...parts) => '<div class="stack">'+parts.filter(Boolean).join("")+'</div>';
  const item = id => rows("items").find(x=>x.id === id);
  const itemOptions = () => rows("items").map(x=>[x.id, x.code+" · "+x.name+" ("+x.unit+")"]);
  const note = value => '<p class="muted">'+e(value)+'</p>';
  const metric = (name,value) => '<div class="metric"><span class="muted">'+e(name)+'</span><div class="value">'+e(value)+'</div></div>';
  const group = (...metrics) => '<div class="metrics">'+metrics.join("")+'</div>';

  function confirmAction(title, text, action, payload, submit, message) {
    modal(title,note(text),()=>run("gestion."+action,payload,message),submit);
  }

  function newReceipt() {
    modal("Registrar entrega",select("item_id","Insumo",itemOptions())+
      input("supplier","Proveedor","text","","required maxlength=100")+
      input("qty","Cantidad prevista","number","",qtyAttrs)+
      input("cost","Costo unitario (S/)","number","",numberAttrs+" required")+
      note("La entrega quedará pendiente de revisión. El stock aumenta al aprobar las unidades recibidas."),
      v=>run("gestion.receipt",{item_id:v.item_id, supplier:v.supplier, qty:v.qty, unit_cents:cents(v.cost)},"Entrega registrada"),
      "Registrar entrega");
  }

  function approveReceipt(r) {
    const perishable = !!item(r.item_id)?.perishable;
    modal("Revisar "+r.code,
      note(r.supplier+" · "+r.item_name+" · "+fmt(r.qty)+" "+r.unit+" previstos.")+
      input("received","Cantidad entregada por el proveedor ("+r.unit+")","number",r.qty,'required min="0" step="0.001"')+
      input("approved","Cantidad en buen estado ("+r.unit+")","number",r.qty,'required min="0" max="'+e(r.qty)+'" step="0.001"')+
      input("expiry",perishable?"Vencimiento del lote aprobado":"Vencimiento, si corresponde","date","","")+
      input("reason","Motivo si hay unidades faltantes o rechazadas","text","","maxlength=500")+
      note("Se incorporará la cantidad en buen estado, hasta el total previsto. Una diferencia de entrega o un rechazo genera una inconformidad."),
      v=>run("gestion.receive",{id:r.id,received:v.received,approved:v.approved,expiry:v.expiry,reason:v.reason},"Revisión registrada"),
      "Confirmar revisión");
  }

  function resolveIncident(x) {
    modal("Resolver "+x.code,note(x.supplier+" · "+x.item_name+" · "+fmt(x.qty)+" "+x.unit+". "+x.reason)+
      input("resolution","Gestión con el proveedor","text","","required maxlength=500"),
      v=>run("gestion.resolve",{id:x.id,resolution:v.resolution},"Inconformidad resuelta"),"Resolver");
  }

  pages.recepcion = () => {
    const deliveries = rows("receipts");
    const issues = rows("incidents");
    return stack(group(metric("Pendientes de revisión",deliveries.filter(x=>x.status==="Pendiente").length),
      metric("Inconformidades abiertas",issues.filter(x=>!x.closed).length)),
      panel("Entregas de proveedores", table(["Entrega","Insumo","Cantidad","Revisión",""],deliveries.map(x=>[
        e(x.code)+sub(when(x.created)+" · "+x.actor),e(x.item_name)+sub(x.supplier),e(fmt(x.qty)+" "+x.unit),
        badge(x.status)+(x.approved!==null?sub((x.received!=null?fmt(x.received)+" entregados · ":"")+fmt(x.approved)+" "+x.unit+" aprobados")+
          sub(when(x.reviewed_at)+" · "+x.reviewer):""),
        x.status==="Pendiente"?button("Revisar",()=>approveReceipt(x)):(x.lot_id?muted(label("LT",x.lot_id)):"")
      ]),"Las entregas pendientes de validación aparecerán aquí."),button("Registrar entrega",newReceipt,"primary")),
      panel("Inconformidades", table(["Informe","Insumo y proveedor","Diferencia","Motivo y seguimiento","Estado"],issues.map(x=>[
        e(x.code)+sub(label("RC",x.receipt_id))+sub(when(x.created)+" · "+x.actor),e(x.item_name)+sub(x.supplier),e(fmt(x.qty)+" "+x.unit)+
        (x.missing!=null?sub(fmt(x.missing)+" faltantes · "+fmt(x.rejected)+" rechazados"):""),e(x.reason)+
        (x.resolution?sub(x.resolution)+sub(when(x.closed)+" · "+x.closer):""),
        actions(badge(x.status),admin()&&!x.closed?button("Resolver",()=>resolveIncident(x)):"")
      ]),"Aún no se han registrado diferencias de recepción.")));
  };

  function newWaste() {
    const assigned=S.inventory_access_areas;
    const lots=rows("lots").filter(x=>{
      const i=item(x.item_id);
      return x.available>0 && i && (admin() || assigned.includes(i.area));
    });
    if(!lots.length){
      toast("No hay lotes con existencias disponibles para reportar una merma.",true);
      return;
    }
    const options=lots.map(x=>[x.id,`${label("LT",x.id)} · ${item(x.item_id).name} · ${fmt(x.available)} ${item(x.item_id).unit} disponibles`]);
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
        return run("gestion.waste",{item_id:lot.item_id,lot_id:lot.id,qty:v.qty,occurred_on:v.occurred_on,reason:v.reason},"Merma reportada");
      },"Enviar a revisión");
    const form=dialog.querySelector("form");
    const dateField=form.elements.namedItem("occurred_on");
    dateField.addEventListener("input",()=>{
      const future=dateField.value>calendarToday&&dateField.value!==activeDay;
      dateField.setCustomValidity(future?"Selecciona hoy, una fecha anterior o la fecha de la jornada activa.":"");
    });
    const lotField=form.elements.namedItem("lot");
    const quantityField=form.elements.namedItem("qty");
    const updateLimit=()=>{quantityField.max=lots.find(x=>x.id===Number(lotField.value)).available;};
    lotField.addEventListener("change",updateLimit);
    updateLimit();
  }

  function reviewWaste(x,approve) {
    const verb=approve?"Aprobar":"Rechazar";
    const effect=approve?"Se descontará la cantidad de la merma.":"Las reservas de esta merma se liberarán.";
    confirmAction(verb+" "+x.code,fmt(x.qty)+" "+x.unit+" de "+x.item_name+". "+x.reason+". "+effect,
      "review_waste",{id:x.id,approve},verb,approve?"Merma aprobada":"Merma rechazada");
  }

  pages.mermas = () => {
    const data=rows("wastes");
    return panel("Reportes de merma",table(["Reporte","Lote e insumo","Cantidad","Motivo","Estado",""],data.map(x=>[
      e(x.code)+sub(date(x.occurred_on||x.created))+sub("Registro: "+when(x.created)),e(x.item_name)+sub(x.lot_id?label("LT",x.lot_id):x.area),
      e(fmt(x.qty)+" "+x.unit),e(x.reason)+sub(x.actor),badge(x.status),
      admin()&&x.status==="Pendiente"?actions(button("Aprobar",()=>reviewWaste(x,true)),button("Rechazar",()=>reviewWaste(x,false))):muted(x.reviewer)
    ]),"Aún no se han reportado mermas."),button("Reportar merma",newWaste,"primary"));
  };

  function purchaseForm(p) {
    const current=new Map((p?.lines||[]).map(x=>[x.item_id,x]));
    const options=admin()?rows("items").map(x=>({item_id:x.id,name:x.name,unit:x.unit})):
      p.lines.map(x=>({item_id:x.item_id,name:x.item_name,unit:x.unit}));
    const delegables=[["","Sin asignar"],...rows("users").filter(x=>x.active).map(x=>[x.id,x.name])];
    const assigned=admin()?select("assignee_id","Responsable delegado",delegables,p?.assignee_id||""):"";
    const lines = table(["Insumo","Cantidad","S/ por unidad"],options.map(x=>{
      const line=current.get(x.item_id);
      const n=x.item_id;
      return [e(x.name)+sub(x.unit),
        '<input aria-label="Cantidad de '+e(x.name)+'" name="q'+n+'" type="number" min="0" step="0.001" value="'+e(line?.qty||"")+'" style="width:7em">',
        '<input aria-label="Costo de '+e(x.name)+'" name="c'+n+'" type="number" min="0" step="0.01" value="'+e(line?line.unit_cents/100:"")+'" style="width:7em">'];
    }),"Agrega insumos al inventario para preparar la compra.");
    modal(p?"Editar "+p.code:"Nueva hoja de compra",
      input("supplier","Proveedor","text",p?.supplier||"","maxlength=100")+assigned+
      '<div class="full">'+note("Completa la cantidad y el costo unitario de los insumos que deseas comprar.")+lines+'</div>',
      v=>{
        const details=options.filter(x=>Number(v["q"+x.item_id])>0).map(x=>({
          item_id:x.item_id, qty:v["q"+x.item_id], unit_cents:cents(v["c"+x.item_id]||0)
        }));
        const payload={supplier:v.supplier,lines:details};
        if (admin()) payload.assignee_id=v.assignee_id;
        if (p) { payload.id=p.id; payload.version=p.version; }
        return run(p?"gestion.edit_purchase":"gestion.purchase",payload,"Hoja de compra guardada");
      },"Guardar hoja");
  }

  function purchaseDetails(p) {
    const details=table(["Insumo","Cantidad","Costo unitario","Importe"],p.lines.map(l=>[
      e(l.item_name),e(fmt(l.qty)+" "+l.unit),e(money(l.unit_cents)),e(money(l.total_cents))]),"Sin renglones.");
    modal("Detalle de "+p.code,'<div class="full">'+note((p.supplier||"Proveedor pendiente")+" · "+p.status)+
      details+note("Total: "+money(p.total_cents))+button("Descargar hoja de compra",()=>downloadPurchase(p))+'</div>',null);
  }

  function downloadPurchase(p) {
    const sheet = [
      ["Orden","Fecha","Proveedor","Estado"],[p.code,when(p.created),p.supplier,p.status],[],
      ["Insumo","Unidad","Cantidad","Precio unitario (S/)","Importe (S/)"],
      ...p.lines.map(l=>[l.item_name,l.unit,l.qty,(l.unit_cents/100).toFixed(2),(l.total_cents/100).toFixed(2)]),
      ["Total (S/)","","","",(p.total_cents/100).toFixed(2)]
    ];
    exportCsv(p.code+".csv",sheet);
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
      button("Cursar compra",()=>confirmAction("Cursar "+p.code,
      "Se comprometerán "+money(p.total_cents)+" y se crearán las recepciones esperadas. Entrega la orden a "+p.supplier+" por el canal acordado.",
      "dispatch",{id:p.id,version:p.version},"Cursar compra","Compra cursada; recepciones generadas")));
    return info;
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
      e(l.item_name),e(fmt(l.available)+" "+l.unit),e(fmt(l.minimum)+" "+l.unit),e(fmt(l.suggested)+" "+l.unit)
    ]),"Todos los insumos superaban el mínimo en el momento del informe.");
    modal("Faltantes · "+r.code,'<div class="full">'+note(when(r.created)+" · Hora de Lima")+
      items+'</div>',null);
  };

  pages.compras = () => {
    const purchases=rows("purchases");
    const procurement=panel(admin()?"Hojas de compra":"Hojas de compra delegadas",
      table(["Orden","Proveedor","Responsable","Total","Estado",""],purchases.map(p=>[
        e(p.code)+sub(when(p.created)),e(p.supplier||"Por definir")+sub(p.origin),e(p.assignee||"Administración"),
        e(money(p.total_cents)),badge(p.status),purchaseActions(p)
      ]),"Todavía no hay hojas de compra."),admin()?button("Nueva compra",()=>purchaseForm(null),"primary"):"");
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

  function configureAlerts() {
    const fields=select("item_id","Insumo",itemOptions())+
      input("min_qty","Cantidad mínima crítica","number","","required min=0 max=1000000 step=0.001")+
      '<div id="alert-expiry-fields">'+
      input("warn_days","Avisar antes del vencimiento (días)","number","","required min=0 max=3650 step=1")+
      '</div><p id="alert-expiry-preview" class="muted" aria-live="polite"></p>';
    const dialog=modal("Configurar alertas",fields,
      values=>run("gestion.configure_alerts",values,"Alertas del insumo actualizadas"),"Guardar alertas");
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
      minimum.value=selected.min_qty;
      minimum.closest("label").querySelector("span").textContent=`Cantidad mínima crítica (${selected.unit})`;
      days.value=source.warn_days;
      days.disabled=!source.perishable;
      expiryFields.hidden=days.disabled;
      updatePreview();
    }
    itemField.addEventListener("change",loadSettings);
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
