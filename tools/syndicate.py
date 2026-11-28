"""Post new articles to Telegram, Blogger, LinkedIn, Bluesky, Mastodon, Tumblr and WordPress.com after they go live. Run by the build workflow after deploy.

Only articles dated within the last RECENT_DAYS days are posted, once each per platform; posted slugs are
recorded in content/syndicated.json. A platform with missing secrets is skipped, so this is safe to run
before the accounts are set up. Every copy links back to kamleshbhagatkar.com as the original; the blogs
(Blogger, WordPress.com) get an excerpt and a link, never the full text.

Secrets (GitHub repo settings > Secrets and variables > Actions):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID                     (e.g. @kamleshbhagatkar or -100123...)
    BLOGGER_BLOG_ID, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN
    LINKEDIN_ACCESS_TOKEN                                    (scopes openid profile w_member_social; lasts 60 days, then renew)
    BLUESKY_HANDLE, BLUESKY_APP_PASSWORD                     (an app password, never the main password)
    MASTODON_INSTANCE, MASTODON_TOKEN                        (e.g. https://mastodon.social)
    TUMBLR_BLOG, TUMBLR_CONSUMER_KEY, TUMBLR_CONSUMER_SECRET, TUMBLR_TOKEN, TUMBLR_TOKEN_SECRET
    WPCOM_SITE, WPCOM_TOKEN                                  (e.g. kamleshbhagatkar.wordpress.com)
    WRITEAS_COLLECTION, WRITEAS_TOKEN                        (blog alias, e.g. kamleshbhagatkar)
    FACEBOOK_PAGE_ID, FACEBOOK_PAGE_TOKEN                    (long-lived Page token; posts to the Page, not a profile)
    PINTEREST_BOARD_ID, PINTEREST_CLIENT_ID, PINTEREST_CLIENT_SECRET, PINTEREST_REFRESH_TOKEN
    ZENODO_TOKEN                                             (new whitepapers become Zenodo DRAFTS; he publishes by hand)
Repo variable (not secret) SYNDICATION_PAUSED=true stops all posting.

Usage:  python3 tools/syndicate.py            (post)
        python3 tools/syndicate.py --dry-run  (show what would be posted; no network, no state change)
        python3 tools/syndicate.py --trim-copies [--apply]  (one-off: list, or with --apply cut, old full-text blog copies to excerpts)
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


def call(method, url, data=None, headers=None, body=None):
    """JSON request with any method; body= sends raw bytes instead (file uploads)."""
    req = urllib.request.Request(url, method=method, data=body if body is not None else (json.dumps(data).encode() if data is not None else None),
                                 headers={"Content-Type": "application/octet-stream" if body is not None else "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


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
              {"title": a["title"], "content": excerpt_html(a), "labels": [a.get("category", "Articles")]},
              {"Authorization": f"Bearer {token}"})


def blogger_token():
    return post_json("https://oauth2.googleapis.com/token", {
        "client_id": os.environ["BLOGGER_CLIENT_ID"], "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
        "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"], "grant_type": "refresh_token"}, form=True)["access_token"]


def note(a):
    return f'<p><i>Originally published at <a href="{a["url"]}">kamleshbhagatkar.com</a>.</i></p>'


MORE = "Continue reading on kamleshbhagatkar.com"
def excerpt_html(a):
    """The note, the first three paragraphs and a link on. The blogs get this, not the full text: Blogger and WordPress.com
    cannot name another site as canonical, so a full copy would compete with the original in Google."""
    paras = re.findall(r"<p>.*?</p>", body_html(a["slug"]), re.S)[:3]
    return note(a) + "".join(paras) + f'<p><b><a href="{a["url"]}">{MORE} →</a></b></p>'


def trim_copies(apply):
    """One-off (--trim-copies, add --apply to write): cut the full-text copies already on Blogger and WordPress.com down to excerpts.
    Only posts carrying this script's "Originally published at" note for an article that still exists are touched."""
    by_slug = {a["slug"]: a for a in articles()}
    def plan(name, url, content):
        m = re.search(r'Originally published at <a[^>]*href="https://kamleshbhagatkar\.com/articles/([a-z0-9-]+)\.html"', content)
        if not m or m[1] not in by_slug:
            print(f"{name}: left alone (not one of ours) {url}"); return None
        if MORE in content:
            print(f"{name}: already an excerpt {url}"); return None
        print(f"{name}: {'trimming' if apply else 'would trim'} {url}")
        return excerpt_html(by_slug[m[1]]) if apply else None
    if all(os.environ.get(k) for k in PLATFORMS["blogger"][0]):
        auth, base, page = {"Authorization": f"Bearer {blogger_token()}"}, f"https://www.googleapis.com/blogger/v3/blogs/{os.environ['BLOGGER_BLOG_ID']}/posts", ""
        while True:
            d = call("GET", f"{base}?maxResults=50&fetchBodies=true{page}", None, auth)
            for p in d.get("items", []):
                new = plan("blogger", p["url"], p.get("content", ""))
                if new:
                    call("PATCH", f"{base}/{p['id']}", {"content": new}, auth); time.sleep(3)
            if not d.get("nextPageToken"):
                break
            page = "&pageToken=" + d["nextPageToken"]
    if all(os.environ.get(k) for k in PLATFORMS["wpcom"][0]):
        auth, base = {"Authorization": f"Bearer {os.environ['WPCOM_TOKEN']}"}, f"https://public-api.wordpress.com/rest/v1.1/sites/{os.environ['WPCOM_SITE']}/posts"
        # shortcut: one page of 100 posts, add paging if the blog ever holds more copies than that before this is run
        for p in call("GET", f"{base}/?number=100&fields=ID,URL,content", None, auth).get("posts", []):
            new = plan("wpcom", p["URL"], p.get("content", ""))
            if new:
                post_json(f"{base}/{p['ID']}", {"content": new}, auth); time.sleep(3)


