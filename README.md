# AionBot

A Discord bot for Aion 2 communities, built with Python and [discord.py](https://github.com/Rapptz/discord.py). It posts reset and Spacetime Rift alerts, shares official news, gives each member a private daily and weekly checklist, and lets members pick their own notification roles with buttons.

> **Source-available, not open source.** The code is free for personal use only. Running it for a community, a public server, or any commercial purpose requires written approval. See [LICENSE](LICENSE).

> **Not affiliated with NCSOFT.** AionBot is a fan-made tool. Reset times, rift schedules, and checklist tasks come from community guides and may change. Always confirm with the in-game timers.

## Features

- **Reset alerts:** pings 4 hours before the daily reset and 1 day before the weekly reset, with a season countdown. Times show in each member's own time zone, and each new alert replaces the previous one.
- **Official news:** checks Steam's official Aion 2 announcements every 10 minutes and posts new ones with a link to the full post.
- **Private checklist:** each member gets a private thread with daily and weekly task menus that clear automatically at reset.
- **Role panel:** one message with a button per role, so members can add or remove their own notification roles.
- **Spacetime Rift alerts:** pings 10 minutes before every rift opens (every 3 hours), with a `/rift` command showing the next four openings.

## Commands

**Everyone**

| Command | What it does |
|---------|--------------|
| `/ping` | Checks that the bot is online |
| `/reset` | Shows the next daily reset, weekly reset, and season end |
| `/season` | Shows the season countdown |
| `/rift` | Shows the next four Spacetime Rift openings |
| `/checklist` | Opens your private checklist (checklist channel only) |

**Admins** (Manage Server; role panel commands need Manage Roles)

| Command | What it does |
|---------|--------------|
| `/setchannel`, `/setrole` | Set the reset alert channel and ping role |
| `/testalert` | Post a sample daily or weekly alert |
| `/setnewschannel`, `/setnewsrole` | Set the news channel and optional ping role |
| `/latestnews` | Post the newest official news item |
| `/setchecklistchannel` | Choose the one channel where `/checklist` works |
| `/addpanelrole`, `/removepanelrole` | Add, edit, or remove a role on the role panel |
| `/postpanel` | Post the role panel, replacing any older one |
| `/setriftchannel`, `/setriftrole` | Set the rift alert channel and ping role |
| `/testrift` | Post a sample rift alert |
| `/riftsync` | Re-align the rift schedule using the in-game timer |

## Project Files

| File | Purpose |
|------|---------|
| `bot.py` | Main program: reset alerts, `/reset`, `/season`, `/ping`, and loads the other features |
| `patchnews.py` | Official news feature |
| `checklist.py` | Private checklist feature |
| `rolepanel.py` | Role panel feature |
| `riftalert.py` | Spacetime Rift alerts |
| `.env` | Your bot token (never committed) |
| `*.json` | Settings and progress files the bot creates on its own |

## Running It Yourself (Personal Use)

**Requirements:** Python 3.10 or newer.

**1. Create the bot.** In the [Discord Developer Portal](https://discord.com/developers/applications), create an application, open the **Bot** tab, and click **Reset Token** to copy your token. Leave all three Privileged Gateway Intents off, since the bot doesn't need them.

**2. Invite it.** Under **OAuth2 → URL Generator**, tick the scopes `bot` and `applications.commands`, plus these permissions: View Channels, Send Messages, Embed Links, Read Message History, Mention Everyone, Manage Roles, Create Private Threads, Send Messages in Threads, and Manage Threads. Open the generated URL and add the bot to your server. Don't give it Administrator.

**3. Install and configure.**

```bash
git clone https://github.com/YogenKharka-Source/AionBot.git
cd AionBot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

Edit `.env` and set `DISCORD_TOKEN=` followed by your token, with no spaces or quote marks.

**4. Start it.**

```bash
python bot.py
```

A successful start prints a `Synced commands` list, then `Logged in as` and the bot's name.

**5. Set it up in your server.** Create your channels and notification roles first, and drag the bot's role above the roles on your panel so it can hand them out. Then run these in order:

1. `/setchannel`, `/setrole`, then `/testalert`
2. `/setnewschannel`, then `/latestnews`
3. `/setchecklistchannel`, then `/checklist`
4. `/addpanelrole` for each role, then `/postpanel`
5. `/setriftchannel`, `/setriftrole`, then `/testrift`

The bot only works while `bot.py` is running, so alerts stop when your computer is off.

## Settings

Editable values sit in a "Settings you can edit" block at the top of each file. Change one, save, and restart the bot.

| File | Examples |
|------|----------|
| `bot.py` | `RESET_HOUR_UTC`, `DAILY_WARNING`, `WEEKLY_WARNING`, `SEASON_NAME`, `SEASON_END` |
| `patchnews.py` | `STEAM_APP_ID`, `NEWS_POLL_MINUTES`, `NEWS_MAX_CHARS` |
| `checklist.py` | `DAILY_TASKS`, `WEEKLY_TASKS` |
| `riftalert.py` | `RIFT_INTERVAL`, `DEFAULT_ANCHOR`, `WARNING`, `PORTAL_MINUTES` |

Update `SEASON_NAME` and `SEASON_END` at the start of each season.

## Security

Never commit your token or your `.env` file, and never post them in screenshots. If a token leaks, click **Reset Token** in the Developer Portal right away. The `.json` files hold server settings and member progress, so back them up and keep them out of the repo.

## Legal

- [Terms of Service](https://yogenkharka-source.github.io/AionBot/terms-of-service)
- [Privacy Policy](https://yogenkharka-source.github.io/AionBot/privacy-policy)
- [License](LICENSE)

## Contact

Questions, or want to request approval for community or commercial use? Reach me at **[YOUR EMAIL OR DISCORD]**.
