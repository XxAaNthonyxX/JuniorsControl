CREATE TABLE dbo.inv_details (
 order_id bigint NOT NULL REFERENCES dbo.inv_orders(id),
 detail_no int NOT NULL CHECK(detail_no>0),
 product_id bigint NOT NULL REFERENCES dbo.inv_products(id),
 qty bigint NOT NULL CHECK(qty>0),
 sent_product bigint NULL REFERENCES dbo.inv_products(id), sent_qty bigint NULL,
 area nvarchar(40), status nvarchar(24), sent_at nvarchar(32), started_at nvarchar(32),
 ready_at nvarchar(32), delivered_at nvarchar(32), delivered_by nvarchar(140),
 revision int NOT NULL DEFAULT 0, PRIMARY KEY(order_id,detail_no)
);
INSERT dbo.inv_details(order_id,detail_no,product_id,qty,sent_product,sent_qty,area,status,sent_at,
 started_at,ready_at,delivered_at,delivered_by)
SELECT l.order_id,ROW_NUMBER() OVER(PARTITION BY l.order_id ORDER BY l.product_id),l.product_id,l.qty,
 d.product_id,CASE WHEN d.product_id IS NOT NULL THEN l.qty END,d.area,d.status,d.sent_at,d.started_at,
 d.ready_at,d.delivered_at,d.delivered_by FROM dbo.inv_lines l LEFT JOIN dbo.inv_dispatch d
 ON d.order_id=l.order_id AND d.product_id=l.product_id;
DROP TABLE dbo.inv_dispatch;
ALTER TABLE dbo.inv_sales ADD payment_method nvarchar(32), cash_day nvarchar(10);
ALTER TABLE dbo.inv_returns ADD cash_day nvarchar(10);
ALTER TABLE dbo.g_settings ADD work_day nvarchar(10);
CREATE TABLE dbo.cash_expenses (
 id bigint IDENTITY PRIMARY KEY, day nvarchar(10) NOT NULL, kind nvarchar(16) NOT NULL,
 reference nvarchar(100) NOT NULL, concept nvarchar(300) NOT NULL, cents bigint NOT NULL CHECK(cents>0),
 actor nvarchar(140) NOT NULL, void_reason nvarchar(300), void_by nvarchar(140), void_at nvarchar(32)
);
CREATE UNIQUE INDEX ux_cash_expense_active ON dbo.cash_expenses(day,kind,reference) WHERE void_at IS NULL;
UPDATE dbo.juniors_version SET version=5 WHERE version=4;
