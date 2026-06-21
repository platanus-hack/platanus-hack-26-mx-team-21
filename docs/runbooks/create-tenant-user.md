# Runbook — create a test user tied to an existing tenant

Adds an email/password user that can log in and is bound to a tenant with a role. Use for
ad-hoc test accounts (the standing dev users are seeded in `supabase/seed/20_auth.sql`).

## Identity chain

```
auth.users (id)
   └─ auth.identities (user_id, provider='email')      ← required for password login
   └─ platform.oidc_subjects (user_id → auth.users.id)
         └─ platform.tenant_memberships (subject_id → oidc_subjects.id, tenant_id, role)
```

Tenants: `select id, name from platform.tenants;`
(e.g. **CityCrawl CDMX** = `a0000000-0000-0000-0000-000000000001`).
Roles in use: `analysis_author` (full app), `viewer` (read-only).

## One-shot insert

Run via `psql` (local) or Supabase MCP `execute_sql` (remote). `pgcrypto` lives in the
`extensions` schema — qualify `extensions.crypt` / `extensions.gen_salt`.

```sql
do $$
declare
  v_user_id    uuid := gen_random_uuid();
  v_subject_id uuid := gen_random_uuid();
  v_tenant_id  uuid := 'a0000000-0000-0000-0000-000000000001';  -- target tenant
  v_email      text := 'tester@citycrawl.dev';
  v_password   text := 'change-me';
  v_name       text := 'Tester';
begin
  insert into auth.users (
    instance_id, id, aud, role, email, encrypted_password,
    email_confirmed_at, created_at, updated_at,
    raw_app_meta_data, raw_user_meta_data,
    -- ⚠️ token columns MUST be '' (not NULL) — see gotcha below
    confirmation_token, recovery_token, email_change,
    email_change_token_new, email_change_token_current,
    phone_change, phone_change_token, reauthentication_token
  ) values (
    '00000000-0000-0000-0000-000000000000', v_user_id, 'authenticated', 'authenticated',
    v_email, extensions.crypt(v_password, extensions.gen_salt('bf')),
    now(), now(), now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    jsonb_build_object('display_name', v_name),
    '', '', '', '', '', '', '', ''
  );

  insert into auth.identities (
    id, user_id, provider, provider_id, identity_data, last_sign_in_at, created_at, updated_at
  ) values (
    gen_random_uuid(), v_user_id, 'email', v_user_id::text,
    jsonb_build_object('sub', v_user_id::text, 'email', v_email, 'email_verified', true),
    now(), now(), now()
  );

  insert into platform.oidc_subjects (id, user_id, display_name, status)
  values (v_subject_id, v_user_id, v_name, 'active');

  insert into platform.tenant_memberships (tenant_id, subject_id, role)
  values (v_tenant_id, v_subject_id, 'analysis_author');
end $$;
```

## Verify

```sql
select u.email, m.role, t.name as tenant
from auth.users u
join auth.identities i on i.user_id=u.id and i.provider='email'
join platform.oidc_subjects o on o.user_id=u.id
join platform.tenant_memberships m on m.subject_id=o.id
join platform.tenants t on t.id=m.tenant_id
where u.email='tester@citycrawl.dev';
```

End-to-end (expect HTTP 200 + an `access_token`):
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  "https://joixzhdpnxqhnuscxsoy.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: <ANON_KEY>" -H "Content-Type: application/json" \
  -d '{"email":"tester@citycrawl.dev","password":"change-me"}'
```

## ⚠️ Gotcha — "Database error querying schema"

If login 500s with `{"code":500,"error_code":"unexpected_failure","msg":"Database error
querying schema"}` (the frontend renders this as an empty `{}` error), the auth row has
**NULL** token columns. GoTrue scans `confirmation_token`, `recovery_token`,
`email_change`, `email_change_token_new`, `email_change_token_current`, `phone_change`,
`phone_change_token`, `reauthentication_token` into non-nullable Go strings; NULL breaks
the scan only when that user is looked up. The insert above sets them to `''`. To fix an
already-broken user:

```sql
update auth.users set
  confirmation_token = coalesce(confirmation_token,''),
  recovery_token = coalesce(recovery_token,''),
  email_change = coalesce(email_change,''),
  email_change_token_new = coalesce(email_change_token_new,''),
  email_change_token_current = coalesce(email_change_token_current,''),
  phone_change = coalesce(phone_change,''),
  phone_change_token = coalesce(phone_change_token,''),
  reauthentication_token = coalesce(reauthentication_token,'')
where email = 'tester@citycrawl.dev';
```

> Note `auth.identities.email` is a **generated** column (derived from
> `identity_data->>'email'`) — to change a user's email, update `identity_data`, not `email`.
