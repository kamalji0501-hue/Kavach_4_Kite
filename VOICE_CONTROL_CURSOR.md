# Voice-control setup for Cursor (hands-free Batman work)

Use this when you drive Cursor by voice and cannot click **Accept** / **Allow** while doing office work.

## One-time UI settings (required)

Open **Cursor Settings** (`Ctrl+Shift+J`) → **Agents**:

| Setting | Set to | Why |
|---------|--------|-----|
| **Run Mode** | **Run Everything** | No classifier prompts for shell, MCP, web fetch, or web search |
| **Auto-run** | **On** | Agent runs tools without stopping each step |
| **External-File Protection** | **Off** | Stops endless **Accept** on file edits (common on Windows paths) |
| **Dotfile Protection** | **Off** (optional) | Same for `.gitignore`, `.cursor/*`, etc. |
| **MCP Tool Protection** | **Off** | MCP runs without extra prompts |
| **Browser Protection** | **On** (your choice) | Only if you use browser automation |

Under **Features** → **Chat** (or search settings for “sound”):

| Setting | Set to |
|---------|--------|
| **Play sound on finish** / chime | **On** |

Reload window after changing Run Mode: **Ctrl+Shift+P** → `Developer: Reload Window`.

### Why you still see Accept sometimes

- **Auto-review** (default in Cursor 3.6+) can still ask for web search or risky calls unless Run Mode is **Run Everything**.
- **File diff Accept** is separate from terminal allow — turn off **External-File Protection** and use **Run Everything**.
- **Inline Diffs OFF** = changes apply without review UI; **ON** = Keep/Accept buttons (normal for careful review).

## Already configured on this machine (files)

| File | Purpose |
|------|---------|
| `.cursor/permissions.json` | `approvalMode: unrestricted`, `terminalAllowlist: ["*"]`, `mcpAllowlist: ["*:*"]`, voice-friendly `autoRun` instructions |
| `~/.cursor/permissions.json` | Same for all projects |
| `.cursor/cli.json` | CLI agent: unrestricted + sandbox disabled |
| `~/.cursor/cli-config.json` | Same globally |
| `.cursor/sandbox.json` | Network allow for sandboxed commands |
| `.cursor/rules/batman-agent-autonomy.mdc` | Agent must not ask you to run commands |
| `.cursor/hooks.json` + `agent-done-chime.ps1` | **Extra beep** when agent **stops** (even if window focused) |
| `~/.cursor/hooks.json` | Global chime hook for other repos |
| User `settings.json` | `cursor.composer.shouldChimeAfterChatFinishes: true` |

## Completion sound (two layers)

1. **Built-in:** `cursor.composer.shouldChimeAfterChatFinishes` in user settings (Composer/Agent finish).
2. **Hook:** On agent `stop`, PowerShell plays Windows **Asterisk** sound (project + global hooks).

Test hook manually:

```powershell
Get-Content .cursor\hooks\agent-done-chime.ps1 | powershell -NoProfile -File -
```

## If web search still asks for approval

1. Confirm **Run Mode = Run Everything** (not Auto-review only).
2. Reload Cursor.
3. In chat, once allow web search and choose **Always allow** if offered.
4. `permissions.json` already tells the classifier to allow WebSearch/WebFetch for this repo.

## Agent mode vs permissions file

- **Run Everything** = deterministic, no prompts (best for voice).
- **Auto-review** + `permissions.json` = fewer prompts but **not** zero — classifier can still block.
- `approvalMode: unrestricted` in `permissions.json` aligns file config with Run Everything.

## Optional: louder custom chime

Put a `.wav` path in user settings:

```json
"cursor.composer.customChimeSoundPath": "C:\\Users\\RK\\Sounds\\done.wav"
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Agent idle waiting for Accept | Run Everything + External-File Protection off + Reload |
| No sound | Enable “Play sound on finish”; test `agent-done-chime.ps1`; check Windows volume |
| Hook not firing | **Cursor Settings → Hooks** tab; **Hooks** output channel; restart Cursor |
| WSL sandbox errors on Windows | Run Everything bypasses sandbox; or install WSL2 for sandbox path |

## Security note

Run Everything is full trust on this dev laptop. `block_instructions` in `permissions.json` still steer away from force-push and secret commits. Do not use this profile on shared/production machines without tightening Run Mode.
