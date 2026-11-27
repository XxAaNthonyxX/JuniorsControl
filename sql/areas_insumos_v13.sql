UPDATE item SET area=CASE
    WHEN LOWER(item.area) IN (N'brasas', N'horno') THEN N'Brasas'
    WHEN LOWER(item.area)=N'parrilla' AND (
        EXISTS (SELECT 1 FROM dbo.inv_portion_groups AS portion_group
                WHERE item.id IN (portion_group.base_id, portion_group.raw_id))
        OR EXISTS (SELECT 1 FROM dbo.inv_recipes AS recipe
                   JOIN dbo.inv_products AS product ON product.id=recipe.product_id
                   WHERE recipe.item_id=item.id AND product.category=N'Brasas')
        OR item.name=N'Pollo entero crudo'
    ) THEN N'Brasas'
    WHEN LOWER(item.area) IN (N'parrilla', N'parrillas') THEN N'Parrillas'
    WHEN LOWER(item.area)=N'barra' THEN N'Barra'
    WHEN LOWER(item.area) IN (N'cocina', N'oriental', N'orientales') THEN N'Orientales'
    ELSE N'Limpieza y Atención'
END
FROM dbo.inv_items AS item;

UPDATE item SET area=base.area
FROM dbo.inv_items AS item
JOIN dbo.inv_stock_equivalents AS equivalent ON equivalent.item_id=item.id
JOIN dbo.inv_items AS base ON base.id=equivalent.base_id
WHERE item.area<>base.area;

UPDATE dbo.juniors_version SET version=13 WHERE version=12;
