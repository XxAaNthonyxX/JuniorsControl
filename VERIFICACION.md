# Verificación de JuniorsControl con SQL Server

Pruebas ejecutadas en Windows x64 con autenticación de Windows, SQL Server 17.0.1155.3, ODBC Driver 18 y bases temporales. Los resultados de este documento corresponden a la edición SQL Server.

| Requisitos del informe, sección 2.1 | Evidencia y alcance |
| --- | --- |
| RF-01, 04, 13 · Pedido y caja | Dos solicitudes simultáneas intentaron reservar seis de las diez botellas disponibles. Una se aceptó y la otra se rechazó. Repetir el cobro produjo una venta. La devolución de dos botellas ajustó el físico y el importe neto. |
| RF-02, 03, 05–08, 11, 12 · Inventario | Se creó el catálogo de demostración con áreas, categorías, unidades, mínimos, vencimientos y recetas. Se ejecutó una transformación, se consultaron cantidades por insumo y se comprobó que cada movimiento tuviera su registro de contexto. |
| RF-09, 10 · Personal | Alta de administrador y de personal por invitación, rol asignado por el servidor, bloqueo de cobro para el área de barra y revocación de la sesión al desactivar la cuenta. Se simuló el envío de correo. |
| RF-14, 16, 24, 25 · Recepción | En un pedido de 8 unidades llegaron 7 y se aprobaron 6. El físico subió en 6 y quedó una inconformidad. La prueba de Edge recorrió la resolución con el proveedor. |
| RF-15, 17–23 · Supervisión | En Edge se recorrieron fondo, compra, hoja CSV, recepción, merma, reporte de faltantes y alertas. El servicio conserva la comprobación periódica de caducidades y la hora configurable del informe. |
| RNF-02 · Rendimiento | 100 lecturas del estado completo por HTTPS local. Cuatro sesiones consultaron una carta de ejemplo con diez ventas. Las 100 respondieron dentro de tres segundos. Percentil 95 de **664,2 ms**. La medición incluye conexión, consulta y lectura del JSON. |
| RNF-03–06, 10 · Seguridad e integridad | Autenticación en SQL Server, sesiones web por usuario, operaciones protegidas por rol, HTTPS y pruebas de concurrencia y cobro repetido. |
| RNF-07, 08 · Crecimiento y recuperación | Migración del respaldo de demostración anterior, con **92 filas** verificadas por tabla. Copia .bak con checksum, reutilización de la copia del día y restauración bajo otro nombre con CHECKDB. Se comprobaron cuentas, venta y cierre de sesiones recuperadas. |
| RNF-01, 09, 11, 12 · Interfaces | Gestión en Edge y navegación táctil simulada a 768 × 1024, 1024 × 768 y 390 × 844. En WinForms/WebView2 se abrió la aplicación, se creó una cuenta y se descargaron el certificado público y la hoja de compra. Se compararon los bytes del certificado y el contenido del CSV. |

El piloto con trabajadores del restaurante, el envío a una cuenta Gmail real, una segunda PC por la red del local y la prueba en una tableta física quedan pendientes. La marca de rendimiento corresponde al equipo y volumen de este ensayo.

## Pruebas de la edición anterior con acceso por usuario y Gmail

Se probó el envío SMTP simulado del código inicial, la sustitución del código al reenviar, el registro con un código vinculado al correo y el rechazo al reutilizarlo. En SQL Server se comprobaron los dos identificadores de acceso, la unicidad de usuario, la reserva del correo tras desactivar y su reutilización con una invitación nueva tras eliminar la cuenta. En Edge se creó un administrador con un código de prueba y se cerró e inició sesión con usuario y con correo. En un catálogo temporal del esquema anterior se verificó la actualización y el acceso por correo y por código US de una cuenta existente. La entrega en una bandeja de Gmail real requiere configurar el remitente.

## Acceso por correo y recuperación de contraseña

La prueba en Edge pasó del registro verificado del primer administrador al formulario de inicio por correo, solicitó la recuperación, introdujo un código de 8 dígitos entregado en un buzón de prueba y entró con la nueva contraseña. En SQL Server se comprobaron el vencimiento, la vinculación al correo, el límite de cinco intentos, el uso único y la revocación de las sesiones anteriores. El transporte a una bandeja real de Gmail queda pendiente.

## Repetición

Desde la raíz del proyecto, con SQL Server accesible y una cuenta de pruebas autorizada para crear y eliminar sus catálogos temporales:

```powershell
.\runtime\python.exe -B -X utf8 .\pruebas\probar_sqlserver.py
.\runtime\python.exe -B -X utf8 .\pruebas\prueba_consultas_https.py
.\runtime\python.exe -B -X utf8 .\pruebas\probar_recuperacion.py
```

Para reproducir también la importación, añade `--origen "C:\MisCopias\demo.sqlite3"` al último comando. El ensayo de recuperación y los de interfaz están preparados para una instancia local. Dan al servicio SQL permiso sobre su carpeta temporal de copias.

Las pruebas de interfaz requieren Edge, WebView2 Evergreen, Node.js y Playwright. En el equipo de desarrollo, desde la raíz, instala la dependencia de prueba y elige el recorrido:

```powershell
npm install --no-save --package-lock=false playwright@1.61.0
.\runtime\python.exe -B -X utf8 .\pruebas\probar_interfaz.py gestion
.\runtime\python.exe -B -X utf8 .\pruebas\probar_interfaz.py tabletas
.\runtime\python.exe -B -X utf8 .\pruebas\probar_interfaz.py escritorio
```
