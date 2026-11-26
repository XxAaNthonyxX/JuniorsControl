ALTER TABLE dbo.inv_cancel_requests ADD revision int NOT NULL DEFAULT 0, prior_status nvarchar(24), request_day nvarchar(10);
ALTER TABLE dbo.refund_requests ADD revision int NOT NULL DEFAULT 0, request_day nvarchar(10);
CREATE TABLE dbo.refund_parts (
 return_id bigint NOT NULL REFERENCES dbo.inv_returns(id), lot_id bigint NOT NULL REFERENCES dbo.inv_lots(id),
 amount bigint NOT NULL CHECK(amount>0), restocked bigint NOT NULL, CHECK(restocked BETWEEN 0 AND amount),
 PRIMARY KEY(return_id,lot_id));
CREATE TABLE dbo.refund_reversals (
 return_id bigint PRIMARY KEY REFERENCES dbo.inv_returns(id), at nvarchar(32) NOT NULL,
 cash_day nvarchar(10) NOT NULL, actor nvarchar(140) NOT NULL);

-- Reconstruye el reparto FIFO de devoluciones aprobadas antes de registrar cada lote por documento.
;WITH lots AS (
 SELECT a.*,l.item_id,
 SUM(a.amount) OVER(PARTITION BY a.order_id,a.product_id,l.item_id) AS item_total,
 SUM(a.amount) OVER(PARTITION BY a.order_id,a.product_id,l.item_id ORDER BY
 CASE WHEN l.expiry IS NULL THEN 1 ELSE 0 END,l.expiry,l.id ROWS UNBOUNDED PRECEDING) AS lot_end
 FROM inv_alloc a JOIN inv_lots l ON l.id=a.lot_id
), credits AS (
 SELECT r.*,SUM(r.qty) OVER(PARTITION BY r.order_id,r.product_id ORDER BY r.id ROWS UNBOUNDED PRECEDING) AS units_end
 FROM inv_returns r
)
INSERT refund_parts(return_id,lot_id,amount,restocked)
SELECT r.id,a.lot_id,ends.hi-starts.lo,COALESCE(m.stock,0)
FROM credits r JOIN refund_requests req ON req.return_id=r.id
JOIN lots a ON a.order_id=r.order_id AND a.product_id=r.product_id
JOIN inv_lines l ON l.order_id=r.order_id AND l.product_id=r.product_id
CROSS APPLY (SELECT MIN(x) AS hi FROM (VALUES(a.lot_end),(r.units_end*(a.item_total/l.qty))) v(x)) ends
CROSS APPLY (SELECT MAX(x) AS lo FROM (VALUES(a.lot_end-a.amount),((r.units_end-r.qty)*(a.item_total/l.qty))) v(x)) starts
OUTER APPLY (SELECT SUM(delta) AS stock FROM inv_moves WHERE lot_id=a.lot_id AND delta>0
 AND ref LIKE CONCAT('DV',FORMAT(r.id,'0000'),' · %')) m
WHERE ends.hi>starts.lo;
UPDATE dbo.juniors_version SET version=8 WHERE version=7;
