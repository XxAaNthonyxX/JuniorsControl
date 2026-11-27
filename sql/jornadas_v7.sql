CREATE TABLE dbo.cash_days (
    day nvarchar(10) NOT NULL PRIMARY KEY,
    opened_at nvarchar(32) NULL,
    opened_by nvarchar(140) NULL
);
INSERT INTO dbo.cash_days(day) SELECT work_day FROM dbo.g_settings WHERE work_day IS NOT NULL;
UPDATE dbo.juniors_version SET version=7 WHERE version=6;
