# JuniorsControl — Atención por pisos, preparación y devoluciones

## Qué contiene esta edición

Esta edición parte del ZIP **JuniorsControl-SQLServer-Gmail (2)** y toma como referencia funcional La Fama Club. No reemplaza el inicio de sesión con Gmail, usuarios, inventario por lotes, compras, reportes ni devoluciones que ya estaban implementados. Los códigos de Gmail para cuentas nuevas o recuperación se generan ahora con **6 dígitos numéricos**; si un código de 8 dígitos quedó pendiente, solicita uno nuevo.

**Mesas:** piso 1, mesas 1–10; piso 2, mesas 11–20. El usuario selecciona el piso y después la mesa. La creación queda asociada al día actual de Lima. Una mesa puede tener una sola comanda activa ese día (también se comprueba con un índice único filtrado en SQL Server). Las mesas vuelven a estar disponibles tras el cobro o la aprobación definitiva de la cancelación. Una solicitud pendiente NO libera la mesa. No se borran las comandas antiguas con mesas escritas en texto libre.

**Atención:** primero guarda la comanda y se reserva stock. En Comandas utiliza **Enviar a preparación**; el pedido se separa por producto y área: Cocina, Barra o Parrilla. Puedes añadir nuevos productos a una comanda abierta y enviarlos posteriormente. Los productos ya enviados quedan fijos; para corregirlos se requiere cancelación o un procedimiento supervisado. No pueden modificarse cantidades ni eliminarse líneas ya enviadas.

**Preparación:** empleados con rol `area` solo ven los productos de su propia área y pueden marcarlos, en orden: `En cola → Preparando → Listo → Entregado`. Administración puede supervisar todas las áreas. Se guarda la hora de cada etapa en `dbo.inv_dispatch`.

**Caja:** solo Caja o Administración cobra cuando todos los productos estén entregados y no haya una cancelación solicitada. El cobro sigue aplicando el consumo del inventario según las reservas. Las devoluciones y cambios de ventas cobradas continúan usando `inv_returns`, `inv_exchanges` y los movimientos de stock del sistema anterior.

**Cancelación:** se solicita indicando un motivo; Caja o Administración puede aprobar o rechazar. Si está pendiente se mantiene la reserva de mesa y se pone en pausa la preparación. No es posible cancelar directamente una comanda con productos ya entregados porque estos requieren conciliación real antes de liberar reservas. Se registra el historial en `inv_cancel_requests` y `inv_events`.

**Limitación:** las líneas ya enviadas no admiten aumentar su cantidad: para pedir más unidades del mismo producto después del envío se requiere ampliar el flujo con envíos parciales por producto. El cambio de una venta cobrada utiliza el mecanismo de cambio inmediato de la versión anterior; no vuelve a entrar en cola de preparación. El sistema conserva este comportamiento como compatibilidad temporal.

## Cómo instalar sin perder los datos

1. Cierra JuniorsControl en todos los equipos y toma un respaldo `.bak` **verificado** de la base configurada. Conserva una copia del ZIP anterior.
2. Extrae todo este ZIP en **otra carpeta**, sin sobrescribir la instalación anterior.
3. Abre `JuniorsControl/sqlserver.json` y comprueba servidor y nombre exactos de tu base actual. No copies archivos privados de credenciales a chats ni repositorios.
4. Ejecuta `configurar_sqlserver.bat` desde la carpeta `JuniorsControl`. El programa actualiza el esquema de la versión 3 a la 4 y conserva las tablas anteriores. **No ejecutes el script `esquema.sql` manualmente sobre una base existente**.
5. Ejecuta `iniciar.bat` o `iniciar_escritorio.bat`. La ventana de escritorio incluye WebView2; no necesitas recompilar el `.exe` para usar estos cambios en Python y la web.
6. En `Equipo y correo`, invita empleados con el rol `area` y un área EXACTA: `Cocina`, `Barra` o `Parrilla` (sin cambiar mayúsculas ni poner "Todas"). El administrador conserva la capacidad exclusiva de gestionar cuentas.
7. En `Inventario → Carta y recetas` verifica o ajusta el campo **Área responsable de preparación** de cada producto. Las categorías de ejemplo se asignaron automáticamente a un área, pero pueden requerir revisión.
8. Usa `sql/CONSULTAS_ATENCION_V4.sql` en SSMS para comprobar estructura y registros. Las consultas son de solo lectura.

## Prueba integral recomendada (en una copia de SQL Server)

1. Inicia como Atención, elige Piso 1 / Mesa 2 y guarda una comanda con un producto de Cocina y uno de Barra. Verifica que otra comanda para esa mesa y fecha es rechazada.
2. Pulsa Enviar a preparación. Comprueba que el usuario de Cocina solo ve su producto y el de Barra solo el suyo.
3. Marca cada producto como Preparando, Listo y Entregado. Comprueba las cuatro horas en SQL Server.
4. Comprueba que Caja no puede cobrar mientras haya un producto por entregar y sí puede cuando todos estén Entregados.
5. Verifica que después del cobro la misma mesa admite una comanda nueva en la misma fecha.
6. En una segunda mesa solicita cancelar, comprueba que sigue ocupada y luego aprueba o rechaza como Caja o Administración.
7. Cobra una venta y registra una devolución para verificar que los importes y movimientos de stock se mantienen correctamente.
8. Haz pruebas en otra sesión de navegador y, si está disponible, en otro dispositivo del local.

## Cómo repetir las pruebas unitarias locales

Desde la carpeta `JuniorsControl`, con un Python de desarrollo (no es necesario conectar SQL Server para estas pruebas unitarias):

```powershell
py -m unittest discover -s pruebas -p test_atencion_v4.py -v
```

Estas pruebas comprueban reglas y permisos aislados usando un simulador pequeño de consultas SQL. **No constituyen una prueba de integración con tu instancia de SQL Server**, ni de envío SMTP real, ni del equipo o dispositivos de producción. Realiza la prueba integral anterior en una base restaurada antes de utilizar el sistema con clientes.
