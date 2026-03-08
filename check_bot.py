#!/usr/bin/env python3
"""
MangaBuff Club AutoCheck Bot
Отдельный бот — только авточек клуба:
- Проверяет карту клуба каждые N секунд
- Если карта есть — жертвует автоматически
- Управление аккаунтами и прокси
- Мультивклад — все аккаунты параллельно
"""

import os
import sys
import json
import time
import re
import threading
import traceback
import requests
from pathlib import Path
from datetime import datetime
import hashlib
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import telebot
    from telebot import types
except ImportError:
    print("❌ pip install pyTelegramBotAPI")
    sys.exit(1)

# ============================================================
# КОНФИГ
# ============================================================
CONFIG_FILE = Path(__file__).parent / "config_check.json"
ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"

BOT_TOKEN = ""  # Укажи свой токен бота

config = {}

def load_config():
    global config
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except:
            config = {}
    config.setdefault("bot_token", BOT_TOKEN)
    config.setdefault("club_slug", "")
    config.setdefault("club_account_name", "")
    config.setdefault("check_interval", 45)  # УВЕЛИЧЕНО: 45 секунд между проверками
    config.setdefault("account_delay", 3)     # УВЕЛИЧЕНО: 3 секунды между аккаунтами
    config.setdefault("max_workers", 2)       # УМЕНЬШЕНО: максимум 2 параллельных потока

def save_config():
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

# ============================================================
# АККАУНТЫ
# ============================================================
def load_accounts():
    if not ACCOUNTS_FILE.exists():
        return []
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except:
        return []

def save_accounts(accounts):
    ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")

