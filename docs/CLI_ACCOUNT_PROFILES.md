# ASTRA CLI account profiles

ASTRA can keep several authorized subscription identities for Codex, Claude
Code, and Antigravity `agy`, then switch one provider explicitly when its
weekly allowance or credit is unavailable. It never rotates accounts
automatically and never changes an account during a deliberative cycle.

The machine-local registry is outside Git at
`%LOCALAPPDATA%\astra\account_profiles\profiles.json` on Windows and under the
user configuration directory on macOS/Linux. It stores only profile labels,
configuration paths, and optional expected emails. OAuth credentials remain in
the provider-owned directories.

## First-time setup

Register the sessions already installed on the workstation:

```powershell
.\venv\Scripts\python.exe scripts\astra_accounts.py bootstrap --name primary
.\venv\Scripts\python.exe scripts\astra_accounts.py status
```

If the workstation already sets `CODEX_HOME` or `CLAUDE_CONFIG_DIR`, bootstrap
honors those paths. Use `bootstrap --name primary --refresh` after intentionally
changing either path.

Create an isolated second profile and authenticate each CLI once:

```powershell
.\venv\Scripts\python.exe scripts\astra_accounts.py add backup
.\venv\Scripts\python.exe scripts\astra_accounts.py login backup codex
.\venv\Scripts\python.exe scripts\astra_accounts.py login backup claude
.\venv\Scripts\python.exe scripts\astra_accounts.py login backup agy
```

Each login uses a separate provider home. Do not copy `auth.json`, OAuth JSON,
cookies, or keychain material between profiles or machines.
For isolated Codex profiles the manager selects Codex's documented file-backed
credential store inside that private `CODEX_HOME`; protect it like a password.

## Explicit switching

Switch only the provider that needs another authorized account:

```powershell
.\venv\Scripts\python.exe scripts\astra_accounts.py use backup --provider codex
```

Or switch all three after all three have been authenticated:

```powershell
.\venv\Scripts\python.exe scripts\astra_accounts.py use backup --provider all
```

The command refuses to switch if a deliberative cycle is active. Every later
ASTRA CLI subprocess reads the current selection dynamically, so an MCP restart
is not required for ordinary profile changes after this code version is loaded.
Cycle output records `cli_account_profiles` alongside the model actually used.

This changes ASTRA's child CLI processes. It does not silently change the
account of an already-running Codex Desktop, Claude Desktop, or Antigravity UI.

An already authenticated provider home can be attached explicitly, with an
identity check before the registry changes:

```powershell
.\venv\Scripts\python.exe scripts\astra_accounts.py configure primary codex C:\Users\me\.codex-work --email me@company.com
.\venv\Scripts\python.exe scripts\astra_accounts.py verify
```

If a CLI reports that it is authenticated but no longer exposes its email, a
user may record an explicit manual check with `confirm`; the registry labels
that evidence as manual rather than presenting it as CLI-derived.

## When a weekly limit is what stopped the cycle

A subscription limit is **account-wide, not per model**. When Claude Code
answers `You've hit your weekly limit`, every rung of `ASTRA_CLAUDE_MODELS`
answers the same way, so the model ladder cannot rescue the phase and the cycle
reports `CUOTA AGOTADA en toda la escalera`. Descending from Opus to Sonnet is
not a workaround; another authorized account is.

Two routes out, in order of cost:

1. Skip the phase that needs the exhausted provider. If the caller writes the
   validation script itself, `astra_execute` / `astra_cluster_submit` runs it
   through the oracle without consuming any CLI subscription.
2. Switch that one provider to another registered profile, then switch back:

```powershell
.\venv\Scripts\python.exe scripts\astra_accounts.py use backup --provider claude
.\venv\Scripts\python.exe scripts\astra_accounts.py use primary --provider claude
```

To prepare the second route before it is needed, authenticate the other account
in an **isolated** configuration directory — never by running `/login` against
the default one, which replaces the credentials of the account already there:

```powershell
$env:CLAUDE_CONFIG_DIR = "C:\Users\me\.claude-backup"; claude   # then /login
.\venv\Scripts\python.exe scripts\astra_accounts.py add backup
.\venv\Scripts\python.exe scripts\astra_accounts.py configure backup claude C:\Users\me\.claude-backup --email other@example.com
```

`configure` verifies the real identity of that home before recording it, so it
doubles as a check that stored credentials are still alive.
