ALTER TABLE dbo.inv_orders ADD take_away bit NOT NULL CONSTRAINT df_orders_take_away DEFAULT 0 WITH VALUES;
UPDATE dbo.juniors_version SET version=10 WHERE version=9;
