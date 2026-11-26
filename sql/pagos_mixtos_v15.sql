CREATE TABLE dbo.inv_sale_payments (
    sale_id bigint NOT NULL REFERENCES dbo.inv_sales(id),
    method nvarchar(32) NOT NULL CHECK(method IN (N'Efectivo',N'Yape',N'Tarjeta')),
    cents bigint NOT NULL CHECK(cents>0),
    PRIMARY KEY (sale_id, method)
);

UPDATE dbo.juniors_version SET version=15 WHERE version=14;
