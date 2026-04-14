"""
Telegram Promotion Bot
======================
Two-component system:
  1. Userbot  (Telethon)            – logs into your ads account, forwards posts
  2. Control Bot (python-telegram-bot) – your personal control panel

Setup:
  pip install telethon python-telegram-bot apscheduler
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.tl.types import InputPeerChannel, InputPeerChat
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("PromoBot")

# ─── Config file ──────────────────────────────────────────────────────────────
CONFIG_FILE = "promo_config.json"

DEFAULT_CONFIG = {
    # --- Fill these before running ---
    "api_id":          0,           # From my.telegram.org
    "api_hash":        "",          # From my.telegram.org
    "bot_token":       "",          # From @BotFather
    "owner_id":        0,           # Your personal Telegram user ID

    # --- Runtime state (managed automatically) ---
    "post_link":       "",          # t.me/channel/123  or  t.me/c/123/456
    "groups":          [],          # list of group usernames / IDs
    "interval_min":    5,           # minutes between each forward round
    "delay_sec":       3,           # seconds between consecutive groups
    "is_running":      False,
    "total_sent":      0,
    "session_name":    "ads_account",
    "stats":           [],          # list of {ts, groups_reached, status}
}


def load_config() -> dict:
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # Merge any missing keys from defaults
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ─── Shared state ─────────────────────────────────────────────────────────────
cfg = load_config()
userbot: TelegramClient | None = None
scheduler = AsyncIOScheduler()
forward_job = None          # APScheduler job reference


# ─── Parse post link ──────────────────────────────────────────────────────────
def parse_post_link(link: str):
    """
    Supports:
      https://t.me/username/123
      https://t.me/c/1234567890/123   (private supergroup)
    Returns (chat_identifier, message_id) or raises ValueError.
    """
    link = link.strip().rstrip("/")
    # Private: t.me/c/CHATID/MSGID
    m = re.match(r"https?://t\.me/c/(\d+)/(\d+)", link)
    if m:
        return int("-100" + m.group(1)), int(m.group(2))
    # Public: t.me/USERNAME/MSGID
    m = re.match(r"https?://t\.me/([^/]+)/(\d+)", link)
    if m:
        return m.group(1), int(m.group(2))
    raise ValueError("Invalid Telegram post link.")


# ─── Forward one round ────────────────────────────────────────────────────────
async def forward_round():
    global cfg
    if not cfg["is_running"] or not cfg["post_link"] or not cfg["groups"]:
        return

    try:
        chat_id, msg_id = parse_post_link(cfg["post_link"])
    except ValueError as e:
        log.error("Bad link: %s", e)
        return

    reached = 0
    failed  = 0

    for group in cfg["groups"]:
        try:
            await userbot.forward_messages(group, msg_id, chat_id)
            reached += 1
            log.info("✅ Forwarded to %s", group)
        except Exception as e:
            failed += 1
            log.warning("❌ Failed %s: %s", group, e)
        await asyncio.sleep(cfg["delay_sec"])

    cfg["total_sent"] += reached
    cfg["stats"].append({
        "ts":             datetime.utcnow().isoformat(),
        "groups_reached": reached,
        "failed":         failed,
    })
    # Keep only last 100 stat entries
    cfg["stats"] = cfg["stats"][-100:]
    save_config(cfg)
    log.info("Round done. Reached %d / %d groups.", reached, len(cfg["groups"]))


# ─── Scheduler helpers ────────────────────────────────────────────────────────
def start_scheduler():
    global forward_job
    if forward_job:
        forward_job.remove()
    forward_job = scheduler.add_job(
        forward_round,
        "interval",
        minutes=cfg["interval_min"],
        id="forward_job",
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()


def stop_scheduler():
    global forward_job
    if forward_job:
        try:
            forward_job.remove()
        except Exception:
            pass
        forward_job = None


# ─── Auth guard ───────────────────────────────────────────────────────────────
def owner_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != cfg["owner_id"]:
            await update.message.reply_text("⛔ Unauthorized.")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


# ─── Main menu keyboard ───────────────────────────────────────────────────────
def main_menu_kb():
    status = "🟢 Running" if cfg["is_running"] else "🔴 Stopped"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Status: {status}", callback_data="noop")],
        [
            InlineKeyboardButton("▶️ Start Ads",  callback_data="start_ads"),
            InlineKeyboardButton("⏹ Stop Ads",   callback_data="stop_ads"),
        ],
        [InlineKeyboardButton("🔗 Change Post Link",   callback_data="change_link")],
        [InlineKeyboardButton("👥 Manage Groups",       callback_data="manage_groups")],
        [InlineKeyboardButton("⏱ Set Interval",         callback_data="set_interval")],
        [InlineKeyboardButton("📊 Stats",               callback_data="stats")],
        [InlineKeyboardButton("🚀 Forward Now (Once)",  callback_data="forward_now")],
        [InlineKeyboardButton("🗑 Reset Stats",          callback_data="reset_stats")],
    ])


# ─── /start command ───────────────────────────────────────────────────────────
@owner_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Promo Bot Control Panel*\n\nChoose an action below:",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


# ─── Callback handler ─────────────────────────────────────────────────────────
@owner_only
async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global cfg
    q = update.callback_query
    await q.answer()
    data = q.data

    # ── Start ads ──────────────────────────────────────────────────────────────
    if data == "start_ads":
        if not cfg["post_link"]:
            await q.edit_message_text("⚠️ Set a post link first using 🔗 Change Post Link.")
            return
        if not cfg["groups"]:
            await q.edit_message_text("⚠️ Add groups first using 👥 Manage Groups.")
            return
        cfg["is_running"] = True
        save_config(cfg)
        start_scheduler()
        # Immediately forward once
        asyncio.create_task(forward_round())
        await q.edit_message_text(
            f"✅ Ads *started*!\n"
            f"📨 Forwarding to *{len(cfg['groups'])}* groups every *{cfg['interval_min']} min*.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )

    # ── Stop ads ───────────────────────────────────────────────────────────────
    elif data == "stop_ads":
        cfg["is_running"] = False
        save_config(cfg)
        stop_scheduler()
        await q.edit_message_text(
            "⏹ Ads *stopped*.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )

    # ── Change link ────────────────────────────────────────────────────────────
    elif data == "change_link":
        ctx.user_data["awaiting"] = "link"
        await q.edit_message_text(
            "🔗 Send the *post link* you want to forward.\n"
            "Example: `https://t.me/yourchannel/42`",
            parse_mode="Markdown",
        )

    # ── Manage groups ──────────────────────────────────────────────────────────
    elif data == "manage_groups":
        groups_text = "\n".join(f"• `{g}`" for g in cfg["groups"]) or "_No groups yet_"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Group",    callback_data="add_group")],
            [InlineKeyboardButton("➖ Remove Group", callback_data="remove_group")],
            [InlineKeyboardButton("📋 Auto-Fetch Groups from Account", callback_data="auto_fetch")],
            [InlineKeyboardButton("🔙 Back",          callback_data="back_main")],
        ])
        await q.edit_message_text(
            f"👥 *Groups* ({len(cfg['groups'])} total):\n\n{groups_text}",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    elif data == "add_group":
        ctx.user_data["awaiting"] = "add_group"
        await q.edit_message_text(
            "➕ Send the group *username* or *invite link* to add.\n"
            "Example: `@mygroup` or `https://t.me/mygroup`",
            parse_mode="Markdown",
        )

    elif data == "remove_group":
        ctx.user_data["awaiting"] = "remove_group"
        await q.edit_message_text(
            "➖ Send the group username to *remove*.\n"
            "Example: `@mygroup`",
            parse_mode="Markdown",
        )

    elif data == "auto_fetch":
        await q.edit_message_text("⏳ Fetching all your joined groups/channels…")
        try:
            dialogs = await userbot.get_dialogs()
            groups = []
            for d in dialogs:
                if d.is_group or d.is_channel:
                    ent = d.entity
                    uid = getattr(ent, "username", None)
                    if uid:
                        groups.append("@" + uid)
                    else:
                        groups.append(str(ent.id))
            cfg["groups"] = list(set(cfg["groups"] + groups))
            save_config(cfg)
            await q.edit_message_text(
                f"✅ Fetched *{len(groups)}* groups/channels.\n"
                f"Total now: *{len(cfg['groups'])}*.",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=main_menu_kb())

    # ── Set interval ───────────────────────────────────────────────────────────
    elif data == "set_interval":
        ctx.user_data["awaiting"] = "interval"
        await q.edit_message_text(
            f"⏱ Current interval: *{cfg['interval_min']} minutes*.\n"
            "Send a new interval in minutes (e.g. `10`):",
            parse_mode="Markdown",
        )

    # ── Stats ──────────────────────────────────────────────────────────────────
    elif data == "stats":
        last = cfg["stats"][-5:] if cfg["stats"] else []
        lines = []
        for s in reversed(last):
            lines.append(
                f"🕐 {s['ts'][:16].replace('T',' ')} UTC — "
                f"✅ {s['groups_reached']} sent, ❌ {s['failed']} failed"
            )
        body = "\n".join(lines) or "_No rounds yet_"
        await q.edit_message_text(
            f"📊 *Stats*\n"
            f"• Total messages sent: *{cfg['total_sent']}*\n"
            f"• Groups tracked: *{len(cfg['groups'])}*\n"
            f"• Post link: `{cfg['post_link'] or 'not set'}`\n"
            f"• Interval: *{cfg['interval_min']} min*\n\n"
            f"*Last 5 rounds:*\n{body}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="back_main")
            ]]),
        )

    # ── Forward now ────────────────────────────────────────────────────────────
    elif data == "forward_now":
        if not cfg["post_link"]:
            await q.edit_message_text("⚠️ No post link set.", reply_markup=main_menu_kb())
            return
        await q.edit_message_text("🚀 Forwarding now…")
        asyncio.create_task(forward_round())
        await asyncio.sleep(1)
        await q.edit_message_text("✅ Forward round triggered.", reply_markup=main_menu_kb())

    # ── Reset stats ────────────────────────────────────────────────────────────
    elif data == "reset_stats":
        cfg["total_sent"] = 0
        cfg["stats"] = []
        save_config(cfg)
        await q.edit_message_text("🗑 Stats reset.", reply_markup=main_menu_kb())

    # ── Back ───────────────────────────────────────────────────────────────────
    elif data == "back_main":
        await q.edit_message_text(
            "🤖 *Promo Bot Control Panel*\n\nChoose an action below:",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )

    elif data == "noop":
        pass


# ─── Text message handler (awaiting input) ────────────────────────────────────
@owner_only
async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global cfg
    text = update.message.text.strip()
    awaiting = ctx.user_data.get("awaiting")

    if awaiting == "link":
        try:
            parse_post_link(text)   # validate
            cfg["post_link"] = text
            save_config(cfg)
            ctx.user_data.pop("awaiting", None)
            await update.message.reply_text(
                f"✅ Post link updated!\n`{text}`",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid link. Try again.")

    elif awaiting == "add_group":
        group = text.replace("https://t.me/", "@").strip()
        if not group.startswith("@"):
            group = "@" + group
        if group not in cfg["groups"]:
            cfg["groups"].append(group)
            save_config(cfg)
            await update.message.reply_text(f"✅ Added `{group}`.", parse_mode="Markdown")
        else:
            await update.message.reply_text("ℹ️ Already in list.")
        ctx.user_data.pop("awaiting", None)

    elif awaiting == "remove_group":
        group = text if text.startswith("@") else "@" + text
        if group in cfg["groups"]:
            cfg["groups"].remove(group)
            save_config(cfg)
            await update.message.reply_text(f"✅ Removed `{group}`.", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ Group not found.")
        ctx.user_data.pop("awaiting", None)

    elif awaiting == "interval":
        try:
            mins = int(text)
            assert mins >= 1
            cfg["interval_min"] = mins
            save_config(cfg)
            if cfg["is_running"]:
                start_scheduler()   # reschedule with new interval
            ctx.user_data.pop("awaiting", None)
            await update.message.reply_text(
                f"✅ Interval set to *{mins} minutes*.",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
        except (ValueError, AssertionError):
            await update.message.reply_text("❌ Enter a number ≥ 1.")

    else:
        await update.message.reply_text(
            "Use /start for the control panel.",
            reply_markup=main_menu_kb(),
        )


# ─── Entry point ──────────────────────────────────────────────────────────────
async def main():
    global userbot, cfg

    # ── Validate config ────────────────────────────────────────────────────────
    if not cfg["api_id"] or not cfg["api_hash"] or not cfg["bot_token"] or not cfg["owner_id"]:
        print("⚠️  Please fill in api_id, api_hash, bot_token, owner_id in promo_config.json first!")
        return

    # ── Start userbot ──────────────────────────────────────────────────────────
    userbot = TelegramClient(cfg["session_name"], cfg["api_id"], cfg["api_hash"])
    await userbot.start()
    log.info("Userbot connected as: %s", await userbot.get_me())

    # ── Start control bot ──────────────────────────────────────────────────────
    app = (
        Application.builder()
        .token(cfg["bot_token"])
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    # Resume scheduler if was running before restart
    if cfg["is_running"]:
        start_scheduler()
        log.info("Resumed scheduled forwarding.")

    log.info("Control bot started. Send /start to your bot.")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Keep running
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await userbot.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
