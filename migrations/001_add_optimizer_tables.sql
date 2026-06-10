-- Migration: Add optimizer tables and columns
-- Created: 2024-12-21
-- Description: Add optimization_results table and is_optimizer_admin flag

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

-- Indexes for optimization_results
CREATE INDEX IF NOT EXISTS idx_optimization_task_id ON backtester.optimization_results(task_id);
CREATE INDEX IF NOT EXISTS idx_optimization_created ON backtester.optimization_results(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_optimization_status ON backtester.optimization_results(status);
CREATE INDEX IF NOT EXISTS idx_optimization_user ON backtester.optimization_results(user_id);
CREATE INDEX IF NOT EXISTS idx_optimization_best_params ON backtester.optimization_results USING GIN (best_params);
CREATE INDEX IF NOT EXISTS idx_optimization_all_trials ON backtester.optimization_results USING GIN (all_trials);

-- Add optimizer admin flag to bot_subscribers
ALTER TABLE market_data.bot_subscribers
ADD COLUMN IF NOT EXISTS is_optimizer_admin BOOLEAN DEFAULT FALSE;

-- Index for optimizer admins
CREATE INDEX IF NOT EXISTS idx_subscribers_optimizer_admin
ON market_data.bot_subscribers(is_optimizer_admin)
WHERE is_optimizer_admin = TRUE;

-- Success message
SELECT 'Migration 001 completed: optimizer tables and columns added' AS status;
