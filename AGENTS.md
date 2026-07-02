# ASTRA_Production Agent Notes

Before changing the remote oracle path, read:

- `C:\Users\Nelson\REMOTE_CLUSTER_GUIDE.md`
- `REMOTE_ORACLE_HANDOFF.md`
- `remote/README.md`

Do not print or commit secrets. `.env` may contain API keys and remote oracle
settings. Local passwords, if needed, live outside this repo in:

`C:\Users\Nelson\Documents\ASTRA Remote\astra_remote_secrets.local.txt`

Use the remote check script after touching executor/oracle code:

```powershell
.\remote\check_remote_oracle.ps1
```
