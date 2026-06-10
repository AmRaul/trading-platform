# Database Migrations

Migrations are applied automatically during CI/CD deployment.

## Quick Start

### Apply Migration Locally

```bash
# Specific migration
docker exec -i backtester_postgres psql -U backtester -d backtester < migrations/001_add_optimizer_tables.sql

# All migrations
for migration in migrations/*.sql; do
  docker exec -i backtester_postgres psql -U backtester -d backtester < "$migration"
done
```

### Create Backup

```bash
./backup-db.sh local   # Local database
./backup-db.sh prod    # Production database
```

### Restore from Backup

```bash
./restore-db.sh backups/backup_local_YYYYMMDD_HHMMSS.sql.gz local
```

## Migrations List

- **001_add_optimizer_tables.sql** - Add optimization_results table and is_optimizer_admin flag (2024-12-21)

## Creating New Migration

1. Find next number: `ls migrations/*.sql | tail -1`
2. Create file: `migrations/NNN_description.sql`
3. Write idempotent SQL (use `IF NOT EXISTS`)
4. Test locally (run twice to verify idempotency)
5. Commit to git - CI/CD will apply automatically

## Full Documentation

See [DATABASE_MIGRATIONS_GUIDE.md](../DATABASE_MIGRATIONS_GUIDE.md) for complete guide on:
- Writing migrations
- Backup/restore procedures
- Rollback strategies
- Troubleshooting
