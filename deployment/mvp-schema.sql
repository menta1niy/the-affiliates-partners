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
  created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS manual_assignments (
  telegram_id BIGINT NOT NULL REFERENCES users(id),
  offer_id TEXT NOT NULL REFERENCES manual_offers(id),
  stage TEXT NOT NULL DEFAULT 'assigned', note TEXT NOT NULL DEFAULT '',
  updated_at BIGINT NOT NULL, PRIMARY KEY(telegram_id,offer_id)
);
CREATE INDEX IF NOT EXISTS ix_manual_assignments_user ON manual_assignments(telegram_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.manual_offers, partners.manual_assignments TO "ta-partners";
COMMIT;
