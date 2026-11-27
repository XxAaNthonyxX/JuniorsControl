ALTER TABLE dbo.inv_details
    ADD remove_pending bit NOT NULL CONSTRAINT df_inv_details_remove_pending DEFAULT 0;

CREATE TABLE dbo.cancel_consumption (
 request_id bigint NOT NULL REFERENCES dbo.inv_cancel_requests(id),
 lot_id bigint NOT NULL REFERENCES dbo.inv_lots(id),
 amount bigint NOT NULL CHECK(amount>0),
 PRIMARY KEY(request_id,lot_id)
);

CREATE TABLE dbo.inv_return_details (
 return_id bigint NOT NULL REFERENCES dbo.inv_returns(id),
 order_id bigint NOT NULL,
 detail_no int NOT NULL,
 qty bigint NOT NULL CHECK(qty>0),
 restock bit NOT NULL,
 PRIMARY KEY(return_id,detail_no),
 FOREIGN KEY(order_id,detail_no) REFERENCES dbo.inv_details(order_id,detail_no)
);

CREATE INDEX ix_inv_return_details_order ON dbo.inv_return_details(order_id,detail_no);

UPDATE dbo.juniors_version SET version=18 WHERE version=17;
