
"use strict";
let ticket={lines:[],table_name:"",table_number:null,floor:1,take_away:false,id:null,version:null,code:"",day:""},menuCategory="Todos",menuQuery="";
let orderFilter="Abiertas",orderDay=null,orderQuery="";
const menuCategoryOrder=["Brasas","Parrillas","Barra","Orientales"];
const paymentMethods=["Efectivo","Yape","Tarjeta"];
function resetTicket(){ticket={lines:[],table_name:"",table_number:null,floor:1,take_away:false,id:null,version:null,code:"",day:""};menuCategory="Todos";menuQuery="";orderFilter="Abiertas";orderDay=null;orderQuery=""}
function norm(v){return String(v||"").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"")}
function orderCode(o){return `${h(o.code)} <small class="sub">${h(displayDate(o.day))}</small>`}
function productBy(id){return S.products.find(p=>p.id===id)}
function originalLine(p){return ticket.id?S.orders.find(o=>o.id===ticket.id)?.lines.find(l=>l.product_id===p.id):null}
function priceFor(p){return originalLine(p)?.price??p.price}
function sumTicket(){return ticket.lines.reduce((sum,l)=>sum+l.price*l.qty,0)}
function wasSentToPreparation(o){return o.details.some(d=>d.sent_at)}
function replacementSlot(){
 return ticket.lines.find(l=>!l.product_id)||ticket.lines.find(l=>l.detail_no===ticket.replaceNumber);
}
function stockForMenu(replaced){
 const order=ticket.id?S.orders.find(o=>o.id===ticket.id):null;
 const recipes=new Map();
 const balances=new Map();
 for(const product of S.products)recipes.set(product.id,product.recipe);
 for(const line of order?.lines||[]){
   if(line.recipe)recipes.set(line.product_id,line.recipe);
 }
 for(const recipe of recipes.values()){
   for(const ingredient of recipe)balances.set(ingredient.item_id,Math.round(ingredient.available*1000));
 }
 if(order?.status==="Reservado"){
   for(const line of order.lines){
     for(const ingredient of line.ingredients){
       const id=ingredient.item_id;
       balances.set(id,(balances.get(id)||0)+Math.round(ingredient.qty*1000));
     }
   }
 }
 for(const line of ticket.lines){
   if(line===replaced)continue;
   for(const ingredient of recipes.get(line.product_id)||[]){
     const id=ingredient.item_id;
     balances.set(id,balances.get(id)-Math.round(ingredient.qty*1000)*line.qty);
   }
 }
 return {recipes,balances};
}
function menuAvailability(product,stock){
 const limits=(stock.recipes.get(product.id)||[]).map(ingredient=>({
   item_id:ingredient.item_id,
   count:Math.max(0,Math.floor(stock.balances.get(ingredient.item_id)/Math.round(ingredient.qty*1000))),
 }));
 const available=limits.length?Math.min(...limits.map(l=>l.count)):0;
 const shared=product.recipe.find(ingredient=>ingredient.shared_stock);
 const portions=shared?limits.find(l=>l.item_id===shared.item_id)?.count:null;
 const limitingNames=limits.filter(l=>l.count===available&&l.item_id!==shared?.item_id)
   .map(l=>product.recipe.find(ingredient=>ingredient.item_id===l.item_id)?.name).filter(Boolean);
 return {available,portions,limitingNames};
}
function addDetail(p){
 if(!ticket.table_number){toast("Selecciona primero el piso y la mesa.",true);jumpTo(".ticket-ref");return}
 const slot=replacementSlot();
 const {available}=menuAvailability(p,stockForMenu(slot));
 if(available<1){toast("Producto sin disponibilidad.",true);return}
 const detail={detail_no:slot?.detail_no??(ticket.nextDetailNo??1),
   product_id:p.id,name:originalLine(p)?.name??p.name,price:priceFor(p),qty:1};
 if(slot)Object.assign(slot,detail);else {ticket.lines.push(detail);ticket.nextDetailNo=detail.detail_no+1}
 ticket.replaceNumber=null;
 drawPOS();
}
function changeDetailQty(l,delta){
 if(l.status==="Entregado")return;
 if(delta>0&&menuAvailability(productBy(l.product_id),stockForMenu()).available<delta){
   toast("Cantidad no disponible.",true);return;
 }
 l.qty+=delta;
 if(!l.qty){l.product_id=null;l.price=0;ticket.replaceNumber=l.detail_no}
 drawPOS();
}
function removeDetail(line){
 if(line.status==="Entregado")return;
 ticket.lines=ticket.lines.filter(other=>other!==line);
 if(ticket.replaceNumber===line.detail_no)ticket.replaceNumber=null;
 drawPOS();
}
function detailCard(l){
 const delivered=l.status==="Entregado";
 const remove=delivered?"":button("Eliminar detalle",()=>removeDetail(l),"link");
 if(!l.product_id)return `<div class="ticket-item"><strong>Detalle ${l.detail_no}</strong><p>Selecciona un producto de la carta.</p>${remove}</div>`;
 const unsent=l.product_id!==l.sent_product||l.qty!==l.sent_qty;
 const state=delivered?"Entregado":unsent?(ticket.confirmChanges?"Pendiente de confirmar":"Pendiente de envío"):l.status;
 const controls=delivered?"":`<div class="actions"><div class="stepper"><button aria-label="Quitar una unidad" ${bind(()=>changeDetailQty(l,-1))}>−</button><b>${l.qty}</b><button aria-label="Añadir una unidad" ${bind(()=>changeDetailQty(l,1))}>+</button></div>
 ${button(ticket.replaceNumber===l.detail_no?"Selecciona el reemplazo en la carta":"Cambiar producto",()=>{ticket.replaceNumber=l.detail_no;drawPOS();jumpTo(".catalog")},"link")}${remove}</div>`;
 return `<div class="ticket-item"><strong>Detalle ${l.detail_no} · ${h(l.name)}</strong><small class="sub">${l.qty} × ${cash(l.price)} · ${h(state)}</small><div class="ticket-item-bottom">${controls}<b style="white-space:nowrap">${cash(l.qty*l.price)}</b></div></div>`;
}
function productStock(p){
 const rows=p.recipe.map(line=>{
   const count=Math.floor(Math.round(line.available*1000)/Math.round(line.qty*1000));
   return [h(line.name),h(formatStockQuantity(line.name,line.unit,line.qty,line)),
     h(formatStockQuantity(line.name,line.unit,line.available,line)),fmt(count)];
 });
 modal('Disponibilidad · '+p.name,
   `<p>Platos disponibles con todos los insumos de la receta: <b>${fmt(p.available)}</b>.</p>`+
   table(['Insumo','Por plato','Stock libre','Platos posibles'],rows)+
   '<p>El insumo que permite preparar menos platos marca el límite de venta. Cuartos, medios y enteros usan el mismo stock de pollo cocido.</p>',null);
}
function menuCards(){
 const products=S.products.filter(p=>(menuCategory==="Todos"||menuCategory===p.category)&&norm(p.name+" "+p.code).includes(norm(menuQuery)));
 if(!products.length)return `<div class="empty-state">No se encontraron productos. ${S.products.length?"Prueba otra búsqueda.":S.user.role==="admin"?"Añade la receta desde Inventario.":""}</div>`;
 const stock=stockForMenu(replacementSlot());
 return `<div class="menu-grid">${products.map(p=>{
 const {available:left,portions,limitingNames}=menuAvailability(p,stock);
 const chicken=portions==null?"":`<small>Pollo cocido para ${fmt(portions)} de esta presentación</small>`;
 const limit=portions>left&&limitingNames.length?`<small>Limitado por ${h(limitingNames.join(", "))}</small>`:"";
 return `<article class="food-card"><div class="food-photo">${p.id<=6&&S.demo_assets!==false&&p.name===["Cuarto de pollo a la brasa","Medio pollo a la brasa","Parrilla personal","Chaufa de pollo","Chicha morada","Gaseosa personal"][p.id-1]?`<img src="/carta-${p.id}.jpg" alt="${h(p.name)}">`:`<div class="food-placeholder">${icon("plate")}</div>`}<span class="food-category">${h(p.category)}</span></div><div class="food-info"><span class="product-code">${h(p.code)}</span><h3>${h(p.name)}</h3><div class="food-base"><div><b>${cash(priceFor(p))}</b><small class="${left<=0?"out":""}">${left>0?`${fmt(left)} platos disponibles`:"Sin platos disponibles"}</small>${chicken}${limit}${S.user.role==="admin"?button("Ver disponibilidad",()=>productStock(p),"link"):""}</div><button type="button" class="add" aria-label="Añadir ${h(p.name)}" ${left>0?bind(()=>addDetail(p)):"disabled"}>+</button></div></div></article>`}).join("")}</div>`;
}
function jumpTo(selector){
 const target=document.querySelector(selector);
 if(target){target.focus({preventScroll:true});target.scrollIntoView({block:"start"})}
}
function jumpToTicket(){
 const units=ticket.lines.reduce((count,line)=>count+line.qty,0);
 return `<button type="button" class="btn ticket-jump" ${bind(()=>jumpTo(".ticket"))}><span>${icon("receipt")} Ver pedido (${units})</span><b>${cash(sumTicket())}</b></button>`;
}
function ticketPanel(){
 const savedOrder=S.orders.find(o=>o.id===ticket.id);
 const activeDetails=(savedOrder?.details||[]).filter(d=>d.status!=="Cancelado");
 const modeLocked=activeDetails.length>0&&activeDetails.every(d=>d.status==="Entregado");
 const n=ticket.lines.reduce((a,l)=>a+l.qty,0);
 const preview=ticket.id?null:S.next_order_code;
 const code=ticket.id?ticket.code:preview;
 const confirmationNotice=ticket.confirmChanges?(ticket.lines.length?
   '<p class="notice">Preparación verá los cambios cuando pulses Confirmar cambios.</p>':
   '<p class="notice">Al confirmar, se retirarán los detalles de preparación y se liberará la mesa.</p>'):"";
 const canSave=(n||ticket.confirmChanges)&&ticket.lines.every(l=>l.product_id);
 const submitLabel=ticket.confirmChanges?"Confirmar cambios":ticket.id?"Guardar cambios":"Registrar comanda";
 return `<section class="ticket" tabindex="-1" aria-label="Pedido actual"><header><div class="ticket-icon">${icon("receipt")}</div><div><div class="eyebrow">${ticket.id?"EDITAR COMANDA":"NUEVA COMANDA"}</div><h2>${code?h(code):"Pedido actual"}</h2>${preview?'<p class="sub">Número provisional hasta registrar</p>':""}</div>${button("Volver a la carta",()=>jumpTo(".catalog"),"link catalog-jump")}</header><div class="ticket-ref"><label class="field"><span>Modalidad de consumo</span><select name="take_away" ${modeLocked?"disabled":""}><option value="0" ${!ticket.take_away?"selected":""}>En el local</option><option value="1" ${ticket.take_away?"selected":""}>Para llevar</option></select></label>${modeLocked?'<small class="muted">Pedido entregado · modalidad bloqueada</small>':""}<div class="grid2">
 ${select("piso","Piso",[[1,"Piso 1 · Mesas 1 a 10"],[2,"Piso 2 · Mesas 11 a 20"]],ticket.floor||1)}
 <label class="field"><span>Número de mesa</span><select id="mesa" name="table_number" required><option value="">Selecciona mesa</option>${Array.from({length:10},(_,i)=>(ticket.floor===2?11:1)+i).map(n=>{
 const occupied=(S.orders||[]).some(o=>o.day===(ticket.day||S.today)&&["Reservado","Por revisar"].includes(o.status)&&o.id!==ticket.id&&(Number(o.table_number)===n||(!o.table_number&&["Mesa "+n,String(n)].includes(o.table_name))));
 return `<option value="${n}" ${Number(ticket.table_number)===n?"selected":""} ${occupied?"disabled":""}>Mesa ${n}${occupied?" · OCUPADA":" · Disponible"}</option>`}).join("")}</select></label></div>
 <p class="muted" style="font-size:12px">Una mesa puede tener una sola comanda activa por fecha. La cancelación solicitada NO libera la mesa.</p></div>
 <div class="ticket-items">${ticket.lines.length?ticket.lines.map(detailCard).join(""):`<div class="ticket-empty"><span>${icon("plate")}</span><b>Comanda vacía</b><p>Agrega un producto de la carta para comenzar.</p></div>`}${confirmationNotice}</div><div class="ticket-bottom"><div class="line"><span>Productos</span><b>${n}</b></div><div class="total"><strong>Total</strong><strong>${cash(sumTicket())}</strong></div><button class="btn primary big" ${canSave?bind(saveTicket):"disabled"}>${icon("receipt")}${submitLabel}</button>
 ${savedOrder&&canCancelOrder(savedOrder)?button("Anular comanda",()=>cancelOrder(savedOrder),"danger clear-ticket"):""}
 ${ticket.id||n?button(ticket.id?"Salir de la edición":"Vaciar comanda",()=>modal("Descartar borrador","<p>Se descartarán los cambios de esta comanda que aún no confirmaste.</p>",async()=>{resetTicket();render()},"Descartar"),"link clear-ticket"):""}</div></section>`;
}
function posBody(){
 const categories=new Set(S.menu_categories??S.products.map(product=>product.category));
 categories.delete("Todos");
 const preferred=menuCategoryOrder.filter(category=>categories.delete(category));
 const cats=["Todos",...preferred,...categories];
 if(!cats.includes(menuCategory))menuCategory="Todos";
 return `<div class="pos"><section class="catalog" tabindex="-1" aria-label="Carta del local"><div class="catalog-head"><div><h2>Carta del local</h2><span class="catalog-count">${S.products.length} productos</span></div><label class="search">${icon("search")}<input id="menu-search" aria-label="Buscar en la carta" placeholder="Buscar producto" value="${h(menuQuery)}"></label></div><div class="tabs menu-tabs">${cats.map(c=>`<button class="${c===menuCategory?"active":""}" ${bind(()=>{menuCategory=c;drawPOS()})}>${h(c)}</button>`).join("")}</div><div id="cards">${menuCards()}</div>${jumpToTicket()}</section>${ticketPanel()}</div>`;
}
function attentionPage(){
 const open=S.orders.filter(o=>o.day===S.today&&["Reservado","Por revisar"].includes(o.status)&&!o.cancel_request);
 const rows=open.map(o=>[h(o.code),h(o.table_name),h(displayOrderStatus(o))+" · "+(o.take_away?"Para llevar":"En el local"),
   button("Editar",()=>editOrder(o),"secondary")+(ticket.id!==o.id&&o.status==="Reservado"&&o.details.some(d=>d.pending)?
     button(wasSentToPreparation(o)?"Confirmar cambios":"Enviar a preparación",()=>sendToPreparation(o),"primary"):"")]);
 return posBody()+(rows.length?panel("Comandas en atención",table(["Comanda","Mesa","Estado","Acciones"],rows)):"");
}
function drawPOS(){if(route==="atencion"){document.querySelector("#view").innerHTML=attentionPage();prune()}}
pages.atencion=attentionPage;
async function saveTicket(){if(!ticket.table_number){document.querySelector("#mesa")?.focus();toast("Selecciona primero un piso y una mesa disponible.",true);return}
 const payload={take_away:ticket.take_away,expected_day:ticket.day||S.today,table_number:ticket.table_number,lines:ticket.lines.map(({detail_no,product_id,qty})=>({detail_no,product_id,qty}))};
 if(ticket.id)Object.assign(payload,{id:ticket.id,version:ticket.version,confirm_changes:ticket.confirmChanges});
 const b=document.querySelector(".ticket-bottom .primary");if(b)b.disabled=true;
 try{
   const result=await api("pedidos.save",payload);
   resetTicket();await reload();go("atencion");
   if(result.cerrada)toast(`${result.code} cerrada. Mesa e insumos liberados.`);
   else if(payload.confirm_changes)toast(`${result.code} actualizada en preparación.`);
   else toast(`${result.code} ${payload.id?"actualizada":"registrada"}.`);
 }finally{if(b)b.disabled=false}
}
function editOrder(o){
 const change=()=>{
   ticket={take_away:!!o.take_away,id:o.id,version:o.version,code:o.code,day:o.day,table_name:o.table_name,
     table_number:o.table_number||Number(String(o.table_name).replace(/^Mesa /i,"")),
     floor:o.floor||(Number(o.table_number||String(o.table_name).replace(/^Mesa /i,""))>10?2:1),
     nextDetailNo:Math.max(0,...o.details.map(l=>l.detail_no))+1,
     confirmChanges:wasSentToPreparation(o),
     lines:o.details.filter(l=>l.status!=="Cancelado"&&!l.remove_pending).map(l=>({...l}))};
   menuQuery="";menuCategory="Todos";go("atencion");
 };
 if((ticket.id||ticket.lines.length)&&ticket.id!==o.id){modal("Cambiar de comanda","<p>Se descartarán los cambios del borrador abierto en atención.</p>",async()=>change(),"Continuar")}else{change()}
}
function formatPayments(payments, fallback=""){
 return payments?.length?payments.map(p=>`${p.method} ${cash(p.cents/100)}`).join(" · "):fallback;
}

