-- Una porción de pechuga en la receta de chaufa equivale a un filete en el catálogo.
UPDATE item
SET display_unit=N'filetes', display_unit_milli=recipe.amount
FROM dbo.inv_items item
JOIN dbo.inv_recipes recipe ON recipe.item_id=item.id
JOIN dbo.inv_products product ON product.id=recipe.product_id
WHERE item.name IN (N'Pechuga de pollo',N'Pechugas de pollo')
  AND item.unit=N'kg' AND item.display_unit_milli IS NULL
  AND product.name=N'Chaufa de pollo';

UPDATE dbo.juniors_version SET version=23 WHERE version=22;
