-- Ambas ediciones v3 comparten el catálogo. Conservar los códigos ya emitidos.
IF COL_LENGTH('dbo.auth_invites','digest') = 32
    ALTER TABLE dbo.auth_invites ALTER COLUMN digest varbinary(48) NOT NULL;
IF COL_LENGTH('dbo.auth_password_resets','digest') = 32
    ALTER TABLE dbo.auth_password_resets ALTER COLUMN digest varbinary(48) NOT NULL;
IF COL_LENGTH('dbo.auth_password_resets','requested_at') IS NULL
    ALTER TABLE dbo.auth_password_resets ADD requested_at bigint NOT NULL
        DEFAULT (DATEDIFF_BIG(SECOND, '19700101', SYSUTCDATETIME())) WITH VALUES;
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.auth_password_resets')
                AND name='requested_at' AND default_object_id=0)
    ALTER TABLE dbo.auth_password_resets ADD DEFAULT
        (DATEDIFF_BIG(SECOND, '19700101', SYSUTCDATETIME())) FOR requested_at;
