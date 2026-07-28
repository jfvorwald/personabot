# personabot

Two Claude-powered personas holding a conversation in a shared Discord channel.
You each define your own character, run your own bot process, and pay for your
own API calls. Every mode is bounded, so there's no runaway loop and no
surprise bill.

## How it works

```
  You                                   Your friend
  ├─ Discord bot app "A"  ─┐        ┌─  Discord bot app "B"
  ├─ your Anthropic key    │        │   their Anthropic key
  └─ persona.md (yours)    │        │   persona.md (theirs)
                           ▼        ▼
                    #persona-chat  (one channel, your server)
```

A bot reads the last ~30 messages in the channel, asks Claude for one
in-character reply, and posts it. What differs between modes is *when* it does
that, and what stops it doing it forever.

## Three modes

```bash
.venv/bin/python bot.py --now     # post once, exit
.venv/bin/python bot.py           # scheduled: post only at POST_TIMES
.venv/bin/python bot.py --live    # stay connected, converse in real time
```

**`--now`** is the smoke test. Connects, posts one message, exits.

**Scheduled** (no flag) is the simple mode. The bot wakes at each time in
`POST_TIMES`, posts once, and goes back to sleep. **It never reacts to message
events.** That's the loop guard, and it's structural: the daily message count
is fixed by your schedule, not by what the other bot says. Three slots a day
means exactly three messages a day, forever.

Stagger the two schedules ~15 minutes apart so they alternate:

| | Slot 1 | Slot 2 | Slot 3 |
|---|---|---|---|
| Bot A | 09:00 | 13:00 | 19:00 |
| Bot B | 09:15 | 13:15 | 19:15 |

**`--live`** is the interesting mode and the one that needs care. The bot stays
connected and responds to messages as they arrive, which means the loop guard
has to be behavioural rather than structural:

- **A daily budget.** Each morning the bot draws a fresh number between
  `LIVE_DAILY_MIN` and `LIVE_DAILY_MAX` (default 4-10). Every message it posts
  spends one. At zero it signs off until tomorrow. This is the only hard stop
  on two live bots talking to each other forever - the range is randomized so
  the bot doesn't visibly flatline on the same count each day.
- **Other bots are ignored by default.** Only display names listed in
  `LIVE_COUNTERPARTS` get through, which is what lets the two personas talk at
  all without opening the door to every bot in the server.
- **A direct @mention is always answered.** No dice roll, no decay, no hanging
  back, and it's answered even after the daily budget is spent - the budget
  guards against the two bots looping, not against you asking a question. It
  also queues behind an in-progress reply rather than being dropped. Merely
  saying the word "jaq" in a message is *not* a mention and stays
  probabilistic.
- **Otherwise, replying is a dice roll, not a reflex.** Before any API call the
  bot rolls against `REPLY_CHANCE_*` - ~95% when addressed by name, 70% to a
  human, 45% to the counterpart bot. Those odds decay if it spoke last
  (`REPLY_DECAY_IF_LAST_SPEAKER`) or has been dominating the recent window
  (`REPLY_DECAY_IF_DOMINATING`). Rolling client-side is cheaper and more
  decisive than asking the model to stay quiet, which it under-uses.
- **It doesn't pounce on a conversation it isn't in.** When others are already
  talking, the bot sits out a random `JOIN_AFTER_MIN`-`JOIN_AFTER_MAX` messages
  before it's eligible to chime in, redrawn per thread so the delay isn't
  countable. Answering the first message of someone else's exchange reads as
  surveillance rather than company. If the thread runs past
  `JOIN_WINDOW_MESSAGES` without it joining, the moment's gone - it resets and
  waits for a fresh opening instead of replying to stale context.
- **Human timing.** It waits out a burst (`SETTLE_SECONDS`), thinks for a few
  seconds, then types at ~13 characters a second with the typing indicator on.
  Instant replies are the biggest tell.
- **It starts things.** After `IDLE_HOURS` of quiet it may open a new thread of
  its own, and a few times a day it "pokes" the counterpart with an unprompted
  question at times drawn fresh each morning. Both spend from the same budget.

Every knob above is an environment variable with a sane default. See
`.env.example` for the full list.

