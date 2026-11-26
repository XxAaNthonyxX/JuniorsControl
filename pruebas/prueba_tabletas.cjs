if(!/^JuniorsQA_[a-f0-9]{32}$/.test(process.env.JUNIORS_SQL_DATABASE||"")) throw Error("Usa probar_interfaz.py para crear una base temporal.");
const {chromium} = require("playwright");
const {spawn} = require("node:child_process");
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
async function test(){
  const app=path.resolve(__dirname,".."), data=fs.mkdtempSync(path.join(process.env.JUNIORS_DATA,"tabletas-"));
  const proc=spawn(path.join(app,"runtime/python.exe"),["-B","-u","servidor.py","--port","0","--no-browser","--local"],{cwd:app,windowsHide:true,env:{...process.env,JUNIORS_DATA:data}});
  let browser,page;
  try{
    const url=await new Promise((ok,fail)=>{
      let buf="";const deadline=setTimeout(()=>fail(Error(buf)),55000);
      proc.stdout.on("data",chunk=>{buf+=chunk;const u=buf.match(/https:\/\/127\.0\.0\.1:\d+/);if(u){clearTimeout(deadline);ok(u[0])}});
      proc.stderr.on("data",chunk=>console.error(String(chunk)));proc.on("exit",()=>{clearTimeout(deadline);fail(Error(buf))});
    });
    browser=await chromium.launch({executablePath:"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",headless:true,args:["--disable-gpu","--disable-renderer-backgrounding","--disable-background-timer-throttling","--disable-backgrounding-occluded-windows"]});
    page=await browser.newPage({viewport:{width:768,height:1024},hasTouch:true,isMobile:true,ignoreHTTPSErrors:true});
    page.setDefaultTimeout(17000);
    const errors=[];page.on("pageerror",e=>errors.push(e.message));
    const button=(name,el=page)=>el.getByRole("button",{name,exact:true});
    const tap=target=>target.tap();
    async function assertTouchSize(selector){
      const rect=await selector.boundingBox();assert(rect && rect.width>=43.5 && rect.height>=43.5,JSON.stringify(rect));
    }
    async function noOverflow(){
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),"Hay desplazamiento horizontal del documento");
    }
    async function navigate(key){
      const ref=page.locator('.sidebar a[href="#'+key+'"]');
      if(!(await ref.isVisible())) await tap(button("Abrir navegación"));
      await tap(ref);await page.waitForFunction(k=>location.hash==="#"+k,key,{polling:50});
      assert.equal(await page.locator(".layout.nav-open").count(),0);
    }
    await page.goto(url+"/#atencion");
    await tap(button("Ya recibí el código"));
    await page.getByLabel("Código de verificación").fill("012345");
    await page.getByLabel("Nombre y apellido").fill("Prueba Tablet");
    await page.getByLabel("Correo electrónico").fill("qa@example.test");
    await page.getByLabel("Contraseña de Juniors",{exact:true}).fill("Solo para prueba 2026");
    await tap(page.getByRole("button",{name:/Crear administrador/}));
    await page.getByRole("heading",{name:"Iniciar sesión",exact:true}).waitFor();
    await page.getByLabel("Correo electrónico").fill("qa@example.test");
    await page.getByLabel("Contraseña",{exact:true}).fill("Solo para prueba 2026");
    await page.getByRole("button",{name:/Ingresar/}).click();
    await page.locator(".food-card").first().waitFor();
    assert(await page.locator('link[href="/tabletas.css"]').count(),"Falta enlace a tabletas.css");
    let idx=0;
    for(const [width,height] of [[768,1024],[1024,768],[390,844]]){
      await page.setViewportSize({width,height});await navigate("atencion");
      await assertTouchSize(button("Añadir Cuarto de pollo a la brasa"));
      await assertTouchSize(button("Brasas"));
      await tap(button("Añadir Cuarto de pollo a la brasa"));
      if(width<620){
        const jump=button("Ver pedido (1) S/ 22.00");
        await assertTouchSize(jump);
        const r=await jump.boundingBox();assert.ok(r.y+r.height<=height+1,"Salto al pedido no visible");await tap(jump);
        await assertTouchSize(button("Volver a la carta"));
        await tap(button("Volver a la carta"));await tap(jump);
        assert(await page.locator(".ticket").evaluate(el=>el.getBoundingClientRect().top<innerHeight/2));
      }
      await tap(button("Añadir una unidad de Cuarto de pollo a la brasa"));await assertTouchSize(button("Quitar una unidad de Cuarto de pollo a la brasa"));
      await tap(button("Quitar una unidad de Cuarto de pollo a la brasa"));
      await page.getByLabel("Mesa o referencia").fill("Mesa tablet "+width);
      await assertTouchSize(button("Registrar comanda"));await noOverflow();
      await page.screenshot({path:path.join(data,"carta-"+width+".png"),timeout:12000});
      await tap(button("Registrar comanda"));await page.waitForFunction(()=>location.hash==="#comandas",null,{polling:70});
      await assertTouchSize(button("Cobrar"));
      await tap(button("Editar"));await page.locator("#mesa").waitFor();
      if(width<620)await tap(button("Ver pedido (1) S/ 22.00"));
      await page.locator("#mesa").fill("Mesa "+width+" final");await tap(button("Guardar cambios"));
      await page.waitForFunction(()=>location.hash==="#comandas",null,{polling:70});
      await noOverflow();await tap(button("Cobrar"));await assertTouchSize(button("Confirmar cobro"));
      await tap(button("Confirmar cobro"));await page.waitForFunction(()=>!document.querySelector("dialog").open,null,{polling:70});
      await navigate("inventario");
      await page.getByRole("button",{name:"Ver lotes",exact:true}).first().waitFor();
      await noOverflow();await tap(page.getByRole("button",{name:"Ver lotes",exact:true}).first());
      await page.getByRole("heading",{name:/Lotes de/}).waitFor();await noOverflow();
      await tap(button("Editar insumo"));await assertTouchSize(button("Guardar",page.locator("dialog")));
      await tap(button("Cerrar",page.locator("dialog")).last());
      ++idx;
      const info=await page.evaluate(()=>S.orders.filter(o=>o.status==="Cobrado").length);
      assert.equal(info,idx);console.log(width+"x"+height+" OK");
    }
    assert.deepEqual(errors,[]);console.log("Sin errores JavaScript; fotografías en "+data);
  }catch(e){
    if(page)console.error((await page.locator("body").innerText()).slice(-1400));
    throw e;
  }finally{if(browser)await browser.close();proc.kill();}
}
test().catch(e=>{console.error(e);process.exitCode=1;});

