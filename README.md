# Based Deobfuscator

Discord bot (discord.py 2.x) that analyzes Lua/Luau scripts, detects obfuscation patterns, and runs them through a modular engine system — including **your own desktop deobfuscator** via a configurable local adapter.

## 1. Requirements

- Python 3.12+
- A Discord application + bot token (see below)

## 2. Create the Discord bot

1. Go to https://discord.com/developers/applications → New Application.
2. Bot → Add Bot → copy token. **Never commit it.**
3. OAuth2 → URL Generator → scopes `bot` + `applications.commands` → invite to your test server.
4. No privileged intents needed (default intents only).

## 3. Configure

```powershell
cd based-deobfuscator
Copy-Item .env.example .env
notepad .env
```

Fill in `DISCORD_TOKEN`, `DISCORD_GUILD_ID` (test server, for fast slash-command sync), `ADMIN_USER_IDS`.

## 4. Install & run (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python bot.py
```

Linux alternative:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Slash commands sync automatically on startup (per-guild if `DISCORD_GUILD_ID` is set, else global which can take ~1h to propagate).

## 5. Configure your desktop deobfuscator

1. Inspect the tool on your Desktop: find its `.exe`/script, run `--help` / `--version`, read its README, and note:
   - input-file flag, output-file flag, extra flags, working dir, timeout.
2. Open `engines.yaml` → `local_desktop` section and fill in:
   `exe_path`, `working_dir`, `input_arg`, `output_arg`, `extra_args`, `health_check_args`.
3. Restart the bot and run `/engines` — the Local Engine must show **Available** before use.
4. Test standalone first:
   ```powershell
   & "C:\path\to\tool.exe" --input sample.lua --output out.lua
   ```
   If the tool is **GUI-only** with no CLI, it cannot run headless — the bot will mark it unavailable (this is by design, not a bug).

> The bot never assumes your Desktop path exists on another machine. `exe_path` must be valid **on the machine hosting the bot**.

## 6. Open-source engines

No third-party engine is bundled as "supported" without verification. Policy:

1. Candidate must be a real deobfuscator (not a formatter/obfuscator), with repo + license + README reviewed.
2. Pin a tested release/commit in `engines.yaml` + document install steps.
3. Add an adapter under `engines/adapters/`, add sample tests, keep it `enabled: false` until green.
4. Never auto-download/execute repos at runtime — installation is an explicit admin action.

The only engine enabled out of the box is `bundled_prettify` (pure-Python normalizer for plain/minified Lua). It honestly **fails** on VM/loader-style input instead of faking success.

## 7. Usage

- `/deobfuscate method:url url:<https link to .lua>` — HTTPS only, SSRF-guarded, size/timeout-limited, HTML rejected.
- `/deobfuscate method:file file:<attach .lua/.luau/.txt>`
- `/deobfuscate method:raw code:<small snippet>` (>6000 chars → asked to upload a file)
- `/analyze`, `/engines`, `/job`, `/cancel`, `/history`, `/help`, `/privacy`, `/admin status|engines|config`

## 8. Test

```powershell
python -m pytest -q
python demo.py
```

`demo.py` runs the analyzer + bundled engine end-to-end on harmless fixtures without Discord.

## 9. Concurrency / privacy / limits

- `MAX_CONCURRENT_JOBS`, `MAX_JOBS_PER_USER`, `JOB_TIMEOUT_SECONDS` in `.env`.
- Temp dirs per job under `temp/` (auto-deleted); logs in `logs/` (rotating, secrets redacted).
- `ENABLE_JOB_HISTORY=false` by default — only minimal metadata (no source) is stored when enabled.
- Submitted code is **never executed** by the bot; engines run as subprocesses with arg arrays (no shell), timeouts, and isolated temp dirs. Sandboxing is best-effort — treat outputs as untrusted.

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `DISCORD_TOKEN missing` | Copy `.env.example` → `.env`, fill token |
| Commands don't appear | Set `DISCORD_GUILD_ID` for instant guild sync; global sync is slow |
| Local Engine unavailable | Fill `exe_path` in `engines.yaml`, verify path on bot host, check `logs/based.log` |
| `Output is identical to input` | Engine couldn't demonstrate change — try `/analyze`, different engine |
| VM unsupported | Expected: no lightweight engine handles custom VMs; add a specialized tool |

## Verified in this environment

- `pytest`: see run output (19 tests).
- `demo.py`: analyzer + bundled engine on `tests/fixtures/*.lua`.
- Real Discord delivery requires a bot token (not included); pipeline uses `original_response().edit()` + file attachment and was reviewed against discord.py 2.x interaction rules.
- Desktop tool integration is **configured-but-pending**: adapter implemented + health-checked, marked unavailable until you supply `exe_path` and CLI docs.
