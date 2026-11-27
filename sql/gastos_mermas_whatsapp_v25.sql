ALTER TABLE dbo.g_wastes ADD
    cost_cents bigint NULL CHECK (cost_cents >= 0),
    expense_day nvarchar(10) NULL;

CREATE TABLE dbo.g_supplier_contacts (
    supplier nvarchar(100) PRIMARY KEY,
    whatsapp varchar(15) NOT NULL
);

UPDATE dbo.juniors_version SET version=25 WHERE version=24;