# ============================================================
# MangaBuff API
# ============================================================
class MangaBuffAPI:
    BASE_URL = "https://mangabuff.ru"
    
    def __init__(self, account_data: dict):
        self.account = account_data
        self._use_cffi = False
        self._setup_session()
    
    def _setup_session(self):
        acc_name = self.account.get("name", "unknown")
        seed = hash(acc_name)
        
        os_profiles = [
            ("Windows NT 10.0; Win64; x64", '"Windows"', 55),
            ("Windows NT 10.0; Win64; x64", '"Windows"', 15),
            ("Macintosh; Intel Mac OS X 10_15_7", '"macOS"', 18),
            ("X11; Linux x86_64", '"Linux"', 7),
            ("X11; Ubuntu; Linux x86_64", '"Linux"', 5),
        ]
        chrome_profiles = [
            ("120", "120.0.6099.110", "chrome120", 15),
            ("120", "120.0.6099.225", "chrome120", 10),
            ("124", "124.0.6367.91", "chrome124", 15),
            ("124", "124.0.6367.207", "chrome124", 10),
            ("131", "131.0.6778.85", "chrome131", 20),
            ("131", "131.0.6778.204", "chrome131", 15),
            ("131", "131.0.6778.109", "chrome131", 15),
        ]
        
        os_profile = os_profiles[seed % len(os_profiles)]
        chrome_profile = chrome_profiles[(seed >> 8) % len(chrome_profiles)]
        
        os_string = os_profile[0]
        platform = os_profile[1]
        chrome_ver = chrome_profile[0]
        chrome_full = chrome_profile[1]
        impersonate = chrome_profile[2]
        
        ua = f"Mozilla/5.0 ({os_string}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_full} Safari/537.36"
        
        try:
            from curl_cffi.requests import Session as CffiSession
            self.session = CffiSession(impersonate=impersonate)
            self._use_cffi = True
        except ImportError:
            self.session = requests.Session()
            self._use_cffi = False
        
        # Прокси
        proxy_host = self.account.get("proxy_host", "")
        proxy_port = self.account.get("proxy_port", "")
        proxy_user = self.account.get("proxy_user", "")
        proxy_pass = self.account.get("proxy_pass", "")
        
        if proxy_host and proxy_port:
            if proxy_user and proxy_pass:
                proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
            else:
                proxy_url = f"http://{proxy_host}:{proxy_port}"
            self.session.proxies = {"http": proxy_url, "https": proxy_url}
        
        # Headers
        not_a_brand_map = {
            "120": '"Not_A Brand";v="8"',
            "124": '"Not-A.Brand";v="99"',
            "131": '"Not)A;Brand";v="99"',
        }
        not_a_brand = not_a_brand_map.get(chrome_ver, '"Not_A Brand";v="8"')
        
        accept_langs = [
            "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "ru,en-US;q=0.9,en;q=0.8",
            "ru-RU,ru;q=0.9",
            "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7,uk;q=0.6",
            "ru-RU,ru;q=0.9,en;q=0.8",
        ]
        accept_lang = accept_langs[(seed >> 16) % len(accept_langs)]
        accept_enc = "gzip, deflate, br, zstd" if int(chrome_ver) >= 123 else "gzip, deflate, br"
        
        headers = {
            "sec-ch-ua": f'"Chromium";v="{chrome_ver}", "Google Chrome";v="{chrome_ver}", {not_a_brand}',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": platform,
            "upgrade-insecure-requests": "1",
            "user-agent": ua,
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "sec-fetch-user": "?1",
            "sec-fetch-dest": "document",
            "accept-encoding": accept_enc,
            "accept-language": accept_lang,
        }
        if int(chrome_ver) >= 128:
            headers["priority"] = "u=0, i"
        if (seed >> 24) % 10 == 0:
            headers["dnt"] = "1"
        
        self.session.headers.update(headers)
        
        self._chrome_ver = chrome_ver
        self._sec_ch_ua = headers["sec-ch-ua"]
        self._accept_lang = accept_lang
        self._platform = platform
        
        # Куки
        cookies = self.account.get("cookies", "")
        if cookies:
            if isinstance(cookies, str):
                if cookies.startswith("["):
                    try:
                        cookies = json.loads(cookies)
                    except:
                        cookies = []
                else:
                    cookie_list = []
                    for c in cookies.split("; "):
                        if "=" in c:
                            name, value = c.split("=", 1)
                            cookie_list.append({"name": name.strip(), "value": value.strip()})
                    cookies = cookie_list
            
            if isinstance(cookies, list):
                for c in cookies:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    domain = c.get("domain", "mangabuff.ru")
                    if domain.startswith("."):
                        domain = domain[1:]
                    if name:
                        self.session.cookies.set(name, value, domain=domain)
    
    def check_auth(self):
        try:
            resp = self._get(f"{self.BASE_URL}/")
            if resp.status_code == 200:
                html = resp.text
                match = re.search(r'data-userid="(\d+)"', html)
                if match:
                    return True, match.group(1)
                if "Выйти" in html or "logout" in html.lower() or 'header__user' in html:
                    match = re.search(r'/users/(\d+)', html)
                    uid = match.group(1) if match else ""
                    return True, uid
            return False, None
        except Exception as e:
            return False, str(e)
    
    def _get_csrf_from_cookies(self):
        from urllib.parse import unquote
        try:
            val = self.session.cookies.get("XSRF-TOKEN") or self.session.cookies.get("xsrf-token")
            if val:
                return unquote(val)
        except:
            pass
        try:
            for cookie in self.session.cookies:
                name = cookie if isinstance(cookie, str) else getattr(cookie, 'name', '')
                if name.upper() == "XSRF-TOKEN":
                    value = self.session.cookies[name] if isinstance(cookie, str) else cookie.value
                    return unquote(value)
        except:
            pass
        return ""
    
    def _get_headers_with_csrf(self, referer=""):
        csrf = self._get_csrf_from_cookies()
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": self._accept_lang,
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "origin": self.BASE_URL,
            "referer": referer or f"{self.BASE_URL}/",
            "sec-ch-ua": self._sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": self._platform,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-requested-with": "XMLHttpRequest",
            "x-xsrf-token": csrf,
        }
    
    def _get(self, url, referer="", timeout=20):  # УВЕЛИЧЕН ТАЙМАУТ
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "sec-ch-ua": self._sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": self._platform,
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin" if referer else "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        }
        if referer:
            headers["referer"] = referer
        return self.session.get(url, headers=headers, timeout=timeout)
    
    def _post(self, url, data=None, json=None, referer="", timeout=20):  # УВЕЛИЧЕН ТАЙМАУТ
        """Универсальный POST с поддержкой JSON"""
        headers = self._get_headers_with_csrf(referer)
        
        if json is not None:
            # Если переданы JSON данные, меняем content-type
            headers["content-type"] = "application/json; charset=UTF-8"
            return self.session.post(url, json=json, headers=headers, timeout=timeout)
        else:
            # Обычный form-urlencoded запрос
            return self.session.post(url, data=data, headers=headers, timeout=timeout)
    
    def login(self, login_or_email, password):
        """HTTP-логин: GET /login -> CSRF -> POST /login -> проверка"""
        try:
            # 1. Получаем страницу логина для CSRF
            resp = self._get(f"{self.BASE_URL}/login")
            if resp.status_code != 200:
                return False, f"GET /login: HTTP {resp.status_code}"
            
            # 2. Извлекаем CSRF токен
            csrf = self._get_csrf_from_cookies()
            if not csrf:
                return False, "CSRF токен не найден"
            
            print(f"[LOGIN DEBUG] CSRF токен: {csrf}")
            print(f"[LOGIN DEBUG] Email: {login_or_email}")
            print(f"[LOGIN DEBUG] Длина пароля: {len(password)}")
            
            time.sleep(1.5)
            
            # 3. Отправляем запрос на логин
            headers_form = {
                "accept": "application/json, text/plain, */*",
                "accept-language": self._accept_lang,
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "origin": self.BASE_URL,
                "referer": f"{self.BASE_URL}/login",
                "sec-ch-ua": self._sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": self._platform,
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "x-requested-with": "XMLHttpRequest",
                "x-xsrf-token": csrf,
            }
            
            # ИСПРАВЛЕНО: Используем поле 'email' вместо 'login'
            login_data = {
                "email": login_or_email,  # <--- ВАЖНО: изменено с "login" на "email"
                "password": password, 
                "remember": "on"
            }
            
            print(f"[LOGIN] Отправка form-data с полем 'email'...")
            resp = self.session.post(
                f"{self.BASE_URL}/login", 
                data=login_data,
                headers=headers_form,
                timeout=20,  # УВЕЛИЧЕН ТАЙМАУТ
                allow_redirects=False
            )
            
            print(f"[LOGIN] Статус ответа: {resp.status_code}")
            print(f"[LOGIN] Заголовки ответа: {dict(resp.headers)}")
            
            # Пробуем прочитать ответ
            try:
                resp_text = resp.text[:500]
                print(f"[LOGIN] Текст ответа: {resp_text}")
            except:
                pass
            
            # Проверяем JSON ответ (успешный логин)
            try:
                resp_json = resp.json()
                print(f"[LOGIN] JSON ответ: {resp_json}")
                
                # ЕСЛИ СТАТУС TRUE - ЛОГИН УСПЕШЕН!
                if isinstance(resp_json, dict) and resp_json.get('status') is True:
                    print(f"[LOGIN] ✅ Успешный логин! Получаем user_id...")
                    
                    # Делаем GET запрос на главную для получения user_id
                    time.sleep(1)
                    check_resp = self._get(f"{self.BASE_URL}/", referer=f"{self.BASE_URL}/login")
                    
                    if check_resp.status_code == 200:
                        html = check_resp.text
                        user_id = None
                        
                        # Ищем user_id разными способами
                        m = re.search(r'data-userid="(\d+)"', html)
                        if m:
                            user_id = m.group(1)
                        if not user_id:
                            m = re.search(r'/users/(\d+)"', html)
                            if m:
                                user_id = m.group(1)
                        if not user_id:
                            m = re.search(r'data-user-id="(\d+)"', html)
                            if m:
                                user_id = m.group(1)
                        
                        if user_id:
                            # Сохраняем финальные куки
                            final_cookies = []
                            try:
                                for name, value in self.session.cookies.items():
                                    final_cookies.append({"name": name, "value": value, "domain": "mangabuff.ru"})
                                print(f"[LOGIN] Финальные куки сохранены: {len(final_cookies)} шт.")
                            except:
                                pass
                            
                            print(f"[LOGIN] ✅ USER_ID получен: {user_id}")
                            return True, {"user_id": user_id, "cookies": final_cookies}
                        else:
                            print(f"[LOGIN] ❌ Не удалось найти user_id на главной")
                            # Даже без user_id, логин успешен, сохраняем куки
                            final_cookies = []
                            try:
                                for name, value in self.session.cookies.items():
                                    final_cookies.append({"name": name, "value": value, "domain": "mangabuff.ru"})
                            except:
                                pass
                            
                            # Возвращаем успех с заглушкой user_id
                            return True, {"user_id": "unknown", "cookies": final_cookies}
                
                # Если есть ошибки в JSON
                if 'errors' in resp_json or 'message' in resp_json:
                    error_msg = resp_json.get('message') or str(resp_json.get('errors', ''))
                    return False, f"Ошибка: {error_msg[:100]}"
                    
            except Exception as e:
                print(f"[LOGIN] Ошибка парсинга JSON: {e}")
            
            # Проверяем успешность по редиректу
            if resp.status_code in (302, 301):
                location = resp.headers.get('location', '')
                print(f"[LOGIN] Редирект на: {location}")
                
                time.sleep(1)
                check_resp = self._get(f"{self.BASE_URL}/", referer=f"{self.BASE_URL}/login")
                if check_resp.status_code == 200:
                    html = check_resp.text
                    user_id = None
                    
                    m = re.search(r'data-userid="(\d+)"', html)
                    if m:
                        user_id = m.group(1)
                    if not user_id:
                        m = re.search(r'/users/(\d+)"', html)
                        if m:
                            user_id = m.group(1)
                    
                    if user_id:
                        final_cookies = []
                        try:
                            for name, value in self.session.cookies.items():
                                final_cookies.append({"name": name, "value": value, "domain": "mangabuff.ru"})
                        except:
                            pass
                        
                        return True, {"user_id": user_id, "cookies": final_cookies}
                    else:
                        return False, "Авторизация не подтверждена"
            
            return False, f"HTTP {resp.status_code}"
            
        except Exception as e:
            print(f"[LOGIN] Исключение: {e}")
            traceback.print_exc()
            return False, str(e)


