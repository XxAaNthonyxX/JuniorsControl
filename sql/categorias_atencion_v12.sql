INSERT dbo.menu_categories(name)
SELECT defaults.name
FROM (VALUES (N'Brasas'), (N'Parrillas'), (N'Barra'), (N'Orientales')) AS defaults(name)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.menu_categories AS current_categories WHERE current_categories.name=defaults.name
);

UPDATE dbo.inv_products SET category=N'Barra' WHERE LOWER(category)=N'bebidas';
UPDATE dbo.inv_products SET category=N'Orientales' WHERE LOWER(category)=N'oriental';
DELETE FROM dbo.menu_categories WHERE LOWER(name) IN (N'bebidas', N'oriental');

UPDATE dbo.juniors_version SET version=12 WHERE version=11;
