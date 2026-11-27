-- Las cuentas existentes conservan su rol y las invitaciones su código.
UPDATE dbo.users
SET area=CASE LOWER(area)
    WHEN N'horno' THEN N'Brasas'
    WHEN N'parrilla' THEN N'Parrillas'
    WHEN N'cocina' THEN N'Orientales'
    WHEN N'oriental' THEN N'Orientales'
    ELSE N'Limpieza y Atención'
END
WHERE LOWER(area)=N'horno' OR
    (role=N'area' AND LOWER(area) IN (N'parrilla',N'cocina',N'oriental',N'limpieza',N'atención'));

UPDATE dbo.auth_invites
SET area=CASE LOWER(area)
    WHEN N'horno' THEN N'Brasas'
    WHEN N'parrilla' THEN N'Parrillas'
    WHEN N'cocina' THEN N'Orientales'
    WHEN N'oriental' THEN N'Orientales'
    ELSE N'Limpieza y Atención'
END
WHERE LOWER(area)=N'horno' OR
    (role=N'area' AND LOWER(area) IN (N'parrilla',N'cocina',N'oriental',N'limpieza',N'atención'));

UPDATE dbo.inv_products
SET prep_area=CASE
    WHEN prep_area=N'Horno' THEN N'Brasas'
    WHEN LOWER(category) LIKE N'%brasa%' THEN N'Brasas'
    WHEN LOWER(category) LIKE N'%parrill%' OR prep_area=N'Parrilla' THEN N'Parrillas'
    WHEN LOWER(category)=N'barra' OR LOWER(category) LIKE N'%bebid%' OR LOWER(category) LIKE N'%coct%' THEN N'Barra'
    ELSE N'Orientales'
END
WHERE prep_area IN (N'Cocina',N'Parrilla',N'Horno') OR prep_area IS NULL;

-- El área del último envío se calcula a partir del producto enviado. Un reemplazo en
-- edición sigue siendo invisible hasta que Atención envíe los cambios.
UPDATE detail
SET area=CASE
    WHEN detail.area=N'Horno' THEN N'Brasas'
    WHEN LOWER(sent.category) LIKE N'%brasa%' THEN N'Brasas'
    WHEN LOWER(sent.category) LIKE N'%parrill%' OR detail.area=N'Parrilla' THEN N'Parrillas'
    WHEN LOWER(sent.category)=N'barra' OR LOWER(sent.category) LIKE N'%bebid%' OR LOWER(sent.category) LIKE N'%coct%' THEN N'Barra'
    ELSE N'Orientales'
END,
revision=revision+1
FROM dbo.inv_details detail JOIN dbo.inv_products sent ON sent.id=detail.sent_product
WHERE detail.area IN (N'Cocina',N'Parrilla',N'Horno');

UPDATE dbo.juniors_version SET version=24 WHERE version=23;