# ============================================================
# КЛУБ: парсинг и пожертвование
# ============================================================
def parse_club_boost(api, club_slug):
    result = {"card_id": None, "card_image": "", "donated": 0, "needed": 0, "has_card": False}
    url = f"https://mangabuff.ru/clubs/{club_slug}/boost"
    resp = api._get(url)
    if resp.status_code != 200:
        return result
    html = resp.text
    
    match = re.search(r'href="/cards/(\d+)/users"', html)
    if match:
        result["card_id"] = match.group(1)
    
    match = re.search(r'club-boost__image[^>]*>\s*<img src="([^"]+)"', html)
    if match:
        result["card_image"] = match.group(1)
    
    match = re.search(r'club-boost__change[^>]*>.*?<span>(\d+)</span>\s*/\s*(\d+)', html, re.S)
    if match:
        result["donated"] = int(match.group(1))
        result["needed"] = int(match.group(2))
    
    result["has_card"] = "У вас нет этой карты" not in html
    return result


def donate_card_to_club(api, club_slug):
    result = {"success": False, "error": ""}
    try:
        boost_url = f"https://mangabuff.ru/clubs/{club_slug}/boost"
        resp = api._get(boost_url, referer=f"https://mangabuff.ru/clubs/{club_slug}")
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result
        
        time.sleep(0.5)  # УВЕЛИЧЕНА задержка перед пожертвованием
        
        resp = api._post("https://mangabuff.ru/clubs/boost", data={}, referer=boost_url)
        
        if resp.status_code == 302:
            result["success"] = True
            return result
        
        if resp.status_code == 200:
            try:
                jr = resp.json()
                msg = str(jr.get("message", "")).lower()
                if "вклад" in msg or "внесли" in msg or "так держать" in msg:
                    result["success"] = True
                    print(f"  [donate] ✅ {jr.get('message')}")
                    return result
                if jr.get("success"):
                    result["success"] = True
                    return result
                result["error"] = str(jr.get("error") or jr.get("message", ""))[:100]
            except:
                progress = re.search(r'(\d+)\s*/\s*(\d+)', resp.text[:5000])
                if progress:
                    result["success"] = True
                    return result
        
        if not result["error"]:
            result["error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        result["error"] = str(e)[:80]
        print(f"  [donate] ❌ {e}")
    return result


def get_card_name(api, card_id):
    try:
        resp = api._get(f"https://mangabuff.ru/cards/{card_id}/users")
        if resp.status_code != 200:
            return "?"
        title = re.search(r'<title>([^<]+)</title>', resp.text)
        if title:
            name = re.sub(r'\s*[-|].*$', '', title.group(1).strip())
            name = re.sub(r'^Пользователи с картой\s*', '', name)
            name = re.sub(r'^Карта\s*', '', name)
            return name.strip() or "?"
    except:
        pass
    return "?"


# Кэш для названий карт
card_name_cache = {}
card_name_cache_time = {}
CACHE_TTL = 300  # 5 минут

def get_card_name_cached(api, card_id):
    """Получение названия карты с кэшированием"""
    current_time = time.time()
    
    # Проверяем кэш
    if card_id in card_name_cache:
        cache_time = card_name_cache_time.get(card_id, 0)
        if current_time - cache_time < CACHE_TTL:
            return card_name_cache[card_id]
    
    # Получаем название
    name = get_card_name(api, card_id)
    
    # Сохраняем в кэш
    card_name_cache[card_id] = name
    card_name_cache_time[card_id] = current_time
    
    return name


# ============================================================
# МУЛЬТИВКЛАД (ПАРАЛЛЕЛЬНАЯ ВЕРСИЯ)
# ============================================================
check_running = False
check_stop = threading.Event()

def check_single_account(account, club_slug, account_stats, current_card_name, current_progress):
    """Проверка одного аккаунта (для параллельного выполнения)"""
    acc_name = account.get("name", "unknown")
    
    # Добавляем небольшую случайную задержку перед началом
    time.sleep(random.uniform(0.5, 1.5))
    
    try:
        api = MangaBuffAPI(account)
        
        # Проверяем авторизацию
        ok, user_id = api.check_auth()
        if not ok:
            print(f"[MULTI] ❌ {acc_name}: не авторизован")
            account_stats[acc_name]["errors"] += 1
            return None
        
        # Получаем информацию о карте
        acc_club_info = parse_club_boost(api, club_slug)
        
        if not acc_club_info["has_card"]:
            print(f"[MULTI] ⏳ {acc_name}: карты нет")
            return None
        
        # Есть карта - жертвуем!
        print(f"[MULTI] ✅ {acc_name}: карта есть! Жертвуем...")
        result = donate_card_to_club(api, club_slug)
        
        if result["success"]:
            account_stats[acc_name]["donated"] += 1
            account_stats[acc_name]["errors"] = 0
            
            # Получаем обновленный прогресс
            updated_info = parse_club_boost(api, club_slug)
            new_progress = f"{updated_info['donated']}/{updated_info['needed']}"
            
            print(f"[MULTI] 🎁 {acc_name}: пожертвовано!")
            
            return {
                "success": True,
                "name": acc_name,
                "new_progress": new_progress
            }
        else:
            print(f"[MULTI] ❌ {acc_name}: ошибка - {result['error']}")
            account_stats[acc_name]["errors"] += 1
            return None
            
    except Exception as e:
        print(f"[MULTI] ❌ {acc_name}: исключение - {e}")
        account_stats[acc_name]["errors"] += 1
        return None


def check_accounts_cycle(chat_id, club_slug, interval=45, account_delay=3):
    """Цикл проверки всех аккаунтов параллельно"""
    global check_running
    check_running = True
    check_stop.clear()
    
    accounts = load_accounts()
    if not accounts:
        bot.send_message(chat_id, "❌ Нет аккаунтов для мультивклада!")
        check_running = False
        return
    
    # Фильтруем только валидные аккаунты
    valid_accounts = [a for a in accounts if a.get("status") == "valid"]
    if not valid_accounts:
        bot.send_message(chat_id, "❌ Нет валидных аккаунтов!")
        check_running = False
        return
    
    max_workers = config.get("max_workers", 2)  # УМЕНЬШЕНО до 2
    print(f"\n[MULTI] Запуск мультивклада (ЩАДЯЩИЙ РЕЖИМ): {len(valid_accounts)} аккаунтов")
    print(f"[MULTI] Клуб: {club_slug}, интервал: {interval}с, потоков: {max_workers}")
    bot.send_message(chat_id, f"✅ Мультивклад запущен (ЩАДЯЩИЙ РЕЖИМ)\n👥 Аккаунтов: {len(valid_accounts)}\n⚙️ Потоков: {max_workers}\n🏠 {club_slug}\n⏱ Интервал: {interval}с")
    
    total_donated = 0
    cycle = 0
    account_stats = {acc.get("name", f"acc_{i}"): {"donated": 0, "errors": 0} for i, acc in enumerate(valid_accounts)}
    current_card_id = None
    current_card_name = ""
    
    while not check_stop.is_set() and check_running:
        cycle += 1
        print(f"\n[MULTI] === Цикл {cycle} ===")
        
        # Получаем информацию о текущей карте (используем первый аккаунт для проверки)
        first_api = MangaBuffAPI(valid_accounts[0])
        club_info = parse_club_boost(first_api, club_slug)
        
        if not club_info["card_id"]:
            print(f"[MULTI] ❌ Карта не найдена, ждем {interval}с")
            check_stop.wait(interval)
            continue
        
        card_id = club_info["card_id"]
        progress = f"{club_info['donated']}/{club_info['needed']}"
        
        # Обновляем название карты если сменилась (с кэшем)
        if card_id != current_card_id:
            current_card_name = get_card_name_cached(first_api, card_id)
            current_card_id = card_id
            print(f"[MULTI] Новая карта: {current_card_name} (ID:{card_id}) {progress}")
            bot.send_message(chat_id, f"🃏 Новая карта: {current_card_name}\n📊 {progress}")
        
        # ПАРАЛЛЕЛЬНАЯ ПРОВЕРКА АККАУНТОВ
        print(f"[MULTI] Запуск проверки {len(valid_accounts)} аккаунтов (макс. {max_workers} потоков)...")
        
        # Перемешиваем аккаунты для равномерной нагрузки
        random.shuffle(valid_accounts)
        
        # Используем ThreadPoolExecutor для параллельной обработки
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for account in valid_accounts:
                if check_stop.is_set():
                    break
                # Добавляем задержку перед отправкой каждой задачи
                time.sleep(account_delay)
                future = executor.submit(check_single_account, account, club_slug, account_stats, current_card_name, progress)
                futures.append(future)
            
            # Собираем результаты по мере завершения
            donation_count_in_cycle = 0
            for future in as_completed(futures):
                if check_stop.is_set():
                    break
                try:
                    result = future.result(timeout=40)  # УВЕЛИЧЕН ТАЙМАУТ
                    if result and result.get("success"):
                        total_donated += 1
                        donation_count_in_cycle += 1
                        acc_name = result.get("name")
                        new_progress = result.get("new_progress")
                        
                        # Отправляем сообщение о пожертвовании (реже, чтобы не спамить)
                        if donation_count_in_cycle <= 2 or donation_count_in_cycle % 4 == 0:
                            bot.send_message(chat_id, 
                                f"🎁 {acc_name} пожертвовал {current_card_name}\n"
                                f"📊 {progress} → {new_progress}\n"
                                f"📈 Всего вкладов: {total_donated}")
                        
                        progress = new_progress
                        
                        # УВЕЛИЧЕНА задержка между отправками сообщений
                        time.sleep(1)
                except Exception as e:
                    print(f"[MULTI] Ошибка при обработке результата: {e}")
        
        print(f"[MULTI] В цикле {cycle} сделано {donation_count_in_cycle} вкладов")
        
        # Пауза перед следующим циклом
        print(f"\n[MULTI] Цикл {cycle} завершен. Ожидание {interval}с до следующего цикла")
        check_stop.wait(interval)
    
    check_running = False
    print(f"\n[MULTI] Остановлен. Всего пожертвований: {total_donated}")
    
    # Отправляем статистику
    stats_msg = f"⏹ Мультивклад остановлен\n🎁 Всего вкладов: {total_donated}\n\nСтатистика по аккаунтам:\n"
    for acc_name, stats in account_stats.items():
        stats_msg += f"• {acc_name}: {stats['donated']} вкладов, {stats['errors']} ошибок\n"
    
    try:
        bot.send_message(chat_id, stats_msg)
    except:
        pass


def _safe_send(chat_id, text, last_time, min_gap=2):
    """Отправляет сообщение с rate limit защитой"""
    now = time.time()
    if now - last_time < min_gap:
        time.sleep(min_gap - (now - last_time))
    try:
        bot.send_message(chat_id, text)
    except Exception as e:
        print(f"[TG] ❌ {e}")


# ============================================================
# БОТ
# ============================================================
load_config()

class BotExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        print(f"\n❌ [BOT ERROR] {exception}")
        traceback.print_exc()
        return True

bot = telebot.TeleBot(config.get("bot_token", BOT_TOKEN), exception_handler=BotExceptionHandler())


def get_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🔍 Мультивклад"),
        types.KeyboardButton("⏹ Стоп"),
    )
    markup.add(
        types.KeyboardButton("👥 Аккаунты"),
        types.KeyboardButton("📊 Статус"),
    )
    markup.add(
        types.KeyboardButton("⚙️ Настройки"),
    )
    return markup


