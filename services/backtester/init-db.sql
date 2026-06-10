-- PostgreSQL initialization script for Backtester + Market Analytics
-- This script creates two schemas: backtester (for backtest data) and market_data (for analytics)

-- ============================================================================
-- SCHEMA 1: backtester (Migration from SQLite)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS backtester;

-- Strategy configurations table
CREATE TABLE IF NOT EXISTS backtester.strategy_configs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    config_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_public BOOLEAN DEFAULT FALSE,
    author VARCHAR(100) DEFAULT 'user',
    tags TEXT[],
    performance_score NUMERIC(10,2) DEFAULT 0.0
);

-- Backtest history table
CREATE TABLE IF NOT EXISTS backtester.backtest_history (
    id SERIAL PRIMARY KEY,
    task_id UUID UNIQUE NOT NULL,
    symbol VARCHAR(50),
    timeframe VARCHAR(10),
    config_name VARCHAR(255),
    config_json JSONB NOT NULL,
    results_json JSONB,
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'error')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    total_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(5,2) DEFAULT 0.0,
    total_return NUMERIC(10,2) DEFAULT 0.0,
    max_drawdown NUMERIC(10,2) DEFAULT 0.0,
    sharpe_ratio NUMERIC(10,4) DEFAULT 0.0,
    order_type VARCHAR(10) DEFAULT 'long',
    start_date DATE,
    end_date DATE
);

-- Optimization results table
CREATE TABLE IF NOT EXISTS backtester.optimization_results (
    id SERIAL PRIMARY KEY,
    task_id UUID UNIQUE NOT NULL,
    symbol VARCHAR(50),
    timeframe VARCHAR(10),
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    n_trials INTEGER DEFAULT 100,
    optimization_metric VARCHAR(50) DEFAULT 'custom_score',
    best_params JSONB,
    best_score NUMERIC(12,4),
    best_config JSONB,
    best_results JSONB,
    all_trials JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_minutes NUMERIC(10,2),
    user_id VARCHAR(100)
);

