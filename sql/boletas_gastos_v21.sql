ALTER TABLE dbo.cash_expenses ADD receipt_no bigint NULL;
GO
WITH numbered AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY day ORDER BY id) AS receipt_no
    FROM dbo.cash_expenses
)
UPDATE expense SET receipt_no=numbered.receipt_no
FROM dbo.cash_expenses AS expense
JOIN numbered ON numbered.id=expense.id;

ALTER TABLE dbo.cash_expenses ALTER COLUMN receipt_no bigint NOT NULL;
CREATE UNIQUE INDEX ux_cash_expense_daily_receipt ON dbo.cash_expenses(day,receipt_no);

DROP INDEX ux_cash_expense_active ON dbo.cash_expenses;
CREATE UNIQUE INDEX ux_cash_expense_active ON dbo.cash_expenses(day,kind,reference)
    WHERE void_at IS NULL AND reference<>N'';

UPDATE dbo.juniors_version SET version=21 WHERE version=20;