def _get_account():
    accounts = load_accounts()
    club_name = config.get("club_account_name", "")
    if club_name:
        for a in accounts:
            if a.get("name", "").lower() == club_name.lower():
                return a
    valid = [a for a in accounts if a.get("status") == "valid"]
    if valid:
        return valid[0]
    if accounts:
        return accounts[0]
    return None


# --- Слэш-команды ---

@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.send_message(message.chat.id,
        "🤖 MangaBuff Club AutoCheck Bot (ЩАДЯЩИЙ РЕЖИМ)\n\n"
        "📋 **Основные команды:**\n"
        "/multistart — запустить мультивклад\n"
        "/stop — остановить\n"
        "/status — текущий статус\n"
        "/accounts — список аккаунтов\n\n"
        "⚙️ **Настройки:**\n"
        "/setclub slug — установить клуб (например: sumerechniy-rassvet)\n"
        "/setinterval N — интервал между циклами (сек, мин. 10)\n"
        "/setworkers N — количество потоков (1-5)\n\n"
        "👤 **Управление аккаунтами:**\n"
        "/addacc email password host:port:user:pass — добавить аккаунт\n"
        "/setproxy имя host:port:user:pass — сменить прокси\n"
        "/delacc имя — удалить аккаунт\n\n"
        "Или используйте кнопки меню ниже 👇",
        reply_markup=get_keyboard(),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=['multistart'])
