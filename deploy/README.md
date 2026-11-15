# Deploy

Pipeline: `.github/workflows/deploy.yml`. PR → tests + builds. Push to `main` → tests, push images to GHCR, deploy.

## 1. DNS
A-records → server IP: `@`, `signals`, `backtester`, `logs`.
On Cloudflare: proxy OFF (grey cloud) until certbot has issued certs, then SSL mode **Full (strict)**.

## 2. SSH key for GitHub Actions (on your machine)
```bash
ssh-keygen -t ed25519 -f ~/.ssh/trading_deploy -C github-actions -N ""
```

## 3. Bootstrap the server (once, as root)
```bash
scp -r deploy root@SERVER_IP:/root/
ssh root@SERVER_IP
DOMAIN=example.com LETSENCRYPT_EMAIL=you@mail.com \
DEPLOY_PUBKEY="$(cat trading_deploy.pub)" bash /root/deploy/bootstrap.sh
```
(paste the contents of `~/.ssh/trading_deploy.pub` into DEPLOY_PUBKEY)

## 4. GitHub → Settings → Environments → `production`
Variable: `DOMAIN` = `example.com`

Secrets:
| name | value |
|---|---|
| SSH_HOST | server IP |
| SSH_USER | `deploy` |
| SSH_KEY | contents of `~/.ssh/trading_deploy` (private) |
| DB_USER, DB_PASSWORD | main Postgres |
| SIGNALS_DB_USER, SIGNALS_DB_PASSWORD | signals Postgres |
| BACKTESTER_DB_PASSWORD | backtester Postgres |
| SECRET_KEY | JWT secret |
| ENCRYPTION_KEY | Fernet key — **must be the same as on the old server**, otherwise stored Bybit API keys can't be decrypted |
| ADMIN_USERNAME | admin login |
| GRAFANA_PASSWORD | Grafana admin |

Generate passwords with `openssl rand -hex 24` (no `'` characters).
When moving from the old server, reuse its DB/SECRET/ENCRYPTION values.

## 5. Migrate data from the old server
Stop bots in the UI first, then:
```bash
# old server
docker exec trading_postgres pg_dump -U <user> -Fc trading_db > trading.dump
docker exec trading_signals_db pg_dump -U <user> -Fc signals_db > signals.dump
# copy to new server, after the first deploy:
docker exec -i trading_postgres pg_restore -U <user> -d trading_db --clean --if-exists < trading.dump
docker exec -i trading_signals_db pg_restore -U <user> -d signals_db --clean --if-exists < signals.dump
docker compose restart backend signals
```
Then add the new server IP to the Bybit API-key whitelist.

## Rollback
Every image is also tagged `sha-<commit>`. Re-run the workflow for an older commit, or on the server
edit the `*_IMAGE` tags in `/opt/trading-platform/.env` and `docker compose up -d`.
