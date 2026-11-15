"""Post new articles to Telegram, Blogger, LinkedIn, Bluesky, Mastodon, Tumblr and WordPress.com after they go live. Run by the build workflow after deploy.

Only articles dated within the last RECENT_DAYS days are posted, once each per platform; posted slugs are
recorded in content/syndicated.json. A platform with missing secrets is skipped, so this is safe to run
before the accounts are set up. Every copy links back to kamleshbhagatkar.com as the original.

Secrets (GitHub repo settings > Secrets and variables > Actions):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID                     (e.g. @kamleshbhagatkar or -100123...)
    BLOGGER_BLOG_ID, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN
    LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN               (urn:li:person:xxxx; token lasts 60 days, then renew)
    BLUESKY_HANDLE, BLUESKY_APP_PASSWORD                     (an app password, never the main password)
    MASTODON_INSTANCE, MASTODON_TOKEN                        (e.g. https://mastodon.social)
    TUMBLR_BLOG, TUMBLR_CONSUMER_KEY, TUMBLR_CONSUMER_SECRET, TUMBLR_TOKEN, TUMBLR_TOKEN_SECRET
    WPCOM_SITE, WPCOM_TOKEN                                  (e.g. kamleshbhagatkar.wordpress.com)

Usage:  python3 tools/syndicate.py            (post)
        python3 tools/syndicate.py --dry-run  (show what would be posted; no network, no state change)
"""
import base64, datetime, hashlib, hmac, html, json, os, secrets, time, pathlib, re, sys, urllib.parse, urllib.request

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


def post_json(url, data, headers=None, form=False, raw=False):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    ctype = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status if raw else json.load(r)


def telegram(a):
    text = (f"<b>{html.escape(a['title'])}</b>\n\n{html.escape(a['summary'])}\n\n"
            f"{html.escape(a.get('category', ''))} · Read: {a['url']}")
    post_json(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
              {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text, "parse_mode": "HTML"})


def blogger(a, token):
    post_json(f"https://www.googleapis.com/blogger/v3/blogs/{os.environ['BLOGGER_BLOG_ID']}/posts/",
              {"title": a["title"], "content": note(a) + body_html(a["slug"]) + note(a), "labels": [a.get("category", "Articles")]},
              {"Authorization": f"Bearer {token}"})


def blogger_token():
    return post_json("https://oauth2.googleapis.com/token", {
        "client_id": os.environ["BLOGGER_CLIENT_ID"], "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
        "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"], "grant_type": "refresh_token"}, form=True)["access_token"]


def note(a):
    return f'<p><i>Originally published at <a href="{a["url"]}">kamleshbhagatkar.com</a>.</i></p>'


def teaser(a, limit):
    """Title, summary and link, cut to the platform's character limit (link always kept whole)."""
    head = f"{a['title']}\n\n{a['summary']}"
    room = limit - len(a["url"]) - 2
    return (head if len(head) <= room else head[:room - 1].rstrip() + "…") + "\n\n" + a["url"]


assert len(teaser({"title": "T" * 400, "summary": "s", "url": "https://x.y/z"}, 300)) <= 300


LINKEDIN_VERSION = "202510"  # LinkedIn API version header (YYYYMM); versions retire after about a year, bump if posts fail with 426


def linkedin(a, _):
    post_json("https://api.linkedin.com/rest/posts", {
        "author": os.environ["LINKEDIN_PERSON_URN"], "commentary": f"{a['title']}\n\n{a['summary']}", "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "content": {"article": {"source": a["url"], "title": a["title"], "description": a["summary"]}},
        "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False},
        {"Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}", "LinkedIn-Version": LINKEDIN_VERSION,
         "X-Restli-Protocol-Version": "2.0.0"}, raw=True)


def bluesky_login():
    return post_json("https://bsky.social/xrpc/com.atproto.server.createSession",
                     {"identifier": os.environ["BLUESKY_HANDLE"], "password": os.environ["BLUESKY_APP_PASSWORD"]})


def bluesky(a, session):
    text = f"{a['title']}\n\n{a['summary']}"
    text = text if len(text) <= 290 else text[:289].rstrip() + "…"  # link goes in the card, not the text
    post_json("https://bsky.social/xrpc/com.atproto.repo.createRecord", {"repo": session["did"], "collection": "app.bsky.feed.post",
              "record": {"$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                         "langs": ["en"], "embed": {"$type": "app.bsky.embed.external",
                         "external": {"uri": a["url"], "title": a["title"], "description": a["summary"]}}}},
              {"Authorization": f"Bearer {session['accessJwt']}"})


