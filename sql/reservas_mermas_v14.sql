CREATE TABLE dbo.g_waste_lots (
    waste_id bigint NOT NULL REFERENCES dbo.g_wastes(id),
    lot_id bigint NOT NULL REFERENCES dbo.inv_lots(id),
    amount bigint NOT NULL CHECK(amount>0),
    PRIMARY KEY (waste_id, lot_id)
);

UPDATE dbo.juniors_version SET version=14 WHERE version=13;
