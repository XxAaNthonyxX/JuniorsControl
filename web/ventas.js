
"use strict";

// Importes en céntimos. Los cobros y devoluciones pertenecen al día de su propia operación.
function ventasPeriodo(orders,start,end){
 const report={count:0,gross:0,refunded:0,net:0,unlocated:0,entries:[]};
 const rows=new Map();
 function addLine(line,quantity,cents,isReturn){
   let row=rows.get(line.product_id);
   if(!row){row={name:line.name,sold:0,returned:0,amount:0};rows.set(line.product_id,row)}
   if(isReturn){row.returned+=quantity;row.amount-=cents}else{row.sold+=quantity;row.amount+=cents}
 }
 const inRange=at=>at&&at.slice(0,10)>=start&&at.slice(0,10)<=end;
 for(const o of orders){
   if(!o.paid_at||o.paid_at.slice(0,10)>end)continue;
   const credits=new Map();
   if(inRange(o.paid_at)){
     let gross=0;
     for(const line of o.lines){
       const amount=Math.round(line.price*100)*line.qty;
       gross+=amount;addLine(line,line.qty,amount,false);
     }
     report.gross+=gross;report.count++;
     report.entries.push({at:o.paid_at,kind:"Cobro",code:o.sale_code,order:o.code,day:o.day,mesa:o.table_name,who:o.cashier,amount:gross,id:o.id});
   }
   for(const r of o.returns||[]){
     const line=o.lines.find(l=>l.product_id===r.product_id);
     if(!line)continue;
     credits.set(line.product_id,(credits.get(line.product_id)||0)+r.qty);
     if(!inRange(r.at))continue;
     const amount=Math.round(line.price*100)*r.qty;
     report.refunded+=amount;addLine(line,r.qty,amount,true);
     report.entries.push({at:r.at,kind:"Devolución",code:r.code,order:o.code,day:o.day,mesa:o.table_name,who:r.operator,amount:-amount,id:o.id});
   }
   for(const l of o.lines){
     report.unlocated+=Math.max(0,l.refunded-(credits.get(l.product_id)||0))*Math.round(l.price*100);
   }
 }
 report.net=report.gross-report.refunded;
 report.products=[...rows.values()].sort((a,b)=>b.amount-a.amount||a.name.localeCompare(b.name,"es"));
 report.entries.sort((a,b)=>b.at.localeCompare(a.at)||b.id-a.id||a.kind.localeCompare(b.kind));
 return report;
}
(() => {
 let owner=null,from="",to="";
 const money=cents=>cash(cents/100);
 function downloadReport(report){
   const rows=[["Fecha y hora","Operación","Código","Comanda","Jornada de comanda","Mesa o referencia","Responsable","Importe (S/)"]];
   for(const e of report.entries)rows.push([e.at,e.kind,e.code,e.order,e.day,e.mesa,e.who,e.amount/100]);
   exportCsv(`Ventas_${from}_${to}.csv`,rows);
 }
 function paint(){
   if(!["admin","caja"].includes(S.user.role))return "";
   if(owner!==S.user.id){owner=S.user.id;from=S.today;to=S.today}
   const r=ventasPeriodo(S.orders,from,to);
   const metric=(label,value)=>`<div class="metric"><span>${h(label)}</span><b class="value">${h(value)}</b></div>`;
   const records=r.entries.map(e=>[
      `<b>${h(e.code)}</b><small class="sub">${h(e.kind)}</small>`,
      h(e.at),`<b>${h(e.order)}</b><small class="sub">${h(displayDate(e.day))}</small>`,
      h(e.mesa),h(e.who),money(e.amount)]);
   const products=r.products.map(p=>[h(p.name),fmt(p.sold),fmt(p.returned),money(p.amount)]);
   const filters=`<form id="ventas-filtro" class="actions filters">${input("desde","Desde","date",from,"required")}${input("hasta","Hasta","date",to,"required")}<button class="btn primary">Consultar</button></form>`;
   return panel("Período de caja",filters)+`<div class="metrics">${metric("Ventas cobradas",r.count)}${metric("Cobros",money(r.gross))}${metric("Devoluciones",money(r.refunded))}${metric("Ingreso neto",money(r.net))}</div>`+
      (r.unlocated?`<p class="notice">El historial anterior contiene ${money(r.unlocated)} en devoluciones sin fecha registrada. El informe incluye los movimientos con fecha verificable.</p>`:"")+
      panel("Movimientos de caja",table(["Documento","Fecha de operación","Comanda","Mesa o referencia","Responsable","Importe"],records,"Sin cobros ni devoluciones en este período."),
            records.length?button("Descargar CSV",()=>downloadReport(r)):"")+
      panel("Ventas por producto",table(["Producto","Unidades cobradas","Devueltas","Importe neto"],products,"Sin productos en el período seleccionado."));
 }
 pages.ventas=paint;
 document.addEventListener("submit",async e=>{
   if(e.target.id!=="ventas-filtro")return;e.preventDefault();
   const form=e.target,values=new FormData(form),a=values.get("desde"),b=values.get("hasta");
   if(a>b){toast("La fecha inicial debe ser anterior o igual a la fecha final.",true);return}
   const btn=form.querySelector("button");btn.disabled=true;
   try{await reload();from=a;to=b;render()}catch(ex){toast(ex.message,true)}finally{btn.disabled=false}
 });
})();

