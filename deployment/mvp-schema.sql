-- Idempotent standalone Partners MVP; run against the existing the_affiliates
-- PostgreSQL database as a schema owner BEFORE deploying the new API.
-- This creates only partners.* tables, never modifies CRM public data.
BEGIN;
SET LOCAL search_path TO partners, public;
ALTER TABLE partners.users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE partners.users ADD CONSTRAINT users_role_check
  CHECK(role IN ('owner','admin','staff','referrer','lead','blogger'));
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
ALTER TABLE manual_offers ADD COLUMN IF NOT EXISTS deleted_at BIGINT NOT NULL DEFAULT 0;
ALTER TABLE manual_offers ADD COLUMN IF NOT EXISTS lead_stages TEXT NOT NULL
  DEFAULT '["application_sent","meeting_scheduled","product_received"]';
CREATE TABLE IF NOT EXISTS offer_logos (
  logo_hash TEXT PRIMARY KEY, image_data BYTEA NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_contacts (
  telegram_id BIGINT PRIMARY KEY,
  phone_number TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS finance_accruals (
  id TEXT PRIMARY KEY, telegram_id BIGINT NOT NULL REFERENCES users(id),
  offer_id TEXT NOT NULL REFERENCES manual_offers(id),
  amount_rub BIGINT NOT NULL CHECK(amount_rub>0),
  source_reference TEXT NOT NULL UNIQUE, note TEXT NOT NULL DEFAULT '',
  confirmed_by BIGINT NOT NULL REFERENCES users(id), created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_finance_accruals_user ON finance_accruals(telegram_id,created_at);
CREATE TABLE IF NOT EXISTS finance_withdrawals (
  id TEXT PRIMARY KEY,telegram_id BIGINT NOT NULL REFERENCES users(id),
  amount_rub BIGINT NOT NULL CHECK(amount_rub>0),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected','paid')),
  review_note TEXT NOT NULL DEFAULT '', payment_reference TEXT NOT NULL DEFAULT '',
  reviewed_by BIGINT REFERENCES users(id), created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_finance_withdrawals_user ON finance_withdrawals(telegram_id,created_at);
ALTER TABLE finance_withdrawals ADD COLUMN IF NOT EXISTS payout_details_encrypted TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_finance_withdrawals_status ON finance_withdrawals(status,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ix_finance_withdrawals_payment_ref
  ON finance_withdrawals(payment_reference) WHERE payment_reference!='';
CREATE TABLE IF NOT EXISTS referral_rewards (
  withdrawal_id TEXT PRIMARY KEY REFERENCES finance_withdrawals(id),
  referrer_id BIGINT NOT NULL REFERENCES users(id),
  referred_id BIGINT NOT NULL REFERENCES users(id),
  amount_kopeks BIGINT NOT NULL CHECK(amount_kopeks>0), created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_referral_rewards_referrer ON referral_rewards(referrer_id,created_at);
CREATE TABLE IF NOT EXISTS blogger_campaigns (
  blogger_uuid TEXT PRIMARY KEY REFERENCES crm_bloggers(blogger_uuid),
  telegram_id BIGINT NOT NULL UNIQUE REFERENCES users(id),
  fixed_rub BIGINT NOT NULL DEFAULT 0 CHECK(fixed_rub>=0),
  percent_bps INTEGER NOT NULL DEFAULT 0 CHECK(percent_bps BETWEEN 0 AND 10000),
  active INTEGER NOT NULL DEFAULT 1,created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS blogger_attributions (
  telegram_id BIGINT PRIMARY KEY REFERENCES users(id),
  blogger_uuid TEXT NOT NULL REFERENCES crm_bloggers(blogger_uuid),created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_blogger_attributions_uuid ON blogger_attributions(blogger_uuid,created_at);
CREATE TABLE IF NOT EXISTS blogger_rewards (
  id TEXT PRIMARY KEY,blogger_uuid TEXT NOT NULL REFERENCES blogger_campaigns(blogger_uuid),
  kind TEXT NOT NULL CHECK(kind IN ('fixed','percent')),
  source_reference TEXT NOT NULL UNIQUE,
  amount_kopeks BIGINT NOT NULL CHECK(amount_kopeks>0),
  status TEXT NOT NULL DEFAULT 'earned' CHECK(status IN ('earned','paid')),
  payment_reference TEXT NOT NULL DEFAULT '',created_at BIGINT NOT NULL,paid_at BIGINT
);
CREATE INDEX IF NOT EXISTS ix_blogger_rewards_uuid ON blogger_rewards(blogger_uuid,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ix_blogger_rewards_payment_ref
  ON blogger_rewards(payment_reference) WHERE payment_reference!='';
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.manual_offers, partners.manual_assignments, partners.offer_logos TO "ta-partners";
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.telegram_contacts TO "ta-partners";
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.manual_offer_events TO "ta-partners";
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.finance_accruals, partners.finance_withdrawals TO "ta-partners";
GRANT SELECT, INSERT, UPDATE, DELETE ON partners.referral_rewards, partners.blogger_campaigns,
  partners.blogger_attributions, partners.blogger_rewards TO "ta-partners";
COMMIT;
