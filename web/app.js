
"use strict";
var S = {user:null}, pages = {};
const roleNames = {admin:"Administración",caja:"Caja",atencion:"Atención",area:"Encargado de área",recepcion:"Recepción"};
const nav = [
  ["atencion","Atención","grid","OPERACIÓN",["admin","caja","atencion"],"Sala y pedidos","Selecciona los productos para armar una comanda."],
  ["preparacion","Preparación y entregas","plate","",["admin","area"],"Pedidos en preparación","Consulta solamente los pedidos de tu área y marca su avance."],
  ["comandas","Comandas","receipt","",["admin","caja","atencion"],"Comandas","Consulta las comandas y los productos de cada mesa."],
  ["solicitudes","Solicitudes y devoluciones","receipt","",["admin","caja","atencion"],"Solicitudes y devoluciones","Consulta el estado de las anulaciones y devoluciones."],
  ["carta","Carta y categorías","plate","",["admin","area"],"Carta y categorías","Productos por categoría y área de preparación."],
  ["jornadas","Jornadas","calendar","",["admin","caja"],"Registro de jornadas","Consulta una fecha o ábrela para trabajar con ella en todo el local."],
  ["ventas","Ventas","flow","",["admin","caja"],"Reporte de ventas","Consulta los cobros y las devoluciones según la fecha en que se registraron."],
  ["inventario","Inventario","box","INVENTARIO",Object.keys(roleNames),"Inventario","Consulta existencias, lotes y recetas por área."],
  ["movimientos","Movimientos","flow","",Object.keys(roleNames),"Movimientos","Sigue las entradas y salidas de insumos por fecha."],
  ["recepcion","Recepción","truck","",["admin","recepcion"],"Recepción","Valida las entregas y registra las diferencias con el proveedor."],
  ["mermas","Mermas","leaf","",["admin","recepcion","area"],"Mermas","Registra pérdidas y revisa los descartes pendientes."],
  ["compras","Compras","basket","GESTIÓN",Object.keys(roleNames),"Compras y presupuesto","Consulta las órdenes y los informes de reposición."],
  ["alertas","Alertas","bell","",Object.keys(roleNames),"Alertas de inventario","Revisa los avisos de stock mínimo y vencimiento."],
  ["equipo","Equipo y correo","team","",["admin"],"Equipo y correo","Configura el registro por Gmail y el acceso del personal."],
  ["dispositivos","Dispositivos","devices","",["admin"],"Conectar dispositivos","Abre Juniors desde otras computadoras y tabletas de la red del local."]
];
const strokes = {
  devices:'<rect x="2" y="3" width="15" height="12" rx="1.5"/><path d="M6 20h8M10 15v5"/><rect x="15" y="9" width="7" height="12" rx="1.3"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.4"/><rect x="14" y="3" width="7" height="7" rx="1.4"/><rect x="3" y="14" width="7" height="7" rx="1.4"/><rect x="14" y="14" width="7" height="7" rx="1.4"/>',
  receipt:'<path d="M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6"/>',
  box:'<path d="m3 7 9-5 9 5v10l-9 5-9-5zM3 7l9 5 9-5M12 12v10M7 4.8l9 5"/>',
  flow:'<path d="M3 7h16m-5-4 5 4-5 4M21 17H5l5 4m-5-4 5-4"/>',
  truck:'<path d="M2 5h13v12H2zM15 9h4l3 4v4h-7"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
  leaf:'<path d="M20 3c-1 6 2 13-7 16-9 3-15-10-3-13 4-1 7 0 10-3ZM4 21l11-12"/>',
  basket:'<path d="m4 10 2 10h12l2-10zM2 10h20M8 10l4-7 4 7M9 13v4m6-4v4"/>',
  bell:'<path d="M4 17h16l-2-4V9a6 6 0 0 0-12 0v4zM10 20c1 2 3 2 4 0"/>',
  team:'<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6m1 4a5 5 0 0 1 4 5"/>',
  logout:'<path d="M9 4H4v16h5m6-13 5 5-5 5M8 12h12"/>',
  refresh:'<path d="M20 9a8 8 0 1 0 0 7M20 3v6h-6"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v5m10-5v5M3 11h18"/>',
  cart:'<path d="M3 4h3l3 12h9l3-8H7"/><circle cx="10" cy="20" r="1"/><circle cx="18" cy="20" r="1"/>',
  plate:'<path d="M3 16h18M5 16a7 7 0 0 1 14 0M12 9V7M2 19h20"/>',
  menu:'<path d="M3 6h18M3 12h18M3 18h18"/>',
  flame:'<path d="M13 2c1 6-5 6-3 11 2-1 4-3 4-5 5 4 7 7 4 11-3 4-10 4-13-1-3-6 3-10 4-13 0 3 1 4 2 5 2-3 2-5 2-8z"/>'
};
function icon(name){return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${strokes[name]||''}</svg>`}
function brand(){return `<div class="brand"><i>${icon("flame")}</i><div><b>Juniors<span>.</span></b><small>POLLOS Y PARRILLAS</small></div></div>`}
function h(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function cash(n){return `S/ ${Number(n||0).toLocaleString("es-PE",{minimumFractionDigits:2,maximumFractionDigits:2})}`}
function fmt(n){return Number(n||0).toLocaleString("es-PE",{maximumFractionDigits:3})}
function exportCsv(filename,rows){
 const encode=value=>{
   if(typeof value==="number" && Number.isFinite(value))return String(value);
   let cell=String(value??"");
   if(/^\s*[=+@-]/.test(cell))cell="'"+cell;
   return '"'+cell.replaceAll('"','""')+'"';
 };
 const body="\ufeff"+rows.map(row=>row.map(encode).join(";")).join("\r\n");
 const url=URL.createObjectURL(new Blob([body],{type:"text/csv;charset=utf-8"}));
 const link=document.createElement("a");link.href=url;link.download=filename;
 document.body.append(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function badge(text){const tone=/^(?:Cobrado|Aprobada|Recibida|Resuelta|Disponible|Activo|Activa)$/i.test(text)?"green":/^(?:Pendiente|Por revisar|Reservado|Parcial|Stock mínimo|Crítico)$/i.test(text)?"amber":"";return `<span class="badge ${tone}">${h(text)}</span>`}
let callbacks=new Map(), seq=0;
function bind(fn){const id=String(++seq); callbacks.set(id,fn);return `data-act="${id}"`}
function button(label,fn,kind="secondary"){return `<button type="button" class="btn ${h(kind)}" ${bind(fn)}>${h(label)}</button>`}
function table(headers,rows,empty="No hay registros para mostrar."){return `<div class="table-wrap"><table><thead><tr>${headers.map(x=>`<th>${h(x)}</th>`).join("")}</tr></thead><tbody>${rows.length?rows.map(row=>`<tr>${row.map(x=>`<td>${x??""}</td>`).join("")}</tr>`).join(""):`<tr><td class="empty-cell" colspan="${headers.length}">${h(empty)}</td></tr>`}</tbody></table></div>`}
function panel(title,content,actions=""){return `<section class="panel"><header class="panel-head"><h2>${h(title)}</h2><div class="actions">${actions}</div></header><div class="panel-body">${content}</div></section>`}
function input(name,label,type="text",value="",attrs=""){return `<label class="field"><span>${h(label)}</span><input name="${h(name)}" type="${h(type)}" value="${h(value)}" ${attrs}></label>`}
function select(name,label,options,value=""){return `<label class="field"><span>${h(label)}</span><select name="${h(name)}">${options.map(([k,v])=>`<option value="${h(k)}" ${String(k)===String(value)?"selected":""}>${h(v)}</option>`).join("")}</select></label>`}
let toastTimeout;
function toast(message,error=false){const el=document.querySelector("#toast");el.textContent=message;el.className=error?"show bad":"show";clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>el.className="",error?7500:4000)}
function modal(title,fields,save,submitLabel="Guardar"){
 const d=document.querySelector("#dialog");
 d.innerHTML=`<form id="modal-form"><header><h2>${h(title)}</h2><button type="button" class="close" aria-label="Cerrar">×</button></header><div class="modal-body">${fields}<p class="err" role="alert" hidden></p></div><footer><button type="button" class="btn secondary close">Cerrar</button>${save?`<button class="btn primary">${h(submitLabel)}</button>`:""}</footer></form>`;
 d.querySelectorAll(".close").forEach(x=>x.onclick=()=>d.close());
 d.querySelector("form").onsubmit=async e=>{e.preventDefault();if(!save)return;const form=e.currentTarget,values=Object.fromEntries(new FormData(form)),btn=form.querySelector("button.primary"),err=form.querySelector(".err");btn.disabled=true;err.hidden=true;
 try{await save(values,form);if(form===d.querySelector("form"))d.close()}catch(ex){err.textContent=ex.message;err.hidden=false}finally{btn.disabled=false}};
 if(!d.open)d.showModal();
 return d;
}
const pending = new Map();
async function api(action,payload={}){
 const retryable=action.includes(".")&&action!=="inv.history";
 const sig=retryable?JSON.stringify([action,payload]):null,id=pending.get(sig)||crypto.randomUUID();
 if(retryable)pending.set(sig,id);
 let res;
 try{res=await fetch("/api/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,payload,request_id:id})})}catch{throw Error("Se perdió la conexión. Reintenta la operación cuando se reanude el servicio.")}
 const obj=await res.json();
 if(res.status<500)pending.delete(sig);
 if(!res.ok){if(res.status===401){await reload();document.querySelector("#dialog").close();render()}throw Error(obj.error||"No se pudo completar la operación.")}
 return obj;
}
let stateRevision=0, lastAlert=0;
function sessionChanged(user){
 return user?.id!==S.user?.id||user?.role!==S.user?.role||user?.area!==S.user?.area;
}
function observeAlerts(state,changed){
 const alerts=state.alerts||[];
 const fresh=changed?[]:alerts.filter(a=>a.id>lastAlert&&!a.closed);
 lastAlert=alerts.reduce((highest,a)=>Math.max(highest,a.id),changed?0:lastAlert);
 if(fresh.length===1)return fresh[0].message;
 return fresh.length?`Hay ${fresh.length} alertas nuevas. Revisa el detalle en Alertas.`:"";
}
function applyState(state){
 const changed=sessionChanged(state.user);
 if(changed){
   const dialog=document.querySelector("#dialog");
   if(dialog.open)dialog.close();
   dialog.replaceChildren();
   pending.clear();
   if(typeof resetTicket==="function")resetTicket();
   authTab="login";
 }
 const notice=observeAlerts(state,changed);
 S=state;
 return notice;
}
async function fetchState(){
 const res=await fetch("/api/state",{cache:"no-store"});
 const state=await res.json();
 if(!res.ok)throw Error(state.error||"No se pudo cargar el sistema.");
 return state;
}
async function reload(){
 const revision=++stateRevision;
 const state=await fetchState();
 if(revision!==stateRevision)return "";
 stateRevision++;
 return applyState(state);
}
async function run(action,payload,message="Cambios guardados"){
 const obj=await api(action,payload),notice=await reload();
 render();
 const feedback=[obj.message||message,notice].filter(Boolean).join(" ");
 if(feedback)toast(feedback);
 return obj;
}
let route="",authTab="login",setupEmail="";
function go(key){if(location.hash.slice(1)!==key)location.hash=key;else{route=key;render()}}
function permitted(){return nav.filter(([k,,,,roles])=>roles.includes(S.user.role)&&(k!=="compras"||S.user.role==="admin"||S.purchases?.length))}
function displayDate(day,full=false){return new Date(day+"T12:00:00").toLocaleDateString("es-PE",full?{weekday:"long",day:"numeric",month:"long"}:{day:"2-digit",month:"2-digit",year:"numeric"})}
function render(){
 if(!S.user){renderAuth();return}
 const allowed=permitted(), entry=allowed.find(x=>x[0]===(location.hash.slice(1)||route))||allowed[0];route=entry[0];
 let group="";let activeGroup="";
 const side=nav.map(([k,label,ic,section])=>{
   if(section)group=section;if(!allowed.some(x=>x[0]===k))return "";
   const heading=activeGroup===group?"":`<div class="nav-label">${group}</div>`;activeGroup=group;
   const count=k==="preparacion"?(S.preparation||[]).filter(x=>x.day===S.today&&x.status!=="Entregado").length:
     k==="comandas"?(S.orders||[]).filter(o=>o.day===S.today&&["Reservado","Por revisar"].includes(o.status)).length:
     k==="alertas"?(S.alerts||[]).filter(a=>!a.closed).length:0;
   const notice=k==="alertas"&&count?` aria-description="${count} alertas activas"`:"";
   return `${heading}<a href="#${k}" class="nav-link ${route===k?"selected":""}" ${route===k?'aria-current="page"':""}${notice}>${icon(ic)}${h(label)}${count?`<em${k==="alertas"?' aria-hidden="true"':""}>${count}</em>`:""}</a>`;
 }).join("");
 document.title=entry[5]+" · Juniors";
 document.querySelector("#app").innerHTML=`<div class="layout"><aside class="sidebar">${brand()}<nav>${side}</nav><div class="identity"><span class="avatar">${h(S.user.name.trim().slice(0,1).toUpperCase())}</span><div><b>${h(S.user.name)}</b><small>${h(roleNames[S.user.role])}</small></div><button type="button" class="iconbtn" title="Cerrar sesión" aria-label="Cerrar sesión" ${bind(logout)}>${icon("logout")}</button></div></aside><div class="workspace"><header class="topbar"><div class="crumb"><button class="iconbtn mobile-nav" aria-label="Abrir navegación" ${bind(()=>document.querySelector(".layout").classList.toggle("nav-open"))}>${icon("menu")}</button><strong>Juniors</strong><span>/</span>${h(entry[1])}</div><div class="top-right"><span class="date">${icon("calendar")}${h(displayDate(S.today,true))}</span><button type="button" class="iconbtn" title="Actualizar datos" aria-label="Actualizar datos" ${bind(async()=>{await reload();render();toast("Datos actualizados")})}>${icon("refresh")}</button></div></header><main class="main"><div class="page-head"><div><h1>${h(entry[5])}</h1><p>${h(entry[6])}</p></div>${route==="atencion"?`<a class="btn secondary all-orders" href="#comandas">${icon("receipt")} Ver comandas</a>`:""}</div><div id="view">${pages[route]?pages[route]():""}</div></main></div></div>`;
 prune();
}
function prune(){queueMicrotask(()=>{const used=new Set([...document.querySelectorAll("[data-act]")].map(e=>e.dataset.act));for(const k of callbacks.keys())if(!used.has(k))callbacks.delete(k)})}
async function logout(){
 modal("Cerrar sesión",`<p>Se cerrará la sesión de ${h(S.user.name)} en este equipo.</p>`,async()=>{await api("logout");pending.clear();if(typeof resetTicket==="function")resetTicket();await reload();authTab="login";history.replaceState(null,"",location.pathname);render()},"Cerrar sesión")
}
function renderAuth(){
 if(S.awaiting_setup){
   document.querySelector("#app").innerHTML=`<main class="auth-layout"><section class="auth-photo">${brand()}</section><section class="auth-main"><div class="auth-box"><h1>Preparando el local</h1><p>Administración debe crear la primera cuenta en la computadora principal. Después podrás ingresar desde este dispositivo.</p><br>${button("Volver a comprobar",async()=>{await reload();render()},"primary")}</div></section></main>`;
   prune();return;
 }
 const setup=S.setup, requestCode=setup&&authTab!=="verify";
 const register=!setup&&location.hash==="#activar";
 const recovery=!setup&&!register&&(authTab==="recover"||authTab==="reset");
 const reset=recovery&&authTab==="reset", creating=register||(setup&&!requestCode);
 const title=setup?"Abrir el local":register?"Activar mi cuenta":recovery?"Recuperar contraseña":"Iniciar sesión";
 const intro=requestCode?"Configura Gmail para verificar el correo de administración.":creating?"Introduce el código de 6 dígitos que recibiste por correo.":reset?"Si el correo tiene una cuenta activa, recibirás un código de 6 dígitos válido durante 15 minutos.":recovery?"Escribe el correo de tu cuenta para solicitar un código.":"Ingresa con tu correo electrónico y contraseña.";
 const codeField=()=>input("code","Código de verificación","text","","required inputmode=numeric pattern=[0-9]{6} minlength=6 maxlength=6 autocomplete=one-time-code placeholder=000000");
 let fields="";
 if(requestCode){
   fields=input("email","Correo electrónico del administrador","email",setupEmail,"required maxlength=254 autocomplete=email")
     +input("smtp_email","Remitente Gmail (si es distinto)","email","","maxlength=254")
     +input("smtp_password","Contraseña de aplicación de Google","password","","required maxlength=32 autocomplete=off")
     +'<p class="muted">Activa la verificación en dos pasos y <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">genera una contraseña de aplicación</a> para el Gmail remitente.</p>';
 }else if(creating){
   fields=input("email","Correo electrónico","email",setup?setupEmail:"","required maxlength=254 autocomplete=email")
     +codeField()
     +input("name","Nombre y apellido","text","","required maxlength=100 autocomplete=name")
     +input("password","Contraseña de Juniors","password","","required minlength=10 maxlength=128 autocomplete=new-password")
     +(setup?'<label class="check"><input type="checkbox" name="demo" checked>Incluir carta e inventario de ejemplo</label>':"");
 }else if(recovery){
   fields=input("email","Correo electrónico","email",setupEmail,"required maxlength=254 autocomplete=email");
   if(reset)fields+=codeField()+input("password","Nueva contraseña","password","","required minlength=10 maxlength=128 autocomplete=new-password");
 }else{
   fields=input("email","Correo electrónico","email",setupEmail,"required maxlength=254 autocomplete=username")
     +input("password","Contraseña","password","","required maxlength=128 autocomplete=current-password");
 }
 const label=requestCode||authTab==="recover"?"Enviar código":setup?"Crear administrador":register?"Activar cuenta":reset?"Guardar contraseña":"Ingresar";
 const switchTab=setup?(requestCode?"Ya recibí el código":"Solicitar otro código"):(register||recovery?"Volver a iniciar sesión":"Recuperar contraseña");
 let alternate=button(switchTab,()=>{
   setupEmail=document.querySelector("#auth-form [name=email]").value;
   if(register)history.replaceState(null,"",location.pathname);
   authTab=setup?(requestCode?"verify":"login"):(register||recovery?"login":"recover");
   renderAuth();
 },"link");
 if(reset)alternate+=" "+button("Solicitar otro código",()=>{authTab="recover";renderAuth()},"link");
 document.querySelector("#app").innerHTML=`<main class="auth-layout"><section class="auth-photo">${brand()}<div class="auth-sign"><span>COMAS · LIMA</span><b>Pollos y<br>parrillas<span>.</span></b></div></section><section class="auth-main"><div class="auth-box"><div class="eyebrow"><i></i> ${setup?"PRIMER INICIO":"ACCESO DEL PERSONAL"}</div><h1>${title}</h1><p>${intro}</p><form id="auth-form" class="stack">${fields}<p class="err" hidden role="alert"></p><button class="btn primary big">${label} <span>→</span></button></form><div class="auth-alt">${alternate}</div></div></section></main>`;
 document.querySelector("#auth-form").onsubmit=async e=>{
   e.preventDefault();
   const f=e.currentTarget,p=Object.fromEntries(new FormData(f)),err=f.querySelector(".err"),btn=f.querySelector("button");
   btn.disabled=true;err.hidden=true;
   try{
     if(requestCode){
       await api("bootstrap_code",p);setupEmail=p.email;authTab="verify";renderAuth();return;
     }
     if(recovery&&!reset){
       await api("reset_request",p);setupEmail=p.email;authTab="reset";renderAuth();return;
     }
     if(setup)p.demo=!!p.demo;
     const result=await api(setup?"bootstrap":register?"register":reset?"reset_password":"login",p);
     if(register||(setup&&location.hash==="#activar"))history.replaceState(null,"",location.pathname);
     await reload();setupEmail=creating||reset?p.email:"";authTab="login";render();
     if(result.message)toast(result.message);
   }catch(ex){err.textContent=ex.message;err.hidden=false}finally{btn.disabled=false}
 };
 prune();
}
document.addEventListener("click",async e=>{const target=e.target.closest("[data-act]");if(!target||target.disabled)return;const fn=callbacks.get(target.dataset.act);if(!fn)return;try{await fn(e)}catch(ex){toast(ex.message,true)}});
function closeMobileNav(returnFocus=false){
 const layout=document.querySelector(".layout.nav-open");
 if(!layout)return;
 layout.classList.remove("nav-open");
 const toggle=layout.querySelector(".mobile-nav");
 toggle.setAttribute("aria-expanded","false");
 toggle.setAttribute("aria-label","Abrir navegación");
 if(returnFocus)toggle.focus();
}
document.addEventListener("click",e=>{
 const toggle=e.target.closest(".mobile-nav");
 if(toggle){
   const open=toggle.closest(".layout").classList.contains("nav-open");
   toggle.setAttribute("aria-expanded",String(open));
   toggle.setAttribute("aria-label",open?"Cerrar navegación":"Abrir navegación");
 }else if(e.target.closest(".nav-link")||!e.target.closest(".sidebar")){
   closeMobileNav();
 }
});
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!document.querySelector("#dialog").open)closeMobileNav(true)});
window.addEventListener("hashchange",()=>{if(S)render()});
document.addEventListener("DOMContentLoaded",async()=>{try{await reload();render()}catch(ex){document.querySelector("#app").innerHTML=`<main class="loading"><h2>No se pudo abrir Juniors</h2><p>${h(ex.message)}</p><button type="button" class="btn primary" ${bind(()=>location.reload())}>Volver a intentar</button></main>`}});
let checkingSession=false;
async function refreshSession(){
 if(!S.user||document.hidden||checkingSession)return;
 const revision=stateRevision;
 checkingSession=true;
 try{
   const fresh=await fetchState();
   if(revision!==stateRevision)return;
   if(sessionChanged(fresh.user)){
     applyState(fresh);render();return;
   }
   const notice=observeAlerts(fresh,false);
   if(notice)toast(notice);
   const editing=document.querySelector("#dialog").open||["INPUT","SELECT","TEXTAREA"].includes(document.activeElement.tagName);
   if(!editing&&(fresh.today!==S.today||["jornadas","ventas","atencion","comandas","preparacion","solicitudes","alertas","recepcion"].includes(route))){S=fresh;render()}
 }catch{}finally{checkingSession=false}
}
setInterval(refreshSession,30000);
document.addEventListener("visibilitychange",refreshSession);

