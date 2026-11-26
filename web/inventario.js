/* Existencias y movimientos comparten los controles de formularios de la aplicación. */
(() => {
  let tab = 'stock', detail = null, selectedItem = '', area = '', category = '';
  let moves = null, historyFilter = {}, owner = null;
  const isAdmin = () => S.user.role === 'admin';
  const itemById = id => S.items.find(item => Number(item.id) === Number(id));
  const asOptions = names => names.map(value => [value, value]);
  const itemOptions = list => list.map(i => [i.id, `${i.code} · ${i.name} (${i.unit})`]);
  const option = (value, label, selected) => `<option value="${h(String(value))}" ${String(value) === String(selected) ? 'selected' : ''}>${h(label)}</option>`;
  const metric = (value, label) => `<div class="metric"><div class="value">${h(String(value))}</div><span class="muted">${h(label)}</span></div>`;
  const yesNo = [[0,'No'],[1,'Sí']];

  function resetForUser() {
    const access = JSON.stringify([S.user.id, S.user.role, S.user.area]);
    if (owner === access) return;
    owner = access;
    tab = 'stock'; detail = null; moves = null; historyFilter = {};
    selectedItem = ''; area = ''; category = '';
  }
  function showTab(next) {
    tab = next; detail = null; refreshPanel();
  }
  function refreshPanel() {
    const slot = document.getElementById('inventory-module');
    if (slot) {
      slot.innerHTML = inventoryPanel();
      prune();
    }
  }
  function sharedAreaNotice(item) {
    const baseId=item.base_id||item.id;
    const sharesStock=baseId!=null&&S.items.some(other=>other.base_id===baseId);
    return sharesStock?'<p class="muted">El cambio de área se aplica también a las presentaciones que comparten este stock.</p>':'';
  }
  function formItem(i = {}) {
    const lists = `<datalist id="inv-categories">${S.categories.map(v=>option(v,v,'')).join('')}</datalist>`;
    const suggested=i.code||S.next_item_code;
    const rule=S.rules.find(r=>Number(r.source_id)===Number(i.id));
    const targets=itemOptions(S.items.filter(item=>Number(item.id)!==Number(i.id)));
    const fields = `<div class="field"><span id="item-code-label">Código del insumo</span><output aria-labelledby="item-code-label" class="notice">${h(suggested)}</output></div>` +
      input('name','Nombre del insumo','text',i.name || '','required maxlength="100"') +
      input('unit','Unidad de medida','text',i.unit || '','required maxlength="20" placeholder="kg, L, und…"') +
      `<label class="field"><span>Área responsable</span><select name="area" required>
        ${option('','Seleccionar área',i.area||'')}${S.areas.map(name=>option(name,name,i.area)).join('')}
      </select></label>` +
      sharedAreaNotice(i) +
      input('category','Categoría','text',i.category || '','required maxlength="60" list="inv-categories"') +
      input('min_qty','Cantidad mínima','number',i.min_qty ?? 0,'required min="0" step="0.001"') +
      input('warn_days','Avisar días antes de vencer','number',i.warn_days ?? 3,'required min="0" max="3650" step="1"') +
      select('perishable','¿Requiere vencimiento?',yesNo,i.perishable ?? 1) +
      select('transformable','¿Se transforma en otro insumo?',yesNo,i.transformable ?? 0) +
      select('target_id','Producto resultante de la transformación',[['','Seleccionar insumo resultante'],...targets],rule?.target_id || '') +
      input('source_qty','Cantidad de materia prima por preparación','number',rule?.source_qty ?? 1,'min="0.001" step="0.001" required') +
      input('target_qty','Cantidad de producto resultante','number',rule?.target_qty ?? 1,'min="0.001" step="0.001" required') +
      '<p class="muted">Equivalencia por preparación. Para convertir 1 pollo crudo en 1 pollo cocido, indica 1 y 1.</p>' +
      select('transform_now','Acción al guardar',[[0,'Guardar equivalencia'],[1,'Guardar y transformar ahora']],0) +
      '<div id="inv-transform-now" class="stack" hidden>' +
      input('transform_qty','Número de preparaciones a ejecutar','number',1,'min="1" max="10000" step="1" required') +
      input('transform_expiry','Vencimiento del producto resultante','date','','') +
      '<p id="inv-transform-summary" class="notice" aria-live="polite"></p></div>' + lists;
    const dialog=modal(i.id ? `Editar ${i.code}` : 'Nuevo insumo',fields,
      async values=>{
        if(i.id)values.id=i.id;
        delete values.code;
        if(values.target_id)values.transformable=1;
        const saved=await run('inv.item',values,'');
        toast(saved.transformed?'Transformación registrada · materia prima descontada y producto resultante ingresado':'Insumo guardado · '+saved.code);
      });
    const form=dialog.querySelector('form');
    const update=()=>{
      const values=Object.fromEntries(new FormData(form));
      const execute=values.transform_now==='1';
      dialog.querySelector('#inv-transform-now').hidden=!execute;
      dialog.querySelector('#inv-transform-now').style.display=execute?'grid':'none';
      form.querySelector('button.primary').textContent=execute?'Guardar y transformar':'Guardar';
      const target=itemById(values.target_id);
      const count=Number(values.transform_qty);
      dialog.querySelector('#inv-transform-summary').textContent=target?
        `Se descontarán ${fmt(Number(values.source_qty)*count)} ${values.unit} de ${values.name} y se ingresarán ${fmt(Number(values.target_qty)*count)} ${target.unit} de ${target.name}.`:
        'Selecciona el producto resultante para transformar.';
    };
    form.addEventListener('input',update);
    form.addEventListener('change',update);
    update();
  }
  function formItemClassification(i) {
    const fields=select('category','Categoría',asOptions(S.categories),i.category)+
      input('new_category','Nueva categoría (opcional)','text','','maxlength="60"')+
      select('area','Área responsable',asOptions(S.areas),i.area)+
      sharedAreaNotice(i);
    modal(`Cambiar categoría o área · ${i.code} · ${i.name}`,fields,values=>{
      const category=values.new_category.trim()||values.category;
      const area=values.area;
      const changes={id:i.id};
      if(category!==i.category)changes.category=category;
      if(area!==i.area)changes.area=area;
      return run('inv.item_category',changes,'Insumo actualizado');
    });
  }
  function formUse(i) {
    const field = input('qty',`Cantidad a consumir (${i.unit})`,'number','','required min="0.001" step="0.001" max="'+Number(i.available)+'"') +
      input('reason','Motivo del consumo','text','','required maxlength="300" placeholder="Actividad del área"');
    modal(`Consumo de ${i.name}`,field,values => run('inv.use',{...values,item_id:i.id},'Consumo registrado'),'Registrar salida');
  }
  function lotsPanel(i) {
    const source=itemById(i.base_id)||i;
    const lots = S.lots.filter(l => Number(l.item_id) === Number(source.id));
    const lotRows = lots.map(l => [h(l.code),h(l.expiry || 'Sin vencimiento'),fmt(l.reserved),fmt(l.available)]);
    const canConsume = isAdmin() || (['area','atencion','recepcion'].includes(S.user.role) &&
      S.inventory_access_areas.includes(i.area));
    const actions = (canConsume && i.available>0 ? button('Registrar consumo',()=>formUse(i),'primary') : '') +
      (isAdmin() ? button('Editar insumo',()=>formItem(i)) : '') + button('Cerrar',()=>{ detail=null; refreshPanel(); });
    return panel(`Lotes de ${source.name} (${source.unit})`,
      table(['Lote','Vencimiento','Reservado','Disponible'],lotRows,'Este insumo aún no tiene lotes con existencias.'),actions);
  }
  function stockTable() {
    const rows = S.items.filter(i=>(!area || i.area===area) && (!category || i.category===category) &&
      (!selectedItem || String(i.id)===selectedItem)).map(i=>[
        h(i.code),`<strong>${h(i.name)}</strong><br><small class="muted">${h(i.category)}${i.base_id?` · ${i.factor} cuartos por unidad<br>Stock compartido con ${h(i.base_code)} · ${fmt(i.available_portions)} cuartos disponibles`:""}</small>`,
        h(i.area),`${fmt(i.reserved)} ${h(i.unit)}`,`<strong>${fmt(i.available)} ${h(i.unit)}</strong>`,
        badge(i.available===0 ? 'Agotado' : i.available<=i.min_qty ? 'Stock bajo' : 'Disponible'),
        (isAdmin()?button('Editar',()=>formItem(i),'secondary')+button('Cambiar categoría o área',()=>formItemClassification(i),'secondary'):'')+button('Ver lotes',()=>{ detail=i.id; refreshPanel(); document.getElementById('inventory-detail')?.scrollIntoView({block:'nearest'}); })
      ]);
    return table(['Código','Insumo','Área','Reservado','Disponible','Estado','Acciones'],rows,'No hay insumos que coincidan con los filtros.');
  }
  function stockPanel() {
    if(!S.areas.includes(area))area='';
    if(!S.categories.includes(category))category='';
    const filter = `<div class="actions" style="flex-wrap:wrap;margin-bottom:16px">
      <label class="field">Buscar insumo<select id="inv-search">${option('','Todos los insumos',selectedItem)}${S.items.map(i=>option(i.id,`${i.code} · ${i.name}`,selectedItem)).join('')}</select></label>
      <label class="field">Área<select id="inv-area">${option('','Todas las áreas',area)}${S.areas.map(v=>option(v,v,area)).join('')}</select></label>
      <label class="field">Categoría<select id="inv-category">${option('','Todas las categorías',category)}${S.categories.map(v=>option(v,v,category)).join('')}</select></label>
      </div>`;
    const selected = detail != null && itemById(detail);
    const metrics = `<div class="metrics">${metric(S.items.length,'Insumos en catálogo')}${metric(S.items.filter(i=>i.available<=i.min_qty).length,'En mínimo o agotados')}${metric(S.lots.length,'Lotes con existencias')}</div>`;
    return metrics + panel('Existencias por insumo',filter+'<div id="inv-results">'+stockTable()+'</div>',isAdmin() ? button('Nuevo insumo',()=>formItem(),'primary') : '') +
      (selected ? '<div id="inventory-detail">'+lotsPanel(selected)+'</div>' : '');
  }

  function recipeRow(line={}) {
    return `<div class="grid2" data-recipe-line style="align-items:end;margin:8px 0;grid-template-columns:minmax(0,2fr) minmax(82px,1fr) auto">
      <label class="field">Insumo<select data-recipe-item required>${option('','Seleccionar',line.item_id)}${itemOptions(S.items).map(([v,label])=>option(v,label,line.item_id)).join('')}</select></label>
      <label class="field">Cantidad<input data-recipe-qty type="number" required min="0.001" step="0.001" value="${h(String(line.qty ?? ''))}"></label>
      <button type="button" class="btn secondary" data-recipe-remove aria-label="Quitar insumo">Quitar</button></div>`;
  }
  function formProduct(prod={}) {
    const presets=(S.portion_groups||[]).map(group=>[ [1,0.5,'¼ pollo'],[2,1.5,'½ pollo'],[4,3,'1 pollo'] ].map(([portions,potato,label])=>button(label,()=>{
      const rows=document.querySelector('#inv-recipe-rows');
      const existing=Array.from(rows.querySelectorAll('[data-recipe-line]'),row=>({item_id:Number(row.querySelector('[data-recipe-item]').value),qty:row.querySelector('[data-recipe-qty]').value}));
      const recipe=existing.filter(r=>r.item_id&&r.item_id!==group.base_id&&r.item_id!==group.potato_id);
      recipe.push({item_id:group.base_id,qty:portions},{item_id:group.potato_id,qty:potato});
      rows.innerHTML=recipe.map(recipeRow).join('');
    })).join('')).join('');
    const fields = input('name','Nombre del producto','text',prod.name || '','required maxlength="100"') +
      input('category','Categoría','text',prod.category || '','required list="categorias-carta" maxlength="120"') +
      `<datalist id="categorias-carta">${(S.menu_categories||[]).map(c=>`<option value="${h(c)}"></option>`).join('')}</datalist>` +
      input('price','Precio de venta (S/)','number',prod.price ?? '','min="0.01" step="0.01" required') +
      select('prep_area','Área responsable de preparación',[["Cocina","Cocina"],["Barra","Barra"],["Parrilla","Parrilla"]],prod.prep_area||"Cocina") +
      `<div class="full"><strong>Insumos por unidad vendida</strong><div class="actions">${presets}</div><div id="inv-recipe-rows">${(prod.recipe || [{}]).map(recipeRow).join('')}</div>
        <button type="button" class="btn secondary" data-recipe-add>Agregar insumo</button></div>`;
    modal(prod.id ? `Editar ${prod.code}` : 'Nuevo producto de carta',fields, values=>{
      const recipe=Array.from(document.querySelectorAll('#inv-recipe-rows [data-recipe-line]'),row=>({
        item_id:row.querySelector('[data-recipe-item]').value,qty:row.querySelector('[data-recipe-qty]').value
      }));
      return run('inv.product',{...values,recipe,...(prod.id ? {id:prod.id} : {})},'Producto y receta guardados');
    });
  }
  function productPanel() {
    const rows=S.products.map(p=>[
      `<strong>${h(p.name)}</strong><br><small class="muted">${h(p.code)}</small>`,h(p.category),h(p.prep_area||"Cocina"),cash(p.price),
      (p.recipe || []).map(row=>{const i=itemById(row.item_id); return i ? `${h(i.name)} · ${fmt(row.qty)} ${h(i.unit)}` : '';}).filter(Boolean).join('<br>'),
      fmt(p.available),button('Editar',()=>formProduct(p))
    ]);
    const create=S.items.length ? button('Nuevo producto',()=>formProduct(),'primary') : button('Registrar primer insumo',()=>formItem(),'primary');
    return panel('Carta y recetas',table(['Producto','Sección','Área de preparación','Precio','Receta por unidad','Porciones posibles','Acción'],rows,'La carta está vacía. Registra insumos para crear una receta.'),create);
  }
  function categoryForm(previous){
    modal(previous?"Renombrar categoría":"Nueva categoría",input("name","Nombre","text",previous||"","required maxlength=120"),
      v=>run("inv.menu_category",{name:v.name,previous},"Categoría guardada"));
  }
  pages.carta=()=>{
    if(S.user.role==="area")return panel("Productos de "+S.user.area,table(["Producto","Categoría"],
      (S.area_menu||[]).map(p=>[h(p.name),h(p.category)]),"Todavía no hay productos asignados a esta área."));
    return productPanel()+panel("Categorías",table(["Categoría","Acción"],S.menu_categories.map(c=>[h(c),button("Renombrar",()=>categoryForm(c),"link")])),
      button("Nueva categoría",()=>categoryForm(""),"primary"));
  };
  function formPortions() {
    const items=itemOptions(S.items.filter(i=>!i.base_id));
    const products=[['','Sin asignar'],...S.products.map(p=>[p.id,`${p.code} · ${p.name}`])];
    const group=S.portion_groups?.[0]||{};
    const fields=select('raw_id','Pollo crudo',items,group.raw_id)+
      select('base_id','Stock de cuartos de pollo cocido',items,group.base_id)+
      select('potato_id','Papa (kg)',items,group.potato_id)+
      select('quarter_product_id','Producto de carta de ¼ pollo',products)+
      select('half_product_id','Producto de carta de ½ pollo',products)+
      select('whole_product_id','Producto de carta de 1 pollo',products)+
      '<p>Dos cuartos equivalen a un medio y cuatro a un entero. Se muestran como stock compartido. La transformación convierte 1 pollo crudo en 1 entero cocido (4 cuartos). Papa por plato: 0,5 kg, 1,5 kg y 3 kg. Las recetas se aplican a nuevas comandas.</p>';
    modal('Equivalencias de pollo',fields,values=>run('inv.portions',values,'Equivalencias y recetas guardadas'));
  }
  function formRule() {
    const source=itemOptions(S.items.filter(i=>i.transformable));
    const fields=select('source_id','Materia prima',source) +
      input('source_qty','Cantidad consumida','number',1,'min="0.001" step="0.001" required') +
      select('target_id','Insumo preparado',itemOptions(S.items)) +
      input('target_qty','Cantidad producida','number',1,'min="0.001" step="0.001" required');
    modal('Equivalencia de preparación',fields,values=>run('inv.rule',values,'Equivalencia guardada'));
  }
  function transformPanel() {
    const rows = S.rules.map(r=>{
      const raw=itemById(r.source_id),prepared=itemById(r.target_id);
      return [h(r.code),`${fmt(r.source_qty)} ${h(raw.unit)} · ${h(raw.name)}`,`${fmt(r.target_qty)} ${h(prepared.unit)} · ${h(prepared.name)}`,
        button('Preparar',()=>{
          const fields=input('qty','Número de preparaciones','number',1,'min="1" step="1" required') +
            input('expiry','Vencimiento del preparado','date','','');
          modal(`Preparar ${prepared.name}`,fields,values=>run('inv.transform',{...values,rule_id:r.id},'Transformación registrada'),'Registrar preparación');
        })];
    });
    return panel('Transformaciones por equivalencia',table(['Código','Materia prima','Resultado','Acción'],rows,'Aún no hay equivalencias para esta área.'),
      (isAdmin() && S.items.some(i=>i.transformable) ? button('Definir equivalencia',formRule,'primary') : '')+(isAdmin()?button('Equivalencias de pollo',formPortions):''));
  }
  function inventoryPanel() {
    const tabs=[['stock','Existencias']];
    if (isAdmin()) tabs.push(['products','Carta y recetas']);
    if (S.can_prepare) tabs.push(['transform','Transformaciones']);
    const nav=tabs.length>1 ? '<nav class="actions" aria-label="Vistas de inventario">'+tabs.map(([id,label])=>button(label,()=>showTab(id),tab===id ? 'primary' : 'secondary')).join('')+'</nav>' : '';
    const body=tab==='products' ? productPanel() : tab==='transform' ? transformPanel() : stockPanel();
    return nav+body;
  }
  pages.inventario=()=>{
    resetForUser();
    return '<section class="stack" id="inventory-module">'+inventoryPanel()+'</section>';
  };

  function moveFilters() {
    const form=input('start','Desde','date',historyFilter.start || '') + input('end','Hasta','date',historyFilter.end || '') +
      select('area','Área',[['','Todas las áreas'],...asOptions(S.areas)],historyFilter.area || '') +
      select('item_id','Insumo',[['','Todos los insumos'],...itemOptions(S.items)],historyFilter.item_id || '');
    modal('Filtrar movimientos',form,async values=>{
      const r=await api('inv.history',values);
      historyFilter=values; moves=r.movements; refreshMoves();
    },'Aplicar filtros');
  }
  function refreshMoves() {
    const slot=document.getElementById('inventory-history');
    if(slot) {
      slot.innerHTML=historyPanel();
      prune();
    }
  }
  function historyPanel() {
    const list=moves ?? S.movements;
    const rows=list.map(m=>[
      `<strong>${h(m.code)}</strong><br><small class="muted">${h(m.at)}</small>`,
      `${h(m.item)}<br><small class="muted">${h(m.lot_code)} · ${h(m.area)}</small>`,
      badge(m.qty>0 ? 'Entrada' : 'Salida'),`<strong>${m.qty>0 ? '+' : ''}${fmt(m.qty)} ${h(m.unit)}</strong>`,
      `${h(m.reason)}<br><small class="muted">${h(m.ref || '')}</small>`,h(m.operator)
    ]);
    const criteria=[historyFilter.start && 'Desde '+historyFilter.start,historyFilter.end && 'Hasta '+historyFilter.end,historyFilter.area,
      historyFilter.item_id && itemById(historyFilter.item_id)?.name].filter(Boolean);
    const title=moves===null ? 'Últimos movimientos' : 'Movimientos consultados';
    const content=(criteria.length ? '<p class="muted">'+criteria.map(h).join(' · ')+'</p>' : '')+
      table(['Movimiento','Insumo / lote','Tipo','Cantidad','Motivo y referencia','Responsable'],rows,'No se encontraron movimientos.');
    return panel(title,content,(moves!==null ? button('Ver recientes',()=>{historyFilter={}; moves=null; refreshMoves();}) : '')+button('Filtrar historial',moveFilters,'primary'));
  }
  pages.movimientos=()=>{
    resetForUser();
    return '<section id="inventory-history">'+historyPanel()+'</section>';
  };

  document.addEventListener('click',e=>{
    if(e.target.closest('[data-recipe-add]')) document.getElementById('inv-recipe-rows')?.insertAdjacentHTML('beforeend',recipeRow());
    if(e.target.closest('[data-recipe-remove]')) e.target.closest('[data-recipe-line]')?.remove();
  });
  document.addEventListener('change',e=>{
    if(!['inv-search','inv-area','inv-category'].includes(e.target.id)) return;
    if(e.target.id==='inv-search') selectedItem=e.target.value;
    else if(e.target.id==='inv-area') area=e.target.value;
    else category=e.target.value;
    document.getElementById('inv-results').innerHTML=stockTable();
    prune();
  });
})();

