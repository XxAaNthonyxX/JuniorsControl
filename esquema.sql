-- Ejecutar en una base exclusiva para JuniorsControl.
IF OBJECT_ID(N'dbo.users',N'U') IS NULL
CREATE TABLE dbo.users (
            id bigint IDENTITY(1,1) PRIMARY KEY,
            name nvarchar(140) NOT NULL,
            email nvarchar(254) NOT NULL UNIQUE,
            username nvarchar(40) NULL,
            deleted bit NOT NULL DEFAULT 0,
            role nvarchar(255) NOT NULL CHECK(role IN ('admin','atencion','caja','area','recepcion')),
            area nvarchar(255) NOT NULL DEFAULT '',
            active bigint NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            salt varbinary(32) NOT NULL,
            digest varbinary(32) NOT NULL,
            rounds bigint NOT NULL
        );
GO
IF OBJECT_ID(N'dbo.auth_sessions',N'U') IS NULL
CREATE TABLE dbo.auth_sessions (
            digest varbinary(32) PRIMARY KEY,
            user_id bigint NOT NULL REFERENCES users(id),
            expires_at bigint NOT NULL
        );
GO
IF OBJECT_ID(N'dbo.auth_invites',N'U') IS NULL
CREATE TABLE dbo.auth_invites (
            email nvarchar(254) PRIMARY KEY,
            role nvarchar(255) NOT NULL,
            area nvarchar(255) NOT NULL,
            digest varbinary(32) NOT NULL,
            expires_at bigint NOT NULL
        );
GO
IF OBJECT_ID(N'dbo.auth_smtp',N'U') IS NULL
CREATE TABLE dbo.auth_smtp (
            id bigint PRIMARY KEY CHECK(id=1),
            email nvarchar(254) NOT NULL,
            protected varbinary(max) NOT NULL
        );
GO
IF OBJECT_ID(N'dbo.inv_items',N'U') IS NULL
CREATE TABLE dbo.inv_items (
 id bigint PRIMARY KEY, code nvarchar(32) NOT NULL UNIQUE,
 name nvarchar(140) NOT NULL, category nvarchar(255) NOT NULL, area nvarchar(255) NOT NULL, unit nvarchar(255) NOT NULL,
 min_qty bigint NOT NULL CHECK(min_qty>=0), warn_days bigint NOT NULL CHECK(warn_days>=0),
 perishable bigint NOT NULL CHECK(perishable IN(0,1)), transformable bigint NOT NULL CHECK(transformable IN(0,1)));
GO
IF OBJECT_ID(N'dbo.inv_lots',N'U') IS NULL
CREATE TABLE dbo.inv_lots (
 id bigint IDENTITY(1,1) PRIMARY KEY, item_id bigint NOT NULL REFERENCES inv_items(id), expiry nvarchar(10),
 physical bigint NOT NULL DEFAULT 0 CHECK(physical>=0), reserved bigint NOT NULL DEFAULT 0, CHECK(reserved>=0 AND reserved<=physical));
GO
IF OBJECT_ID(N'dbo.inv_moves',N'U') IS NULL
CREATE TABLE dbo.inv_moves (
 id bigint IDENTITY(1,1) PRIMARY KEY, at nvarchar(32) NOT NULL, lot_id bigint NOT NULL REFERENCES inv_lots(id),
 delta bigint NOT NULL CHECK(delta!=0), reason nvarchar(640) NOT NULL, ref nvarchar(512) NOT NULL, operator nvarchar(255) NOT NULL, user_id bigint NOT NULL);
GO
IF OBJECT_ID(N'dbo.inv_products',N'U') IS NULL
CREATE TABLE dbo.inv_products (
 id bigint IDENTITY(1,1) PRIMARY KEY, name nvarchar(140) NOT NULL UNIQUE, category nvarchar(255) NOT NULL, price bigint NOT NULL CHECK(price>0));
GO
IF OBJECT_ID(N'dbo.inv_recipes',N'U') IS NULL
CREATE TABLE dbo.inv_recipes (
 product_id bigint NOT NULL REFERENCES inv_products(id),item_id bigint NOT NULL REFERENCES inv_items(id),
 amount bigint NOT NULL CHECK(amount>0),PRIMARY KEY(product_id,item_id));
