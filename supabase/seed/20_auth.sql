set search_path = public, extensions;

-- auth.users (email confirmed; bcrypt password). encrypted_password uses pgcrypto in extensions.
insert into auth.users
  (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
   raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
   confirmation_token, recovery_token, email_change_token_new, email_change)
values
  ('00000000-0000-0000-0000-000000000000','c0000000-0000-0000-0000-00000000000a','authenticated','authenticated','author.a@citycrawl.test',
     extensions.crypt('citycrawl-dev-2026!', extensions.gen_salt('bf')),'2026-06-01 00:00:00+00',
     '{"provider":"email","providers":["email"]}','{"display_name":"Author A"}','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','','','',''),
  ('00000000-0000-0000-0000-000000000000','c0000000-0000-0000-0000-00000000000b','authenticated','authenticated','viewer.a@citycrawl.test',
     extensions.crypt('citycrawl-dev-2026!', extensions.gen_salt('bf')),'2026-06-01 00:00:00+00',
     '{"provider":"email","providers":["email"]}','{"display_name":"Viewer A"}','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','','','',''),
  ('00000000-0000-0000-0000-000000000000','c0000000-0000-0000-0000-00000000000c','authenticated','authenticated','nomember@citycrawl.test',
     extensions.crypt('citycrawl-dev-2026!', extensions.gen_salt('bf')),'2026-06-01 00:00:00+00',
     '{"provider":"email","providers":["email"]}','{"display_name":"No Member"}','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','','','','')
on conflict (id) do nothing;

-- auth.identities (email provider; provider_id = user id for email logins)
insert into auth.identities
  (id, provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
values
  ('1de0000a-0000-0000-0000-00000000000a','c0000000-0000-0000-0000-00000000000a','c0000000-0000-0000-0000-00000000000a',
     '{"sub":"c0000000-0000-0000-0000-00000000000a","email":"author.a@citycrawl.test","email_verified":true}','email','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00'),
  ('1de0000b-0000-0000-0000-00000000000b','c0000000-0000-0000-0000-00000000000b','c0000000-0000-0000-0000-00000000000b',
     '{"sub":"c0000000-0000-0000-0000-00000000000b","email":"viewer.a@citycrawl.test","email_verified":true}','email','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00'),
  ('1de0000c-0000-0000-0000-00000000000c','c0000000-0000-0000-0000-00000000000c','c0000000-0000-0000-0000-00000000000c',
     '{"sub":"c0000000-0000-0000-0000-00000000000c","email":"nomember@citycrawl.test","email_verified":true}','email','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00')
on conflict (provider_id, provider) do nothing;

-- oidc_subjects bridge (issuer null => Supabase is the issuer)
insert into platform.oidc_subjects (id, user_id, display_name, status) values
  ('05000000-0000-0000-0000-00000000000a','c0000000-0000-0000-0000-00000000000a','Author A','active'),
  ('05000000-0000-0000-0000-00000000000b','c0000000-0000-0000-0000-00000000000b','Viewer A','active'),
  ('05000000-0000-0000-0000-00000000000c','c0000000-0000-0000-0000-00000000000c','No Member','active')
on conflict do nothing;

-- memberships (nomember intentionally has none)
insert into platform.tenant_memberships (tenant_id, subject_id, role) values
  ('a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','analysis_author'),
  ('a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000b','viewer')
on conflict do nothing;
