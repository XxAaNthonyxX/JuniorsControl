
"use strict";

// Importes en céntimos. Los cobros y devoluciones pertenecen al día de su propia operación.
function ventasPeriodo(orders,start,end){
 const report={count:0,gross:0,refunded:0,voided:0,net:0,unlocated:0,entries:[],collections:new Map()};
 const rows=new Map();
 function addLine(line,quantity,cents,isReturn){
   let row=rows.get(line.product_id);
   if(!row){row={name:line.name,sold:0,returned:0,amount:0};rows.set(line.product_id,row)}
   if(isReturn){row.returned+=quantity;row.amount-=cents}else{row.sold+=quantity;row.amount+=cents}
 }
 const inRange=at=>at&&at.slice(0,10)>=start&&at.slice(0,10)<=end;
 for(const o of orders){
   const v=o.sale_void;
   if(v&&inRange(v.cash_day)){
     report.voided+=v.cents;
     report.entries.push({at:v.at,kind:"Anulación de venta",code:o.sale_code||o.code,order:o.code,day:o.day,mesa:o.table_name,who:v.actor,amount:-v.cents,id:o.id});
     if(o.paid_at)for(const l of o.lines)addLine(l,-(l.qty-l.refunded),-Math.round(l.price*100)*(l.qty-l.refunded),false);
   }
   if(!o.paid_at)continue;
   const credits=new Map();
   if(inRange(o.cash_day||o.paid_at)){
     let gross=0;
     for(const line of o.lines){
       const amount=Math.round(line.price*100)*line.qty;
       gross+=amount;addLine(line,line.qty,amount,false);
     }
     report.gross+=gross;report.count++;
     const payments=o.payments?.length?o.payments:[{method:o.payment_method||"Sin especificar",cents:gross}];
     for(const {method,cents} of payments){
       report.collections.set(method,(report.collections.get(method)||0)+cents);
     }
     report.entries.push({at:o.paid_at,kind:"Cobro",payments,code:o.sale_code,order:o.code,day:o.day,mesa:o.table_name,who:o.cashier,amount:gross,id:o.id});
   }
   for(const r of o.returns||[]){
     const line=o.lines.find(l=>l.product_id===r.product_id);
     if(!line)continue;
     const amount=Math.round(line.price*100)*r.qty;
     if(r.undone_at&&inRange(r.undone_day)){
       report.refunded-=amount;addLine(line,-r.qty,-amount,true);
       report.entries.push({at:r.undone_at,kind:"Reversión de devolución",code:r.code,order:o.code,day:o.day,mesa:o.table_name,who:r.undone_by,amount,id:o.id});
     }
     if(!r.undone_at)credits.set(line.product_id,(credits.get(line.product_id)||0)+r.qty);
     if(!inRange(r.cash_day||r.at))continue;
     report.refunded+=amount;addLine(line,r.qty,amount,true);
     report.entries.push({at:r.at,kind:"Devolución",code:r.code,order:o.code,day:o.day,mesa:o.table_name,who:r.operator,amount:-amount,id:o.id});
   }
   for(const l of o.lines){
     report.unlocated+=Math.max(0,l.refunded-(credits.get(l.product_id)||0))*Math.round(l.price*100);
   }
 }
 report.net=report.gross-report.refunded-report.voided;
 report.products=[...rows.values()].sort((a,b)=>b.amount-a.amount||a.name.localeCompare(b.name,"es"));
 report.entries.sort((a,b)=>b.at.localeCompare(a.at)||b.id-a.id||a.kind.localeCompare(b.kind));
 return report;
}
(() => {
 let owner=null,from="",to="",activeDay="";
 const money=cents=>cash(cents/100);
 const resultLabel=value=>value<0?"Pérdida":value>0?"Ganancia":"Resultado";
 const expensesFor=(start,end)=>(S.cash_expenses||[]).filter(e=>e.day>=start&&e.day<=end);
 function cashResult(net,expenses){
   const active=expenses.filter(e=>!e.void_at);
   const personal=active.filter(e=>e.kind==="Personal").reduce((sum,e)=>sum+e.cents,0);
   const market=active.filter(e=>e.kind==="Mercado").reduce((sum,e)=>sum+e.cents,0);
   return {personal,market,expenses:personal+market,result:net-personal-market};
 }
 async function openCashCount(start,end){
   await reload();
   const sales=ventasPeriodo(S.orders,start,end);
   const count=cashResult(sales.net,expensesFor(start,end));
   const amounts=[
     ["Ventas cobradas",sales.gross],["Devoluciones",-sales.refunded],["Anulaciones",-sales.voided],
     ["Ventas netas",sales.net],["Gastos de personal",-count.personal],["Gastos de mercado",-count.market],
     ["Total de gastos",-count.expenses],
   ];
   const period=start===end?displayDate(start):displayDate(start)+" al "+displayDate(end);
   modal("Arqueo de caja",`<p>${h(period)}</p>${table(["Concepto","Importe"],amounts.map(([label,value])=>[h(label),money(value)]))}
     <div class="total"><strong>${resultLabel(count.result)}</strong><strong>${money(count.result)}</strong></div>`,null);
 }
 function addExpense(){
   modal("Registrar gasto",input("day","Jornada","date",S.today,"readonly required")+
     input("receipt_preview","Boleta provisional","text",S.next_cash_expense_code,"readonly")+
     select("kind","Tipo",[["Personal","Personal"],["Mercado","Mercado"]])+
     input("reference","Referencia externa (opcional)","text","","maxlength=100")+
     input("concept","Concepto","text","","required maxlength=300")+
     input("amount","Importe (S/)","number","","min=0.01 step=0.01 required"),
     async ({day,kind,reference,concept,amount})=>{
       const expense=await run("gestion.cash_expense",{day,kind,reference,concept,amount},"");
       toast("Gasto registrado · "+expense.code);
     });
 }
 function downloadReport(report){
   const rows=[["Fecha y hora","Operación","Código","Comanda","Jornada de comanda","Mesa o referencia","Responsable","Importe (S/)","Medios de pago"]];
   for(const e of report.entries)rows.push([e.at,e.kind,e.code,e.order,e.day,e.mesa,e.who,e.amount/100,formatPayments(e.payments)]);
   exportCsv(`Ventas_${from}_${to}.csv`,rows);
 }
 function viewDay(day){
   owner=S.user.id;activeDay=S.today;from=day;to=day;go("ventas");
 }
 function openDay(day){
   const expected=S.today;
   modal("Abrir jornada",input("day","Fecha de trabajo","date",day||S.today,"required")+
     "<p>La fecha seleccionada se aplicará a Atención, preparación y Caja.</p>",
     v=>run("gestion.cash_day",{day:v.day,expected_day:expected},"Jornada abierta"),"Abrir jornada");
 }
 pages.jornadas=()=>{
   const counts=new Map();
   for(const order of S.orders)counts.set(order.day,(counts.get(order.day)||0)+1);
   const rows=S.registered_days.map(d=>[
     h(d.day),d.day===S.today?badge("Activa"):"",
     counts.get(d.day)||0,h(d.opened_by||"—"),h(d.opened_at||"—"),
     button("Ver comandas",()=>viewOrdersDay(d.day),"link")+button("Ver arqueo",()=>viewDay(d.day),"link")+(d.day===S.today?"":button("Abrir jornada",()=>openDay(d.day),"secondary"))]);
   return panel("Jornada activa · "+displayDate(S.today),table(["Fecha","Estado","Comandas","Registrada por","Fecha de registro","Acciones"],rows),
     button("Abrir fecha",()=>openDay(),"primary"));
 };
 function saleActions(o){
   if(!o)return "";
   if(o.cancel_request)return '<small class="muted">Anulación solicitada</small>';
   const refund=o.status==="Cobrado"&&o.details.some(d=>d.refundable_qty>0)?
     button("Gestionar devolución",()=>refundOrder(o),"secondary"):"";
   return refund+(canRequestCancel(o)?button("Solicitar anulación",()=>requestCancel(o),"secondary"):"");
 }
 function collectionPanel(){
   const orders=S.orders.filter(o=>o.day===S.today&&["Reservado","Por revisar"].includes(o.status)&&!o.cancel_request&&o.details.some(d=>d.status==="Entregado"));
   const rows=orders.map(o=>{
     const delivered=o.details.filter(d=>d.status==="Entregado");
     const cents=delivered.reduce((total,d)=>total+Math.round(d.price*100)*d.qty,0);
     return [h(o.code),h(o.table_name),cash(o.total),money(cents),
       button("Cobrar",()=>chargeOrder(o),"primary")+button("Solicitar anulación",()=>requestCancel(o),"secondary")];
   });
   return panel("Comandas con entregas",table(["Comanda","Mesa","Solicitado","A cobrar ahora","Acción"],rows,"Aún no hay comandas pendientes de cobro con productos entregados."));
 }
 function paint(){
   if(!["admin","caja"].includes(S.user.role))return "";
   if(owner!==S.user.id||activeDay!==S.today){owner=S.user.id;activeDay=S.today;from=S.today;to=S.today}
   const r=ventasPeriodo(S.orders,from,to);
   const metric=(label,value)=>`<div class="metric"><span>${h(label)}</span><b class="value">${h(value)}</b></div>`;
   const records=r.entries.map(e=>[
      `<b>${h(e.code)}</b><small class="sub">${h(e.kind)}</small>${e.payments?.length?`<small class="sub">${h(formatPayments(e.payments))}</small>`:""}`,
      h(e.at),`<b>${h(e.order)}</b><small class="sub">${h(displayDate(e.day))}</small>`,
      h(e.mesa),h(e.who),money(e.amount),button("Ver detalle de comanda",()=>details(S.orders.find(o=>o.id===e.id),true),"link")+(e.kind==="Cobro"?saleActions(S.orders.find(o=>o.id===e.id)):"")]);
   const products=r.products.map(p=>[h(p.name),fmt(p.sold),fmt(p.returned),money(p.amount)]);
   const filters=`<form id="ventas-filtro" class="actions filters">${input("desde","Desde","date",from,"required")}${input("hasta","Hasta","date",to,"required")}<button class="btn primary">Consultar</button></form>`;
   const expenses=expensesFor(from,to);
   const count=cashResult(r.net,expenses);
   const outsidePurchase=(S.cash_expenses||[]).find(e=>e.purchase_id&&!e.void_at&&(e.day<from||e.day>to));
   const purchaseNotice=outsidePurchase?`<div class="notice actions">
     <span>Hay compras registradas el ${h(displayDate(outsidePurchase.day))} fuera del período de caja.</span>
     ${button("Incluir esas compras en el arqueo",()=>{
       if(outsidePurchase.day<from)from=outsidePurchase.day;
       if(outsidePurchase.day>to)to=outsidePurchase.day;
       render();
     },"link")}</div>`:"";
   const expenseRows=expenses.map(e=>[h(displayDate(e.day)),h(e.code),h(e.kind),h(e.purchase_id?"OC"+String(e.purchase_id).padStart(4,"0"):e.reference||"—"),h(e.concept),money(e.cents),h(e.actor),
     e.void_at?h("Anulado · "+e.void_reason+" · "+e.void_by):e.purchase_id?"Automático · Compras":e.day!==S.today?"Registrado":button("Anular",()=>modal("Anular gasto · "+e.code,input("reason","Motivo","text","","required"),
       v=>run("gestion.void_expense",{id:e.id,day:e.day,reason:v.reason},"Gasto anulado")),"link")]);
   const methodOrder=new Set([...paymentMethods,"Sin especificar","Cambio",...r.collections.keys()]);
   const methods=[...methodOrder].map(method=>[method,r.collections.get(method)]).filter(([,amount])=>amount);
   const expectedDay=S.today;
   const jornada=button("Cambiar jornada",()=>modal("Jornada de caja",input("day","Fecha de trabajo (vacía para usar la fecha actual)","date",S.today),
     async v=>{await run("gestion.cash_day",{...v,expected_day:expectedDay},"Jornada actualizada");from=S.today;to=S.today;render()}),"secondary");
   return collectionPanel()+panel("Período de caja",filters,jornada)+`<div class="metrics">${metric("Ventas cobradas",r.count)}${metric("Cobros",money(r.gross))}${metric("Devoluciones",money(r.refunded))}${metric("Anulaciones",money(r.voided))}${metric("Ingreso neto",money(r.net))}</div>`+
      (r.unlocated?`<p class="notice">El historial anterior contiene ${money(r.unlocated)} en devoluciones sin fecha registrada. El informe incluye los movimientos con fecha verificable.</p>`:"")+
      panel("Arqueo de caja",`<div class="metrics">${metric("Ventas netas",money(r.net))}${metric("Personal",money(count.personal))}${metric("Mercado",money(count.market))}${metric(resultLabel(count.result),money(count.result))}</div>`+
        table(["Medio de pago","Cobros"],methods.map(([m,v])=>[h(m),money(v)]),"Sin cobros"),
        button("Calcular arqueo",()=>openCashCount(from,to),"primary"))+
      panel("Gastos de caja",purchaseNotice+table(["Fecha","Boleta","Tipo","Referencia","Concepto","Importe","Responsable","Estado"],expenseRows,"Sin gastos en el período seleccionado."),button("Registrar gasto",addExpense,"primary"))+
      panel("Movimientos de caja",table(["Documento","Fecha de operación","Comanda","Mesa o referencia","Responsable","Importe","Acción"],records,"Sin cobros ni devoluciones en este período."),
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