> ⚠️ Setting `LIVE_DAILY_MAX=0` removes the cap entirely. The only remaining
> brake is the model's own choice to pass. Don't.

---

## Part 1 - Server owner (you), one-time setup

Do this first and send your friend the output of step 4.

**1. Create the server and channel**

- In Discord: **+** in the left sidebar → **Create My Own** → name it.
- Create a text channel, e.g. `#persona-chat`.
- Right-click the channel → **Edit Channel** → **Permissions**. Optional but
  recommended: deny `@everyone` **Send Messages** so only the two bots talk.

**2. Turn on Developer Mode**

User Settings → **Advanced** → **Developer Mode** on. This gives you the
"Copy Channel ID" right-click option.

**3. Grab the channel ID**

Right-click `#persona-chat` → **Copy Channel ID**. It's an 18-19 digit number.

**4. Send your friend:**

- The channel ID from step 3
- An **invite link to the server** (right-click server → Invite People →
  set it to never expire) - they need to be in the server to add their bot
- A link to this repo/folder

**5. Now build your own bot** - continue to Part 2. Both of you do Part 2.

---

## Part 2 - Each person, independently

You each do all of this. Nothing here is shared except the channel ID.

**1. Create your Discord bot application**

- Go to <https://discord.com/developers/applications> → **New Application**.
  Name it whatever your persona is called - this becomes the display name in
  the channel, and it's the name your friend puts in `LIVE_COUNTERPARTS`.
- Left sidebar → **Bot**.
- **Reset Token** → copy it. This is your `DISCORD_TOKEN`. It's shown once.
  Never share it; anyone with it controls your bot.
- Scroll to **Privileged Gateway Intents** and enable **MESSAGE CONTENT
  INTENT**. ⚠️ Required - without it the bot reads empty messages and will
  reply to nothing.

**2. Invite your bot to the shared server**

- Left sidebar → **OAuth2** → **URL Generator**.
- Scopes: check **bot**.
- Bot Permissions: check **View Channel**, **Send Messages**, and
  **Read Message History**.
- Copy the generated URL at the bottom, open it, pick the shared server,
  authorise.

**3. Get an Anthropic API key**

<https://console.anthropic.com> → **API Keys** → **Create Key**. This is your
`ANTHROPIC_API_KEY`. Your key pays only for your own bot's messages.

**4. Install**

```bash
cd personabot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**5. Write your persona**

```bash
cp persona.example.md persona.md
```

Edit `persona.md`. It's dropped into the system prompt verbatim, so write it as
instructions to the character: who they are, how they talk, what they keep
circling back to, how they treat the other person. Give them at least one
opinion they'll defend - two agreeable personas produce very boring logs.

**6. Configure**

```bash
.venv/bin/python setup_env.py
```

Prompts for each value and writes `.env`. Secrets are read with hidden input,
so they don't land in your shell history or scrollback. (Prefer an editor?
`cp .env.example .env` and fill it in by hand.)

You need `DISCORD_TOKEN`, `ANTHROPIC_API_KEY`, and the shared `CHANNEL_ID`.
Set `TIMEZONE`, and:

- **Scheduled mode:** set `POST_TIMES` - **coordinate so the two of you use
  different times**, offset ~15 minutes (see the table above).
- **Live mode:** set `LIVE_COUNTERPARTS` to the other bot's display name.
  Miss this and the two bots will share a channel in total silence.

**7. Check the setup**

```bash
.venv/bin/python doctor.py
```

Checks each layer in order - env vars, Discord login, channel access,
Anthropic key - and stops at the first failure with the specific fix. Sends
nothing. Add `--send` to also post a throwaway test message.

**8. Smoke-test for real**

```bash
.venv/bin/python bot.py --now
```

Posts one in-character message immediately and exits. Check the channel. If it
looks right, you're done configuring.

**9. Run it**

```bash
.venv/bin/python bot.py          # scheduled
.venv/bin/python bot.py --live   # live
```

It has to stay running - see below.

---

## Keeping it running

The process must be alive at the scheduled times. Pick one:

**`restart.sh` (live mode, no root):** wraps the whole deploy loop. It
syntax-checks `bot.py` before deploying, so a typo can't take the bot down;
kills the old process and *waits for it to actually exit* before starting a new
one, since two instances means every message gets answered twice; and tracks
whether `bot.py`, `persona.md`, or `.env` have been edited since the running
process started.

```bash
./restart.sh          # syntax-check, restart, report status
./restart.sh status   # running? since when? anything stale?
./restart.sh stop
./restart.sh logs     # tail -f
```

The PID lives in `.bot.pid`; output goes to `live.log`. Dies on reboot.

**systemd (Linux/WSL, survives reboot):** create
`~/.config/systemd/user/personabot.service`:

```ini
[Unit]
Description=personabot
After=network-online.target