GO
IF OBJECT_ID(N'dbo.inv_rules',N'U') IS NULL
CREATE TABLE dbo.inv_rules (
 id bigint IDENTITY(1,1) PRIMARY KEY, source_id bigint NOT NULL REFERENCES inv_items(id), source_qty bigint NOT NULL CHECK(source_qty>0),
 target_id bigint NOT NULL REFERENCES inv_items(id), target_qty bigint NOT NULL CHECK(target_qty>0),
 UNIQUE(source_id,target_id),CHECK(source_id!=target_id));
GO
IF OBJECT_ID(N'dbo.inv_orders',N'U') IS NULL
CREATE TABLE dbo.inv_orders (
 id bigint IDENTITY(1,1) PRIMARY KEY, table_name nvarchar(255) NOT NULL, status nvarchar(255) NOT NULL, created nvarchar(255) NOT NULL,
 operator nvarchar(255) NOT NULL, user_id bigint NOT NULL, paid_at nvarchar(255), cashier nvarchar(255), version bigint NOT NULL DEFAULT 1,
 day nvarchar(10) NOT NULL, number bigint NOT NULL CHECK(number>0), UNIQUE(day,number));
GO
IF OBJECT_ID(N'dbo.inv_lines',N'U') IS NULL
CREATE TABLE dbo.inv_lines (
 order_id bigint NOT NULL REFERENCES inv_orders(id), product_id bigint NOT NULL REFERENCES inv_products(id),
 name nvarchar(140) NOT NULL, qty bigint NOT NULL CHECK(qty>0), price bigint NOT NULL CHECK(price>0),
 refunded bigint NOT NULL DEFAULT 0,PRIMARY KEY(order_id,product_id), CHECK(refunded BETWEEN 0 AND qty));
GO
IF OBJECT_ID(N'dbo.inv_line_recipes',N'U') IS NULL
CREATE TABLE dbo.inv_line_recipes (
 order_id bigint NOT NULL, product_id bigint NOT NULL, item_id bigint NOT NULL REFERENCES inv_items(id),
 amount bigint NOT NULL CHECK(amount>0), PRIMARY KEY(order_id,product_id,item_id),
 FOREIGN KEY(order_id,product_id) REFERENCES inv_lines(order_id,product_id) ON DELETE CASCADE);
GO
IF OBJECT_ID(N'dbo.inv_alloc',N'U') IS NULL
CREATE TABLE dbo.inv_alloc (
 order_id bigint NOT NULL, product_id bigint NOT NULL, lot_id bigint NOT NULL REFERENCES inv_lots(id),
 amount bigint NOT NULL CHECK(amount>0), processed bigint NOT NULL DEFAULT 0,
 PRIMARY KEY(order_id,product_id,lot_id),FOREIGN KEY(order_id,product_id) REFERENCES inv_lines(order_id,product_id), CHECK(processed BETWEEN 0 AND amount));
GO
IF OBJECT_ID(N'dbo.inv_events',N'U') IS NULL
CREATE TABLE dbo.inv_events (
 id bigint IDENTITY(1,1) PRIMARY KEY, order_id bigint NOT NULL REFERENCES inv_orders(id), at nvarchar(32) NOT NULL, action nvarchar(255) NOT NULL,
 reason nvarchar(640) NOT NULL, user_id bigint NOT NULL, operator nvarchar(255) NOT NULL);
GO
IF OBJECT_ID(N'dbo.inv_sales',N'U') IS NULL
CREATE TABLE dbo.inv_sales (
 id bigint IDENTITY(1,1) PRIMARY KEY,order_id bigint NOT NULL UNIQUE REFERENCES inv_orders(id));
GO
IF OBJECT_ID(N'dbo.inv_returns',N'U') IS NULL
CREATE TABLE dbo.inv_returns (
 id bigint IDENTITY(1,1) PRIMARY KEY,order_id bigint NOT NULL,product_id bigint NOT NULL,qty bigint NOT NULL CHECK(qty>0),
 reason nvarchar(640) NOT NULL,at nvarchar(32) NOT NULL,operator nvarchar(255) NOT NULL,
 FOREIGN KEY(order_id,product_id) REFERENCES inv_lines(order_id,product_id));
