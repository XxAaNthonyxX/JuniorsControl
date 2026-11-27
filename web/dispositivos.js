(() => {
  let selectedAddress = "";

  // WebView2 descarga la hoja que la sesión HTTPS ya validó en el visor.
  document.addEventListener("click",async event=>{
    const link=event.target.closest('a[download="Juniors-CA.cer"]');
    if(!link || !window.chrome?.webview || link.protocol==="blob:")return;
    event.preventDefault();
    try{
      const response=await fetch(link.href);
      if(!response.ok)throw Error("Vuelve a iniciar sesión para descargar el certificado.");
      const url=URL.createObjectURL(await response.blob()), copy=document.createElement("a");
      copy.download=link.download;copy.href=url;document.body.append(copy);
      copy.click();copy.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
    }catch(error){toast(error.message,true)}
  });

  async function copyAddress(address) {
    try {
      await navigator.clipboard.writeText(address);
      toast("Dirección copiada");
    } catch {
      const dlg = modal("Copiar dirección",input("address","Enlace de la red","text",address,"readonly"),null);
      dlg.querySelector("[name=address]").select();
    }
  }

  async function checkFile(picker) {
    const file = picker.files[0];
    if (!file) return;
    try {
      if (file.size > 65536) throw Error("Selecciona el archivo Juniors-CA.cer.");
      const expected = String(S.network.fingerprint).replace(/[\s:]/g,"").toLowerCase();
      const digest = await crypto.subtle.digest("SHA-256",await file.arrayBuffer());
      const actual = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2,"0")).join("");
      if (actual !== expected) throw Error("La huella es distinta. Descarga una copia nueva en la PC principal.");
      toast("La copia coincide con el certificado de este local");
    } catch (err) {
      toast(err.message || "No se pudo verificar el certificado.",true);
    } finally {
      picker.value="";
    }
  }

  function connection(network) {
    if (network.local_only) {
      return panel("Acceso limitado a esta PC",
        '<p>Conecta la PC principal a la red privada del restaurante. Cierra el servidor y vuelve a abrir <strong>iniciar.bat</strong> con doble clic para habilitar el acceso desde otros equipos.</p>');
    }
    const urls = (network.urls || []).filter(address => /^https:\/\/(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\/?$/.test(address));
    if (!urls.length) {
      return panel("Conecta la PC a la red del local",
        '<p>Conecta el cable de red o el Wi-Fi de trabajo y vuelve a abrir <strong>iniciar.bat</strong> para detectar la dirección.</p>');
    }
    if (!urls.includes(selectedAddress)) selectedAddress = urls[0];
    const ip = new URL(selectedAddress).hostname;
    const choose = urls.length > 1 ?
      select("juniors_network","Dirección de la red del local",urls.map(u=>[u,new URL(u).hostname]),selectedAddress) : "";
    const url = h(selectedAddress);
    return panel("Enlace de la red del local",'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:24px">'+
      '<img width="168" height="168" style="image-rendering:pixelated;background:white" alt="Código QR para abrir Juniors en la red del local" src="/api/qr?ip='+encodeURIComponent(ip)+'">'+
      '<div class="stack" style="flex:1;min-width:min(100%,220px)">'+choose+
      '<p>Conecta el equipo al Wi-Fi o al cable de red del restaurante. Una vez instalado el certificado, escanea el QR o abre este enlace.</p>'+
      '<a href="'+url+'" target="_blank" rel="noopener" style="overflow-wrap:anywhere">'+url+'</a>'+
      '<div class="actions">'+button("Copiar enlace",()=>copyAddress(selectedAddress))+'</div></div></div>');
  }

  function publicConnection(address) {
    return panel("Acceso desde el navegador",'<div class="stack">'+
      '<p>Comparte este enlace con las personas invitadas en Equipo y correo. Cada persona ingresa con su cuenta de Juniors.</p>'+
      '<a href="'+h(address)+'" target="_blank" rel="noopener">'+h(address)+'</a></div>',
      button("Copiar enlace remoto",()=>copyAddress(address)));
  }

  function trust(network) {
    const fp = String(network.fingerprint || "").replace(/[\s:]/g,"").toLowerCase();
    const valid = /^[a-f0-9]{64}$/.test(fp);
    const file = network.cert_url === "/Juniors-CA.cer" && valid
      ? '<a class="btn primary" href="/Juniors-CA.cer" download="Juniors-CA.cer">Descargar certificado público</a>' : "";
    return panel("Certificado del local",'<div class="stack">'+
      '<p>En la PC principal, descarga <strong>Juniors-CA.cer</strong> y transfiérelo a cada equipo por USB o por un canal de confianza. Compara la huella antes de instalarlo.</p>'+
      (valid?'<div><strong>Huella SHA-256</strong><div style="font-family:monospace;overflow-wrap:anywhere;user-select:all">'+h(fp.toUpperCase())+'</div></div>':
        '<p>Vuelve a iniciar la aplicación para cargar los datos del certificado.</p>')+
      '<div class="actions">'+file+(valid?button("Verificar una copia",()=>document.getElementById("juniors-cert-file").click())+
      '<input type="file" id="juniors-cert-file" accept=".cer,.der" hidden>':"")+'</div></div>');
  }

  const instructions = [
    ["Windows","Abre el archivo .cer y elige «Instalar certificado». Selecciona «Usuario actual» y el almacén «Entidades de certificación raíz de confianza». Finaliza y abre el enlace en Edge o Chrome."],
    ["Tablet Android","En Ajustes busca «Instalar un certificado». Elige «Certificado de CA», identifica tu cuenta y selecciona Juniors-CA.cer. Abre el enlace en Chrome. Los nombres de los menús dependen del fabricante."],
    ["iPad","Abre el certificado recibido. En Configuración, instala «Perfil descargado». Después entra en General → Información → Configuración de certificados de confianza y activa la confianza plena para la raíz de Juniors. Abre el enlace en Safari."]
  ];

  pages.dispositivos = () => {
    if (S.user?.role !== "admin" || !S.network) return "";
    if (S.network.public_url) return publicConnection(S.network.public_url);
    const guides = instructions.map(([title,text])=>'<details><summary style="cursor:pointer"><strong>'+h(title)+
      '</strong></summary><p style="margin:8px 0 0">'+h(text)+'</p></details>').join("");
    return '<div class="stack">'+connection(S.network)+trust(S.network)+
      panel("Instalar en cada dispositivo",'<div class="stack">'+guides+
        '<p class="muted">Mantén abierta la ventana de iniciar.bat en la PC principal. Cada trabajador ingresa con su propia cuenta. Encontrarás los pasos de red y firewall en CONEXION.txt, junto a iniciar.bat.</p></div>')+'</div>';
  };

  document.addEventListener("change",e=>{
    if (e.target.id === "juniors-cert-file") { checkFile(e.target); return; }
    if (e.target.name !== "juniors_network" || !S.network?.urls?.includes(e.target.value)) return;
    selectedAddress=e.target.value;
    render();
  });
})();