def mastodon(a, _):
    post_json(os.environ["MASTODON_INSTANCE"].rstrip("/") + "/api/v1/statuses", {"status": teaser(a, 480), "language": "en"},
              {"Authorization": f"Bearer {os.environ['MASTODON_TOKEN']}", "Idempotency-Key": a["slug"]})


def oauth1_header(method, url, params, ck, cs, tk, ts):
    """OAuth 1.0a HMAC-SHA1 Authorization header (Tumblr's posting API)."""
    q = lambda v: urllib.parse.quote(str(v), safe="~-._")
    oauth = {"oauth_consumer_key": ck, "oauth_nonce": secrets.token_hex(16), "oauth_signature_method": "HMAC-SHA1",
             "oauth_timestamp": str(int(time.time())), "oauth_token": tk, "oauth_version": "1.0"}
    pairs = sorted((q(k), q(v)) for k, v in {**params, **oauth}.items())
    base = "&".join([method, q(url), q("&".join(f"{k}={v}" for k, v in pairs))])
    oauth["oauth_signature"] = base64.b64encode(hmac.new(f"{q(cs)}&{q(ts)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(oauth.items()))


assert oauth1_header("POST", "https://a.b/c", {"x": "1 2"}, "k", "s", "t", "u").startswith('OAuth oauth_consumer_key="k"')


def tumblr(a, _):
    url = f"https://api.tumblr.com/v2/blog/{os.environ['TUMBLR_BLOG']}/post"
    params = {"type": "text", "title": a["title"], "body": note(a) + body_html(a["slug"]) + note(a),
              "tags": "India,geopolitics," + a.get("category", ""), "source_url": a["url"]}
    post_json(url, params, {"Authorization": oauth1_header("POST", url, params, os.environ["TUMBLR_CONSUMER_KEY"],
              os.environ["TUMBLR_CONSUMER_SECRET"], os.environ["TUMBLR_TOKEN"], os.environ["TUMBLR_TOKEN_SECRET"])}, form=True)


def wpcom(a, _):
    post_json(f"https://public-api.wordpress.com/rest/v1.1/sites/{os.environ['WPCOM_SITE']}/posts/new",
              {"title": a["title"], "content": note(a) + body_html(a["slug"]) + note(a), "excerpt": a["summary"],
               "categories": a.get("category", "Articles"), "tags": "India,geopolitics"},
              {"Authorization": f"Bearer {os.environ['WPCOM_TOKEN']}"})


PLATFORMS = {
    "telegram": (("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"), lambda: None, lambda a, _: telegram(a)),
    "blogger": (("BLOGGER_BLOG_ID", "BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN"), blogger_token, blogger),
    "linkedin": (("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN"), lambda: None, linkedin),
    "bluesky": (("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"), bluesky_login, bluesky),
    "mastodon": (("MASTODON_INSTANCE", "MASTODON_TOKEN"), lambda: None, mastodon),
    "tumblr": (("TUMBLR_BLOG", "TUMBLR_CONSUMER_KEY", "TUMBLR_CONSUMER_SECRET", "TUMBLR_TOKEN", "TUMBLR_TOKEN_SECRET"), lambda: None, tumblr),
    "wpcom": (("WPCOM_SITE", "WPCOM_TOKEN"), lambda: None, wpcom),
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