GO
IF OBJECT_ID(N'dbo.inv_exchanges',N'U') IS NULL
CREATE TABLE dbo.inv_exchanges (
 id bigint IDENTITY(1,1) PRIMARY KEY,return_id bigint NOT NULL UNIQUE REFERENCES inv_returns(id),
 replacement_sale_id bigint NOT NULL UNIQUE REFERENCES inv_sales(id),
 difference_cents bigint NOT NULL);
GO
IF OBJECT_ID(N'dbo.inv_seed',N'U') IS NULL
CREATE TABLE dbo.inv_seed (id bigint PRIMARY KEY);
GO
IF OBJECT_ID(N'dbo.g_settings',N'U') IS NULL
CREATE TABLE dbo.g_settings(
        id bigint PRIMARY KEY CHECK(id=1), run_time nvarchar(255) NOT NULL,
        opening_cents bigint NOT NULL CHECK(opening_cents>=0));
GO
IF OBJECT_ID(N'dbo.g_purchases',N'U') IS NULL
CREATE TABLE dbo.g_purchases(
        id bigint IDENTITY(1,1) PRIMARY KEY, origin nvarchar(255) NOT NULL, created nvarchar(255) NOT NULL, actor nvarchar(255) NOT NULL,
        supplier nvarchar(255) NOT NULL, assignee_id bigint REFERENCES users(id),
        status nvarchar(255) NOT NULL CHECK(status IN ('Borrador','Aprobada','Rechazada','Enviada','Recibida')),
        reviewed_at nvarchar(255), reviewer nvarchar(255), sent_at nvarchar(255), sender nvarchar(255), version bigint NOT NULL DEFAULT 1);
GO
IF OBJECT_ID(N'dbo.g_lines',N'U') IS NULL
CREATE TABLE dbo.g_lines(
        id bigint IDENTITY(1,1) PRIMARY KEY, purchase_id bigint NOT NULL REFERENCES g_purchases(id),
        item_id bigint NOT NULL REFERENCES inv_items(id), qty_m bigint NOT NULL CHECK(qty_m>0),
        unit_cents bigint NOT NULL CHECK(unit_cents>=0), UNIQUE(purchase_id,item_id));
GO
IF OBJECT_ID(N'dbo.g_receipts',N'U') IS NULL
CREATE TABLE dbo.g_receipts(
        id bigint IDENTITY(1,1) PRIMARY KEY, item_id bigint NOT NULL REFERENCES inv_items(id),
        line_id bigint REFERENCES g_lines(id), supplier nvarchar(255) NOT NULL,
        qty_m bigint NOT NULL CHECK(qty_m>0), unit_cents bigint NOT NULL CHECK(unit_cents>=0),
        approved_m bigint, reason nvarchar(640) NOT NULL DEFAULT '',
        created nvarchar(255) NOT NULL, actor nvarchar(255) NOT NULL, reviewed_at nvarchar(255), reviewer nvarchar(255),
        lot_id bigint REFERENCES inv_lots(id),
        received_m bigint, CHECK(approved_m BETWEEN 0 AND qty_m), CHECK(received_m>=0 AND received_m>=approved_m));
GO
IF OBJECT_ID(N'dbo.g_incidents',N'U') IS NULL
CREATE TABLE dbo.g_incidents(
        id bigint IDENTITY(1,1) PRIMARY KEY, receipt_id bigint NOT NULL UNIQUE REFERENCES g_receipts(id),
        created nvarchar(255) NOT NULL, resolution nvarchar(640), closed nvarchar(255), closer nvarchar(255));
GO
IF OBJECT_ID(N'dbo.g_wastes',N'U') IS NULL
CREATE TABLE dbo.g_wastes(
        id bigint IDENTITY(1,1) PRIMARY KEY, item_id bigint NOT NULL REFERENCES inv_items(id),
        lot_id bigint REFERENCES inv_lots(id), qty_m bigint NOT NULL CHECK(qty_m>0),
        reason nvarchar(640) NOT NULL, created nvarchar(255) NOT NULL, actor nvarchar(255) NOT NULL,
        status nvarchar(255) NOT NULL CHECK(status IN ('Pendiente','Aprobada','Rechazada')),
        reviewed_at nvarchar(255), reviewer nvarchar(255), occurred_on nvarchar(255));
