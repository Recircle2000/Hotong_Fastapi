# GitHub Actions Deployment

## Workflow

- Pull request / push to `main`: backend test + frontend build
- Push to `main`: SSH deploy to server

## Required GitHub Secrets

- `DEPLOY_HOST`
- `DEPLOY_PORT`
- `DEPLOY_USER`
- `DEPLOY_PATH`
- `DEPLOY_SSH_KEY`
- `DEPLOY_KNOWN_HOSTS`

`DEPLOY_KNOWN_HOSTS` can be created with:

```bash
ssh-keyscan -H your-server-host
```

## Server Requirements

- Repository already cloned at `DEPLOY_PATH`
- Docker installed
- Docker Compose plugin or `docker-compose` installed
- `.env` present on server
- `certbot/` and `nginx/nginx.conf` ready on server

## Deploy Behavior

The deploy step runs `scripts/deploy_server.sh` on the server.

That script:

1. Builds `frontend-admin` with `node:22-alpine`
2. Copies the build output into `nginx/static/admin-v2/`
3. Runs `docker compose -f docker-compose.server.yml up -d --build`
