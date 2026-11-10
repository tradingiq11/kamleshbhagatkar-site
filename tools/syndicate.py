"""Post new articles to Telegram and Blogger after they go live. Run by the build workflow after deploy.

Only articles dated within the last RECENT_DAYS days are posted, once each per platform; posted slugs are
recorded in content/syndicated.json. A platform with missing secrets is skipped, so this is safe to run
before the accounts are set up. Every copy links back to kamleshbhagatkar.com as the original.

Secrets (GitHub repo settings > Secrets and variables > Actions):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID                     (e.g. @kamleshbhagatkar or -100123...)
    BLOGGER_BLOG_ID, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN

Usage:  python3 tools/syndicate.py            (post)
        python3 tools/syndicate.py --dry-run  (show what would be posted; no network, no state change)
"""
import datetime, html, json, os, pathlib, re, sys, urllib.parse, urllib.request

SITE = pathlib.Path(__file__).resolve().parent.parent
BASE = "https://kamleshbhagatkar.com/"
STATE = SITE / "content/syndicated.json"
RECENT_DAYS = 3
DRY = "--dry-run" in sys.argv


def articles():
    for p in sorted((SITE / "content/articles").glob("*.md")):
        m = re.match(r"---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
        meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in m[1].splitlines() if ":" in l)}
        meta["slug"], meta["url"] = p.stem, f"{BASE}articles/{p.stem}.html"
        yield meta


def body_html(slug):
    """The article text as built for the site, without header, author box or share links."""
    page = (SITE / "articles" / f"{slug}.html").read_text(encoding="utf-8")
    return extract_body(page)


def extract_body(page):
    start = page.index('<article class="prose">') + len('<article class="prose">')
    return page[start:page.index('<p class="author-box">', start)].strip()


assert extract_body('<x><article class="prose">\n<p>Hi</p>\n<p class="author-box">a</p>') == "<p>Hi</p>"


def post_json(url, data, headers=None, form=False):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    ctype = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def telegram(a):
    text = (f"<b>{html.escape(a['title'])}</b>\n\n{html.escape(a['summary'])}\n\n"
            f"{html.escape(a.get('category', ''))} · Read: {a['url']}")
    post_json(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
              {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text, "parse_mode": "HTML"})


def blogger(a, token):
    note = f'<p><i>Originally published at <a href="{a["url"]}">kamleshbhagatkar.com</a>.</i></p>'
    post_json(f"https://www.googleapis.com/blogger/v3/blogs/{os.environ['BLOGGER_BLOG_ID']}/posts/",
              {"title": a["title"], "content": note + body_html(a["slug"]) + note, "labels": [a.get("category", "Articles")]},
              {"Authorization": f"Bearer {token}"})


def blogger_token():
    return post_json("https://oauth2.googleapis.com/token", {
        "client_id": os.environ["BLOGGER_CLIENT_ID"], "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
        "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"], "grant_type": "refresh_token"}, form=True)["access_token"]


PLATFORMS = {
    "telegram": (("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"), lambda: None, lambda a, _: telegram(a)),
    "blogger": (("BLOGGER_BLOG_ID", "BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN"), blogger_token, blogger),
}


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).date()  # IST
    recent = [a for a in articles() if (today - datetime.date.fromisoformat(a["date"])).days <= RECENT_DAYS]
    failed = False
    for name, (keys, auth, send) in PLATFORMS.items():
        done = set(state.get(name, []))
        todo = [a for a in recent if a["slug"] not in done]
        if not todo:
            continue
        if not DRY and not all(os.environ.get(k) for k in keys):
            print(f"{name}: skipped, secrets not set ({', '.join(keys)})")
            continue
        try:
            token = None if DRY else auth()
        except Exception as e:
            print(f"{name}: login failed: {e}"); failed = True; continue
        for a in todo:
            if DRY:
                print(f"{name}: would post {a['slug']}"); continue
            try:
                send(a, token)
                done.add(a["slug"]); print(f"{name}: posted {a['slug']}")
            except Exception as e:  # one failure must not block the rest; it retries on the next run
                print(f"{name}: failed {a['slug']}: {e}"); failed = True
        state[name] = sorted(done)
    if not DRY:
        STATE.write_text(json.dumps(state, indent=1) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
