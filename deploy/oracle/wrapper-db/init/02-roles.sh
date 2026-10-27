#!/bin/sh
# PostgREST logs in as authenticator and switches to the role named in the request's JWT:
# service_role for the site's server key, anon (no grants) for anything without one.
set -eu
psql -v ON_ERROR_STOP=1 -U postgres -d wrapper -v pw="$AUTHENTICATOR_PASSWORD" <<'SQL'
create role anon nologin;
create role service_role nologin bypassrls;
create role authenticator login noinherit password :'pw';
grant anon, service_role to authenticator;

grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
SQL
