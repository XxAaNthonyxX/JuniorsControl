if(!/^JuniorsQA_[a-f0-9]{32}$/.test(process.env.JUNIORS_SQL_DATABASE||"")) throw Error("Usa probar_interfaz.py para crear una base temporal.");
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const net = require("node:net");
const { chromium } = require("playwright");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function freePort() {
  const s = net.createServer();
  await new Promise(resolve => s.listen(0, "127.0.0.1", resolve));
  const port = s.address().port;
  await new Promise(resolve => s.close(resolve));
  return port;
}

(async () => {
  const app = path.resolve(__dirname,".."), scratch = fs.mkdtempSync(path.join(process.env.JUNIORS_DATA,"ventana-"));
  const downloadPath = path.join(scratch, "descargas");
  fs.mkdirSync(downloadPath);
  console.log("Prueba de ventana en", scratch);
  const server = spawn(path.join(app, "runtime/python.exe"), ["-B", "-u", "servidor.py", "--no-browser", "--local", "--port", "0"],
    {cwd:app, windowsHide:true, env:{...process.env,JUNIORS_DATA:scratch}});
  let desktop, browser, appLog = "";
  try {
    server.stdout.on("data", d => appLog += d);
    server.stderr.on("data", d => appLog += d);
    let url;
    for (let i=0; i<240 && !url; ++i) {
      url = appLog.match(/https:\/\/127\.0\.0\.1:\d+/)?.[0];
      if (server.exitCode !== null) throw new Error(appLog);
      if (!url) await delay(250);
    }
    assert.ok(url, appLog);
    const port = await freePort(), cdpUrl = "http://127.0.0.1:"+port;
    desktop = spawn(path.join(app,"escritorio/Juniors.exe"),
      ["--url",url,"--data-dir",path.join(scratch,"perfil"),"--cert",path.join(scratch,"https/cert.pem")],
      {cwd:app, windowsHide:true, env:{...process.env,JUNIORS_DESCARGAS:downloadPath,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:"--disable-gpu --enable-logging --log-file=\""+path.join(scratch,"webview.log")+"\" --remote-debugging-port="+port}});
    console.log("Proceso WinForms",desktop.pid,"· servidor",url,"· CDP",cdpUrl);
    let targets;
    for (let i=0; i<150 && !targets; ++i) {
      try { const r=await fetch(cdpUrl+"/json/list"); const t=await r.json(); if(t.some(x=>x.type==="page")) targets=t; } catch {}
      if (desktop.exitCode !== null) throw Error("WinForms terminó con "+desktop.exitCode);
      if (!targets) await delay(300);
    }
    assert.ok(targets, "WebView2 no llegó a iniciarse.");
    console.log("WebView2:", targets.map(x=>x.url));
    browser = await chromium.connectOverCDP(cdpUrl);
    const ctx = browser.contexts()[0], page = ctx.pages()[0];
    page.setDefaultTimeout(18000);
    page.on("console", msg => { if(msg.type()==="error") console.log("WebView:", msg.text()) });
    await page.waitForFunction(()=>document.querySelector("form#auth-form"));
    console.log("Formulario del servidor visible en el control WebView2.");
    const session = await ctx.newCDPSession(page);
    await session.send("Browser.setDownloadBehavior",{behavior:"default"});
    const field = name => page.locator("[name='"+name+"']");
    await page.getByRole("button",{name:"Ya recibí el código"}).click();
    await field("code").fill("012345");
    await field("name").fill("Encargada de prueba");
    await field("email").fill("qa@example.test");
    await field("password").fill("Prueba local 1749!");
    await page.getByRole("button",{name:/Crear administrador/}).click();
    await page.getByRole("heading",{name:"Iniciar sesión",exact:true}).waitFor();
    await page.getByLabel("Correo electrónico").fill("qa@example.test");
    await page.getByLabel("Contraseña",{exact:true}).fill("Prueba local 1749!");
    await page.getByRole("button",{name:/Ingresar/}).click();
    await page.getByRole("link",{name:"Dispositivos",exact:true}).click();
    await page.locator("a[download='Juniors-CA.cer']").click();
    async function waitFile(file) {
      const dest = path.join(downloadPath,file);
      for (let i=0;i<100 && !fs.existsSync(dest);i++) await delay(150);
      assert.ok(fs.existsSync(dest),"Descarga ausente "+file+"; archivos: "+fs.readdirSync(downloadPath));
      return fs.readFileSync(dest);
    }
    assert.deepEqual(await waitFile("Juniors-CA.cer"), fs.readFileSync(path.join(scratch,"https/Juniors-CA.cer")));
    console.log("Descarga DER verificada, coincide byte por byte.");
    await page.getByRole("link",{name:"Compras",exact:true}).click();
    await page.getByRole("button",{name:"Editar fondo",exact:true}).click();
    await field("soles").fill("1000");
    let modal=page.locator("dialog[open]");
    await modal.getByRole("button",{name:"Guardar",exact:true}).click();
    await modal.waitFor({state:"hidden"});
    await page.getByRole("button",{name:"Nueva compra",exact:true}).click();
    await field("supplier").fill("Proveedor Juniors QA");
    await modal.getByRole("spinbutton",{name:"Cantidad de Gaseosa personal sellada",exact:true}).fill("5");
    await modal.getByRole("spinbutton",{name:"Costo de Gaseosa personal sellada",exact:true}).fill("2.50");
    await modal.getByRole("button",{name:"Guardar hoja",exact:true}).click();
    await modal.waitFor({state:"hidden"});
    const row=page.getByRole("row").filter({hasText:"Proveedor Juniors QA"});
    await row.getByRole("button",{name:"Detalle",exact:true}).click();
    await modal.getByRole("button",{name:"Descargar hoja de compra",exact:true}).click();
    const csv=await waitFile("OC0001.csv");
    assert.ok(csv.toString("utf8").includes("Proveedor Juniors QA"));
    console.log("OK: ventana WinForms x64 real, HTTPS con hoja fijada, alta, menús web, modales, DER y CSV descargados.");
  } finally {
    if (desktop && desktop.exitCode===null) {
      spawnSync("powershell.exe",["-NoProfile","-NonInteractive","-Command",
        "(Get-Process -Id "+desktop.pid+").CloseMainWindow()"],{windowsHide:true});
      for(let i=0;i<40 && desktop.exitCode===null;i++) await delay(100);
      if(desktop.exitCode===null)desktop.kill();
    }
    if (browser) await browser.close().catch(()=>{});
    if (server.exitCode===null) server.kill();
    await delay(2000);
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
