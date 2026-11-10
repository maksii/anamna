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
  `secret.key` beside the database, readable only by the server's user. It keys the stored hashes of
  one-time doctor codes and the device cookies that mark a browser as known. It encrypts nothing. If
  it is lost, outstanding doctor codes stop working and every browser is treated as new; nothing else
  is affected.
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
- Sign-in attempts are limited per account and per visitor. The limit is 20 failed sign-ins in 15
  minutes. A browser that has signed in to an account before holds a device cookie and is counted
  on its own, so somebody guessing an account's password cannot lock its owner out of a browser they
  already use. A new browser has to wait out the limit. Behind Cloudflare the visitor is taken from
  the `CF-Connecting-IP` header; behind another proxy every visitor shares one address, and the
  per-account limit is what bounds password guessing.
- A record can be shared only with an account that already exists on the server. Sign-up does not
  verify email addresses, so keep sign-up closed unless you trust everyone who can reach the form.
- AI requests sent through OpenRouter are routed only to providers that do not store or train on
  prompts. An administrator can lift that on the AI page; decide deliberately, because the text
  sent is medical.
- Access tokens of connected services (Paperless-ngx, Oura, Garmin, OpenWearables, laboratory
  accounts) are stored unencrypted in the database, because the server must present them. Treat the
  database and every backup of it as credentials: keep them encrypted, and if a copy leaks, revoke
  the tokens at each provider and change the laboratory passwords.
- A record can be shared read only or with full access. Full access lets the other account send the
  record to the AI provider through the assistant and place laboratory orders through the owner's
  laboratory account. Grant it only to people you would hand those to.
- Laboratory orders can be placed only from a signed-in browser session, never with a bearer token,
  and each order form can be submitted once.
- The supplied `compose.yaml` drops all Linux capabilities except the four the entrypoint needs
  (`CHOWN`, `SETUID`, `SETGID`, `DAC_OVERRIDE`), mounts the root filesystem read-only and limits the
  process count. If the container cannot take ownership of the data volume it stops, unless
  `ANAMNA_ALLOW_ROOT=1` is set.
- The server writes no access log. Application logs at the default level do not contain file names,
  document titles or the bodies of upstream error replies. Those appear only at `DEBUG` level, so do
  not run production at `ANAMNA_LOG_LEVEL=DEBUG`.
- A person can delete their own account and download their own record from the Profile page, under
  the security tab. Deleting needs the account's password and its address typed in full. An
  administrator can delete their own account only while another enabled administrator exists. The
  deletion removes the account's rows and the original document files that no other account uses.
  Device exports uploaded through the application are removed with the account. A folder an operator placed in `sources/` by hand and imported from the command line stays there for the operator to remove. The download is a ZIP of the account's original files
  and of CSV copies of its results, documents, vaccinations and device data. The ZIP is not encrypted,
  so keep it as protected as the database.
- Changing the sign-in email needs the account's current password. The new address must not belong to
  another account.
- Scripts: every page allows scripts only from the server itself or from inline scripts that carry the
  request's nonce (Content-Security-Policy `script-src 'self' 'nonce-…'`). No template uses
  inline event handler attributes such as `onclick` or `onsubmit`; the browser blocks them under this
  policy, so behaviour is attached from script files. Styles still allow inline `style` attributes. The policy is set by `CSP_STRICT_SCRIPTS`
  in `src/anamna/web/app.py`, which is on.
