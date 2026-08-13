# Discord Quest Auto-Completer

Automatically accept and complete Discord Quests by emulating the Discord Desktop client. Zero setup, no Discord Bot Application required, no database — runs entirely in a single Python script.

## Installation

```bash
pip install requests
```

## How to Get Your User Token

1. Open Discord (Web or Desktop App)
2. Press `F12` to open Developer Tools → select the **Console** tab
3. Paste the following snippet and press Enter:

```js
token=webpackChunkdiscord_app.push([[Symbol()],0,e=>{for(i in e.c)if(i=e.c[i].exports.getToken)return i()}])
```

4. Copy the returned string token (starts with `MTU...` or similar).

## Usage

```bash
# Interactive mode — paste tokens directly in terminal
python direct_run.py

# Pass a token directly via argument
python direct_run.py --token "YOUR_TOKEN_HERE"

# Multiple accounts from a file (one token per line, lines starting with # are ignored)
python direct_run.py --file tokens.txt

# Run once and exit (no continuous loop)
python direct_run.py --once

# Set polling interval between scan cycles (seconds, default: 60)
python direct_run.py --poll 120
```

## Supported Quest Task Types

| Task Type | Description |
|---|---|
| `WATCH_VIDEO` | Emulates video watching progress |
| `WATCH_VIDEO_ON_MOBILE` | Emulates video watching progress on mobile |
| `PLAY_ON_DESKTOP` | Emulates playing a desktop game |
| `STREAM_ON_DESKTOP` | Emulates streaming a game to friends |
| `PLAY_ACTIVITY` | Emulates playing a Discord Activity |

## Exit

Press `Ctrl+C` to gracefully stop all workers.
