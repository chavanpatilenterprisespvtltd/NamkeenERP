-- V90.bf: Security session/device hardening and login-throttle persistence.
-- Runtime registration is idempotent; this migration records the PostgreSQL deployment contract.
CREATE TABLE IF NOT EXISTS security_devices (
  device_id varchar(64) PRIMARY KEY,
  user_id varchar(64) NOT NULL,
  device_code varchar(120) NOT NULL,
  device_name varchar(160) NOT NULL,
  platform varchar(40) NOT NULL DEFAULT 'ANDROID',
  fingerprint_hash varchar(128),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at timestamptz NULL,
  UNIQUE(user_id, device_code)
);
CREATE TABLE IF NOT EXISTS security_sessions (
  session_id varchar(64) PRIMARY KEY,
  user_id varchar(64) NOT NULL,
  token_digest char(64) NOT NULL UNIQUE,
  device_id varchar(64) NULL,
  ip_address varchar(64) NULL,
  user_agent text NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at timestamptz NOT NULL,
  last_seen_at timestamptz NULL,
  revoked_at timestamptz NULL,
  revoked_reason varchar(160) NULL
);
CREATE TABLE IF NOT EXISTS security_login_attempts (
  attempt_id varchar(64) PRIMARY KEY,
  username varchar(120) NOT NULL,
  ip_address varchar(64) NOT NULL,
  attempted_at timestamptz NOT NULL,
  success boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS ix_security_sessions_user_active ON security_sessions(user_id, revoked_at, expires_at);
CREATE INDEX IF NOT EXISTS ix_security_attempts_lookup ON security_login_attempts(username, ip_address, attempted_at);
