# 01 — Install from the README

**Status:** red
**Severity:** blocker

## What I tried

Followed the README literally on a fresh Hetzner VPS (IP 178.104.137.208):

```
curl -fsSL https://raw.githubusercontent.com/Philipp258/life-assistant/main/deploy/install.sh \
  | LIFE_ASSISTANT_REPO_URL=https://github.com/Philipp258/life-assistant.git bash
```

(`LIFE_ASSISTANT_REF=rev` added by release-test mechanics — not a
user-facing concern.)

## What broke

Two distinct failures, in order:

**Workarounds applied to keep the run going** (none of these are
fixes — the install path itself is what scenario 01 grades):

- Replaced apt's `python3.11`/`python3.11-venv` with a standalone
  `python-build-standalone` cpython-3.11.15.
- Bumped NodeSource from setup_20.x to setup_22.x.
- Switched certbot to the Let's Encrypt staging environment.
- Manually seeded the login password via `python -m app.users.set_password`
  because the env file was already created by an earlier failed run,
  so re-running install.sh did not re-seed.

### 1. README install URL 404 — repo was private

Initial `curl -fsSL https://raw.githubusercontent.com/.../install.sh`
returned `curl: (22) The requested URL returned error: 404`. The
`Philipp258/life-assistant` repo was private at the time the README
told the operator to fetch a public raw URL from it. A first-time
operator with no prior access cannot get past line 1 of the install
block.

Resolved out-of-band: operator made the repo public mid-run.

After fixing: `curl` returned 200, installer executed.

### 2. Let's Encrypt rate limit on sslip.io is a recurring blocker

After fixing the python issue, the installer reached the certbot step
and hit:

```
too many certificates (250000) already issued for "sslip.io" in the
last 168h0m0s, retry after 2026-05-24 07:19:46 UTC
```

This is the cert-per-registered-domain quota that Let's Encrypt
applies to the public-suffix wildcard sslip.io. It is **shared across
every sslip.io user worldwide** — when you happen to install during a
busy week, the install fails outright with no fallback. Waiting one
minute past the printed retry timestamp did not help (other users
immediately consume the freed quota).

Worked around by switching certbot to the Let's Encrypt staging
endpoint (`--staging`) for the rest of this run. Real installs cannot
do that.

Recommended fixes for the deploy:

- Detect the LE quota error from certbot and surface a clear "sslip.io
  is rate-limited right now, try again later or use --domain
  YOUR_OWN.tld" message instead of dumping certbot output and dying.
- Document an alternative IP-DNS service (e.g. nip.io) in
  `deploy/README.md` for when sslip.io is exhausted, so operators have
  a one-flag fallback.
- Optionally fall back to LE staging when the operator opts in.

### 3. Node.js 20 is now incompatible with the frontend dependencies

After the cert worked, the first build failed with:

```
ERR_PNPM_UNSUPPORTED_ENGINE
Your Node version is incompatible with
"vite-plugin-static-copy@4.1.0(vite@5.4.21(@types/node@25.6.0)
(lightningcss@1.32.0))".
Expected version: ^22.0.0 || >=24.0.0
Got: v20.20.2
```

`install.sh` hard-pins NodeSource setup_20.x, but the frontend
lockfile pulled in a dep that requires Node ≥22. Either the dep needs
to be pinned back, or `install.sh` needs to move to Node 22 (or 24
LTS). This will break every new install on `main` once it lands
there. Worked around by `sed`-bumping the nodesource version to 22
for the rest of this run.

### 4. Installer assumes Ubuntu 24.04; OS preflight missing

The VPS image was Ubuntu **26.04** ("Resolute Raccoon"). The README
says the supported target is Ubuntu 24.04, but the installer does not
check this — it goes straight into `apt-get install -y python3.11 ...`,
which fails on 26.04 because `python3.11` is not in the default repos:

```
==> system packages
E: Unable to locate package python3.11
E: Couldn't find any package by glob 'python3.11'
E: Couldn't find any package by regex 'python3.11'
E: Unable to locate package python3.11-venv
E: Couldn't find any package by glob 'python3.11-venv'
E: Couldn't find any package by regex 'python3.11-venv'
```

A naive operator who provisioned the wrong image gets three lines of
apt noise with no hint that the cause is OS version. A two-line
preflight check (`. /etc/os-release; [ "$VERSION_ID" = "24.04" ] || …`)
would have turned this into a clear error message instead of a
debugging session.

Worked around for the rest of the run by installing a standalone
Python 3.11 from python-build-standalone before re-running the
installer. That is not something a user should have to do.

## Rate

- **Time to a working install:** much longer than it should have been.
  Two unrelated bugs, both surfacing on the very first command.
- **Doc gaps:** none in the README itself, but two real gaps in the
  install script: no auth-failure message for the curl step, no
  OS-version preflight.
- **Anything fragile:** install.sh hard-codes a Python version that
  is one LTS behind whatever image a user might pick today. Either
  bump to the latest LTS Python, install Python via uv, or block on
  unsupported OS up front.

## Recommendations before shipping

1. Add an OS-version preflight at the top of `install.sh`:
   "Supported on Ubuntu 24.04. Detected: $VERSION_ID."
2. Either make the repo public, switch the README to a clone-based
   flow that fails gracefully on auth, or document a deploy-key path.
3. Consider letting `uv` manage Python so the installer is not pinned
   to a system package name that ages out.