GO
IF OBJECT_ID(N'dbo.g_alerts',N'U') IS NULL
CREATE TABLE dbo.g_alerts(
        id bigint IDENTITY(1,1) PRIMARY KEY, event_key nvarchar(128) NOT NULL, kind nvarchar(255) NOT NULL,
        item_id bigint NOT NULL REFERENCES inv_items(id), message nvarchar(640) NOT NULL,
        created nvarchar(255) NOT NULL, closed nvarchar(255));
GO
IF OBJECT_ID(N'dbo.g_reports',N'U') IS NULL
CREATE TABLE dbo.g_reports(
        id bigint IDENTITY(1,1) PRIMARY KEY, day nvarchar(10) NOT NULL, created nvarchar(255) NOT NULL, scheduled bigint NOT NULL,
        purchase_id bigint REFERENCES g_purchases(id));
GO
IF OBJECT_ID(N'dbo.g_shortage',N'U') IS NULL
CREATE TABLE dbo.g_shortage(
        report_id bigint NOT NULL REFERENCES g_reports(id), item_id bigint NOT NULL REFERENCES inv_items(id),
        available_m bigint NOT NULL, minimum_m bigint NOT NULL, suggested_m bigint NOT NULL,
        PRIMARY KEY(report_id,item_id));
GO
IF OBJECT_ID(N'dbo.operaciones',N'U') IS NULL
CREATE TABLE dbo.operaciones (
                      usuario bigint NOT NULL, clave nvarchar(80) NOT NULL, huella nvarchar(255) NOT NULL,
                      resultado nvarchar(max) NOT NULL, PRIMARY KEY(usuario,clave));
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'auth_sessions_user' AND object_id=OBJECT_ID(N'dbo.auth_sessions'))
CREATE INDEX auth_sessions_user ON dbo.auth_sessions(user_id);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'inv_by_item' AND object_id=OBJECT_ID(N'dbo.inv_lots'))
CREATE INDEX inv_by_item ON dbo.inv_lots(item_id,expiry,id);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'inv_by_time' AND object_id=OBJECT_ID(N'dbo.inv_moves'))
CREATE INDEX inv_by_time ON dbo.inv_moves(at,id);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'inv_alloc_lot' AND object_id=OBJECT_ID(N'dbo.inv_alloc'))
CREATE INDEX inv_alloc_lot ON dbo.inv_alloc(lot_id);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'inv_returns_order' AND object_id=OBJECT_ID(N'dbo.inv_returns'))
CREATE INDEX inv_returns_order ON dbo.inv_returns(order_id);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'ix_g_alert_live' AND object_id=OBJECT_ID(N'dbo.g_alerts'))
CREATE UNIQUE INDEX ix_g_alert_live ON dbo.g_alerts(event_key) WHERE closed IS NULL;
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'ix_g_report_day' AND object_id=OBJECT_ID(N'dbo.g_reports'))
CREATE UNIQUE INDEX ix_g_report_day ON dbo.g_reports(day) WHERE scheduled=1;
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'ix_g_receipt_item' AND object_id=OBJECT_ID(N'dbo.g_receipts'))
CREATE INDEX ix_g_receipt_item ON dbo.g_receipts(item_id,id);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name=N'ix_g_lines_purchase' AND object_id=OBJECT_ID(N'dbo.g_lines'))
CREATE INDEX ix_g_lines_purchase ON dbo.g_lines(purchase_id);
GO
IF OBJECT_ID(N'dbo.inv_move_context',N'U') IS NULL
CREATE TABLE dbo.inv_move_context(move_id bigint PRIMARY KEY REFERENCES inv_moves(id),area nvarchar(255) NOT NULL,item_name nvarchar(255) NOT NULL);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='ux_receipt_line' AND object_id=OBJECT_ID('dbo.g_receipts')) CREATE UNIQUE INDEX ux_receipt_line ON dbo.g_receipts(line_id) WHERE line_id IS NOT NULL;
GO
IF NOT EXISTS(SELECT 1 FROM dbo.g_settings WHERE id=1) INSERT INTO dbo.g_settings VALUES(1,'18:00',0);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='ux_users_username' AND object_id=OBJECT_ID('dbo.users'))
CREATE UNIQUE INDEX ux_users_username ON dbo.users(username) WHERE username IS NOT NULL;
GO
IF OBJECT_ID('dbo.juniors_version','U') IS NULL BEGIN CREATE TABLE dbo.juniors_version(version int PRIMARY KEY); INSERT INTO dbo.juniors_version VALUES(2); END;
