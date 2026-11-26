-- Migración 4, idempotente. Ejecutar únicamente en la base de JuniorsControl con respaldo .bak.
IF COL_LENGTH('dbo.inv_orders','table_number') IS NULL
    ALTER TABLE dbo.inv_orders ADD table_number int NULL;
IF COL_LENGTH('dbo.inv_products','prep_area') IS NULL
    ALTER TABLE dbo.inv_products ADD prep_area nvarchar(40) NULL;
GO
IF OBJECT_ID('dbo.inv_dispatch','U') IS NULL
CREATE TABLE dbo.inv_dispatch (
    order_id bigint NOT NULL REFERENCES dbo.inv_orders(id),
    product_id bigint NOT NULL REFERENCES dbo.inv_products(id),
    area nvarchar(40) NOT NULL CHECK(area IN (N'Cocina',N'Barra',N'Parrilla')),
    status nvarchar(24) NOT NULL CHECK(status IN (N'En cola',N'Preparando',N'Listo',N'Entregado')),
    sent_at nvarchar(32) NOT NULL, started_at nvarchar(32) NULL, ready_at nvarchar(32) NULL,
    delivered_at nvarchar(32) NULL, delivered_by nvarchar(140) NULL,
    PRIMARY KEY(order_id, product_id),
    FOREIGN KEY(order_id,product_id) REFERENCES dbo.inv_lines(order_id,product_id)
);
GO
IF OBJECT_ID('dbo.inv_cancel_requests','U') IS NULL
CREATE TABLE dbo.inv_cancel_requests (
    id bigint IDENTITY(1,1) PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES dbo.inv_orders(id),
    status nvarchar(20) NOT NULL CHECK(status IN (N'Pendiente',N'Aprobada',N'Rechazada')),
    reason nvarchar(500) NOT NULL, requester nvarchar(140) NOT NULL,
    requested_at nvarchar(32) NOT NULL, decided_at nvarchar(32) NULL, decided_by nvarchar(140) NULL
);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'ux_juniors_mesa_jornada_abierta' AND object_id=OBJECT_ID(N'dbo.inv_orders'))
    CREATE UNIQUE INDEX ux_juniors_mesa_jornada_abierta
    ON dbo.inv_orders(day,table_number)
    WHERE table_number IS NOT NULL AND status IN (N'Reservado',N'Por revisar');
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'ix_juniors_preparacion_area' AND object_id=OBJECT_ID(N'dbo.inv_dispatch'))
    CREATE INDEX ix_juniors_preparacion_area ON dbo.inv_dispatch(area,status,order_id);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'ux_juniors_cancel_pendiente' AND object_id=OBJECT_ID(N'dbo.inv_cancel_requests'))
    CREATE UNIQUE INDEX ux_juniors_cancel_pendiente ON dbo.inv_cancel_requests(order_id) WHERE status=N'Pendiente';
GO
IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'ck_juniors_numero_mesa')
    ALTER TABLE dbo.inv_orders ADD CONSTRAINT ck_juniors_numero_mesa
    CHECK(table_number IS NULL OR table_number BETWEEN 1 AND 20);
-- No sobreescribir mesas antiguas con texto libre, ni imputar entregas históricas inexistentes.
-- Clasificar productos de ejemplo según su categoría. La administración puede ajustar el área después.
GO
UPDATE dbo.inv_products SET prep_area =
 CASE WHEN LOWER(category) LIKE N'%bebid%' OR LOWER(category) LIKE N'%coct%' THEN N'Barra'
 WHEN LOWER(category) LIKE N'%brasa%' OR LOWER(category) LIKE N'%parrill%' THEN N'Parrilla'
 ELSE N'Cocina' END WHERE prep_area IS NULL;
GO
-- Volcar números de mesas existentes que tengan formato canónico inequívoco y no estén duplicados.
;WITH parsed AS (
 SELECT id,day,status,TRY_CONVERT(int,SUBSTRING(table_name,6,100)) AS n
 FROM dbo.inv_orders WHERE table_number IS NULL AND table_name LIKE N'Mesa %'
), valid AS (
 SELECT p.id,p.day,p.n,p.status,COUNT(*) OVER (PARTITION BY p.day,p.n) AS amount
 FROM parsed p WHERE p.n BETWEEN 1 AND 20 AND p.status IN (N'Reservado',N'Por revisar')
)
UPDATE o SET table_number=v.n FROM dbo.inv_orders o JOIN valid v ON o.id=v.id
WHERE v.amount=1 AND NOT EXISTS(SELECT 1 FROM dbo.inv_orders q
 WHERE q.day=v.day AND q.table_number=v.n AND q.status IN (N'Reservado',N'Por revisar'));
UPDATE dbo.juniors_version SET version=4 WHERE version=3;