-- Indexes for backtester schema
CREATE INDEX IF NOT EXISTS idx_backtest_task_id ON backtester.backtest_history(task_id);
CREATE INDEX IF NOT EXISTS idx_backtest_symbol ON backtester.backtest_history(symbol);
CREATE INDEX IF NOT EXISTS idx_backtest_created ON backtester.backtest_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_status ON backtester.backtest_history(status);
CREATE INDEX IF NOT EXISTS idx_strategy_name ON backtester.strategy_configs(name);
CREATE INDEX IF NOT EXISTS idx_strategy_updated ON backtester.strategy_configs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_optimization_task_id ON backtester.optimization_results(task_id);
CREATE INDEX IF NOT EXISTS idx_optimization_created ON backtester.optimization_results(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_optimization_status ON backtester.optimization_results(status);
CREATE INDEX IF NOT EXISTS idx_optimization_user ON backtester.optimization_results(user_id);

-- JSONB indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_backtest_config_json ON backtester.backtest_history USING GIN (config_json);
CREATE INDEX IF NOT EXISTS idx_backtest_results_json ON backtester.backtest_history USING GIN (results_json);
CREATE INDEX IF NOT EXISTS idx_strategy_config_json ON backtester.strategy_configs USING GIN (config_json);
CREATE INDEX IF NOT EXISTS idx_optimization_best_params ON backtester.optimization_results USING GIN (best_params);
CREATE INDEX IF NOT EXISTS idx_optimization_all_trials ON backtester.optimization_results USING GIN (all_trials);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION backtester.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for strategy_configs
CREATE TRIGGER update_strategy_configs_updated_at
    BEFORE UPDATE ON backtester.strategy_configs
    FOR EACH ROW
    EXECUTE FUNCTION backtester.update_updated_at_column();

-- ============================================================================
-- SCHEMA 2: market_data (New analytics data)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS market_data;

-- General metrics table (Fear & Greed, Altseason, BTC Dominance, etc.)
CREATE TABLE IF NOT EXISTS market_data.metrics (
    id SERIAL PRIMARY KEY,
    metric_type VARCHAR(50) NOT NULL,
    value NUMERIC,
    metadata JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(100),
    UNIQUE(metric_type, timestamp)
);

-- Market narrative table
CREATE TABLE IF NOT EXISTS market_data.market_narrative (
    id SERIAL PRIMARY KEY,
    narrative VARCHAR(50) NOT NULL CHECK (narrative IN ('Risk-on', 'Risk-off', 'Distribution', 'Accumulation', 'Uncertain')),
    components JSONB NOT NULL,
    confidence NUMERIC(3,2) CHECK (confidence >= 0 AND confidence <= 1),
    score INTEGER,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Macro indicators table (DXY, SPX, NASDAQ, US10Y, GOLD, etc.)
CREATE TABLE IF NOT EXISTS market_data.macro_indicators (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    value NUMERIC NOT NULL,
    change_1d NUMERIC,
    change_7d NUMERIC,
    direction VARCHAR(10) CHECK (direction IN ('up', 'down', 'neutral')),
    timestamp TIMESTAMPTZ NOT NULL,
    UNIQUE(symbol, timestamp)
);

-- Funding rates table (for top altcoins)
CREATE TABLE IF NOT EXISTS market_data.funding_rates (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    rate NUMERIC(10,8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    UNIQUE(exchange, symbol, timestamp)
);

-- Liquidations table
CREATE TABLE IF NOT EXISTS market_data.liquidations (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50),
    total_usd NUMERIC,
    long_usd NUMERIC,
    short_usd NUMERIC,
    long_pct NUMERIC(5,2),
    short_pct NUMERIC(5,2),
    top_symbols JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    period VARCHAR(10) DEFAULT '24h'
);

-- BTC key levels table
CREATE TABLE IF NOT EXISTS market_data.btc_levels (
    id SERIAL PRIMARY KEY,
    level_type VARCHAR(20) NOT NULL,  -- 'support', 'resistance', 'vwap', 'fibonacci'
    value NUMERIC NOT NULL,
    strength NUMERIC(3,2),  -- 0.00 - 1.00
    timestamp TIMESTAMPTZ NOT NULL,
    metadata JSONB
);

-- Volatility metrics table
CREATE TABLE IF NOT EXISTS market_data.volatility (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    atr NUMERIC,
    realized_vol NUMERIC,
    state VARCHAR(20),  -- 'compression', 'expansion', 'normal'
    timestamp TIMESTAMPTZ NOT NULL,
    UNIQUE(symbol, timestamp)
);

-- Indexes for market_data schema
CREATE INDEX IF NOT EXISTS idx_metrics_type_time ON market_data.metrics(metric_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_narrative_time ON market_data.market_narrative(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_narrative_type ON market_data.market_narrative(narrative);
CREATE INDEX IF NOT EXISTS idx_macro_symbol_time ON market_data.macro_indicators(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_funding_symbol_time ON market_data.funding_rates(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_funding_exchange_time ON market_data.funding_rates(exchange, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_liquidations_time ON market_data.liquidations(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_btc_levels_type ON market_data.btc_levels(level_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_volatility_symbol_time ON market_data.volatility(symbol, timestamp DESC);

-- JSONB indexes for flexible queries
CREATE INDEX IF NOT EXISTS idx_metrics_metadata ON market_data.metrics USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_narrative_components ON market_data.market_narrative USING GIN (components);
CREATE INDEX IF NOT EXISTS idx_liquidations_symbols ON market_data.liquidations USING GIN (top_symbols);

-- Views for easy access to latest data
CREATE OR REPLACE VIEW market_data.latest_metrics AS
SELECT DISTINCT ON (metric_type)
    metric_type,
    value,
    metadata,
    timestamp,
    source
FROM market_data.metrics
ORDER BY metric_type, timestamp DESC;

CREATE OR REPLACE VIEW market_data.latest_narrative AS
SELECT *
FROM market_data.market_narrative
ORDER BY timestamp DESC
LIMIT 1;

CREATE OR REPLACE VIEW market_data.latest_macro AS
SELECT DISTINCT ON (symbol)
    symbol,
    value,
    change_1d,
    change_7d,
    direction,
    timestamp
FROM market_data.macro_indicators
ORDER BY symbol, timestamp DESC;

-- Grant permissions (if needed for specific user)
-- GRANT ALL PRIVILEGES ON SCHEMA backtester TO backtester;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA backtester TO backtester;
-- GRANT ALL PRIVILEGES ON SCHEMA market_data TO backtester;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA market_data TO backtester;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA backtester TO backtester;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA market_data TO backtester;

-- Telegram bot subscribers table
CREATE TABLE IF NOT EXISTS market_data.bot_subscribers (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(100),
    first_name VARCHAR(100),
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    active BOOLEAN DEFAULT TRUE,
    timezone VARCHAR(50) DEFAULT 'UTC',
    notifications_enabled BOOLEAN DEFAULT TRUE,
    last_notification_at TIMESTAMPTZ,
    is_optimizer_admin BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_subscribers_user_id ON market_data.bot_subscribers(user_id);
CREATE INDEX IF NOT EXISTS idx_subscribers_active ON market_data.bot_subscribers(active) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS idx_subscribers_optimizer_admin ON market_data.bot_subscribers(is_optimizer_admin) WHERE is_optimizer_admin = TRUE;

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Database initialization complete!';
    RAISE NOTICE 'Created schemas: backtester, market_data';
    RAISE NOTICE 'Tables created in backtester: strategy_configs, backtest_history, optimization_results';
    RAISE NOTICE 'Tables created in market_data: metrics, market_narrative, macro_indicators, funding_rates, liquidations, btc_levels, volatility, bot_subscribers';
    RAISE NOTICE 'Added is_optimizer_admin flag to bot_subscribers table';
END $$;
