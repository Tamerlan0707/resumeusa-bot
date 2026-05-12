import requests
from bs4 import BeautifulSoup
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

REDDIT_KEYWORDS = [
    "resume review", "resume help", "us resume", "resume for usa",
    "h1b resume", "opt resume", "ats resume", "resume feedback",
    "job search usa", "american resume", "resume critique",
    "roast my resume", "getting callbacks", "no callbacks",
    "resume format usa", "job hunt usa", "f1 visa job",
    "opt job", "h1b job", "resume help india",
]

X_KEYWORDS = [
    "resume help usa", "h1b resume", "opt resume",
    "ats resume india", "resume for us companies",
    "job search usa india", "resume review please",
    "h1b job search", "opt job search usa",
]

QUORA_QUERIES = [
    "site:quora.com resume USA Indian professional",
    "site:quora.com H1B resume tips India",
    "site:quora.com OPT resume US format",
    "site:quora.com ATS resume India US job",
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
    hot = ["please help", "urgent", "need help", "struggling", "no callbacks",
           "not getting", "rejected", "roast my", "help me", "desperate", "frustrated"]
    return "🔴 ГОРЯЧИЙ" if any(w in text.lower() for w in hot) else "🟡 ТЁПЛЫЙ"

def send(message):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            },
            timeout=10
        )
        log.info("✅ Telegram OK" if resp.status_code == 200 else f"❌ {resp.text}")
    except Exception as e:
        log.error(f"❌ Telegram: {e}")

def check_reddit():
    log.info("🔍 Reddit...")
    found = 0
    for sub in SUBREDDITS:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/new/.rss?limit=25",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15
            )
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for entry in soup.find_all("entry"):
                pid_tag = entry.find("id")
                if not pid_tag:
                    continue
                post_id = f"reddit_{pid_tag.text.strip()[-10:]}"
                if is_seen(post_id):
                    continue

                title = entry.find("title").text.strip() if entry.find("title") else ""
                link_tag = entry.find("link")
                link = link_tag.get("href", "") if link_tag else ""
                content_tag = entry.find("content")
                body = BeautifulSoup(content_tag.text, "html.parser").get_text()[:600].strip() if content_tag else ""
                author_tag = entry.find("author")
                name_tag = author_tag.find("name") if author_tag else None
                author = name_tag.text if name_tag else "unknown"

                if not any(kw in (title + " " + body).lower() for kw in REDDIT_KEYWORDS):
                    continue

                mark_seen(post_id, "reddit")
                priority = get_priority(title + " " + body)
                body_block = f"\n\n📄 *Текст:*\n{body}..." if body else ""

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
            time.sleep(3)
        except Exception as e:
            log.error(f"r/{sub}: {e}")
    log.info(f"Reddit: {found} новых")

def check_x():
    log.info("🔍 X...")
    found = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
    nitter_instances = [
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
        "https://nitter.net",
    ]
    for keyword in X_KEYWORDS[:5]:
        try:
            query = requests.utils.quote(f"{keyword} lang:en")
            resp = None
            for instance in nitter_instances:
                try:
                    resp = requests.get(f"{instance}/search?q={query}&f=tweets", headers=headers, timeout=10)
                    if resp.status_code == 200:
                        break
                except:
                    continue
            if not resp or resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for tweet in soup.select(".timeline-item")[:8]:
                link_tag = tweet.select_one(".tweet-link")
                if not link_tag:
                    continue
                tweet_path = link_tag.get("href", "")
                tweet_id = f"x_{abs(hash(tweet_path))}"
                if is_seen(tweet_id):
                    continue

                text_tag = tweet.select_one(".tweet-content")
                text = text_tag.get_text().strip()[:500] if text_tag else ""
                user_tag = tweet.select_one(".username")
                username = user_tag.get_text().strip() if user_tag else "unknown"
                date_tag = tweet.select_one(".tweet-date a")
                date_str = date_tag.get_text().strip() if date_tag else ""

                mark_seen(tweet_id, "x")
                send(
                    f"{get_priority(text)}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 *X (Twitter)*\n"
                    f"👤 {username}  🕐 {date_str}\n"
                    f"🔑 *Запрос:* {keyword}\n\n"
                    f"📝 {text}\n\n"
                    f"🔗 https://x.com{tweet_path}"
                )
                found += 1
                time.sleep(1)
            time.sleep(4)
        except Exception as e:
            log.error(f"X '{keyword}': {e}")
    log.info(f"X: {found} новых")

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
                    f"{get_priority(title + snippet)}\n"
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
    stats = "\n".join([f"  • {src}: {cnt} постов" for src, cnt in rows]) or "  Пока пусто"
    send(f"📊 *Статистика ResumeUSA Monitor*\n━━━━━━━━━━━━━━━━━━━━\n{stats}\n\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

def main():
    init_db()
    send("🚀 *ResumeUSA Monitor запущен!*\n\n📌 Reddit — каждые 10 минут\n🐦 X — каждые 15 минут\n❓ Quora — каждые 30 минут\n\nБуду присылать горячие посты 🔥")
    schedule.every(10).minutes.do(check_reddit)
    schedule.every(15).minutes.do(check_x)
    schedule.every(30).minutes.do(check_quora)
    schedule.every().day.at("09:00").do(send_daily_stats)
    check_reddit()
    check_x()
    check_quora()
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