def cmd_multistart(message):
    """Запуск мультивклада через слэш-команду"""
    global check_running
    chat_id = message.chat.id
    
    club_slug = config.get("club_slug", "")
    if not club_slug:
        bot.send_message(chat_id, "❌ Клуб не настроен! /setclub slug")
        return
    
    if check_running:
        bot.send_message(chat_id, "⚠️ Мультивклад уже запущен! Нажми /stop")
        return
    
    accounts = load_accounts()
    valid_accounts = [a for a in accounts if a.get("status") == "valid"]
    if not valid_accounts:
        bot.send_message(chat_id, "❌ Нет валидных аккаунтов! /addacc")
        return
    
    interval = config.get("check_interval", 45)
    max_workers = config.get("max_workers", 2)
    
    bot.send_message(chat_id, f"🚀 Запуск мультивклада (ЩАДЯЩИЙ РЕЖИМ)\n"
                             f"👥 Аккаунтов: {len(valid_accounts)}\n"
                             f"⚙️ Потоков: {max_workers}\n"
                             f"🏠 Клуб: {club_slug}\n"
                             f"⏱ Интервал циклов: {interval}с")
    
    threading.Thread(
        target=check_accounts_cycle,
        args=(chat_id, club_slug, interval, config.get("account_delay", 3)),
        daemon=True
    ).start()


