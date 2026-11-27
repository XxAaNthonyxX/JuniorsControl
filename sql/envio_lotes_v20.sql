ALTER TABLE dbo.g_receipts ADD version bigint NOT NULL DEFAULT 1;
ALTER TABLE dbo.g_incidents ADD decision bit NULL;
UPDATE dbo.juniors_version SET version=20 WHERE version=19;
