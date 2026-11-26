CREATE TABLE dbo.menu_categories(name nvarchar(255) PRIMARY KEY);
INSERT dbo.menu_categories SELECT DISTINCT category FROM dbo.inv_products;
CREATE TABLE dbo.refund_requests (
 id bigint IDENTITY PRIMARY KEY, order_id bigint NOT NULL, product_id bigint NOT NULL,
 qty bigint NOT NULL CHECK(qty>0), reason nvarchar(300) NOT NULL,
 requester_id bigint NOT NULL, requester nvarchar(140) NOT NULL, requested_at nvarchar(32) NOT NULL,
 status nvarchar(24) NOT NULL, decided_by nvarchar(140), decided_at nvarchar(32),
 decision_reason nvarchar(300), return_id bigint REFERENCES dbo.inv_returns(id),
 FOREIGN KEY(order_id,product_id) REFERENCES dbo.inv_lines(order_id,product_id));
ALTER TABLE dbo.inv_cancel_requests ADD decision_reason nvarchar(300), requester_id bigint;
CREATE INDEX ix_refund_requests_line ON dbo.refund_requests(order_id,product_id,status);
UPDATE dbo.juniors_version SET version=6 WHERE version=5;
