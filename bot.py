import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import schedule
import time
import sqlite3
import logging
from datetime import datetime

TELEGRAM_TOKEN   = "8594887514:AAFfZRau0lQhvm_jthkH7MEj9Rz4A1CKiKs"
TELEGRAM_CHAT_ID = "858417303"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

SUBREDDITS = [
    "H1B", "OPTjobs", "f1visa", "cscareerquestions",
    "india", "indiansabroad", "resumes", "jobs",
    "ITCareerQuestions", "datascience", "forhire",
]

# Широкие ключевые слова — одиночные слова и короткие фразы
KEYWORDS = [
    "resume", "cv", "h1b", "opt", "ats", "visa",
    "job usa", "jobs usa", "work usa", "us job",
    "job search", "callback", "interview",
    "relocate", "relocation", "green card",
    "software engineer", "data analyst", "developer",
    "hiring", "apply", "application", "rejection",
    "linkedin", "cover letter", "job offer",
]

QUORA_QUERIES = [
    "site:quora.com resume USA Indian",
    "site:quora.com H1B resume",
    "site:quora.com OPT job USA",
    "site:quora.com ATS resume India",
]

def init_db():
    conn = sqlite3.connect("seen_posts.db")
    conn.execute("CREATE TABLE IF NOT EXISTS seen_posts (id TEXT PRIMARY KEY, source TEXT, seen_at TEXT)")
    conn.commit()
    conn.close()

def is_seen(post_id):
    conn = sqlite3.connect("seen_posts.db")
    c = conn.cursor()
    c.execute("SELECT id FROM seen_posts WHERE id = ?", (post_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def mark_seen(post_id, source):
    conn = sqlite3.connect("seen_posts.db")
    conn.execute("INSERT OR IGNORE INTO seen_posts VALUES (?, ?, ?)",
                 (post_id, source, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def total_seen():
    conn = sqlite3.connect("seen_posts.db")
    c = conn.cursor()
    c.execute("SELECT source, COUNT(*) FROM seen_posts GROUP BY source")
    rows = c.fetchall()
    conn.close()
    return rows

def get_priority(text):
    text = text.lower()
    hot = ["help", "urgent", "struggling", "no callbacks", "rejected",
           "please review", "roast my", "desperate", "frustrated",
           "no response", "not getting", "advice needed"]
    return "🔴 ГОРЯЧИЙ" if any(w in text for w in hot) else "🟡 ТЁПЛЫЙ"

def send(message):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message,
                  "parse_mode": "Markdown", "disable_web_page_preview": False},
            timeout=10
        )
        if resp.status_code == 200:
            log.info("✅ Telegram OK")
        else:
            log.error(f"❌ Telegram: {resp.text}")
    except Exception as e:
        log.error(f"❌ Telegram: {e}")

def check_reddit():
    log.info("🔍 Reddit...")
    found = 0
    headers = {"User-Agent": "Mozilla/5.0 (compatible; bot/1.0)"}

    for sub in SUBREDDITS:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/new/.rss?limit=20",
                headers=headers, timeout=15
            )
            if resp.status_code != 200:
                log.warning(f"r/{sub}: HTTP {resp.status_code}")
                time.sleep(2)
                continue

            # Парсим XML через ElementTree
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
                log.error(f"r/{sub}: XML parse error")
                continue

            # Пространства имён RSS/Atom
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)
            if not entries:
                entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for entry in entries:
                # ID
                id_el = entry.find("{http://www.w3.org/2005/Atom}id")
                if id_el is None:
                    id_el = entry.find("id")
                if id_el is None:
                    continue
                post_id = f"reddit_{id_el.text.strip()[-12:]}"
                if is_seen(post_id):
                    continue

                # Заголовок
                title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                if title_el is None:
                    title_el = entry.find("title")
                title = title_el.text.strip() if title_el is not None else ""

                # Ссылка
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                if link_el is None:
                    link_el = entry.find("link")
                link = ""
                if link_el is not None:
                    link = link_el.get("href", "") or link_el.text or ""

                # Автор
                author_el = entry.find(".//{http://www.w3.org/2005/Atom}name")
                author = author_el.text if author_el is not None else "unknown"

                # Контент
                content_el = entry.find("{http://www.w3.org/2005/Atom}content")
                if content_el is None:
                    content_el = entry.find("content")
                body = ""
                if content_el is not None and content_el.text:
                    body = BeautifulSoup(content_el.text, "html.parser").get_text()[:500]

                full_text = (title + " " + body).lower()
                if not any(kw in full_text for kw in KEYWORDS):
                    continue

                mark_seen(post_id, "reddit")
                priority = get_priority(title + " " + body)
                body_block = f"\n\n📄 *Текст:*\n{body[:400]}..." if body.strip() else ""

                send(
                    f"{priority}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 *Reddit* r/{sub}\n"
                    f"👤 {author}\n"
                    f"📝 {title}"
                    f"{body_block}\n\n"
                    f"🔗 {link}"
                )
                found += 1
                time.sleep(1)

            time.sleep(4)

        except Exception as e:
            log.error(f"r/{sub}: {e}")

    log.info(f"Reddit: {found} новых")
    return found

def check_quora():
    log.info("🔍 Quora...")
    found = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

    for query in QUORA_QUERIES:
        try:
            resp = requests.get(
                f"https://www.google.com/search?q={requests.utils.quote(query)}&num=5",
                headers=headers, timeout=10
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            for g in soup.select("div.g")[:5]:
                a_tag = g.select_one("a")
                if not a_tag:
                    continue
                link = a_tag.get("href", "")
                if "quora.com" not in link:
                    continue
                title_tag = g.select_one("h3")
                title = title_tag.text if title_tag else "Quora"
                snippet_tag = g.select_one("div.VwiC3b")
                snippet = snippet_tag.text if snippet_tag else ""
                post_id = f"quora_{abs(hash(link))}"
                if is_seen(post_id):
                    continue
                mark_seen(post_id, "quora")
                send(
                    f"{get_priority(title+snippet)}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 *Quora*\n"
                    f"❓ {title[:200]}\n\n"
                    f"📄 {snippet[:400]}\n\n"
                    f"🔗 {link}"
                )
                found += 1
                time.sleep(2)
            time.sleep(6)
        except Exception as e:
            log.error(f"Quora: {e}")

    log.info(f"Quora: {found} новых")

def send_daily_stats():
    rows = total_seen()
    stats = "\n".join([f"  • {src}: {cnt}" for src, cnt in rows]) or "  Пока пусто"
    send(f"📊 *Статистика*\n━━━━━━━━━━━━━━━━━━━━\n{stats}\n\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

def main():
    init_db()
    log.info("🚀 ResumeUSA Monitor v4 запущен!")
    send("🚀 *ResumeUSA Monitor v4 запущен!*\n\n📌 Reddit — каждые 10 минут\n❓ Quora — каждые 30 минут\n\nБуду присылать горячие посты 🔥")

    schedule.every(10).minutes.do(check_reddit)
    schedule.every(30).minutes.do(check_quora)
    schedule.every().day.at("09:00").do(send_daily_stats)

    check_reddit()
    check_quora()

    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
