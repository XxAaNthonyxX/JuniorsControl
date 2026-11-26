-- SSMS: ejecutar con una cuenta autorizada de recuperación.
-- Primero indica la ruta que generó la instancia y ejecuta. En Resultados
-- aparecen los nombres lógicos (LogicalName, tipos D y L). Escríbelos debajo,
-- elige un nombre libre para la base de ensayo y ejecuta de nuevo.
USE master;
GO
DECLARE @archivo nvarchar(4000) = N'',
        @nueva sysname = N'JuniorsControl_Recuperada',
        @datos sysname = N'',
        @log sysname = N'';
IF @archivo = N'' THROW 50001, N'Escribe la ruta del archivo .bak en @archivo.', 1;
RESTORE VERIFYONLY FROM DISK = @archivo WITH CHECKSUM;
RESTORE FILELISTONLY FROM DISK = @archivo;
IF @datos = N'' OR @log = N'' RETURN;
IF DB_ID(@nueva) IS NOT NULL THROW 50002, N'El destino ya existe. Elige un nombre nuevo.', 1;
IF @nueva = N'' OR @nueva COLLATE Latin1_General_100_BIN2 LIKE N'%[^a-zA-Z0-9_]%'
    THROW 50003, N'Usa letras, dígitos y guion bajo para la nueva base.', 1;
DECLARE @baseDatos nvarchar(4000) = CONVERT(nvarchar(4000), SERVERPROPERTY('InstanceDefaultDataPath')),
        @baseLog nvarchar(4000) = CONVERT(nvarchar(4000), SERVERPROPERTY('InstanceDefaultLogPath'));
IF @baseDatos IS NULL OR @baseLog IS NULL THROW 50004, N'Comprueba las carpetas de datos y log de la instancia.', 1;
DECLARE @mdf nvarchar(4000) = @baseDatos + @nueva + N'.mdf',
        @ldf nvarchar(4000) = @baseLog + @nueva + N'_log.ldf';
RESTORE DATABASE @nueva FROM DISK = @archivo
    WITH MOVE @datos TO @mdf, MOVE @log TO @ldf, CHECKSUM, RECOVERY;
DECLARE @verificar nvarchar(max) = N'USE ' + QUOTENAME(@nueva) + N';
    IF OBJECT_ID(''dbo.juniors_version'',''U'') IS NULL THROW 50005, N''La copia recuperada carece del esquema de JuniorsControl.'', 1;
    DBCC CHECKDB WITH NO_INFOMSGS;
    SET XACT_ABORT ON;
    BEGIN TRANSACTION;
    DELETE FROM dbo.auth_sessions;
    DELETE FROM dbo.auth_invites;
    IF OBJECT_ID(''dbo.auth_password_resets'',''U'') IS NOT NULL EXEC(N''DELETE FROM dbo.auth_password_resets'');
    COMMIT;
    SELECT DB_NAME() AS base_recuperada, COUNT(*) AS cuentas FROM dbo.users;';
EXEC sys.sp_executesql @verificar;
