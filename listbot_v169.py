#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import cloudscraper
from bs4 import BeautifulSoup
import json
import time
import random
import os
import re
import threading
from datetime import date, datetime

# ================== НАСТРОЙКИ ==================

TOKEN = "8510221632:AAF4BIEAh-LNZGvyJd3tFWjVhyOFnd7YftY"
CHAT_ID = "-1003396992260"
CHANNEL_ID = "@test5557555"       # канал для информации (текст)
PHOTO_CHANNEL_ID = "@homevia7"    # канал для фото

# Контакты для подписи в каждом объявлении
CONTACT_PHONE = "+374 41 08 22 09"
CONTACT_TELEGRAM = "@uslen7"

URL = "https://www.list.am/category/63?n=0&sname=&s=&cmtype=0&crc=&price1=&price2="

DATA_FILE = "sent_ids.json"
LAST_TODAY_ID_FILE = "last_today_id.txt"
LOG_FILE = "log.txt"
PENDING_FILE = "pending_publish.json"

CHECK_INTERVAL = 60       # было 35
TOP_ITEMS = 8

REQUEST_DELAY_MIN = 12    # было 8
REQUEST_DELAY_MAX = 20    # было 15

MAIN_PAGE_DELAY_MIN = 10  # было 5
MAIN_PAGE_DELAY_MAX = 20  # было 10

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]

# ================== ЛОГ ==================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass

# ================== PENDING ==================

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return {}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_pending(data):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Ошибка save_pending: {e}")

# ================== TELEGRAM ==================

def send_to_telegram(text, reply_markup=None):
    try:
        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=payload,
            timeout=15
        )
        if r.status_code == 200:
            return r.json().get("result", {}).get("message_id")
        return None
    except Exception as e:
        log(f"Ошибка Telegram sendMessage: {e}")
        return None

def answer_callback(callback_query_id, text="✅"):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
            data={"callback_query_id": callback_query_id, "text": text},
            timeout=10
        )
    except:
        pass

def edit_message_reply_markup(message_id, reply_markup=None):
    try:
        payload = {
            "chat_id": CHAT_ID,
            "message_id": message_id,
        }
        payload["reply_markup"] = json.dumps(reply_markup or {"inline_keyboard": []})
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/editMessageReplyMarkup",
            data=payload,
            timeout=10
        )
    except:
        pass