function splitPaymentAmounts(values){
 const payments=[];
 for(const method of paymentMethods){
   const value=String(values["amount_"+method]??"").trim();
   if(!value)continue;
   const match=/^(\d+)(?:[.,](\d{1,2}))?$/.exec(value);
   if(!match)throw Error("Escribe importes con hasta dos decimales.");
   const cents=Number(match[1])*100+Number((match[2]||"").padEnd(2,"0"));
   if(!Number.isSafeInteger(cents))throw Error("Revisa el importe del pago.");
   if(cents)payments.push({method,cents});
 }
 return payments;
}

function chargeOrder(o){
 const day=S.today;
 const delivered=o.details.filter(d=>d.status==="Entregado");
 const cents=delivered.reduce((sum,d)=>sum+Math.round(d.price*100)*d.qty,0);
 const fields=`<div class="summary"><span>${h(o.table_name)} · ${h(displayDate(o.day))}</span></div>
   <div class="line"><span>Solicitado</span><b>${cash(o.total)}</b></div>`+
   table(["Producto entregado","Cantidad","Importe"],delivered.map(d=>[h(d.name),d.qty,cash(d.price*d.qty)]))+
   `<div class="total"><strong>A cobrar ahora</strong><strong>${cash(cents/100)}</strong></div>`+
   '<label class="check"><input type="checkbox" name="split_payment"> Dividir pago entre varios medios</label>'+
   '<div id="single-payment">'+select("payment_method","Medio de pago",paymentMethods.map(m=>[m,m]))+'</div>'+
   '<fieldset id="split-payments" disabled style="display:none"><legend>Importes por medio de pago</legend>'+
   paymentMethods.map(method=>input("amount_"+method,method+" (S/)","number","","min=0 step=0.01")).join("")+
   '<p class="muted" id="payment-balance" role="status"></p></fieldset>'+
   "<p>Al cobrar se cerrará la comanda y se cancelarán los detalles pendientes.</p>";
 const dialog=modal("Cobrar "+o.code,fields,async values=>{
   const payments=values.split_payment?splitPaymentAmounts(values):[{method:values.payment_method,cents}];
   if(payments.reduce((sum,p)=>sum+p.cents,0)!==cents)throw Error("Los importes por medio deben sumar el total a cobrar.");
   await run("pedidos.pay",{id:o.id,version:o.version,payments,expected_day:day,expected_cents:cents},o.code+" cobrada.");
   if(ticket.id===o.id)resetTicket();
 },"Confirmar cobro");
 const form=dialog.querySelector("form");
 const toggle=form.elements.namedItem("split_payment");
 const single=dialog.querySelector("#single-payment");
 const split=dialog.querySelector("#split-payments");
 const balance=dialog.querySelector("#payment-balance");
 form.addEventListener("input",()=>{
   const enabled=toggle.checked;
   single.hidden=enabled;
   form.elements.namedItem("payment_method").disabled=enabled;
   split.disabled=!enabled;
   split.style.display=enabled?"grid":"none";
   if(!enabled)return;
   try{
     const payments=splitPaymentAmounts(Object.fromEntries(new FormData(form)));
     const remaining=cents-payments.reduce((sum,p)=>sum+p.cents,0);
     balance.textContent=remaining>0?`Faltan ${cash(remaining/100)}`:
       remaining<0?`El pago excede el total en ${cash(-remaining/100)}`:"Total cubierto";
   }catch(error){
     balance.textContent=error.message;
   }
 });
}
function refundDetailFields(details){
 return table(["Detalle","Producto","Unidades a devolver","Regresa al inventario"],details.map(d=>[
   h(d.detail_no),h(d.name),input("qty_"+d.detail_no,`Hasta ${d.refundable_qty}`,"number",0,
     `min="0" step="1" max="${d.refundable_qty}" data-refund-qty`),
   `<label class="check"><input type="checkbox" name="restock_${d.detail_no}" aria-label="Reponer detalle ${d.detail_no}"> Sí</label>`,
 ]));
}
function selectedRefundDetails(details,values){
 return details.map(d=>({detail_no:d.detail_no,qty:Number(values["qty_"+d.detail_no]||0),
   restock:!!values["restock_"+d.detail_no]})).filter(d=>d.qty>0);
}
function refundOrder(o,productId=null){
 const details=o.details.filter(d=>d.refundable_qty>0&&(productId===null||d.product_id===productId));
 if(!details.length){toast("No hay detalles con unidades pendientes de devolución.",true);return}
 const price=new Map(details.map(d=>[d.detail_no,Math.round(d.price*100)]));
 const day=S.today;
 const scope=productId===null?select("scope","Qué devolver",[["items","Seleccionar detalles"],["whole","Devolver toda la comanda"]],"items"):"";
 const dialog=modal("Devolución · "+o.code,scope+refundDetailFields(details)+
   input("reason","Motivo de devolución","text","","required maxlength=300")+
   '<div class="summary" aria-live="polite"><span>Importe a devolver de caja</span><b id="refund-total"></b></div>',
   values=>{
     const selected=selectedRefundDetails(details,values);
     if(!selected.length)throw Error("Indica las unidades de al menos un detalle.");
     return run("pedidos.refund_order",{id:o.id,version:o.version,expected_day:day,reason:values.reason,
       whole:values.scope==="whole",details:selected},"Devolución registrada en caja");
   },"Confirmar devolución");
 const form=dialog.querySelector("form");
 const summary=dialog.querySelector("#refund-total");
 const update=()=>{
   const entries=selectedRefundDetails(details,Object.fromEntries(new FormData(form)));
   const amount=entries.reduce((c,d)=>c+d.qty*price.get(d.detail_no),0);
   summary.textContent=cash(amount/100);
 };
 form.elements.namedItem("scope")?.addEventListener("change",e=>{
   const whole=e.target.value==="whole";
   for(const field of form.querySelectorAll("[data-refund-qty]")){
     field.readOnly=whole;field.value=whole?field.max:0;
   }
   update();
 });
 form.addEventListener("input",update);
 update();
}
function refund(o,l,exchange=false){
 if(!exchange&&o.details.some(d=>d.product_id===l.product_id&&d.refundable_qty>0)){
   refundOrder(o,l.product_id);
   return;
 }
 const max=l.qty-l.refunded, alternatives=S.products.filter(p=>p.id!==l.product_id);
 if(exchange&&!alternatives.length){toast("Agrega otro producto a la carta antes de registrar un cambio.",true);return}
 const restockFields=l.ingredients.map(i=>`<label class="check"><input type="checkbox" name="rec_${i.item_id}">${h(i.name)}</label>`).join("");
 const replaceFields=exchange?
   select("replacement_id","Producto de reemplazo",alternatives.map(p=>[p.id,`${p.code} · ${p.name} · ${cash(p.price)}`]))+
   input("replacement_qty","Unidades de reemplazo","number",1,"required min=1 max=10000 step=1")+
   '<div class="summary" aria-live="polite" id="diferencia-cambio"></div>':"";
 const fields=`<p><b>${h(l.name)}</b> · ${cash(l.price)} por unidad</p>`+
   input("qty","Unidades a devolver","number",1,`required step=1 min=1 max=${max}`)+replaceFields+
   input("reason",exchange?"Motivo del cambio":"Motivo de la devolución","text","","required maxlength=300")+
   `<fieldset><legend>Reposición de inventario</legend><p>Marca los insumos que regresan al lote. Deja todas las casillas vacías para devolver solo el importe.</p>${restockFields}</fieldset>`;
 function difference(values){return Math.round(productBy(Number(values.replacement_id)).price*100)*Number(values.replacement_qty)-Math.round(l.price*100)*Number(values.qty)}
 const dialog=modal((exchange?"Cambio en ":"Devolución de ")+o.code,fields,async values=>{
   const data={id:o.id,version:o.version,product_id:l.product_id,qty:values.qty,reason:values.reason,restock:l.ingredients.filter(i=>values["rec_"+i.item_id]).map(i=>i.item_id)};
   if(exchange)Object.assign(data,{replacement_id:Number(values.replacement_id),replacement_qty:values.replacement_qty,expected_difference_cents:difference(values)});
   const result=await run(exchange?"pedidos.exchange":"pedidos.refund",data,exchange?"Cambio registrado":"Devolución registrada");
   if(exchange&&result.replacement_sale_code)toast(`${result.exchange_code} registrado · Venta ${result.replacement_sale_code}`);
 },exchange?"Confirmar cambio":"Registrar devolución");
 if(exchange){
   const form=dialog.querySelector("form"),label=dialog.querySelector("#diferencia-cambio");
   const update=()=>{const cents=difference(Object.fromEntries(new FormData(form)));label.textContent=cents>0?"Diferencia a cobrar · "+cash(cents/100):cents<0?"Importe a devolver · "+cash(-cents/100):"Cambio sin diferencia de precio"};
   form.addEventListener("input",update);update();
 }
}
function sendToPreparation(o){
 const pending=o.details.filter(l=>l.pending);
 const label=wasSentToPreparation(o)?"Confirmar cambios":"Enviar al área de preparación";
 const rows=pending.map(l=>[
   h("Detalle "+l.detail_no+" · "+l.name),
   h(l.remove_pending?l.area:productBy(l.product_id)?.prep_area||"Cocina"),h(l.qty),
   l.remove_pending?"Retirar":"Enviar",
 ]);
 modal(label+" · "+o.code,`<p>Los cambios se aplicarán a la cola de cada área al confirmar.</p>${table(["Producto","Área","Cantidad","Acción"],rows)}`,
   async()=>{
     const result=await run("pedidos.send",{id:o.id,version:o.version},"");
     toast(result.cerrada?"Comanda cerrada. Mesa e insumos liberados.":"Cola de preparación actualizada.");
   },wasSentToPreparation(o)?"Confirmar cambios":"Confirmar envío");
}
function canCancelOrder(o){
 return !o.cancel_request&&["Reservado","Por revisar"].includes(o.status)&&!o.details.some(d=>d.status==="Entregado");
}
function canRequestCancel(o){
 if(o.cancel_request)return false;
 if(o.paid_at)return ["Cobrado","Devuelto"].includes(o.status)&&o.lines.some(l=>l.qty>0);
 return ["Reservado","Por revisar"].includes(o.status)&&o.details.some(d=>d.status==="Entregado");
}
function cancelOrder(o){
 const withdrawal=wasSentToPreparation(o)?" Los detalles se retirarán de la cola de preparación.":"";
 modal("Anular comanda · "+o.code,`<p>Se anulará la comanda de ${h(o.table_name)} y se liberarán la mesa y sus insumos reservados.${withdrawal}</p>`,
   async()=>{await run("pedidos.cancel",{id:o.id,version:o.version},"Comanda anulada. Mesa e insumos liberados.");if(ticket.id===o.id){resetTicket();render()}},"Anular comanda");
}
function requestCancel(o){
 const effect=o.paid_at?"Caja revisará la solicitud antes de registrar la anulación del cobro.":
   "La mesa seguirá ocupada hasta la aprobación de Caja o Administración.";
 modal("Solicitar anulación · "+o.code,input("reason","Motivo de la solicitud","text","","required maxlength=500")+
   `<p>${effect}</p>`,v=>run("pedidos.request_cancel",{id:o.id,version:o.version,reason:v.reason},"Solicitud de anulación enviada."),
   "Enviar solicitud");
}
function decideCancel(o){
 const reason=o.cancel_request?.reason||"";
 const eligible=o.details.filter(d=>o.paid_at?d.refundable_qty>0:d.status==="Entregado");
 const inventory=eligible.length?`<fieldset id="cancel-restock"><legend>Detalles que regresan al inventario</legend>
   ${eligible.map(d=>`<label class="check"><input type="checkbox" name="restock_${d.detail_no}">Detalle ${d.detail_no} · ${h(d.name)} × ${o.paid_at?d.refundable_qty:d.qty}</label>`).join("")}
   ${o.paid_at?"":'<p class="muted">Los detalles entregados que queden sin marcar se registrarán como consumo.</p>'}</fieldset>`:"";
 const options=o.paid_at?[["","Selecciona una decisión"],["yes","Aprobar la anulación"],["no","Rechazar y mantener el cobro"]]:
   [["yes","Aprobar y liberar mesa"],["no","Rechazar y mantener comanda"]];
 const effect=o.paid_at?`<p class="notice">Importe pendiente de anular en Caja <strong>${cash(o.total)}</strong></p>`:"";
 const dialog=modal("Resolver anulación · "+o.code,`<p><b>Motivo</b> ${h(reason)}</p>${effect}${select("approve","Decisión",options)}${inventory}${input("reason","Observación (opcional)","text","","maxlength=300")}`,v=>{
   if(!v.approve)throw Error("Indica si apruebas o rechazas la solicitud.");
   return run("pedidos.decide_cancel",{id:o.id,request_id:o.cancel_request.id,revision:o.cancel_request.revision,reason:v.reason,
     expected_day:S.today,approve:v.approve==="yes",restock_details:eligible.filter(d=>v["restock_"+d.detail_no]).map(d=>d.detail_no)},
     v.approve==="yes"?"Anulación aprobada.":"Solicitud rechazada.");
 },"Confirmar decisión");
 const stock=dialog.querySelector("#cancel-restock");
 if(stock)dialog.querySelector('[name="approve"]').addEventListener("change",e=>{stock.hidden=e.target.value==="no"});
}
function displayOrderStatus(o){
 if(o.cancel_request)return "Anulación solicitada";
 if(o.status!=="Reservado")return o.status;
 if(!o.lines.length||o.details.some(l=>l.pending))return wasSentToPreparation(o)?"Cambios por confirmar":"Pendiente de envío";
 if(o.details.filter(l=>l.status!=="Cancelado").every(l=>l.status==="Entregado"))return "Entregada · por cobrar";
 return "En preparación";
}
function details(o,manageReturns=false){
 const mayCharge=manageReturns&&!o.cancel_request&&["admin","caja"].includes(S.user.role);
 const rows=o.lines.map(l=>[h(l.name),h(l.qty),cash(l.price),h(l.prep_status||"Sin enviar")+(l.prep?.delivered_at?`<small class="sub">${h(l.prep.delivered_at)}</small>`:""),h(l.refunded),cash((l.qty-l.refunded)*l.price),o.status==="Cobrado"&&mayCharge&&l.qty>l.refunded?'<div class="actions">'+button("Devolver",()=>refund(o,l),"link")+button("Cambiar",()=>refund(o,l,true),"secondary")+'</div>':""]);
 const returns=(o.returns||[]).map(r=>[h(r.code),h(r.name),h(r.qty),h(r.reason)+(r.undone_at?`<small class="sub">Revertida · ${h(r.undone_by)}</small>`:"")+(r.replacement_sale_code?`<small class="sub">Reemplazo · ${h(r.replacement_sale_code)}</small>`:""),h(r.operator)]);
 const origin=o.exchange_origin;
 const paymentSummary=formatPayments(o.payments,o.payment_method);
 const source=origin?`<p class="notice">Reemplazo ${h(origin.exchange_code)} de la venta ${h(origin.sale_code)} · ${h(origin.code)} del ${h(displayDate(origin.day))} · Devolución ${h(origin.return_code)}.</p>`:"";
 modal(o.code+" · "+o.table_name,`${o.sale_void?`<p class="notice">Venta anulada · ${h(o.sale_void.actor)} · ${h(o.sale_void.at)} · ${h(o.sale_void.reason)}</p>`:""}${source}<p class="notice">${o.take_away?"Para llevar":"En el local"}</p>${table(["Detalle","Producto","Cantidad","Estado"],o.details.map(d=>[d.detail_no,h(d.name),d.qty,h(d.remove_pending&&d.pending?"Retiro pendiente de envío":d.pending?"Pendiente de envío":d.status)]))}<div class="summary"><span>${h(displayDate(o.day))} · ${h(o.operator)}</span>${badge(o.status)}</div>${table(["Producto","Uds.","Precio","Preparación / entrega","Dev.","Neto",""],rows)}<div class="total"><strong>Total neto</strong><strong>${cash(o.total)}</strong></div>${o.paid_at?`<p class="muted">${o.sale_code?`Venta ${h(o.sale_code)} · `:""}Cobro registrado el ${h(o.paid_at)} por ${h(o.cashier)}.</p>${paymentSummary?`<p>${h(paymentSummary)}</p>`:""}`:""}${returns.length?`<h3>Devoluciones</h3>${table(["Código","Producto","Uds.","Motivo","Responsable"],returns)}`:""}`,null);
}
function viewOrdersDay(day){
 orderDay=day;orderQuery="";orderFilter="Todas";go("comandas");
}
function filteredOrders(){
 const q=norm(orderQuery),day=orderDay??S.today;
 return S.orders.filter(o=>(!day||o.day===day)&&(!q||norm(o.code+" "+(o.sale_code||"")+" "+o.table_name+" "+o.operator).includes(q))&&
 (orderFilter==="Todas"||orderFilter==="Abiertas"&&["Reservado","Por revisar"].includes(o.status)||orderFilter==="Cobradas"&&["Cobrado","Devuelto"].includes(o.status)||orderFilter==="Canceladas"&&["Anulada","Cancelado"].includes(o.status)));
}
function orderTable(){
 return table(["Comanda","Piso / Mesa","Estado","Creada","Total","Acciones"],filteredOrders().map(o=>{
 let acts=button("Ver detalle de comanda",()=>details(o),"secondary");
 if(["admin","caja","atencion"].includes(S.user.role)&&["Reservado","Por revisar"].includes(o.status)){
   if(o.cancel_request)acts+='<small class="muted">Envío bloqueado por solicitud de cancelación.</small>';
   else {
     acts+=button("Editar comanda",()=>editOrder(o),"secondary");
     if(o.status==="Reservado"&&o.details.some(d=>d.pending))acts+=button(
       wasSentToPreparation(o)?"Confirmar cambios":"Enviar al área de preparación",()=>sendToPreparation(o),"primary");
   }
   if(canCancelOrder(o))acts+=button("Anular comanda",()=>cancelOrder(o),"danger");
 }
 if(canRequestCancel(o))acts+=button("Solicitar anulación",()=>requestCancel(o),"secondary");
 return [`<b class="mono">${orderCode(o)}</b>`,`<strong>${h(o.table_name)}</strong><small class="sub">${o.take_away?"Para llevar":"En el local"}</small><small class="sub">${o.floor?`Piso ${o.floor}`:"Anterior a la actualización"}</small>`,badge(displayOrderStatus(o))+(o.cancel_request?`<small class="sub">${h(o.cancel_request.reason)}</small>`:""),h(o.created),cash(o.total),`<div class="actions">${acts}</div>`]}),"No hay comandas que coincidan con estos filtros.");
}
pages.comandas=()=>{
 const statuses=S.user.role==="atencion"?["Abiertas","Cobradas"]:["Abiertas","Cobradas","Canceladas","Todas"];if(!statuses.includes(orderFilter))orderFilter=statuses[0];
 const day=orderDay??S.today,periodOrders=day?S.orders.filter(o=>o.day===day):S.orders;
 const metrics=[["Comandas abiertas",periodOrders.filter(o=>["Reservado","Por revisar"].includes(o.status)).length]];
 if(S.user.role!=="atencion"){
   metrics.push(["Comandas",periodOrders.length]);
   if(day)metrics.push(["Ingreso neto de la jornada",cash(ventasPeriodo(S.orders,day,day).net/100)]);
 }
 return `<div class="metrics">${metrics.map(([label,value])=>`<div class="metric"><span>${h(label)}</span><b class="value">${h(value)}</b></div>`).join("")}</div><section class="panel"><header class="panel-head"><h2>Registro de comandas</h2></header><div class="panel-body"><div class="actions filters"><div class="tabs">${statuses.map(s=>`<button class="${s===orderFilter?"active":""}" ${bind(()=>{orderFilter=s;render()})}>${h(s)}</button>`).join("")}</div><label class="search">${icon("search")}<input id="order-search" placeholder="Código o mesa" aria-label="Buscar comanda" value="${h(orderQuery)}"></label><input type="date" id="order-day" value="${h(orderDay??S.today)}" aria-label="Fecha de comanda"></div><div id="order-list">${orderTable()}</div></div></section>`;
};
document.addEventListener("input",e=>{
 if(e.target.name==="take_away" && e.target.closest(".ticket-ref"))ticket.take_away=e.target.value==="1";
 if(e.target.name==="piso" && e.target.closest(".ticket-ref")){
   ticket.floor=Number(e.target.value);ticket.table_number=null;ticket.table_name="";drawPOS();
 }
 if(e.target.id==="mesa"){
   ticket.table_number=e.target.value?Number(e.target.value):null;
   if(!ticket.id&&!ticket.lines.length)ticket.day=S.today;
   ticket.table_name=ticket.table_number?"Mesa "+ticket.table_number:"";
 }
 if(e.target.id==="menu-search"){menuQuery=e.target.value;document.querySelector("#cards").innerHTML=menuCards();prune()}
 if(e.target.id==="order-day"){orderDay=e.target.value;render();return}
 if(e.target.id==="order-search"){orderQuery=e.target.value;document.querySelector("#order-list").innerHTML=orderTable();prune()}
});

