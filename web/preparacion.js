"use strict";
// Vista específica del área; el servidor filtra de nuevo y autoriza cada transición.
(() => {
 const stages={"En cola":["preparar","Iniciar preparación"],"Preparando":["listo","Marcar listo"],"Listo":["entregar","Marcar entregado"]};
 function card(r){
  const next=stages[r.status];
  const controls=r.cancel_pending?'<span class="badge amber">Cancelación pendiente · en pausa</span>':next?button(next[1],()=>advance(r,next[0]),"primary"):'<span class="badge green">Entregado</span>';
  return `<article class="prep-card"><div><strong>${h(r.code)} · ${h(r.name)}</strong><small class="sub">${h(r.day)} · Piso ${r.table_number?Number(r.table_number)>10?2:1:"?"} · Mesa ${h(r.table_number||"-")} · ${h(r.qty)} unidades</small></div><div class="prep-status">${badge(r.status)} <span class="muted">${h(r.area)}</span></div><div class="muted">Enviado: ${h(r.sent_at||"-")} · Iniciado: ${h(r.started_at||"-")} · Listo: ${h(r.ready_at||"-")} · Entregado: ${h(r.delivered_at||"-")}</div>${controls}</article>`;
 }
 async function advance(r,step){
  await run("pedidos.prep",{id:r.order_id,product_id:r.product_id,step},"Estado actualizado en preparación");
 }
 pages.preparacion=()=>{
  const jobs=S.preparation||[];
  const areas=[...new Set(jobs.map(r=>r.area))];
  const active=jobs.filter(r=>r.status!=="Entregado");
  return `<div class="metrics"><div class="metric"><span>Pedidos del área</span><b class="value">${jobs.length}</b></div><div class="metric"><span>Por atender</span><b class="value">${active.length}</b></div></div>`+
    panel("Cola de " +(S.user.role==="area"?S.user.area:"todas las áreas"),
      `<p class="muted">Cada producto avanza: En cola → Preparando → Listo → Entregado. Se conservan las horas de cada paso.</p><div class="prep-grid">${jobs.length?jobs.map(card).join(""):'<div class="empty-state">No hay pedidos enviados a esta área.</div>'}</div>`);
 };
})();