def teaser(a, limit):
    """Title, summary and link, cut to the platform's character limit (link always kept whole)."""
    head = f"{a['title']}\n\n{a['summary']}"
    room = limit - len(a["url"]) - 2
    return (head if len(head) <= room else head[:room - 1].rstrip() + "…") + "\n\n" + a["url"]


assert len(teaser({"title": "T" * 400, "summary": "s", "url": "https://x.y/z"}, 300)) <= 300


LINKEDIN_VERSION = "202510"  # LinkedIn API version header (YYYYMM); versions retire after about a year, bump if posts fail with 426


def linkedin_login():
    """The member URN comes from the token itself, so only one secret is needed."""
    req = urllib.request.Request("https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return "urn:li:person:" + json.load(r)["sub"]


def linkedin(a, urn):
    post_json("https://api.linkedin.com/rest/posts", {
        "author": urn, "commentary": f"{a['title']}\n\n{a['summary']}", "visibility": "PUBLIC",
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
    params = {"type": "text", "title": a["title"], "body": excerpt_html(a),
              "tags": "India,geopolitics," + a.get("category", ""), "source_url": a["url"]}
    post_json(url, params, {"Authorization": oauth1_header("POST", url, params, os.environ["TUMBLR_CONSUMER_KEY"],
              os.environ["TUMBLR_CONSUMER_SECRET"], os.environ["TUMBLR_TOKEN"], os.environ["TUMBLR_TOKEN_SECRET"])}, form=True)


def wpcom(a, _):
    post_json(f"https://public-api.wordpress.com/rest/v1.1/sites/{os.environ['WPCOM_SITE']}/posts/new",
              {"title": a["title"], "content": excerpt_html(a), "excerpt": a["summary"],
               "categories": a.get("category", "Articles"), "tags": "India,geopolitics"},
              {"Authorization": f"Bearer {os.environ['WPCOM_TOKEN']}"})


def md_body(slug):
    t = (SITE / "content/articles" / f"{slug}.md").read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", t, flags=re.S).strip()


def writeas(a, _):
    post_json(f"https://write.as/api/collections/{os.environ['WRITEAS_COLLECTION']}/posts",
              {"title": a["title"], "body": f"*Originally published at [kamleshbhagatkar.com]({a['url']}).*\n\n" + "\n\n".join(md_body(a["slug"]).split("\n\n")[:3]) + f"\n\n**[{MORE} →]({a['url']})**"},
              {"Authorization": f"Token {os.environ['WRITEAS_TOKEN']}"})


def facebook(a, _):
    post_json(f"https://graph.facebook.com/{os.environ['FACEBOOK_PAGE_ID']}/feed",  # unversioned: uses the app's default Graph version
              {"message": f"{a['title']}\n\n{a['summary']}", "link": a["url"], "access_token": os.environ["FACEBOOK_PAGE_TOKEN"]}, form=True)


def pinterest_token():
    basic = base64.b64encode(f"{os.environ['PINTEREST_CLIENT_ID']}:{os.environ['PINTEREST_CLIENT_SECRET']}".encode()).decode()
    return post_json("https://api.pinterest.com/v5/oauth/token", {"grant_type": "refresh_token", "refresh_token": os.environ["PINTEREST_REFRESH_TOKEN"]},
                     {"Authorization": f"Basic {basic}"}, form=True)["access_token"]


def pinterest(a, token):
    post_json("https://api.pinterest.com/v5/pins", {"board_id": os.environ["PINTEREST_BOARD_ID"], "title": a["title"][:100],
              "description": a["summary"][:500], "link": a["url"], "alt_text": a["title"][:500],
              "media_source": {"source_type": "image_url", "url": f"{BASE}images/og/{a['slug']}.png"}}, {"Authorization": f"Bearer {token}"})


def zenodo_drafts(state):
    """Whitepapers without a DOI become Zenodo drafts (never published here: a DOI is permanent). Prints ZENODO_DRAFT lines for the workflow."""
    if DRY or not os.environ.get("ZENODO_TOKEN"):
        return
    auth = {"Authorization": f"Bearer {os.environ['ZENODO_TOKEN']}"}
    done = set(state.get("zenodo", []))
    for p in sorted((SITE / "content/whitepapers").glob("*.md")):
        m = re.match(r"---\n(.*?)\n---\n(.*)", p.read_text(encoding="utf-8"), re.S)
        meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in m[1].splitlines() if ":" in l)}
        if meta.get("doi") or p.stem in done:
            continue
        try:
            d = call("POST", "https://zenodo.org/api/deposit/depositions", {}, auth)
            pdf = SITE / "downloads/whitepapers" / meta["pdf"]
            call("PUT", f"{d['links']['bucket']}/{urllib.parse.quote(meta['pdf'])}", headers=auth, body=pdf.read_bytes())
            call("PUT", f"https://zenodo.org/api/deposit/depositions/{d['id']}", {"metadata": {
                "upload_type": "publication", "publication_type": "report", "title": meta["title"], "publication_date": meta["date"],
                "creators": [{"name": "Bhagatkar, Kamlesh", "affiliation": "Independent researcher"}], "access_right": "open",
                "description": html.escape(m[2].strip()).replace("\n\n", "<br><br>"), "keywords": ["India", "national security", "geopolitics"],
                "related_identifiers": [{"identifier": f"{BASE}whitepapers/{p.stem}.html", "relation": "isIdenticalTo"}]}}, auth)
            done.add(p.stem); print(f"ZENODO_DRAFT {p.stem} {d['links']['html']}")
        except Exception as e:
            print(f"zenodo: failed {p.stem}: {e}")
    state["zenodo"] = sorted(done)


PLATFORMS = {
    "telegram": (("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"), lambda: None, lambda a, _: telegram(a)),
    "blogger": (("BLOGGER_BLOG_ID", "BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN"), blogger_token, blogger),
    "linkedin": (("LINKEDIN_ACCESS_TOKEN",), linkedin_login, linkedin),
    "bluesky": (("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"), bluesky_login, bluesky),
    "mastodon": (("MASTODON_INSTANCE", "MASTODON_TOKEN"), lambda: None, mastodon),
    "tumblr": (("TUMBLR_BLOG", "TUMBLR_CONSUMER_KEY", "TUMBLR_CONSUMER_SECRET", "TUMBLR_TOKEN", "TUMBLR_TOKEN_SECRET"), lambda: None, tumblr),
    "wpcom": (("WPCOM_SITE", "WPCOM_TOKEN"), lambda: None, wpcom),
    "writeas": (("WRITEAS_COLLECTION", "WRITEAS_TOKEN"), lambda: None, writeas),
    "facebook": (("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"), lambda: None, facebook),
    "pinterest": (("PINTEREST_BOARD_ID", "PINTEREST_CLIENT_ID", "PINTEREST_CLIENT_SECRET", "PINTEREST_REFRESH_TOKEN"), pinterest_token, pinterest),
}


def main():
    if os.environ.get("SYNDICATION_PAUSED", "").strip().lower() in ("1", "true", "yes", "on"):
        print("syndication paused (repo variable SYNDICATION_PAUSED)"); return
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
                time.sleep(5)  # Blogger returned 429 after 5 quick posts in a row
                done.add(a["slug"]); print(f"{name}: posted {a['slug']}")
            except Exception as e:  # one failure must not block the rest; it retries on the next run
                detail = e.read().decode(errors="replace")[:300] if hasattr(e, "read") else ""  # the site's own reason, e.g. API disabled
                print(f"{name}: failed {a['slug']}: {e} {detail}"); failed = True
        state[name] = sorted(done)
    zenodo_drafts(state)
    if not DRY:
        STATE.write_text(json.dumps(state, indent=1) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    trim_copies("--apply" in sys.argv) if "--trim-copies" in sys.argv else main()
