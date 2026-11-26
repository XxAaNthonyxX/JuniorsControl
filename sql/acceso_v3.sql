ALTER TABLE dbo.auth_invites ADD attempts tinyint NOT NULL DEFAULT 0;
CREATE TABLE dbo.auth_password_resets (
    user_id bigint PRIMARY KEY REFERENCES dbo.users(id),
    digest varbinary(32) NOT NULL,
    expires_at bigint NOT NULL,
    attempts tinyint NOT NULL DEFAULT 0
);
UPDATE dbo.juniors_version SET version=3 WHERE version=2;
