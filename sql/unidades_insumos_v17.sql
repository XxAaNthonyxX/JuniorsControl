ALTER TABLE dbo.inv_items ADD display_unit nvarchar(20) NULL, display_unit_milli bigint NULL;
GO
ALTER TABLE dbo.inv_items ADD CONSTRAINT ck_inv_items_display_unit CHECK (
    (display_unit IS NULL AND display_unit_milli IS NULL) OR
    (display_unit IS NOT NULL AND display_unit_milli IS NOT NULL AND display_unit_milli > 0)
);

UPDATE dbo.inv_items SET display_unit=N'filetes', display_unit_milli=280
WHERE name=N'Bistec de res' AND unit=N'kg';

UPDATE dbo.inv_items SET display_unit=N'porciones', display_unit_milli=500
WHERE unit=N'kg' AND (name=N'Arroz' OR name LIKE N'Arroz %');

UPDATE recipe SET amount=500
FROM dbo.inv_recipes recipe
JOIN dbo.inv_items item ON item.id=recipe.item_id
JOIN dbo.inv_products product ON product.id=recipe.product_id
WHERE item.unit=N'kg' AND (
    (item.name=N'Arroz cocido' AND product.name=N'Chaufa de pollo' AND recipe.amount=250) OR
    (item.name=N'Papa para freír' AND product.name=N'Parrilla personal' AND recipe.amount=200)
);

UPDATE dbo.juniors_version SET version=17 WHERE version=16;
