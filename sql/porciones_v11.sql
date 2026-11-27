CREATE TABLE dbo.inv_portion_groups (
 base_id bigint PRIMARY KEY REFERENCES dbo.inv_items(id),
 raw_id bigint NOT NULL REFERENCES dbo.inv_items(id),
 potato_id bigint NOT NULL REFERENCES dbo.inv_items(id)
);
CREATE TABLE dbo.inv_stock_equivalents (
 item_id bigint PRIMARY KEY REFERENCES dbo.inv_items(id),
 base_id bigint NOT NULL REFERENCES dbo.inv_portion_groups(base_id),
 factor int NOT NULL CHECK(factor IN (2,4)),
 UNIQUE(base_id,factor), CHECK(item_id<>base_id)
);
UPDATE dbo.juniors_version SET version=11 WHERE version=10;
