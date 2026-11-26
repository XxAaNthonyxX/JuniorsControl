-- Consultas de solo lectura para SSMS. Selecciona antes el nombre real de tu catálogo JuniorsControl.
-- 1. Versión instalada
SELECT version AS version_esquema FROM dbo.juniors_version;
-- 2. Mesas ocupadas por jornada (fecha actual de SQL Server, puede ser distinta de Lima si el servidor está en otra zona)
SELECT day AS fecha, number AS numero, table_number AS mesa,
       CASE WHEN table_number BETWEEN 1 AND 10 THEN 1 WHEN table_number BETWEEN 11 AND 20 THEN 2 END AS piso,
       status AS estado, created AS creada_en, paid_at AS cobrada_en
FROM dbo.inv_orders ORDER BY day DESC,number DESC;
-- 3. Colas y entrega por área (hora en Perú)
SELECT o.day AS fecha, o.number AS comanda, o.table_number AS mesa,
       p.name AS producto, d.area, l.qty AS cantidad,
       d.status AS estado, d.sent_at AS enviada_en,
       d.started_at AS preparando_en, d.ready_at AS lista_en,
       d.delivered_at AS entregada_en, d.delivered_by AS entregada_por
FROM dbo.inv_dispatch d
JOIN dbo.inv_orders o ON o.id=d.order_id
JOIN dbo.inv_lines l ON l.order_id=d.order_id AND l.product_id=d.product_id
JOIN dbo.inv_products p ON p.id=d.product_id
ORDER BY d.sent_at DESC, o.id, d.product_id;
-- 4. Cancelaciones solicitadas y resueltas
SELECT o.day AS fecha,o.number AS comanda,o.table_number AS mesa,
       r.status,r.reason,r.requester,r.requested_at,r.decided_by,r.decided_at
FROM dbo.inv_cancel_requests r JOIN dbo.inv_orders o ON o.id=r.order_id
ORDER BY r.id DESC;
-- 5. Comandas con productos y estado de entrega
SELECT o.day,o.number,o.table_number,o.status,l.name,l.qty,l.price,
       COALESCE(d.status,N'Sin enviar') AS preparacion,
       d.delivered_at,o.paid_at
FROM dbo.inv_orders o JOIN dbo.inv_lines l ON l.order_id=o.id
LEFT JOIN dbo.inv_dispatch d ON d.order_id=l.order_id AND d.product_id=l.product_id
ORDER BY o.day DESC,o.number DESC,l.product_id;
-- 6. Ventas cobradas y devoluciones
SELECT o.day,o.number,o.table_number,o.paid_at,s.id AS venta_id,
       r.id AS devolucion_id,r.at AS devuelta_en,r.qty AS unidades,r.reason
FROM dbo.inv_sales s JOIN dbo.inv_orders o ON o.id=s.order_id
LEFT JOIN dbo.inv_returns r ON r.order_id=o.id
ORDER BY o.day DESC,o.number DESC;
-- 7. Llaves foráneas nuevas
SELECT fk.name,OBJECT_NAME(fk.parent_object_id) AS tabla_hija,
       OBJECT_NAME(fk.referenced_object_id) AS tabla_padre,
       fk.is_disabled,fk.is_not_trusted
FROM sys.foreign_keys fk WHERE OBJECT_NAME(fk.parent_object_id) IN
 (N'inv_dispatch',N'inv_cancel_requests') ORDER BY fk.name;
-- 8. Área asociada a cada producto de carta
SELECT id,name,category,prep_area FROM dbo.inv_products ORDER BY name;
-- 9. Detectar posibles duplicados históricos con mesa escrita en texto y sin normalizar
SELECT day,table_name,COUNT(*) AS abiertas FROM dbo.inv_orders
WHERE status IN (N'Reservado',N'Por revisar') AND table_number IS NULL
GROUP BY day,table_name HAVING COUNT(*)>1;
