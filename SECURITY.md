# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub security advisories:
open https://github.com/maksii/anamna/security/advisories/new (the **Report a vulnerability**
button on the repository's Security tab). Do not open a public issue, pull request or discussion
for a security problem.

Include what you found, how to reproduce it, and what an attacker could reach. Never attach real
health records; use synthetic documents and test accounts. You will get an acknowledgement, and a
fix is coordinated in the advisory before anything is disclosed.

## Supported versions

Only the `main` branch, and the `ghcr.io/maksii/anamna:latest` image built from it, receive
security fixes. There are no maintained release branches.

## Deploying safely

Anamna stores personal health information. Treat every installation as sensitive:

- Serve it only over TLS, behind a reverse proxy or tunnel you control, and set
  `ANAMNA_SECURE_COOKIES=1` when TLS terminates in front of the app.
- `ANAMNA_SECRET` is optional. Without it a random secret is generated on first start and stored as
  `secret.key` beside the database, readable only by the server's user. Protect it and back it up
  with the database.
- Do not expose a fresh installation to the internet before finishing `/setup`; the one-time setup
  code in the server log is what keeps a stranger from claiming it. Keep sign-up closed unless you
  mean to open it.
- Consider an additional authentication layer (VPN, SSO proxy or access gateway) in front of an
  internet-reachable instance.
- Keep the database and `sources/` directory on encrypted storage, back them up, and protect the
  backups as health data.
- Bearer tokens (`anamna_agent_`, `anamna_api_`, `anamna_guest_`) are credentials: give guests an
  expiry, and revoke tokens you no longer use from `/profile` or `/admin/tokens`.
- Optional integrations (AI providers, Telegram, Paperless-ngx, OpenWearables, lab accounts) send
  data to the services you configure. Enable only the ones you trust with that data.
- The container runs the server as an unprivileged user (uid 10001). It starts as root only to take
  ownership of the data volume, then drops privileges. Start it with `--user` to skip that step when
  the volume is already owned by the user you choose.
- Sign-in attempts are limited per account and per visitor. Behind Cloudflare the visitor is taken
  from the `CF-Connecting-IP` header; behind another proxy every visitor shares one address, and the
  per-account limit is what bounds password guessing.
- A record can be shared only with an account that already exists on the server. Sign-up does not
  verify email addresses, so keep sign-up closed unless you trust everyone who can reach the form.
- AI requests sent through OpenRouter are routed only to providers that do not store or train on
  prompts. An administrator can lift that on the AI page; decide deliberately, because the text
  sent is medical.
