ALTER TABLE dbo.sale_voids ALTER COLUMN reason nvarchar(500) NOT NULL;
ALTER TABLE dbo.sale_voids ADD cancel_request_id bigint NULL REFERENCES dbo.inv_cancel_requests(id);
ALTER TABLE dbo.refund_requests ADD voided_by_cancel_id bigint NULL REFERENCES dbo.inv_cancel_requests(id);

CREATE TABLE dbo.sale_void_stock (
    order_id bigint NOT NULL REFERENCES dbo.sale_voids(order_id),
    lot_id bigint NOT NULL REFERENCES dbo.inv_lots(id),
    amount bigint NOT NULL CHECK(amount>0),
    PRIMARY KEY(order_id,lot_id)
);

UPDATE dbo.juniors_version SET version=19 WHERE version=18;
