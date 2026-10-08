# hermes-bot-chat-rotation

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) **skill** for rotating a bot's main conversation.

In Bot Mode every bot is a Hermes profile, and its main conversation is the session titled exactly `Bot Chat`
(one per profile, no session-id pointer). This skill retires the current one and opens a fresh one **whose first
turn reads the archived conversation**, so the new chat starts with context instead of amnesia.

## What it does

For each bot (or the ones you name):

1. **Archive** the current `Bot Chat` (`session.archive`) — messages kept, session retired.
   The archived row keeps its history but gives up the name, so from then on it is reachable **by session id only**.
2. **Mint a fresh `Bot Chat`** (`session.create` with the exact title, born hidden, following the profile's own
   config) and set the title immediately so the registry has exactly one `Bot Chat` row.
3. **Submit an opening turn** that tells the new chat to read the archived conversation
   (`session_search(session_id="<old id>")`) and write a short handoff record, then carry on from there.

Everything goes through the **desktop backend's JSON-RPC** (`hermes serve`, the same channel the Bots pane uses),
so the new chats are real desktop Bot Chats — *not* one-shot CLI sessions, which would not be the bot's main chat.

## Install

Copy this folder into a profile's skills directory — profiles are isolated, so copy it into each bot that should
have it:

```bash
cp -r hermes-bot-chat-rotation ~/.hermes/profiles/<bot>/skills/autonomous-ai-agents/
# Windows default install: %LOCALAPPDATA%\hermes\profiles\<bot>\skills\autonomous-ai-agents\
```

## Requirements

- A running Hermes backend on the same machine: the desktop app, or any `hermes serve` process (the script only
  talks to `127.0.0.1`).
- Python with `websockets` for the actual call. Running with a plain `python` is fine — if `websockets` is missing,
  the script re-execs itself into the Hermes venv Python.
- Optional overrides when discovery fails: `HERMES_PYTHON`, `HERMES_DESKTOP_URL`, `HERMES_SESSION_TOKEN`.

## Usage

```bash
python scripts/rotate_bot_chats.py --dry-run         # show which bots would be rotated
python scripts/rotate_bot_chats.py                   # every profile on this machine
python scripts/rotate_bot_chats.py research steward  # only these profiles
python scripts/rotate_bot_chats.py --no-prompt       # archive + open fresh, no opening turn
```

The script then prints its own verification: the RPC view (`session.list` for the title, `profiles.list`
canonical session) and, when the profile's `state.db` is on this machine, the two database rows
(`old: archived=1, title NULL` / `new: title='Bot Chat', hidden=1, source='desktop'`).

The opening instruction lives in `OPENING` at the top of the script — edit it there (language, handoff format)
instead of rewriting the skill.

## Also a valid Hermes skill

`SKILL.md` is a normal Hermes skill file: drop the folder where your skills live and the agent will load it
when the user asks for a bot-chat rotation. This repo is just the same skill, distributed.

## License

MIT — see [LICENSE](LICENSE).
