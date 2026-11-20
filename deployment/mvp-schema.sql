-- Idempotent standalone Partners MVP; run against the existing the_affiliates
-- PostgreSQL database as a schema owner BEFORE deploying the new API.
-- This creates only partners.* tables, never modifies CRM public data.
BEGIN;
SET LOCAL search_path TO partners, public;
CREATE TABLE IF NOT EXISTS manual_offers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  target_action TEXT NOT NULL, payout_rub INTEGER NOT NULL,
  hold_days INTEGER NOT NULL, instructions TEXT NOT NULL DEFAULT '',
  referral_url TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
  logo_hash TEXT NOT NULL DEFAULT '',
  lead_stages TEXT NOT NULL DEFAULT '["application_sent","meeting_scheduled","product_received"]',
  created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
);
ALTER TABLE manual_offers ADD COLUMN IF NOT EXISTS logo_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE manual_offers ADD COLUMN IF NOT EXISTS lead_stages TEXT NOT NULL
  DEFAULT '["application_sent","meeting_scheduled","product_received"]';
CREATE TABLE IF NOT EXISTS offer_logos (
  logo_hash TEXT PRIMARY KEY, image_data BYTEA NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS registration_profiles (
  telegram_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  birth_date TEXT NOT NULL,
  credit_cards INTEGER NOT NULL DEFAULT 0,
  installments INTEGER NOT NULL DEFAULT 0,
  loans INTEGER NOT NULL DEFAULT 0,
  mortgages INTEGER NOT NULL DEFAULT 0,
  consent_version TEXT NOT NULL,
  submitted_at BIGINT NOT NULL,
  credit_updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS participant_identities (
  telegram_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  full_name_encrypted TEXT NOT NULL,
  inn_encrypted TEXT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS manual_assignments (
  telegram_id BIGINT NOT NULL REFERENCES users(id),
  offer_id TEXT NOT NULL REFERENCES manual_offers(id),
  stage TEXT NOT NULL DEFAULT 'assigned', note TEXT NOT NULL DEFAULT '',
  updated_at BIGINT NOT NULL, PRIMARY KEY(telegram_id,offer_id)
);
CREATE INDEX IF NOT EXISTS ix_manual_assignments_user ON manual_assignments(telegram_id);
CREATE TABLE IF NOT EXISTS manual_offer_events (
  id TEXT PRIMARY KEY,
  telegram_id BIGINT NOT NULL REFERENCES users(id),
  offer_id TEXT NOT NULL REFERENCES manual_offers(id),
  kind TEXT NOT NULL, lead_stage TEXT NOT NULL DEFAULT '',
  proof_url TEXT NOT NULL DEFAULT '',
  evidence_data BYTEA, evidence_type TEXT NOT NULL DEFAULT '',
  review_status TEXT NOT NULL DEFAULT 'pending',
  review_note TEXT NOT NULL DEFAULT '',
  reviewed_by BIGINT REFERENCES users(id),
  created_at BIGINT NOT NULL, reviewed_at BIGINT
);
CREATE INDEX IF NOT EXISTS ix_manual_offer_events_user ON manual_offer_events(telegram_id,created_at);
CREATE INDEX IF NOT EXISTS ix_manual_offer_events_review ON manual_offer_events(review_status,created_at);
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.manual_offers, partners.manual_assignments, partners.offer_logos TO "ta-partners";
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.registration_profiles TO "ta-partners";
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.participant_identities TO "ta-partners";
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.manual_offer_events TO "ta-partners";
COMMIT;
