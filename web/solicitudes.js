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
   const line=S.orders.find(o=>o.id===r.order_id)?.lines.find(l=>l.product_id===r.product_id);
   const ingredients=line?.ingredients||[];
   const fields=approve?`<fieldset><legend>Insumos aptos para volver al lote original</legend>${ingredients.map(i=>
     `<label class="check"><input type="checkbox" name="rec_${i.item_id}">${h(i.name)}</label>`).join("")}</fieldset>`:
     input("reason","Motivo del rechazo","text","","required maxlength=300");
   modal(approve?"Aprobar devolución":"Rechazar devolución",`<p>${h(reference(r))} · ${r.qty} × ${h(r.name)}</p><p>${h(r.reason)}</p>`+fields,
     v=>run("pedidos.resolve_refund",{id:r.id,approve,reason:v.reason,restock:ingredients.filter(i=>v["rec_"+i.item_id]).map(i=>i.item_id)},
       approve?"Devolución registrada en caja":"Solicitud rechazada"),approve?"Confirmar devolución":"Rechazar");
 }
 pages.solicitudes=()=>{
   const data=S.service_requests,manager=["admin","caja"].includes(S.user.role);
   const open=S.orders.filter(o=>["Reservado","Por revisar"].includes(o.status)&&!o.cancel_request&&!o.details.some(d=>d.status==="Entregado"));
   const cancels=data.cancellations.map(r=>{
     const order=S.orders.find(o=>o.id===r.order_id);
     return [h(reference(r)),h(r.reason),h(r.requester),h(r.requested_at),badge(r.status),h(r.decided_by||""),h([r.decided_at,r.decision_reason].filter(Boolean).join(" · ")),
       manager&&order?.cancel_request?.id===r.id?button("Resolver",()=>decideCancel(order)):""];
   });
   const refunds=data.refunds.map(r=>[h(reference(r)),h(r.name),r.qty,h(r.reason),h(r.requester),h(r.requested_at),badge(r.status),
     h([r.decided_by,r.decided_at,r.decision_reason,r.return_id?"DV"+String(r.return_id).padStart(4,"0"):""].filter(Boolean).join(" · ")),
     manager&&r.status==="Pendiente"?button("Aprobar",()=>decide(r,true),"primary")+button("Rechazar",()=>decide(r,false)):""]);
   const completed=manager?S.orders.flatMap(o=>(o.returns||[]).map(r=>[h(r.code),h(o.code+" · "+o.day),h(r.name),r.qty,h(r.reason),h(r.operator),h(r.at),h(r.exchange_code||"")])):[];
   return panel("Solicitudes de anulación",table(["Comanda","Motivo","Solicitante","Fecha","Estado","Responsable","Resuelta","Acción"],cancels),
     open.length?button("Solicitar anulación",()=>modal("Seleccionar comanda",select("order","Comanda",open.map(o=>[o.id,o.code+" · "+o.day+" · "+o.table_name]))+
       input("reason","Motivo","text","","required maxlength=500"),v=>{const o=open.find(o=>o.id===Number(v.order));return run("pedidos.request_cancel",{id:o.id,version:o.version,reason:v.reason},"Solicitud registrada")})):"")+
     panel("Solicitudes de devolución",table(["Comanda","Producto","Unidades","Motivo","Solicitante","Fecha","Estado","Resolución","Acciones"],refunds))+
     panel("Productos que se pueden devolver",table(["Venta de la comanda","Producto","Unidades disponibles","Acción"],
       data.refundable.filter(r=>r.remaining>0).map(r=>[h(reference(r)),h(r.name),r.remaining,button("Solicitar devolución",()=>requestReturn(r))])))+
     (manager?panel("Devoluciones registradas",table(["Documento","Comanda","Producto","Unidades","Motivo","Responsable","Fecha","Cambio"],completed)):"");
 };
})();
