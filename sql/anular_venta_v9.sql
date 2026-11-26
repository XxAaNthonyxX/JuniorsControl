ALTER TABLE dbo.inv_details ADD closed_name nvarchar(140), closed_price bigint;
CREATE TABLE dbo.sale_voids (
 order_id bigint PRIMARY KEY REFERENCES dbo.inv_orders(id), cash_day nvarchar(10) NOT NULL,
 at nvarchar(32) NOT NULL, actor nvarchar(140) NOT NULL, reason nvarchar(300) NOT NULL,
 cents bigint NOT NULL CHECK(cents>=0));
UPDATE dbo.juniors_version SET version=9 WHERE version=8;
