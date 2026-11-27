if(!/^JuniorsQA_[a-f0-9]{32}$/.test(process.env.JUNIORS_SQL_DATABASE||"")) throw Error("Usa probar_interfaz.py para crear una base temporal.");
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
  const app=path.resolve(__dirname,'..');
  const folder=fs.mkdtempSync(path.join(process.env.JUNIORS_DATA,"gestion-ui-"));
  const qaServer=[
    'import os, re, sys',
    'from pathlib import Path',
    'from unittest.mock import patch',
    'import servidor',
    'assert re.fullmatch(r"JuniorsQA_[a-f0-9]{32}", os.environ["JUNIORS_SQL_DATABASE"])',
    'def mailbox(sender, protected, recipient, code, **options):',
    '    assert recipient == "qa@example.test" and options["recovery"]',
    '    (Path(os.environ["JUNIORS_DATA"])/"codigo-qa.txt").write_text(code, encoding="ascii")',
    'with patch("acceso._send_code", mailbox): servidor.main()'
  ].join("\n");
  const server=spawn(path.join(app,'runtime','python.exe'),['-B','-u','-c',qaServer,'--port','0','--no-browser','--local'],
    {cwd:app,env:{...process.env,JUNIORS_DATA:folder,JUNIORS_NO_BROWSER:'1',PYTHONUTF8:'1'},windowsHide:true});
  let browser, page;
  try {
    const url=await new Promise((resolve,reject)=>{
      let log='';
      const timer=setTimeout(()=>reject(Error('Servidor sin respuesta: '+log)),35000);
      server.stdout.on('data',part=>{log+=part;const m=log.match(/https:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0])}});
      server.stderr.on('data',part=>{log+=part;});
      server.once('exit',code=>{clearTimeout(timer);reject(Error(code+': '+log))});
    });
    browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
    page=await browser.newPage({ignoreHTTPSErrors:true,viewport:{width:1440,height:960}});
    page.setDefaultTimeout(45000);
    const runtimeErrors=[];
    page.on('pageerror',error=>runtimeErrors.push(String(error)));
    await page.goto(url);
    const field=n=>page.locator('[name="'+n+'"]');
    const btn=(txt,el=page)=>el.getByRole('button',{name:txt,exact:true});
    const dialog=page.locator('dialog[open]');
    const nav=txt=>page.getByRole('link',{name:txt,exact:true}).evaluate(el=>el.click());
    const submit=async txt=>{
      await btn(txt,dialog).evaluate(el=>el.click());
      await dialog.waitFor({state:'hidden',timeout:20000}).catch(async()=>{throw Error('Al enviar '+txt+': '+await dialog.innerText())});
    };
    await btn('Ya recibí el código').click();
    await field('code').fill('012345');
    await field('name').fill('Encargada QA');
    await field('email').fill('qa@example.test');
    await field('password').fill('Ejemplo local 459!');
    await page.getByRole('button',{name:/Crear administrador/}).evaluate(el=>el.click());
    console.log('Alta de prueba enviada.');
    await page.getByRole('heading',{name:'Iniciar sesión',exact:true}).waitFor();
    assert.equal(await field('username').count(),0);
    assert.equal(await btn('Activar mi cuenta').count(),0);
    await btn('Recuperar contraseña').click();
    await field('email').fill('qa@example.test');
    await page.getByRole('button',{name:/Enviar código/}).click();
    await field('code').waitFor();
    const delivered=path.join(folder,'codigo-qa.txt');
    for(let i=0;i<100&&!fs.existsSync(delivered);i++) await new Promise(resolve=>setTimeout(resolve,100));
    const code=fs.readFileSync(delivered,'utf8');
    assert.match(code,/^[0-9]{6}$/);
    await field('code').fill(code);
    await field('password').fill('Nueva clave de prueba 1234');
    await page.getByRole('button',{name:/Guardar contraseña/}).click();
    await page.getByRole('heading',{name:'Iniciar sesión',exact:true}).waitFor();
    await field('email').fill('qa@example.test');
    await field('password').fill('Nueva clave de prueba 1234');
    await page.getByRole('button',{name:/Ingresar/}).click();
    await page.locator('.sidebar').waitFor();
    await nav('Compras');
    await btn('Editar fondo').evaluate(el=>el.click());
    await field('soles').fill('1000');
    await submit('Guardar');
    await btn('Nueva compra').evaluate(el=>el.click());
    await field('supplier').fill('Distribuidor de prueba');
    await dialog.getByRole('spinbutton',{name:'Cantidad de Gaseosa personal sellada',exact:true}).fill('30');
    await dialog.getByRole('spinbutton',{name:'Costo de Gaseosa personal sellada',exact:true}).fill('2.50');
    await submit('Guardar hoja');
    const purchase=page.getByRole('row').filter({hasText:'Distribuidor de prueba'});
    await btn('Detalle',purchase).evaluate(el=>el.click());
    const downloadEvent=page.waitForEvent('download');
    await btn('Descargar hoja de compra',dialog).evaluate(el=>el.click());
    const downloaded=await downloadEvent;
    assert.match(downloaded.suggestedFilename(),/^OC\d{4,}\.csv$/);
    assert.ok(fs.readFileSync(await downloaded.path(),'utf8').includes('Distribuidor de prueba'));
    await dialog.locator('footer').getByRole('button',{name:'Cerrar'}).evaluate(el=>el.click());
    await btn('Aprobar',purchase).evaluate(el=>el.click());
    await submit('Aprobar');
    await btn('Cursar compra',purchase).evaluate(el=>el.click());
    await submit('Cursar compra');
    console.log('Compra enviada.');
    await nav('Recepción');
    await btn('Revisar').evaluate(el=>el.click());
    await field('received').fill('29');
    await field('approved').fill('28');
    await field('expiry').fill('2027-12-31');
    await field('reason').fill('Dos botellas averiadas');
    await submit('Confirmar revisión');
    await btn('Resolver').evaluate(el=>el.click());
    await field('resolution').fill('Reposición acordada');
    await submit('Resolver');
    await nav('Mermas');
    await btn('Reportar merma').evaluate(el=>el.click());
    const wasteItem=field('item_id').locator('option').filter({hasText:'Gaseosa personal sellada'});
    await field('item_id').selectOption(await wasteItem.getAttribute('value'));
    const opts=await field('lot').locator('option').allTextContents();
    const chosen=opts.find(x=>x.includes('28 bot'));
    assert.ok(chosen,JSON.stringify(opts));
    await field('lot').selectOption({label:chosen});
    await field('qty').fill('1');
    await field('reason').fill('Envase con fuga');
    await submit('Enviar a revisión');
    await btn('Aprobar').evaluate(el=>el.click());
    await submit('Aprobar');
    await nav('Compras');
    await btn('Generar informe').evaluate(el=>el.click());
    await submit('Generar informe');
    await page.screenshot({path:path.join(process.env.JUNIORS_DATA,"gestion-compras.png")});
    const report=page.getByRole('row').filter({hasText:'Manual'}).filter({hasText:'INF'});
    await btn('Ver faltantes',report).evaluate(el=>el.click());
    await dialog.locator('footer').getByRole('button',{name:'Cerrar'}).evaluate(el=>el.click());
    await nav('Alertas');
    await page.locator('h1').filter({hasText:'Alertas de inventario'}).waitFor();
    const data=await page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
    assert.equal(data.budget.opening_cents,100000);
    assert.equal(data.budget.available_cents,93000);
    assert.equal(data.budget.issues_cents,250);
    assert.equal(data.purchases.find(p=>p.supplier==='Distribuidor de prueba').status,'Recibida');
    assert.equal(data.receipts[0].approved,28);
    assert.equal(data.receipts[0].received,29);
    assert.equal(data.incidents[0].missing,1);
    assert.equal(data.incidents[0].rejected,1);
    assert.equal(data.incidents[0].status,'Resuelta');
    assert.equal(data.wastes[0].status,'Aprobada');
    assert.equal(data.reports.some(r=>!r.scheduled),true);
    assert.equal(await page.evaluate(()=>document.querySelector('.icon').getBoundingClientRect().width<80),true);
    assert.deepEqual(runtimeErrors,[]);
    await page.screenshot({path:path.join(process.env.JUNIORS_DATA,"gestion-alertas.png")});
    console.log('OK Edge: alta local, fondo, compra, CSV, recepción parcial, resolución, merma, informe, alertas. Presupuesto, salidas y CSS verificados.');
  } catch (err) {
    if(page) console.log('Página durante el fallo:',(await page.locator('body').innerText()).slice(-2000));
    throw err;
  } finally {
    if(browser) await browser.close();
    server.kill();
  }
})().catch(e=>{console.error(e);process.exitCode=1});
