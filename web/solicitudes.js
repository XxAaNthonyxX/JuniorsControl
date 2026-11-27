"use strict";
(() => {
 const reference=r=>"C"+String(r.number).padStart(4,"0")+" · "+r.day+" · "+r.table_name;
 function requestReturn(r){
   modal("Solicitar devolución",`<p>${h(reference(r))} · ${h(r.name)}</p>`+
     input("qty","Unidades","number",1,`required min=1 max=${r.remaining} step=1`)+
     input("reason","Motivo","text","","required maxlength=300"),
     v=>run("pedidos.request_refund",{id:r.id,product_id:r.product_id,qty:v.qty,reason:v.reason},"Solicitud registrada"));
 }
 function decide(r,approve){
   const order=S.orders.find(o=>o.id===r.order_id);
   const details=(order?.details||[]).filter(d=>d.product_id===r.product_id&&d.refundable_qty>0);
   const ingredients=order?.lines.find(l=>l.product_id===r.product_id)?.ingredients||[];
   const fields=approve?(details.length?
     `<p>Selecciona ${r.qty} unidades y marca los detalles que regresan al inventario.</p>`+refundDetailFields(details):
     `<fieldset><legend>Insumos que regresan al inventario</legend>${ingredients.map(i=>
       `<label class="check"><input type="checkbox" name="restock_${i.item_id}">${h(i.name)}</label>`).join("")}</fieldset>`):
     input("reason","Motivo del rechazo","text","","required maxlength=300");
   modal(approve?"Aprobar devolución":"Rechazar devolución",`<p>${h(reference(r))} · ${r.qty} × ${h(r.name)}</p><p>${h(r.reason)}</p>`+fields,
     v=>{
       const payload={id:r.id,revision:r.revision,approve,reason:v.reason};
       if(approve&&details.length){
         payload.details=selectedRefundDetails(details,v);
         if(payload.details.reduce((sum,d)=>sum+d.qty,0)!==r.qty)throw Error(`Selecciona exactamente ${r.qty} unidades.`);
       }else if(approve){
         payload.restock=ingredients.filter(i=>v["restock_"+i.item_id]).map(i=>i.item_id);
       }
       return run("pedidos.resolve_refund",payload,approve?"Devolución registrada en caja":"Solicitud rechazada");
     },approve?"Confirmar devolución":"Rechazar");
 }
 function undo(r,kind){
   const effect=r.status==="Rechazada"?"Podrás volver a resolver la solicitud.":kind==="cancel"?
     (r.paid_at?"Se revertirá la anulación en Caja y la reposición de inventario.":
       "La comanda volverá a ocupar la mesa y quedará en pausa hasta que resuelvas la solicitud."):
     "Caja registrará la reversión del abono y se descontarán los insumos que volvieron al inventario.";
   modal("Deshacer decisión",`<p>${h(reference(r))} · ${h(r.status)}</p><p>La solicitud volverá a Pendiente. ${effect}</p>`,
     ()=>run("pedidos.undo_request",{id:r.id,kind,revision:r.revision},"Decisión deshecha. Solicitud pendiente."),"Deshacer");
 }
 pages.solicitudes=()=>{
   const data=S.service_requests,manager=["admin","caja"].includes(S.user.role);
   const eligible=S.orders.filter(o=>(o.day===S.today||o.cash_day===S.today)&&canRequestCancel(o));
   const cancels=data.cancellations.map(r=>{
     const order=S.orders.find(o=>o.id===r.order_id);
     return [h(reference(r))+(r.paid_at?'<small class="sub">Venta cobrada</small>':""),h(r.reason),h(r.requester),h(r.requested_at),badge(r.status),h(r.decided_by||""),h([r.decided_at,r.decision_reason].filter(Boolean).join(" · ")),
       manager&&r.status==="Pendiente"&&order?.cancel_request?.id===r.id?button("Resolver",()=>decideCancel(order)):manager&&r.status!=="Pendiente"?button("Deshacer",()=>undo(r,"cancel")):""];
   });
   const refunds=data.refunds.map(r=>{
     const order=S.orders.find(o=>o.id===r.order_id);
     const actions=manager&&order?.status!=="Anulada"&&!order?.cancel_request;
     return [h(reference(r)),h(r.name),r.qty,h(r.reason),h(r.requester),h(r.requested_at),badge(r.status),
     h([r.decided_by,r.decided_at,r.decision_reason,r.return_id?"DV"+String(r.return_id).padStart(4,"0"):""].filter(Boolean).join(" · ")),
       actions&&r.status==="Pendiente"?button("Aprobar",()=>decide(r,true),"primary")+button("Rechazar",()=>decide(r,false)):
         actions?button("Deshacer",()=>undo(r,"refund")):""];
   });
   const completed=manager?S.orders.flatMap(o=>(o.returns||[]).filter(r=>(r.cash_day||r.at.slice(0,10))===S.today||r.undone_day===S.today).map(r=>[h(r.code),h(o.code+" · "+o.day),h(r.name),r.qty,h(r.reason),h(r.operator),h(r.at),h(r.undone_at?"Revertida · "+r.undone_by:r.exchange_code||"Registrada")])):[];
   return panel("Solicitudes de anulación",table(["Comanda","Motivo","Solicitante","Registrada el","Estado","Responsable","Resuelta","Acción"],cancels),
     eligible.length?button("Solicitar anulación",()=>modal("Seleccionar comanda",select("order","Comanda",eligible.map(o=>[o.id,o.code+" · "+o.day+" · "+o.table_name]))+
       input("reason","Motivo","text","","required maxlength=500"),v=>{const o=eligible.find(o=>o.id===Number(v.order));return run("pedidos.request_cancel",{id:o.id,version:o.version,reason:v.reason},"Solicitud registrada")})):"")+
     panel("Solicitudes de devolución",table(["Comanda","Producto","Unidades","Motivo","Solicitante","Registrada el","Estado","Resolución","Acciones"],refunds))+
     panel("Productos que se pueden devolver",table(["Venta de la comanda","Producto","Unidades disponibles","Acción"],
       data.refundable.filter(r=>r.remaining>0).map(r=>[h(reference(r)),h(r.name),r.remaining,button("Solicitar devolución",()=>requestReturn(r))])))+
     (manager?panel("Devoluciones registradas",table(["Documento","Comanda","Producto","Unidades","Motivo","Responsable","Fecha","Estado / cambio"],completed)):"");
 };
})();
