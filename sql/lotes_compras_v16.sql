ALTER TABLE dbo.g_purchases ADD purchase_day nvarchar(10) NULL;
UPDATE dbo.juniors_version SET version=16 WHERE version=15;