def crop_top(image_bytes, crop_percent=10):
    """Обрезает верхние crop_percent% фото — убирает логотип list.am."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        top = int(h * crop_percent / 100)
        cropped = img.crop((0, top, w, h))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    except Exception as e:
        log(f"Ошибка обрезки фото: {e}")
        return image_bytes  # если не вышло — возвращаем оригинал

def download_photo(url):
    """Скачивает фото, обрезает логотип сверху и возвращает байты."""
    try:
        sc = make_scraper()
        sc.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        r = sc.get(url, timeout=15)
        if r.status_code == 200 and len(r.content) > 1000:
            return crop_top(r.content, crop_percent=10)
    except Exception as e:
        log(f"Ошибка скачивания фото {url}: {e}")
    return None

def send_media_group_to_channel(caption, photo_urls):
    """Отправить альбом в PHOTO_CHANNEL_ID. Скачиваем фото локально — обходим WEBPAGE_CURL_FAILED."""
    if not photo_urls:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={
                    "chat_id": PHOTO_CHANNEL_ID,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                },
                timeout=15
            )
            return r.status_code == 200
        except Exception as e:
            log(f"Ошибка отправки текста в канал фото: {e}")
            return False

    # Скачиваем все фото локально
    photos_bytes = []
    for url in photo_urls[:10]:
        data = download_photo(url)
        if data:
            photos_bytes.append(data)
        if len(photos_bytes) >= 10:
            break

    if not photos_bytes:
        log("⚠️ Не удалось скачать ни одного фото — отправляю текст")
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={"chat_id": PHOTO_CHANNEL_ID, "text": caption,
                      "parse_mode": "HTML"},
                timeout=15
            )
            return r.status_code == 200
        except Exception as e:
            log(f"Ошибка отправки текста: {e}")
            return False

    # Одно фото — sendPhoto
    if len(photos_bytes) == 1:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                data={"chat_id": PHOTO_CHANNEL_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("photo.jpg", photos_bytes[0], "image/jpeg")},
                timeout=30
            )
            if r.status_code != 200:
                log(f"sendPhoto ошибка: {r.text[:200]}")
            return r.status_code == 200
        except Exception as e:
            log(f"Ошибка sendPhoto: {e}")
            return False

    # Несколько фото — sendMediaGroup с файлами
    try:
        media = []
        files = {}
        for i, photo_bytes in enumerate(photos_bytes):
            key = f"photo{i}"
            files[key] = (f"{key}.jpg", photo_bytes, "image/jpeg")
            item = {"type": "photo", "media": f"attach://{key}"}
            if i == 0:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media.append(item)

        for attempt in range(4):
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup",
                data={"chat_id": PHOTO_CHANNEL_ID, "media": json.dumps(media)},
                files=files,
                timeout=60
            )
            if r.status_code == 200:
                return True
            resp = r.json()
            if r.status_code == 429:
                wait = resp.get("parameters", {}).get("retry_after", 10)
                log(f"⏳ 429 от Telegram → жду {wait} сек (попытка {attempt+1}/4)")
                time.sleep(wait + 1)
                continue
            log(f"sendMediaGroup ошибка: {r.text[:200]}")
            return False
        return False
    except Exception as e:
        log(f"Ошибка sendMediaGroup: {e}")
        return False

# ================== ID ==================

def load_sent():
    if not os.path.exists(DATA_FILE):
        return set()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()

def save_sent(ids):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(list(ids), f)
    except Exception as e:
        log(f"Ошибка save_sent: {e}")

def load_last_today_id():
    if not os.path.exists(LAST_TODAY_ID_FILE):
        return 0
    try:
        return int(open(LAST_TODAY_ID_FILE).read().strip())
    except:
        return 0

def save_last_today_id(pid):
    try:
        with open(LAST_TODAY_ID_FILE, "w") as f:
            f.write(str(pid))
    except:
        pass

# ================== SCRAPER ==================

# Webshare Rotating Residential прокси
PROXY_PASS = "4303l298seho"
PROXY_LIST = [
    ("iieriqoh-gb-1", "p.webshare.io", 3128),
    ("iieriqoh-ca-2", "p.webshare.io", 3128),
    ("iieriqoh-de-3", "p.webshare.io", 3128),
    ("iieriqoh-fr-4", "p.webshare.io", 3128),
    ("iieriqoh-au-5", "p.webshare.io", 3128),
    ("iieriqoh-nl-6", "p.webshare.io", 3128),
    ("iieriqoh-it-7", "p.webshare.io", 3128),
    ("iieriqoh-es-8", "p.webshare.io", 3128),
    ("iieriqoh-be-9", "p.webshare.io", 3128),
    ("iieriqoh-at-10", "p.webshare.io", 3128),
]

def get_proxy():
    user, host, port = random.choice(PROXY_LIST)
    url = f"http://{user}:{PROXY_PASS}@{host}:{port}"
    return {"http": url, "https": url}

def make_scraper(use_proxy=True):
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.headers.update({
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.list.am/",
        "Connection": "keep-alive",
    })
    if use_proxy:
        proxy = get_proxy()
        if proxy:
            scraper.proxies.update(proxy)
    return scraper

def extract_post_id(href):
    if not href:
        return None
    try:
        return href.split("/")[-1].split("?")[0]
    except:
        return None

# ================== ПАРСИНГ ОБЪЯВЛЕНИЯ ==================

def get_post_details(scraper, post_url):
    """Парсит страницу объявления. Возвращает все данные включая фото."""
    result = {"date": None, "title": "", "price": "", "description": "", "photos": [], "attrs": {}, "amenities": [], "address": ""}

    for attempt in range(3):
        try:
            sc = make_scraper()  # свежий scraper на каждую попытку
            sc.headers.update({"User-Agent": random.choice(USER_AGENTS)})
            r = sc.get(post_url, timeout=20)

            if r.status_code == 403:
                log(f"403 BLOCKED ({attempt+1}/3)")
                time.sleep(random.uniform(20, 40))
                continue
            if r.status_code == 429:
                wait = random.uniform(60, 120)
                log(f"429 RATE LIMIT → жду {int(wait)} сек")
                time.sleep(wait)
                continue

            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # --- Дата ---
            meta = soup.find("meta", {"itemprop": "datePosted"})
            if meta and meta.get("content"):
                result["date"] = meta["content"][:10]
            else:
                span = soup.find(attrs={"itemprop": "datePosted"})
                if span and span.get("content"):
                    result["date"] = span["content"][:10]

            # --- Заголовок ---
            h1 = soup.find("h1")
            if h1:
                result["title"] = h1.get_text(strip=True)

            # --- Цена ---
            price_el = soup.find(attrs={"itemprop": "price"}) or soup.find(class_="price")
            if price_el:
                result["price"] = price_el.get_text(strip=True)

            # --- Описание ---
            desc_el = soup.find(attrs={"itemprop": "description"}) or soup.find(class_="body")
            if desc_el:
                result["description"] = desc_el.get_text(strip=True)[:800]

            # --- Характеристики: парсим div.bo2.attr-info-wraper ---
            # Структура: каждый блок содержит 2 p.attr-value: [название][значение]
            attrs = {}
            amenities = []  # список удобств (посудомойка, кондиционер и т.д.)

            for block in soup.select("div.bo2.attr-info-wraper"):
                ps = block.select("p.attr-value")
                if len(ps) >= 2:
                    key = ps[0].get_text(strip=True)
                    val = ps[1].get_text(strip=True)
                    if key and val:
                        attrs[key] = val
                elif len(ps) == 1:
                    # Одиночный элемент — это удобство/amenity (посудомойка, кондиционер и т.д.)
                    val = ps[0].get_text(strip=True)
                    if val:
                        amenities.append(val)

            result["attrs"] = attrs
            result["amenities"] = amenities

            # Адрес
            addr_el = soup.find(class_="loc") or soup.find(class_="post-location-title")
            result["address"] = addr_el.get_text(strip=True) if addr_el else ""

            # --- Фотографии ---
            photos = []
            html_text = r.text
            method_used = "none"

            # ДИАГНОСТИКА: сохраняем HTML первый раз для анализа
            debug_path = "/tmp/listam_debug.html"
            import os
            if not os.path.exists(debug_path):
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(html_text)
                log(f"🔍 HTML сохранён в {debug_path} для диагностики")

            # СПОСОБ 1: все f/ URL из <script> тегов (list.am грузит через JS)
            # Ищем паттерны типа: "98645681" или '/f/681/98645681.webp'
            for script in soup.find_all("script"):
                sc_text = script.string or ""
                # Паттерн с полным путём /f/NNN/NNNNNN.webp или .jpg
                found = re.findall(r'["\'](?:https?:)?//s\.list\.am/f/\d+/\d+\.\w+["\']', sc_text)
                for raw in found:
                    url = raw.strip("\"'")
                    if url.startswith("//"):
                        url = "https:" + url
                    if url not in photos:
                        photos.append(url)
                # Паттерн: числовые ID фото через запятую ["123","456"]
                if not photos:
                    nums = re.findall(r'["\'](\d{7,9})["\']', sc_text)
                    for n in nums:
                        folder = n[-3:]
                        url = f"https://s.list.am/f/{folder}/{n}.webp"
                        if url not in photos:
                            photos.append(url)
            if photos:
                method_used = "script_tags"

            # СПОСОБ 2: все /f/ URL прямо в сыром HTML
            if not photos:
                found = re.findall(r'(?:https?:)?//s\.list\.am/f/\d+/\d+\.\w+', html_text)
                for url in found:
                    if url.startswith("//"):
                        url = "https:" + url
                    if url not in photos:
                        photos.append(url)
                if photos:
                    method_used = "raw_html_f"

            # СПОСОБ 3: img теги — src и data-src
            if not photos:
                for img in soup.find_all("img"):
                    for attr in ("data-src", "data-lazy-src", "src"):
                        src = img.get(attr, "")
                        if src and "s.list.am" in src:
                            if src.startswith("//"):
                                src = "https:" + src
                            if src not in photos:
                                photos.append(src)
                if photos:
                    method_used = "img_tags"

            # СПОСОБ 4: og:image
            if not photos:
                for og in soup.find_all("meta", property="og:image"):
                    url = og.get("content", "")
                    if url and url not in photos:
                        photos.append(url)
                if photos:
                    method_used = "og_image"

            # Фильтруем дубли и иконки (маленькие файлы)
            photos = list(dict.fromkeys(photos))  # убираем дубли сохраняя порядок

            log(f"📸 Фото найдено: {len(photos)} шт [метод: {method_used}] → {photos[:2]}")
            result["photos"] = photos[:10]
            return result

        except Exception as e:
            log(f"Ошибка get_post_details ({attempt+1}/3): {e}")
            time.sleep(random.uniform(10, 20))

    return result

# ================== ПУБЛИКАЦИЯ В КАНАЛ (БЕЗ ПОВТОРНОГО ЗАПРОСА) ==================

def build_caption(pending_data):
    """Строит красивый caption по образцу."""
    title     = pending_data.get("title") or "Квартира"
    price     = pending_data.get("price", "")
    attrs     = pending_data.get("attrs", {})
    amenities = pending_data.get("amenities", [])
    address   = pending_data.get("address", "")

    # Армянские ключи из реального HTML list.am
    # attrs = {название_поля: значение}
    def ga(*keys):
        """Возвращает значение по ключу-полю."""
        for k in keys:
            for ak, av in attrs.items():
                if k.lower() in ak.lower():
                    return av
        return ""

    def in_amenities(*keywords):
        """Проверяет наличие удобства в списке amenities."""
        for kw in keywords:
            for a in amenities:
                if kw.lower() in a.lower():
                    return True
        return False

    # Парсим поля
    rooms     = ga("Սենյակների քանակ", "сенякнери", "rooms")
    bathrooms = ga("Սանհանգույցների", "санузл", "bathroom")
    area      = ga("Ընդհանուր մակերես", "площадь", "area")
    floor_num = ga("Հարկ", "этаж", "floor")
    floor_all = ga("Հարկերի քանակ", "всего этажей", "floors total")
    building  = ga("Շինության տիպ", "тип дома", "building")
    new_build = ga("Նորակառույց", "новостройк", "new build")
    balcony   = ga("Պատշգամբ", "балкон", "balcony")
    furniture = ga("Կահույք", "мебель", "furniture")
    renovation= ga("Վերանորոգում", "ремонт", "renovation")

    # Удобства из amenities
    has_ac         = in_amenities("Օդորակիչ", "кондиц", "air cond")
    has_dishwasher = in_amenities("Սպասք լվացող", "посудомо", "dishwasher")
    has_microwave  = in_amenities("Միկրոալիքային", "микровол", "microwave")
    has_washer     = in_amenities("Լվացքի մեքենա", "стиральн", "washing")

    # Новостройка
    is_new = "Այո" in new_build or "նոր" in building.lower() or "new" in building.lower()

    # Этаж — формат "2/4"
    floor_str = ""
    if floor_num and floor_all:
        floor_str = f"{floor_num}/{floor_all}"
    elif floor_num:
        floor_str = floor_num

    lines = []
    lines.append(f"🏠 <b>{title}</b>")
    lines.append("")

    if address:
        lines.append(f"📍 {address}")

    if is_new:
        lines.append("🏢 New building | Новостройка")
    elif building:
        lines.append(f"🏢 {building}")

    if rooms:
        lines.append(f"🛏 {rooms} rooms | {rooms} комнат")
    if bathrooms:
        lines.append(f"🛁 {bathrooms} bathrooms | {bathrooms} санузла")
    if area:
        lines.append(f"📐 {area}")
    if floor_str:
        lines.append(f"🏙 {floor_str} floor | {floor_str} этаж")
    if balcony:
        lines.append(f"🌿 Balcony | Балкон ({balcony})")
    if furniture:
        lines.append(f"🛋 Furniture | Мебель ({furniture})")
    if renovation:
        lines.append(f"✨ Renovation | Ремонт ({renovation})")

    # Техника — только если есть
    if has_dishwasher:
        lines.append("🍽 Dishwasher | Посудомоечная машина")
    if has_microwave:
        lines.append("📡 Microwave | Микроволновка")
    if has_ac:
        lines.append("❄️ Air conditioner | Кондиционер")
    if has_washer:
        lines.append("🫧 Washing machine | Стиральная машина")

    if price:
        lines.append("")
        lines.append(f"💵 {price}")

    lines.append("")
    lines.append(f"📞 WhatsApp / Call: {CONTACT_PHONE}")
    lines.append(f"📩 Telegram  {CONTACT_TELEGRAM}")

    return "\n".join(lines)


def send_text_to_channel(text):
    """Отправляет текстовое сообщение в канал."""
    for attempt in range(4):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={
                    "chat_id": CHANNEL_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15
            )
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 10)
                log(f"⏳ 429 текст → жду {wait} сек")
                time.sleep(wait + 1)
                continue
            log(f"sendMessage канал ошибка: {r.text[:200]}")
            return False
        except Exception as e:
            log(f"Ошибка sendMessage канал: {e}")
            return False
    return False


def publish_photos(post_id, pending_data):
    """Публикует только фото в канал."""
    log(f"📸 Публикую фото: {post_id}")
    photos = pending_data.get("photos", [])
    if not photos:
        log(f"⚠️ Нет фото для: {post_id}")
        return False
    ok = send_media_group_to_channel("", photos)
    if ok:
        log(f"✅ Фото опубликованы: {post_id}")
    else:
        log(f"❌ Ошибка фото: {post_id}")
    return ok


def publish_text(post_id, pending_data):
    """Публикует только текст/информацию в канал."""
    log(f"📋 Публикую информацию: {post_id}")
    caption = build_caption(pending_data)
    ok = send_text_to_channel(caption)
    if ok:
        log(f"✅ Информация опубликована: {post_id}")
    else:
        log(f"❌ Ошибка информации: {post_id}")
    return ok

# ================== ОБРАБОТКА КНОПОК ==================

def handle_callback(callback_query):
    global _publishing_now
    cq_id = callback_query["id"]
    data  = callback_query.get("data", "")
    message    = callback_query.get("message", {})
    message_id = message.get("message_id")

    # Определяем тип действия
    if data.startswith("pub_photo:"):
        action  = "photo"
        post_id = data.split(":", 1)[1]
    elif data.startswith("pub_text:"):
        action  = "text"
        post_id = data.split(":", 1)[1]
    elif data == "done":
        answer_callback(cq_id, "✅")
        return
    else:
        answer_callback(cq_id, "❓ Неизвестная команда")
        return

    lock_key = f"{post_id}_{action}"

    # Защита от двойного нажатия
    with _publish_lock:
        if lock_key in _publishing_now:
            answer_callback(cq_id, "⏳ Уже публикуется, подожди...")
            return
        _publishing_now.add(lock_key)

    try:
        pending = load_pending()

        if post_id not in pending:
            answer_callback(cq_id, "⚠️ Не найдено — возможно уже удалено")
            return

        answer_callback(cq_id, "⏳ Публикую...")
        pending_data = pending[post_id]

        if action == "photo":
            ok = publish_photos(post_id, pending_data)
            done_text = "✅ Фото"
        else:
            ok = publish_text(post_id, pending_data)
            done_text = "✅ Инфо"

        if ok:
            # Обновляем кнопку которую нажали на "✅"
            # Проверяем что уже опубликовано чтобы убрать обе кнопки если всё готово
            pdata = pending[post_id]
            photo_done = pdata.get("photo_published", False)
            text_done  = pdata.get("text_published", False)

            if action == "photo":
                photo_done = True
                pending[post_id]["photo_published"] = True
            else:
                text_done = True
                pending[post_id]["text_published"] = True
            save_pending(pending)

            if photo_done and text_done:
                # Оба опубликованы — убираем кнопки
                edit_message_reply_markup(message_id, {"inline_keyboard": [[
                    {"text": "✅ Фото + Инфо опубликованы", "callback_data": "done"}
                ]]})
                pending = load_pending()
                if post_id in pending:
                    del pending[post_id]
                    save_pending(pending)
            else:
                # Обновляем кнопки — одна стала ✅
                new_buttons = []
                if photo_done:
                    new_buttons.append({"text": "✅ Фото", "callback_data": "done"})
                else:
                    new_buttons.append({"text": "📸 Фото", "callback_data": f"pub_photo:{post_id}"})
                if text_done:
                    new_buttons.append({"text": "✅ Инфо", "callback_data": "done"})
                else:
                    new_buttons.append({"text": "📋 Информация", "callback_data": f"pub_text:{post_id}"})
                edit_message_reply_markup(message_id, {"inline_keyboard": [new_buttons]})
        else:
            answer_callback(cq_id, "❌ Ошибка, попробуй ещё раз")
    finally:
        with _publish_lock:
            _publishing_now.discard(lock_key)

# ================== POLLING ==================

_last_update_id = 0
_publish_lock = threading.Lock()
_publishing_now = set()  # защита от двойной публикации

def poll_updates():
    global _last_update_id
    for attempt in range(3):
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                params={"offset": _last_update_id + 1, "timeout": 5},
                timeout=15
            )
            if r.status_code != 200:
                return
            updates = r.json().get("result", [])
            for update in updates:
                _last_update_id = update["update_id"]
                if "callback_query" in update:
                    threading.Thread(
                        target=handle_callback,
                        args=(update["callback_query"],),
                        daemon=True
                    ).start()
            return  # успех — выходим
        except Exception as e:
            if attempt < 2:
                time.sleep(5)  # небольшая пауза перед retry
            else:
                log(f"Ошибка poll_updates: {e}")

# ================== ПРОВЕРКА ОБЪЯВЛЕНИЙ ==================

def fetch_main_page(sent_ids):
    """Получает главную страницу с retry-логикой. Возвращает текст или None."""
    for attempt in range(5):
        scraper = make_scraper()  # свежий scraper на каждую попытку
        try:
            time.sleep(random.uniform(MAIN_PAGE_DELAY_MIN, MAIN_PAGE_DELAY_MAX))
            scraper.headers.update({"User-Agent": random.choice(USER_AGENTS)})
            r = scraper.get(URL, timeout=30)

            if r.status_code == 403:
                wait = random.uniform(60, 120)
                log(f"⛔ 403 Forbidden на главной ({attempt+1}/5) → жду {int(wait)} сек")
                time.sleep(wait)
                continue

            if r.status_code == 429:
                wait = random.uniform(120, 180)
                log(f"⏳ 429 Rate Limit на главной ({attempt+1}/5) → жду {int(wait)} сек")
                time.sleep(wait)
                continue

            r.raise_for_status()
            return scraper, r.text

        except Exception as e:
            wait = random.uniform(30, 60)
            log(f"Ошибка главной страницы ({attempt+1}/5): {e} → жду {int(wait)} сек")
            time.sleep(wait)

    log("❌ Главная страница недоступна после 5 попыток — пропускаю цикл")
    return None, None


def check_ads_once(scraper, sent_ids):
    scraper, html = fetch_main_page(sent_ids)
    if html is None:
        return

    soup = BeautifulSoup(html, "html.parser")
    all_items = soup.select(".dl .gl a")

    if not all_items:
        log("Объявления не найдены")
        return

    today = date.today().strftime("%Y-%m-%d")
    last_today_id = load_last_today_id()
    pending = load_pending()

    new_items = []
    for item in all_items:
        href = item.get("href") or ""
        pid = extract_post_id(href)
        if not pid:
            continue
        try:
            pid_int = int(pid)
        except:
            continue
        if pid not in sent_ids and pid_int > last_today_id:
            new_items.append((pid, pid_int, item))

    items_to_check = new_items[:TOP_ITEMS]
    log(f"Проверяю {len(items_to_check)} новых объявлений")

    for pid, pid_int, item in items_to_check:
        try:
            href = item.get("href")
            link = "https://www.list.am" + href

            # Парсим ВСЕ данные сразу (один запрос)
            details = get_post_details(scraper, link)

            if not details["date"]:
                log(f"ID {pid} | дата не получена — пропускаю")
                continue

            if details["date"] != today:
                log(f"Пропущено (не сегодня): {pid} | {details['date']}")
                continue

            # Сообщение в личный чат
            text_parts = [f"🏠 <b>Собственник</b>"]
            raw_text = " | ".join([t.strip() for t in item.stripped_strings])
            text_parts.append(raw_text)
            if details["price"]:
                text_parts.append(f"💰 {details['price']}")
            text_parts.append(f"🔗 {link}")
            msg = "\n".join(text_parts)

            keyboard = {
                "inline_keyboard": [[
                    {"text": "📸 Фото", "callback_data": f"pub_photo:{pid}"},
                    {"text": "📋 Информация", "callback_data": f"pub_text:{pid}"}
                ]]
            }

            msg_id = send_to_telegram(msg, reply_markup=keyboard)
            if msg_id:
                log(f"✅ Отправлено: {pid} | фото: {len(details['photos'])}")
                # Сохраняем ВСЕ данные — при публикации повторный запрос не нужен
                pending[pid] = {
                    "link": link,
                    "msg_id": msg_id,
                    "title": details["title"],
                    "price": details["price"],
                    "description": details["description"],
                    "photos": details["photos"],
                    "attrs": details.get("attrs", {}),
                    "amenities": details.get("amenities", []),
                    "address": details.get("address", ""),
                }
                save_pending(pending)
                sent_ids.add(pid)
                save_last_today_id(pid_int)
                save_sent(sent_ids)
            else:
                log(f"❌ Ошибка отправки: {pid}")

            time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

        except Exception as e:
            log(f"Ошибка обработки {pid}: {e}")

    log("Цикл завершён")

# ================== MAIN ==================

def run_forever():
    send_to_telegram("✅ Бот запущен — объявления с кнопкой «Опубликовать в канал»")
    sent_ids = load_sent()
    log(f"Загружено ID: {len(sent_ids)}")

    cycle = 0
    while True:
        try:
            for _ in range(CHECK_INTERVAL // 3):
                poll_updates()
                time.sleep(3)

            check_ads_once(None, sent_ids)
            cycle += 1
        except Exception as e:
            log(f"Глобальная ошибка: {e}")

        log(f"Жду {CHECK_INTERVAL} сек... (цикл {cycle})")

if __name__ == "__main__":
    run_forever()