[Service]
WorkingDirectory=%h/personabot
ExecStart=%h/personabot/.venv/bin/python bot.py
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
```

Add `--live` to `ExecStart` for live mode. Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now personabot
systemctl --user status personabot
loginctl enable-linger $USER   # keeps it running when you're logged out
journalctl --user -u personabot -f
```

**tmux (quick and dirty):** `tmux new -s bot` → run it → `Ctrl-B D` to detach.
Dies on reboot.

**cron instead of a long-running process:** if you'd rather not keep a process
alive, skip `POST_TIMES` and let cron invoke `bot.py --now`:

```
0 9,13,19 * * * cd ~/personabot && .venv/bin/python bot.py --now >> bot.log 2>&1
```

Each run connects, posts once, exits. Same result, no daemon. Not an option for
live mode, which needs a persistent connection.

---

## Cost

Each message is one API call: ~30 short messages of history in, a few hundred
tokens out. At 3 messages/day on `claude-opus-5` that's cents per day per
person; live mode at 4-10 messages/day is a small multiple of that. Knobs in
`.env`:

- `EFFORT=low` (default) - keeps replies snappy and cheap.
- `MODEL=claude-sonnet-5` - cheaper still if you want to cut it further.
- `HISTORY_LIMIT` - lower it to shrink the input.
- `LIVE_DAILY_MAX` - the ceiling on live mode. This is the one that matters.

## Tuning the conversation

- **Boring?** Sharpen the disagreement in both `persona.md` files.
- **Too long-winded?** The framing already caps length; add an explicit
  "keep it under three sentences" line to your persona.
- **Losing the thread?** Raise `HISTORY_LIMIT` to 50+.
- **Repetitive?** They're seeing the same context every time. Add a
  "don't restate what you've already said" line, or add a slot so the
  conversation moves faster.
- **Too chatty in live mode?** Lower `LIVE_DAILY_MAX` or the `REPLY_CHANCE_*`
  values. **Too quiet?** Raise them, or lower `IDLE_HOURS` so it breaks
  silences sooner.
- **Replies feel robotic?** Widen `THINK_SECONDS_MIN`/`MAX` and drop
  `TYPING_CPS`.

## Troubleshooting

Run `doctor.py` first - it isolates which layer is broken.

| Symptom | Cause |
|---|---|
| `LoginFailure` | Bad `DISCORD_TOKEN` - reset it in the portal |
| Bot posts but reads empty history | MESSAGE CONTENT INTENT not enabled |
| `Forbidden`/404 on the channel | Bot not invited, or lacks View Channel / Send Messages |
| `authentication_error` | Bad `ANTHROPIC_API_KEY` |
| Posts at the wrong hour | `TIMEZONE` wrong, or the host clock is UTC |
| Both bots post at once | You forgot to offset `POST_TIMES` |
| Live bots ignore each other | `LIVE_COUNTERPARTS` unset or doesn't match the other bot's display name |
| Live bot goes quiet mid-day | Daily budget spent - expected. Raise `LIVE_DAILY_MAX` |
| Slow to join a conversation | By design - lower `JOIN_AFTER_MIN`/`MAX`, or 0/0 to disable |
| Ignores an @mention | Shouldn't happen. Check the log for the message arriving at all - an empty `clean_content` means MESSAGE CONTENT INTENT is off |
| Every message answered twice | Two instances running - `./restart.sh` |

## Security

`.env` holds two secrets that are individually yours. Don't commit it, don't
paste tokens into the shared channel. The `.gitignore` covers `.env` *and*
`.env.*`, so backups like `.env.bak` don't slip through. If a Discord token
leaks, **Reset Token** in the portal immediately.
