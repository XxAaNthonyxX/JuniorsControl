"use strict";
// Vista específica del área; el servidor filtra de nuevo y autoriza cada transición.
(() => {
 function card(r){
  const controls=r.cancel_pending?'<span class="badge amber">Cancelación pendiente · en pausa</span>':r.status!=="Entregado"?button("Marcar como entregado",()=>deliver(r),"primary"):'<span class="badge green">Entregado</span>';
  return `<article class="prep-card"><div><strong>${h(r.code)} · Detalle ${r.detail_no} · ${h(r.name)}</strong><small class="sub">${h(r.day)} · Piso ${r.table_number?Number(r.table_number)>10?2:1:"?"} · Mesa ${h(r.table_number||"-")} · ${h(r.qty)} unidades</small></div><div class="prep-status">${badge(r.status)} ${badge(r.take_away?"Para llevar":"En el local")} <span class="muted">${h(r.area)}</span></div><div class="muted">Enviado: ${h(r.sent_at||"-")}${r.started_at?" · Iniciado: "+h(r.started_at):""}${r.ready_at?" · Listo: "+h(r.ready_at):""} · Entregado: ${h(r.delivered_at||"-")}</div>${controls}</article>`;
 }
 async function deliver(r){
  await run("pedidos.prep",{id:r.order_id,product_id:r.product_id,detail_no:r.detail_no,revision:r.revision,step:"entregar"},"Producto marcado como entregado");
 }
 pages.preparacion=()=>{
  const jobs=(S.preparation||[]).filter(r=>r.day===S.today);
  const active=jobs.filter(r=>r.status!=="Entregado");
  return `<div class="metrics"><div class="metric"><span>Pedidos del área</span><b class="value">${jobs.length}</b></div><div class="metric"><span>Por atender</span><b class="value">${active.length}</b></div></div>`+
    panel("Cola de " +(S.user.role==="area"?S.user.area:"todas las áreas"),
      `<div class="prep-grid">${jobs.length?jobs.map(card).join(""):'<div class="empty-state">No hay pedidos enviados a esta área.</div>'}</div>`);
 };
})();
