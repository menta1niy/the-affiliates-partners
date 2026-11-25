-- Run once against the Partners database as the schema owner, after backup.
-- Only the obsolete registration and identity tables are dropped.
BEGIN;
CREATE TABLE IF NOT EXISTS partners.telegram_contacts (
  telegram_id BIGINT PRIMARY KEY,
  phone_number TEXT NOT NULL,
  updated_at BIGINT NOT NULL
);
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.telegram_contacts TO "ta-partners";
DROP TABLE IF EXISTS partners.participant_identities;
DROP TABLE IF EXISTS partners.registration_profiles;
COMMIT;