@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    """Остановка мультивклада через слэш-команду"""
    global check_running
    chat_id = message.chat.id
    
    if check_running:
        check_stop.set()
        check_running = False
        bot.send_message(chat_id, "⏹ Мультивклад остановлен")
    else:
        bot.send_message(chat_id, "ℹ️ Мультивклад не запущен")


@bot.message_handler(commands=['status'])
def cmd_status(message):
    """Статус через слэш"""
    chat_id = message.chat.id
    accounts = load_accounts()
    valid_count = len([a for a in accounts if a.get("status") == "valid"])
    club_slug = config.get("club_slug", "")
    interval = config.get("check_interval", 45)
    max_workers = config.get("max_workers", 2)
    status = "🟢 Запущен" if check_running else "🔴 Остановлен"
    
    bot.send_message(chat_id,
        f"📊 **Текущий статус**\n\n"
        f"{status}\n"
        f"👥 Всего аккаунтов: {len(accounts)}\n"
        f"✅ Валидных: {valid_count}\n"
        f"🏠 Клуб: {club_slug or 'не задан'}\n"
        f"⏱ Интервал циклов: {interval}с\n"
        f"⚙️ Параллельных потоков: {max_workers}",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=['accounts'])
def cmd_accounts(message):
    """Список аккаунтов через слэш"""
    chat_id = message.chat.id
    accounts = load_accounts()
    
    if not accounts:
        bot.send_message(chat_id, "📋 Нет аккаунтов\n/addacc email password host:port:user:pass")
        return
    
    lines = ["👥 **Список аккаунтов:**\n"]
    for i, a in enumerate(accounts, 1):
        proxy = f"{a.get('proxy_host','')}:{a.get('proxy_port','')}" if a.get('proxy_host') else "нет"
        status = a.get('status', '?')
        user_id = a.get('user_id', '?')
        status_emoji = "✅" if status == "valid" else "❌"
        lines.append(f"{i}. {status_emoji} **{a.get('name','?')}**\n"
                    f"   └ ID: {user_id}, Прокси: {proxy}")
    
    bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['setclub'])
