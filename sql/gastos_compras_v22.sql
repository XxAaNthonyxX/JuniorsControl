ALTER TABLE dbo.cash_expenses ADD purchase_id bigint NULL REFERENCES dbo.g_purchases(id);
GO
CREATE UNIQUE INDEX ux_cash_expense_purchase ON dbo.cash_expenses(purchase_id) WHERE purchase_id IS NOT NULL;
UPDATE dbo.juniors_version SET version=22 WHERE version=21;
