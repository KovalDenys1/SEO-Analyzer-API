# wrapper-db

Postgres 16 and PostgREST for the seo-analyzer-web site (users, API keys, usage logs). The site talks to it with supabase-js, so its env is:

- `NEXT_PUBLIC_SUPABASE_URL` = `https://<SEO_API_HOST>` (Caddy sends `/rest/v1/*` to PostgREST)
- `SUPABASE_SERVICE_ROLE_KEY` = the service-role JWT below

## First start on the VM

```sh
cd /opt/seo-api/deploy/oracle/wrapper-db
python3 -c "import secrets as s; print(f'POSTGRES_PASSWORD={s.token_urlsafe(32)}\nAUTHENTICATOR_PASSWORD={s.token_urlsafe(32)}\nJWT_SECRET={s.token_urlsafe(48)}')" | sudo tee .env >/dev/null
sudo chmod 600 .env
sudo docker compose up -d
```

`init/` runs once, on an empty volume: the site's schema, then the roles. A schema change after that is applied by hand with `docker compose exec db psql -U postgres -d wrapper`.

## The service-role key

An HS256 JWT with the payload `{"role": "service_role"}`, signed with `JWT_SECRET`. On the VM it is kept in `service_role.jwt` (root, 0600). Rotating `JWT_SECRET` invalidates it, and the site's env then needs the new one plus a redeploy.

## Access

Postgres publishes no port. PostgREST listens on 127.0.0.1:3001 only. A request without the key runs as `anon`, which has no grants, and gets 401.
