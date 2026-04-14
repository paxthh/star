# 📢 Telegram Promo Bot

A two-component bot system to auto-forward your promotional posts to all your joined groups.

---

## 🧩 Components

| Component | Library | Role |
|-----------|---------|------|
| **Userbot** | Telethon | Logs into your ads Telegram account, does the actual forwarding |
| **Control Bot** | python-telegram-bot | Your private control panel via a bot |

---

## ⚙️ Setup Guide

### Step 1 — Get API credentials

1. Go to **https://my.telegram.org**
2. Log in with your **ads account** phone number
3. Go to **API Development Tools**
4. Create an app → copy `api_id` and `api_hash`

### Step 2 — Create a Control Bot

1. Open Telegram → message **@BotFather**
2. Send `/newbot` → follow steps → copy the **bot token**

### Step 3 — Get your Owner ID

1. Message **@userinfobot** on Telegram
2. Copy your **numeric user ID**

### Step 4 — Fill in config

Open `promo_config.json` and fill in:

```json
{
  "api_id":     123456,
  "api_hash":   "your_api_hash_here",
  "bot_token":  "123456:ABC-your-bot-token",
  "owner_id":   987654321,

  "interval_min": 5,
  "delay_sec":    3
}
```

| Field | Description |
|-------|-------------|
| `api_id` | From my.telegram.org |
| `api_hash` | From my.telegram.org |
| `bot_token` | From @BotFather |
| `owner_id` | Your Telegram numeric ID |
| `interval_min` | Minutes between each forward round (default: 5) |
| `delay_sec` | Seconds between each group forward to avoid flood ban (default: 3) |

### Step 5 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 6 — Run the bot

```bash
python bot.py
```

On first run, Telethon will ask for your **ads account phone number** and a **verification code** sent to it. After that, a session file (`ads_account.session`) is saved so you won't need to log in again.

---

## 🎮 Control Panel Commands

Send `/start` to your control bot. You'll see a full menu:

| Button | Action |
|--------|--------|
| ▶️ Start Ads | Begin auto-forwarding on schedule |
| ⏹ Stop Ads | Pause forwarding |
| 🔗 Change Post Link | Set a new post to forward |
| 👥 Manage Groups | Add/remove groups or auto-fetch all joined groups |
| ⏱ Set Interval | Change how often rounds run |
| 📊 Stats | View total sent, last 5 rounds, group count |
| 🚀 Forward Now | Trigger a one-time immediate round |
| 🗑 Reset Stats | Clear counters |

---

## 📋 Supported Post Link Formats

```
https://t.me/yourchannel/42          ← public channel/group post
https://t.me/c/1234567890/42         ← private supergroup post
```

---

## 💡 Tips

- Use **Auto-Fetch Groups** to automatically pull all groups your ads account has joined.
- Set `delay_sec` to at least `2–3` seconds to avoid Telegram flood limits.
- If you get flood errors, increase `interval_min` to `10–15`.
- The session file (`ads_account.session`) stores your login. Keep it private.
- The bot resumes automatically after restart — state is saved in `promo_config.json`.

---

## ⚠️ Important Notes

- Only use this for groups where you have permission to post.
- Telegram may restrict accounts that spam too aggressively. Use reasonable intervals.
- Never share your `.session` file or `api_hash`.