def cmd_setclub(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Использование: /setclub sumerechniy-rassvet")
        return
    config["club_slug"] = parts[1].strip()
    save_config()
    bot.send_message(message.chat.id, f"✅ Клуб установлен: {config['club_slug']}")


@bot.message_handler(commands=['setinterval'])
def cmd_setinterval(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Использование: /setinterval 45")
        return
    try:
        val = int(parts[1])
        if val < 10:  # УВЕЛИЧЕНО минимальное значение
            val = 10
        config["check_interval"] = val
        save_config()
        bot.send_message(message.chat.id, f"✅ Интервал между циклами: {val}с")
    except:
        bot.send_message(message.chat.id, "❌ Введите число!")


@bot.message_handler(commands=['setworkers'])
def cmd_setworkers(message):
    """Установка количества параллельных потоков"""
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Использование: /setworkers 2")
        return
    try:
        val = int(parts[1])
        if val < 1:
            val = 1
        if val > 5:  # УМЕНЬШЕНО максимальное значение
            val = 5
        config["max_workers"] = val
        save_config()
        bot.send_message(message.chat.id, f"✅ Максимум параллельных потоков: {val}")
    except:
        bot.send_message(message.chat.id, "❌ Введите число!")


@bot.message_handler(commands=['addacc'])
def cmd_addacc(message):
    """Добавляет аккаунт: /addacc email password [proxy]"""
    chat_id = message.chat.id
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        bot.send_message(chat_id, "📝 Использование: /addacc email password host:port:user:pass\n"
                                 "Пример: /addacc 0508719526@mail.ru 12345678aze! 45.94.228.73:8000:uaYsD5:AhoS7U")
        return
    
    email = parts[1]
    password = parts[2]
    proxy_str = parts[3] if len(parts) > 3 else ""
    
    proxy_host, proxy_port, proxy_user, proxy_pass = "", "", "", ""
    if proxy_str:
        pp = proxy_str.split(":")
        if len(pp) >= 2:
            proxy_host, proxy_port = pp[0], pp[1]
        if len(pp) >= 4:
            proxy_user, proxy_pass = pp[2], pp[3]
    
    proxy_info = f"{proxy_host}:{proxy_port}" if proxy_host else "без прокси"
    bot.send_message(chat_id, f"🔄 Вхожу: {email}\n🌐 Прокси: {proxy_info}")
    
    temp_acc = {
        "name": email.split("@")[0],
        "proxy_host": proxy_host, 
        "proxy_port": proxy_port,
        "proxy_user": proxy_user, 
        "proxy_pass": proxy_pass,
        "cookies": []
    }
    api = MangaBuffAPI(temp_acc)
    success, result = api.login(email, password)
    
    if success:
        uid = result["user_id"]
        acc_name = email.split("@")[0]
        
        # Конвертируем proxy_port в int если возможно
        proxy_port_int = 0
        if proxy_port and proxy_port.isdigit():
            proxy_port_int = int(proxy_port)
        
        new_acc = {
            "id": hashlib.md5(f"{email}{time.time()}".encode()).hexdigest()[:8],
            "name": acc_name,
            "email": email,
            "proxy_host": proxy_host,
            "proxy_port": proxy_port_int,
            "proxy_user": proxy_user,
            "proxy_pass": proxy_pass,
            "cookies": result["cookies"],
            "status": "valid",
            "user_id": uid,
        }
        accounts = load_accounts()
        # Удаляем старый с таким email/именем
        accounts = [a for a in accounts if a.get("name") != acc_name and a.get("email") != email]
        accounts.append(new_acc)
        save_accounts(accounts)
        
        bot.send_message(chat_id, f"✅ Аккаунт {acc_name} добавлен!\n👤 user_id: {uid}")
    else:
        bot.send_message(chat_id, f"❌ Ошибка входа: {result}")


@bot.message_handler(commands=['setproxy'])
def cmd_setproxy(message):
    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "❌ Использование: /setproxy имя host:port:user:pass")
        return
    name = parts[1]
    proxy_parts = parts[2].split(":")
    
    accounts = load_accounts()
    for a in accounts:
        if a.get("name") == name:
            a["proxy_host"] = proxy_parts[0] if len(proxy_parts) > 0 else ""
            a["proxy_port"] = int(proxy_parts[1]) if len(proxy_parts) > 1 and proxy_parts[1].isdigit() else 0
            a["proxy_user"] = proxy_parts[2] if len(proxy_parts) > 2 else ""
            a["proxy_pass"] = proxy_parts[3] if len(proxy_parts) > 3 else ""
            save_accounts(accounts)
            bot.send_message(message.chat.id, f"✅ Прокси для {name} обновлён")
            return
    bot.send_message(message.chat.id, f"❌ Аккаунт {name} не найден")


@bot.message_handler(commands=['delacc'])
def cmd_delacc(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Использование: /delacc имя")
        return
    name = parts[1]
    accounts = load_accounts()
    before = len(accounts)
    accounts = [a for a in accounts if a.get("name") != name]
    if len(accounts) < before:
        save_accounts(accounts)
        bot.send_message(message.chat.id, f"✅ Аккаунт {name} удалён")
    else:
        bot.send_message(message.chat.id, f"❌ Аккаунт {name} не найден")


# --- Обработчик кнопок ---
@bot.message_handler(func=lambda m: m.text and m.text in ["🔍 Мультивклад", "⏹ Стоп", "👥 Аккаунты", "📊 Статус", "⚙️ Настройки"])
def handle_buttons(message):
    text = message.text
    chat_id = message.chat.id
    print(f"[BTN] {text} от {chat_id}")
    
    if text == "🔍 Мультивклад":
        global check_running
        club_slug = config.get("club_slug", "")
        if not club_slug:
            bot.send_message(chat_id, "❌ Клуб не настроен! /setclub slug")
            return
        if check_running:
            bot.send_message(chat_id, "⚠️ Уже запущен! Нажми ⏹ Стоп")
            return
        interval = config.get("check_interval", 45)
        max_workers = config.get("max_workers", 2)
        threading.Thread(
            target=check_accounts_cycle,
            args=(chat_id, club_slug, interval, config.get("account_delay", 3)),
            daemon=True
        ).start()
    
    elif text == "⏹ Стоп":
        if check_running:
            check_stop.set()
            check_running = False
            bot.send_message(chat_id, "⏹ Остановка...")
        else:
            bot.send_message(chat_id, "ℹ️ Мультивклад не запущен")
    
    elif text == "👥 Аккаунты":
        accounts = load_accounts()
        if not accounts:
            bot.send_message(chat_id, "📋 Нет аккаунтов\n/addacc email password host:port:user:pass")
            return
        lines = []
        for i, a in enumerate(accounts, 1):
            proxy = f"{a.get('proxy_host','')}:{a.get('proxy_port','')}" if a.get('proxy_host') else "нет"
            status = a.get('status', '?')
            user_id = a.get('user_id', '?')
            status_emoji = "✅" if status == "valid" else "❌"
            lines.append(f"{i}. {status_emoji} {a.get('name','?')} (user_id={user_id}) proxy={proxy}")
        bot.send_message(chat_id, "👥 Аккаунты:\n" + "\n".join(lines))
    
    elif text == "📊 Статус":
        accounts = load_accounts()
        valid_count = len([a for a in accounts if a.get("status") == "valid"])
        club_slug = config.get("club_slug", "")
        interval = config.get("check_interval", 45)
        max_workers = config.get("max_workers", 2)
        status = "🟢 Запущен" if check_running else "🔴 Остановлен"
        bot.send_message(chat_id,
            f"📊 Статус\n"
            f"{status}\n"
            f"👥 Аккаунтов: {len(accounts)} (✅ {valid_count})\n"
            f"🏠 Клуб: {club_slug or 'не задан'}\n"
            f"⏱ Интервал циклов: {interval}с\n"
            f"⚙️ Параллельных потоков: {max_workers}"
        )
    
    elif text == "⚙️ Настройки":
        interval = config.get("check_interval", 45)
        max_workers = config.get("max_workers", 2)
        bot.send_message(chat_id,
            f"⚙️ Текущие настройки:\n"
            f"⏱ Интервал между циклами: {interval}с\n"
            f"⚙️ Параллельных потоков: {max_workers}\n\n"
            f"Для изменения:\n"
            f"/setinterval N — интервал циклов (мин. 10)\n"
            f"/setworkers N — количество потоков (1-5)"
        )


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    print("🤖 MangaBuff Club AutoCheck Bot (ЩАДЯЩИЙ РЕЖИМ)")
    print("=" * 60)
    
    accounts = load_accounts()
    print(f"📁 Файл аккаунтов: {ACCOUNTS_FILE}")
    print(f"👥 Всего аккаунтов: {len(accounts)}")
    valid_count = len([a for a in accounts if a.get("status") == "valid"])
    print(f"✅ Валидных: {valid_count}")
    print(f"🏠 Клуб: {config.get('club_slug', 'не задан')}")
    print(f"⏱ Интервал циклов: {config.get('check_interval', 45)}с")
    print(f"⚙️ Параллельных потоков: {config.get('max_workers', 2)}")
    print()
    
    token = config.get("bot_token", BOT_TOKEN)
    if not token:
        print("❌ Не указан BOT_TOKEN!")
        print("Укажи его в config_check.json или в переменной BOT_TOKEN в коде")
        sys.exit(1)
    
    print("✅ Бот запущен! Доступные команды:")
    print("   /multistart - запуск мультивклада (ЩАДЯЩИЙ РЕЖИМ)")
    print("   /stop - остановка")
    print("   /status - статус")
    print("   /accounts - список аккаунтов")
    print("   /setclub - установить клуб")
    print("   /setinterval - интервал между циклами (мин. 10)")
    print("   /setworkers - количество потоков (1-5)")
    print("   /addacc - добавить аккаунт")
    print("\n🖱 Или используй кнопки в Telegram")
    print("=" * 60)
    print()
    
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
    except KeyboardInterrupt:
        print("\n⏹ Бот остановлен")
        check_stop.set()