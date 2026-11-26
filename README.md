# JuniorsControl para Windows · SQL Server

La web y la ventana de escritorio usan la misma base Microsoft SQL Server. El servicio Python mantiene la lógica de atención, caja y control de inventario del proyecto original. La cuenta Windows que abre el iniciador se conecta a SQL Server. Cada trabajador se identifica además con su propia cuenta de JuniorsControl.

## Primera instalación

1. Extrae el ZIP completo y abre la carpeta **JuniorsControl** en VS Code. La raíz contiene este archivo, los iniciadores y `sqlserver.json`.
2. En la PC principal necesitas Windows x64 y **Microsoft ODBC Driver 18 for SQL Server x64**. Puedes usar una instancia de SQL Server que ya tengas o instalar SQL Server Express. Python y el conector Python–ODBC están incluidos. [SQL Server](https://www.microsoft.com/es-es/sql-server/sql-server-downloads) · [ODBC 18 para Windows](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server?view=sql-server-ver18)
3. Abre `sqlserver.json`. El valor inicial de `server` es `localhost`, para la instancia predeterminada. Si tu instancia se llama SQLEXPRESS, escribe `"server": "localhost\\SQLEXPRESS"` dentro del JSON. Deja `"database": "JuniorsControl_PVF"` o elige un nombre propio. Para un servidor remoto usa su nombre DNS y un certificado SQL de confianza que coincida con ese nombre.
4. Desde la terminal PowerShell ejecuta `.\configurar_sqlserver.bat`. La cuenta instaladora necesita permiso de creación de bases, o acceso como propietaria a una base vacía preparada por el administrador. El instalador crea las tablas, índices, relaciones y la marca de versión. Puedes volver a ejecutarlo sobre la misma instalación.
5. Ejecuta `.\iniciar.bat` para abrir el navegador o `.\iniciar_escritorio.bat` para la ventana nativa con WebView2 Evergreen. También puedes usar **Terminal → Ejecutar tarea** en VS Code. Si aparece un error al conectar, comprueba el nombre de instancia, el servicio SQL, el controlador x64 y los permisos de la cuenta Windows. [WebView2 Evergreen](https://developer.microsoft.com/microsoft-edge/webview2/)
6. En la PC principal abre **Abrir el local**, introduce el correo del administrador y la contraseña de aplicación del Gmail remitente y pulsa **Enviar código**. Si los correos difieren, indica también el remitente. Verifica el código de 6 dígitos recibido y crea tu contraseña de Juniors. A continuación inicia sesión con tu correo y esa contraseña. Si la olvidas, pulsa **Recuperar contraseña** para recibir otro código por Gmail. Puedes incluir la carta de ejemplo. Si vas a importar registros de una instalación anterior, hazlo antes de crear la primera cuenta.

Deja abierta la consola durante el turno. Ctrl+C detiene el servidor. En otras PC y tabletas, abre el enlace HTTPS de **Dispositivos**. El certificado público y los pasos de conexión están en `CONEXION.txt`. SQL Server solo necesita ser accesible desde la máquina que ejecuta el servidor de JuniorsControl.

## Comprobar un turno

En la carta de ejemplo, registra dos gaseosas para una mesa. En Inventario verás 10 botellas físicas, 2 reservadas y 8 disponibles. Al confirmar el cobro de S/ 10,00, quedan 8 físicas y se libera la reserva. Para devolver una botella, abre la venta cobrada, indica el motivo y marca el insumo si está apto para reincorporarlo. Ventas y Movimientos permiten comprobar el importe y el lote.

Las comandas empiezan en C0001 cada jornada de Lima. Insumos, lotes, ventas, devoluciones y cambios tienen identificadores propios. En `LEEME.txt` se explican las cuentas, invitaciones por Gmail, recetas, recepciones parciales, mermas, presupuestos, compras y alertas.

## Datos y respaldo

- El catálogo configurado en SQL Server contiene las cuentas y todas las operaciones. La carpeta `%LOCALAPPDATA%\Juniors Restaurante\datos` contiene certificados HTTPS, perfiles del visor y comprobantes de respaldo. `JUNIORS_DATA` permite elegir esa carpeta. Las variables `JUNIORS_SQL_SERVER` y `JUNIORS_SQL_DATABASE` prevalecen sobre el JSON si están definidas.
- Una vez creada la primera cuenta, el servicio realiza una copia diaria con `BACKUP DATABASE`, `COPY_ONLY` y `CHECKSUM` mientras está abierto. El archivo .bak se crea en la carpeta de backup de la **instancia SQL**. La ruta figura en el comprobante JSON de la carpeta `respaldos`. Para usar otra carpeta, define `JUNIORS_SQL_BACKUP_DIR` y concede escritura al servicio de SQL Server en esa ubicación. Los errores aparecen en la consola y el mantenimiento reintenta la copia.
- Si administras permisos por separado, la cuenta Windows de ejecución necesita conexión al catálogo, lectura y escritura de las tablas de la aplicación y permiso de respaldo. La creación del esquema y la restauración corresponden a la cuenta instaladora o al administrador de la instancia.
- Para recuperar un .bak, ejecuta `restaurar.bat`, indica la ruta visible para el servicio SQL y un **nombre de base nuevo**. Se comprueba la copia, se restaura en el destino, se ejecuta CHECKDB y se invalidan sesiones e invitaciones recuperadas. Cierra Juniors, configura el nombre recuperado y vuelve a iniciar. También se incluye `sql/recuperar_copia.sql` para SSMS. Guarda una copia del .bak en otra unidad.

## Importar datos del avance anterior

Con el servidor de la versión anterior cerrado, conserva una copia de su respaldo y elige en `sqlserver.json` un catálogo nuevo y vacío. Ejecuta el instalador y después, antes del primer inicio, este comando desde la raíz.

```powershell
.\runtime\python.exe -B -X utf8 .\migrar_sqlite.py "C:\MisCopias\juniors.sqlite3"
```

El conversor abre el origen en modo de lectura, conserva identificadores, comprueba claves y recuentos y confirma las escrituras en una sola transacción. Un destino que ya contiene operaciones se rechaza. Al terminar puedes entrar con tus cuentas anteriores. Configura otra vez el remitente Gmail y vuelve a invitar a quienes tenían códigos pendientes. Esta herramienta de traslado es el único componente que lee el formato anterior.

## Pruebas y código

En `VERIFICACION.md` figuran los resultados, el alcance y los comandos para repetirlos. Las pruebas crean catálogos SQL Server con prefijo `JuniorsQA_` y un identificador aleatorio. El servidor está en `servidor.py`, la conexión en `sqlserver.py` y el esquema T-SQL en `esquema.sql`. Los módulos de negocio son `acceso.py`, `inventario.py` y `gestion.py`. Las interfaces están en `web/` y `escritorio/`.
