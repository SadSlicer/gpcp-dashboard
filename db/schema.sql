-- ============================================================
-- GPCP Dashboard — Supabase Postgres schema
-- Multi-tenant: every domain row has user_id pointing to auth.users
-- Row-Level Security ensures each user sees ONLY their own data
-- ============================================================
--
-- TO INSTALL : open Supabase → SQL Editor → New query → paste this
-- whole file → click Run. Idempotent (safe to re-run on schema bumps).
--
-- Tables mirror the V15 sqlite schema 1:1, plus user_id + portfolio_id
-- composite keys so several users can each have several portfolios.
-- ============================================================

-- -------------------------------------------------------------
-- 1. User profile (1 row per auth.users — extended fields)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_user_profile (
    user_id     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name TEXT,
    is_admin    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE app_user_profile ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users can read their profile" ON app_user_profile
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "users can update their profile" ON app_user_profile
    FOR UPDATE USING (user_id = auth.uid());

-- Auto-create the profile row when a new auth user signs up
CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.app_user_profile (user_id, display_name)
    VALUES (NEW.id, NEW.email);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- -------------------------------------------------------------
-- 2. Portfolios — replaces portfolios/_registry.json
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolios (
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    id          TEXT NOT NULL,                          -- short slug, e.g. "GPCP", "TEST"
    name        TEXT NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'EUR',
    seed_from_workbook BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, id)
);

ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own portfolios" ON portfolios
    FOR ALL USING (user_id = auth.uid());

-- -------------------------------------------------------------
-- 3. Current portfolio selector — 1 row per user
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS current_portfolio (
    user_id      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL
);

ALTER TABLE current_portfolio ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own current_portfolio" ON current_portfolio
    FOR ALL USING (user_id = auth.uid());

-- -------------------------------------------------------------
-- 4. Holdings — registered assets per portfolio
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS holdings (
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL,
    asset        TEXT NOT NULL,
    isin         TEXT,
    fund         TEXT,
    fees         REAL DEFAULT 0,
    ticker       TEXT,
    added_at     TIMESTAMPTZ DEFAULT NOW(),
    currency     TEXT NOT NULL DEFAULT 'EUR',
    PRIMARY KEY (user_id, portfolio_id, asset)
);

ALTER TABLE holdings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own holdings" ON holdings
    FOR ALL USING (user_id = auth.uid());

-- -------------------------------------------------------------
-- 5. Prices — daily native-currency closes (adjusted)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prices (
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL,
    trade_date   DATE NOT NULL,
    asset        TEXT NOT NULL,
    price        REAL NOT NULL,
    PRIMARY KEY (user_id, portfolio_id, trade_date, asset)
);

ALTER TABLE prices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own prices" ON prices
    FOR ALL USING (user_id = auth.uid());

CREATE INDEX IF NOT EXISTS idx_prices_lookup ON prices(user_id, portfolio_id, asset, trade_date);

-- -------------------------------------------------------------
-- 6. Transactions — BUY / SELL / DEPOSIT / WITHDRAW
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL,
    trade_date   DATE NOT NULL,
    asset        TEXT NOT NULL,           -- 'Cash' for DEPOSIT/WITHDRAW
    isin         TEXT,
    txn_type     TEXT NOT NULL DEFAULT 'BUY',
    price        REAL,
    shares       REAL,
    amount_eur   REAL NOT NULL,            -- native-currency total
    currency     TEXT NOT NULL DEFAULT 'EUR'
);

ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own transactions" ON transactions
    FOR ALL USING (user_id = auth.uid());

CREATE INDEX IF NOT EXISTS idx_tx_lookup ON transactions(user_id, portfolio_id, trade_date);

-- -------------------------------------------------------------
-- 7. FX rates — cached Yahoo FX
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fx_rates (
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL,
    trade_date   DATE NOT NULL,
    pair         TEXT NOT NULL,             -- e.g. "USDEUR"
    rate         REAL NOT NULL,
    PRIMARY KEY (user_id, portfolio_id, trade_date, pair)
);

ALTER TABLE fx_rates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own fx_rates" ON fx_rates
    FOR ALL USING (user_id = auth.uid());

-- -------------------------------------------------------------
-- 8. Meta — inception date and other per-portfolio settings
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta (
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT,
    PRIMARY KEY (user_id, portfolio_id, key)
);

ALTER TABLE meta ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own meta" ON meta
    FOR ALL USING (user_id = auth.uid());

-- ============================================================
-- Admin promotion helper
-- After your first signup, run this in SQL Editor (replace email):
--   UPDATE app_user_profile SET is_admin = TRUE
--   WHERE user_id = (SELECT id FROM auth.users WHERE email = 'YOUR@EMAIL.COM');
-- ============================================================
