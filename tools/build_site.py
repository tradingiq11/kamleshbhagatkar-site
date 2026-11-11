"""Generate the article pages, PDFs, home-page cards, archive, sitemap and RSS feed
from content/articles/*.md.

Usage:  python3 tools/build_site.py            (build everything)
        python3 tools/build_site.py --no-pdf   (skip PDFs, e.g. where Chrome is missing)
        python3 tools/build_site.py --check    (validate articles only, write nothing)

Article file format (content/articles/<slug>.md):
    ---
    title: Headline
    date: 2026-11-10
    category: Geopolitics            (Geopolitics | Current Affairs | Defence | RSS at 100)
    summary: One line for the card.
    description: One sentence for Google (optional, defaults to summary)
    image: images/x.jpg              (optional; cards without one get a typographic panel)
    image_position: 50% 30%          (optional)
    countries: EU, USA               (optional; Geopolitics map highlights, comma-separated)
    place: New Delhi                 (optional; Indian city marked on Current Affairs / Defence maps)
    essay: yes                       (optional; personal essays may skip the Sources list)
    ---
    Body in simple Markdown: paragraphs, ## headings, - lists, > quotes, *italic*, **bold**, [text](https://url).
    End with a "## Sources" list of links.
"""
import datetime, email.utils, hashlib, html, json, math, pathlib, re, shutil, subprocess, sys

SITE = pathlib.Path(__file__).resolve().parent.parent
BASE = "https://kamleshbhagatkar.com/"
CATEGORIES = ["Geopolitics", "Current Affairs", "Defence", "RSS at 100"]
ICON = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m0 0l-5-5m5 5l5-5M4 21h16"/></svg>')
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link href="https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,400;0,700;1,400&family=Oswald:wght@500;600;700&display=swap" rel="stylesheet">')
AUTHOR_BOX = ('Kamlesh Bhagatkar is an author and geopolitical analyst from Nagpur. His first book, <i>RSS: 100 Years of Selfless Service – '
              'Engineers of Glorious Bharat</i> (2025), returns soon in a <a href="../#books">new edition</a>. '
              'His next book, <i>Nineteen Days</i>, on Pahalgam and Operation Sindoor, is coming soon.')

# ---------------------------------------------------------------- markdown subset
def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{m[2].replace(chr(34), "&quot;")}" rel="noopener">{m[1]}</a>', t)  # t is already escaped; only quotes are left
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return t

def markdown(md):
    out = []
    for block in re.split(r"\n\s*\n", md.strip()):
        lines = [l.rstrip() for l in block.strip().splitlines()]
        if lines[0].startswith("## "):
            out.append(f'<p class="h">{inline(lines[0][3:].strip())}</p>')
            lines = lines[1:]
            if not lines:
                continue
        if all(l.lstrip().startswith(("- ", "* ")) for l in lines):
            out.append("<ul>" + "".join(f"<li>{inline(l.lstrip()[2:])}</li>" for l in lines) + "</ul>")
        elif all(l.startswith(">") for l in lines):
            out.append("<blockquote><p>" + inline(" ".join(l[1:].strip() for l in lines)) + "</p></blockquote>")
        else:
            out.append(f"<p>{inline(' '.join(l.strip() for l in lines))}</p>")
    return "\n\n".join(out)

assert markdown("## Head\n\nA *b* **c** [d](https://e.f)\n\n- x\n- y") == \
    '<p class="h">Head</p>\n\n<p>A <i>b</i> <strong>c</strong> <a href="https://e.f" rel="noopener">d</a></p>\n\n<ul><li>x</li><li>y</li></ul>'
assert markdown('[s](https://e.f/?a=1&b=2"x)') == '<p><a href="https://e.f/?a=1&amp;b=2&quot;x" rel="noopener">s</a></p>'  # & once, quote closed off
assert markdown("Tom & Jerry <script>") == "<p>Tom &amp; Jerry &lt;script&gt;</p>"  # raw HTML in articles is never trusted

# ---------------------------------------------------------------- load articles
def load(path):
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not m:
        raise SystemExit(f"{path.name}: missing --- front matter ---")
    meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in m[1].splitlines() if ":" in l)}
    errors = [f"missing {k}" for k in ("title", "date", "category", "summary") if not meta.get(k)]
    if meta.get("category") and meta["category"] not in CATEGORIES:
        errors.append(f"category must be one of {CATEGORIES}")
    try:
        meta["date_obj"] = datetime.date.fromisoformat(meta.get("date", ""))
    except ValueError:
        errors.append("date must be YYYY-MM-DD")
    body = m[2]
    if "## Sources" not in body and meta.get("category") in ("Geopolitics", "Current Affairs") and meta.get("essay") != "yes":
        errors.append("news articles must end with a '## Sources' list")
    if re.search(r"[—–]", body + meta.get("title", "")):
        errors.append("contains em/en dashes (humanizer rule: use commas, colons or full stops)")
    if errors:
        raise SystemExit(f"{path.name}: " + "; ".join(errors))
    meta["slug"] = path.stem
    meta["body"] = markdown(body)
    meta["words"] = len(re.findall(r"\w+", body))
    meta.setdefault("description", meta["summary"])
    meta["url"] = f"{BASE}articles/{meta['slug']}.html"
    return meta

ARTS = sorted((load(p) for p in (SITE / "content/articles").glob("*.md")), key=lambda a: (a["date_obj"], a["slug"][:1].isdigit(), a["slug"]), reverse=True)
if "--check" in sys.argv:
    print(f"OK: {len(ARTS)} articles valid"); sys.exit()

# ---------------------------------------------------------------- card art (maps), for articles without a photo
WORLD = json.loads((SITE / "tools/world.json").read_text())  # simplified Natural Earth, India point-of-view boundaries
EU = ["Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland", "France", "Germany",
      "Greece", "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Poland", "Portugal",
      "Romania", "Slovakia", "Slovenia", "Spain", "Sweden"]
ALIASES = {"usa": "United States of America", "us": "United States of America", "united states": "United States of America",
           "america": "United States of America", "uk": "United Kingdom", "britain": "United Kingdom", "uae": "United Arab Emirates",
           "south korea": "South Korea", "north korea": "North Korea", "czech republic": "Czechia", "serbia": "Republic of Serbia",
           "tanzania": "United Republic of Tanzania", "ivory coast": "Ivory Coast", "burma": "Myanmar"}
CITIES = {"new delhi": (77.21, 28.61), "delhi": (77.21, 28.61), "mumbai": (72.88, 19.08), "nagpur": (79.09, 21.15),
          "bengaluru": (77.59, 12.97), "chennai": (80.27, 13.08), "kolkata": (88.36, 22.57), "hyderabad": (78.49, 17.39),
          "ahmedabad": (72.57, 23.02), "gandhinagar": (72.64, 23.22), "pune": (73.86, 18.52), "lucknow": (80.95, 26.85),
          "jaipur": (75.79, 26.91), "bhopal": (77.41, 23.26), "patna": (85.14, 25.59), "guwahati": (91.74, 26.14),
          "srinagar": (74.80, 34.08), "jammu": (74.86, 32.73), "leh": (77.58, 34.15), "thiruvananthapuram": (76.94, 8.52),
          "kochi": (76.27, 9.93), "bhubaneswar": (85.82, 20.30), "chandigarh": (76.78, 30.73), "sriharikota": (80.23, 13.72),
          "raipur": (81.63, 21.25), "ranchi": (85.31, 23.34), "dehradun": (78.03, 30.32), "shimla": (77.17, 31.10),
          "panaji": (73.83, 15.49), "visakhapatnam": (83.22, 17.69), "imphal": (93.94, 24.82), "port blair": (92.73, 11.62)}

def entities(text):
    """'EU, USA, France' -> [(label, [country names], (lon, lat))] for the map highlights."""
    out = []
    for raw in (t.strip() for t in (text or "").split(",")):
        if not raw:
            continue
        if raw.lower() in ("eu", "european union"):
            out.append(("EU", EU, (9.0, 50.0)))
            continue
        name = ALIASES.get(raw.lower(), next((k for k in WORLD if k.lower() == raw.lower()), None))
        if name and name != "India":
            out.append((name, [name], tuple(WORLD[name]["c"])))
        elif not name:
            print(f"note: unknown country '{raw}' in countries:, ignored")
    return out

def card_art(a):
    W_, H_ = 800, 500
    cat, ents = a["category"], entities(a.get("countries"))
    place = CITIES.get((a.get("place") or "").strip().lower())
    india = tuple(WORLD["India"]["c"])
    if cat == "Geopolitics":
        pts = [india] + [e[2] for e in ents]
        lon0, lon1 = min(p[0] for p in pts) - 18, max(p[0] for p in pts) + 22
        lat0, lat1 = min(p[1] for p in pts) - 16, max(p[1] for p in pts) + 14
        lon0, lon1 = min(lon0, 40), max(lon1, 110)
        lat0, lat1 = min(lat0, -2), max(lat1, 48)
    else:  # India-centred: country on the right, room for the label on the left
        lon0, lon1, lat0, lat1 = 50.0, 101.0, 4.0, 39.0
    k = math.cos(math.radians((lat0 + lat1) / 2))
    # fit to the 8:5 frame by widening whichever side is short
    w_deg, h_deg = (lon1 - lon0) * k, lat1 - lat0
    if w_deg / h_deg < W_ / H_:
        extra = (h_deg * W_ / H_ - w_deg) / k / 2; lon0 -= extra; lon1 += extra
    else:
        extra = (w_deg * H_ / W_ - h_deg) / 2; lat0 -= extra; lat1 += extra
    s = W_ / ((lon1 - lon0) * k)
    P = lambda lon, lat: ((lon - lon0) * k * s, (lat1 - lat) * s)
    def path(name):
        return " ".join("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in (P(*q) for q in ring)) + "Z" for ring in WORLD[name]["r"])
    def visible(name):
        return any(lon0 - 5 < q[0] < lon1 + 5 and lat0 - 5 < q[1] < lat1 + 5 for ring in WORLD[name]["r"] for q in ring[::5])
    hi = {n for e in ents for n in e[1]}
    bg = {"Geopolitics": ("#18283a", "#0d1117"), "Current Affairs": ("#3a1810", "#120c0b"),
          "Defence": ("#202619", "#0e100c"), "RSS at 100": ("#46200b", "#140b07")}.get(cat, ("#1d1f24", "#121316"))
    g = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W_} {H_}" width="{W_}" height="{H_}">',
         f'<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{bg[0]}"/><stop offset="1" stop-color="{bg[1]}"/></linearGradient>',
         '<linearGradient id="in" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F09A3E"/><stop offset="1" stop-color="#C8321F"/></linearGradient>',
         '<pattern id="dots" width="9" height="9" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="#ffffff" fill-opacity=".13"/></pattern>',
         '<linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".6"/></linearGradient></defs>',
         f'<rect width="{W_}" height="{H_}" fill="url(#bg)"/>']
    for lat in range(-60, 90, 15):  # graticule
        y = P(lon0, lat)[1]
        if 0 < y < H_: g.append(f'<line x1="0" y1="{y:.1f}" x2="{W_}" y2="{y:.1f}" stroke="#fff" stroke-opacity=".05"/>')
    for lon in range(-180, 181, 15):
        x = P(lon, lat0)[0]
        if 0 < x < W_: g.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{H_}" stroke="#fff" stroke-opacity=".05"/>')
    for name in WORLD:
        if name == "India" or name in hi or not visible(name):
            continue
        g.append(f'<path d="{path(name)}" fill="#fff" fill-opacity=".055" stroke="#fff" stroke-opacity=".16" stroke-width=".7"/>')
    for name in sorted(hi):
        if name in WORLD and visible(name):
            g.append(f'<path d="{path(name)}" fill="#C9A45C" fill-opacity=".42" stroke="#E6C580" stroke-width="1"/>')
    g.append(f'<path d="{path("India")}" fill="url(#in)" stroke="#F7D58C" stroke-width="1.3"/>')
    if cat != "Geopolitics":
        g.append(f'<path d="{path("India")}" fill="url(#dots)"/>')
    ix, iy = P(*india)
    if cat == "Geopolitics":
        for _, _, c in ents:
            x, y = P(*c)
            mx, my = (ix + x) / 2, min(iy, y) - abs(x - ix) * .28 - 30
            g.append(f'<path d="M{ix:.1f},{iy:.1f} Q{mx:.1f},{my:.1f} {x:.1f},{y:.1f}" fill="none" stroke="#F7D58C" stroke-width="2" stroke-dasharray="6 6"/>'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#F7D58C"/><circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="none" stroke="#F7D58C" stroke-opacity=".5"/>')
        g.append(f'<circle cx="{ix:.1f}" cy="{iy:.1f}" r="6" fill="#fff"/>')
    target = P(*place) if place else (P(*india) if cat == "Defence" else None)
    if target:
        x, y = target
        if cat == "Defence":
            g += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="none" stroke="#B9E07A" stroke-opacity="{o}"/>' for r, o in ((40, .5), (80, .35), (120, .22), (160, .12))]
            g.append(f'<path d="M{x:.1f},{y:.1f} L{x + 160:.1f},{y - 30:.1f} A160,160 0 0 0 {x + 120:.1f},{y - 106:.1f} Z" fill="#B9E07A" fill-opacity=".14"/>')
        g += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="none" stroke="#fff" stroke-opacity="{o}" stroke-width="1.5"/>' for r, o in ((14, .7), (26, .35), (40, .15))]
        g.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#fff"/>')
    g.append(f'<rect width="{W_}" height="{H_}" fill="url(#fade)"/></svg>')
    return "\n".join(g)

def esc(t): return html.escape(t, quote=True)
def nice(d): return f"{d.day} {d:%B %Y}"
def cat_class(c): return "cat-" + re.sub(r"[^a-z]+", "-", c.lower()).strip("-")

# ---------------------------------------------------------------- article pages
PAGE = """<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta name="author" content="Kamlesh Bhagatkar">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og_image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@KBhagatkar">
<meta name="twitter:creator" content="@KBhagatkar">
<meta property="article:author" content="{base}">
<meta property="article:published_time" content="{date}">
<link rel="alternate" type="application/rss+xml" title="Kamlesh Bhagatkar: articles" href="{base}feed.xml">
{fonts}
<link rel="stylesheet" href="../style.css">
<script type="application/ld+json">{ld}</script>
</head>
<body>
<nav class="nav" aria-label="Main"><div class="wrap">
  <a class="brand" href="../">Kamlesh Bhagatkar</a>
  <ul><li><a href="../#books">Books</a></li><li><a href="./">Articles</a></li><li><a href="../publications/">Publications</a></li><li><a href="../#about">About</a></li><li><a href="../#contact">Contact</a></li></ul>
</div></nav>
<header class="article-head"><div class="wrap">
  <p class="art-meta"><span class="tag-pill">{cat}</span> {nice_date} · {mins} min read</p>
  <h1>{title}</h1>
  <p class="by">By <a href="../" style="color:inherit">Kamlesh Bhagatkar</a>, author &amp; geopolitical analyst</p>
  <a class="btn primary dl-btn" href="../downloads/{slug}.pdf" download>{icon} Download PDF</a>
  {share}
</div></header>
<main><article class="prose">
{body}

<p class="author-box">{author_box}</p>
<p class="dl-end"><a class="btn primary dl-btn" href="../downloads/{slug}.pdf" download>{icon} Download PDF</a> <a class="dl" href="./">All articles</a></p>
{share}
</article></main>
<footer><div class="wrap"><span>© {year} Kamlesh Bhagatkar · <a href="../">Home</a> · <a href="./">Articles</a> · <a href="../#books">Books</a></span></div></footer>
<script>document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',()=>navigator.clipboard.writeText(b.dataset.copy).then(()=>b.textContent='Copied')))</script>
</body>
</html>
"""

# ---------------------------------------------------------------- security policy (CSP) on every page
# GitHub Pages cannot send headers, so the policy goes in a <meta> tag. Inline scripts are allowed by exact
# SHA-256 hash only; JSON-LD blocks are data, not executed, so they need no hash.
import base64
CSP_RE = re.compile(r'\n?<meta http-equiv="Content-Security-Policy"[^>]*>')
ICON_RE = re.compile(r'\n?<link rel="(?:icon|apple-touch-icon)"[^>]*>')
def with_csp(t):
    t = CSP_RE.sub("", t)
    hashes = sorted({"'sha256-" + base64.b64encode(hashlib.sha256(m.encode()).digest()).decode() + "'"
                     for m in re.findall(r"<script>(.*?)</script>", t, re.S)})
    policy = "; ".join([
        "default-src 'self'", "script-src 'self' " + " ".join(hashes), "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com", "img-src 'self' data: https://i.ytimg.com", "frame-src https://www.youtube-nocookie.com",
        "connect-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "upgrade-insecure-requests"])
    t = ICON_RE.sub("", t)
    icons = ('\n<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n<link rel="icon" href="/favicon.ico" sizes="32x32">'
             '\n<link rel="apple-touch-icon" href="/apple-touch-icon.png">')
    if 'name="theme-color"' not in t:
        icons += '\n<meta name="theme-color" content="#121316">'
    return t.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="{policy}">{icons}', 1)

def write_if_changed(path, text):
    if path.suffix == ".html":
        text = with_csp(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
        print("wrote", path.relative_to(SITE))

live = {a["slug"] for a in ARTS}
for stale in [*(SITE / "articles").glob("*.html"), *(SITE / "downloads").glob("*.pdf"), *(SITE / "images/cards").glob("*.svg")]:
    if stale.stem not in live and stale.name != "index.html":  # article was deleted: remove its page and PDF
        stale.unlink(); print("removed", stale.relative_to(SITE))

def social(title, desc, url):
    """Open Graph + X card tags for listing pages (articles use the fuller PAGE template)."""
    img = BASE + "images/kamlesh-bhagatkar.jpg"
    return "\n".join([f'<meta property="og:type" content="website">', f'<meta property="og:title" content="{esc(title)}">',
                      f'<meta property="og:description" content="{esc(desc)}">', f'<meta property="og:url" content="{url}">',
                      f'<meta property="og:image" content="{img}">', '<meta name="twitter:card" content="summary_large_image">',
                      '<meta name="twitter:site" content="@KBhagatkar">'])


def share_bar(a):
    """Share links for one article; plain URLs, no third-party scripts or trackers."""
    from urllib.parse import quote
    u, t = quote(a["url"], safe=""), quote(a["title"])
    links = [("WhatsApp", f"https://wa.me/?text={t}%20{u}"),
             ("X", f"https://twitter.com/intent/tweet?text={t}&url={u}&via=KBhagatkar"),
             ("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={u}"),
             ("LinkedIn", f"https://www.linkedin.com/sharing/share-offsite/?url={u}"),
             ("Telegram", f"https://t.me/share/url?url={u}&text={t}")]
    items = "".join(f'<a href="{esc(h)}" target="_blank" rel="noopener" aria-label="Share on {n}">{n}</a>' for n, h in links)
    copy = f'<button type="button" data-copy="{esc(a["url"])}">Copy link</button>'  # wired by COPY_JS (CSP blocks onclick)
    return f'<p class="share"><span>Share</span>{items}{copy}</p>'


for a in ARTS:
    og = BASE + f"images/og/{a['slug']}.png"
    ld = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": a["title"], "description": a["description"],
                     "url": a["url"], "datePublished": a["date"], "image": og, "inLanguage": "en-IN", "articleSection": a["category"],
                     "author": {"@type": "Person", "@id": BASE + "#person", "name": "Kamlesh Bhagatkar", "url": BASE},
                     "publisher": {"@id": BASE + "#person"}, "mainEntityOfPage": a["url"]}, ensure_ascii=False).replace("</", "<\\/")
    crumbs = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": BASE},
        {"@type": "ListItem", "position": 2, "name": "Articles", "item": BASE + "articles/"},
        {"@type": "ListItem", "position": 3, "name": a["title"], "item": a["url"]}]}, ensure_ascii=False).replace("</", "<\\/")
    ld = ld + '</script>\n<script type="application/ld+json">' + crumbs
    write_if_changed(SITE / "articles" / f"{a['slug']}.html", PAGE.format(
        # Google shows ~60 characters; keep the name suffix only when it fits
        page_title=esc(a["title"] + " | Kamlesh Bhagatkar" if len(a["title"]) <= 40 else a["title"]),
        title=esc(a["title"]), desc=esc(a["description"]), url=a["url"], og_image=og, base=BASE, date=a["date"], fonts=FONTS,
        ld=ld, cat=esc(a["category"]), nice_date=nice(a["date_obj"]), mins=max(1, round(a["words"] / 220)),
        slug=a["slug"], icon=ICON, body=a["body"], author_box=AUTHOR_BOX, year=a["date_obj"].year, share=share_bar(a)))

# ---------------------------------------------------------------- cards (home + archive)
def card(a, prefix):
    if a.get("image"):
        pos = f' style="object-position:{esc(a["image_position"])}"' if a.get("image_position") else ""
        img = f'<img src="{prefix}{esc(a["image"])}" alt="" loading="lazy"{pos}>'
        cls = "card-img"
    else:
        art = f"images/cards/{a['slug']}.svg"
        write_if_changed(SITE / art, card_art(a))
        img = (f'<img class="card-art" src="{prefix}{art}" alt="" loading="lazy">'
               f'<span class="typo-cat">{esc(a["category"])}</span><span class="typo-date">{nice(a["date_obj"])}</span>')
        cls = f"card-img card-typo has-art {cat_class(a['category'])}"
    link = f"{prefix}articles/{a['slug']}.html"
    return f"""      <article class="card reveal">
        <a class="{cls}" href="{link}" tabindex="-1" aria-hidden="true">{img}</a>
        <div class="card-body">
          <span class="tag">{esc(a['category'])} · {nice(a['date_obj'])}</span>
          <h3><a href="{link}">{esc(a['title'])}</a></h3>
          <p>{esc(a['summary'])}</p>
          <div class="card-actions"><a class="more" href="{link}">Read →</a><a class="dl" href="{prefix}downloads/{a['slug']}.pdf" download>{ICON}PDF</a></div>
        </div>
      </article>"""

home = SITE / "index.html"
h = home.read_text()
cards = "\n".join(card(a, "") for a in ARTS[:6])
more = f'\n    <p class="all-link reveal"><a class="btn dark" href="articles/">All {len(ARTS)} articles →</a></p>' if len(ARTS) > 6 else \
       '\n    <p class="all-link reveal"><a class="btn dark" href="articles/">All articles →</a></p>'
new = re.sub(r"(<!-- ARTICLES:START -->).*?(<!-- ARTICLES:END -->)",
             lambda m: f'{m[1]}\n    <div class="cards">\n{cards}\n    </div>{more}\n    {m[2]}', h, flags=re.S)
assert "<!-- ARTICLES:START -->" in h, "index.html needs the ARTICLES markers"
write_if_changed(home, new)

ARCHIVE = f"""<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Articles | Kamlesh Bhagatkar</title>
<meta name="description" content="Articles by Kamlesh Bhagatkar, author and geopolitical analyst from Nagpur, on geopolitics, current affairs, defence and Bharat.">
<link rel="canonical" href="{BASE}articles/">
{social("Articles | Kamlesh Bhagatkar", "Articles by Kamlesh Bhagatkar on geopolitics, current affairs, defence and Bharat.", BASE + "articles/")}
<link rel="alternate" type="application/rss+xml" title="Kamlesh Bhagatkar: articles" href="{BASE}feed.xml">
{FONTS}
<link rel="stylesheet" href="../style.css">
</head>
<body>
<nav class="nav" aria-label="Main"><div class="wrap">
  <a class="brand" href="../">Kamlesh Bhagatkar</a>
  <ul><li><a href="../#books">Books</a></li><li><a href="./">Articles</a></li><li><a href="../publications/">Publications</a></li><li><a href="../#about">About</a></li><li><a href="../#contact">Contact</a></li></ul>
</div></nav>
<header class="article-head"><div class="wrap">
  <h1>Articles</h1>
  <p class="by">Geopolitics, current affairs and Bharat's choices, in plain language. New pieces every morning. <a href="../feed.xml" style="color:inherit">RSS feed</a></p>
</div></header>
<main><section><div class="wrap">
  <div class="filters" role="group" aria-label="Filter by topic">
    <button type="button" class="chip on" data-cat="all" aria-pressed="true">All</button>
    {''.join(f'<button type="button" class="chip" data-cat="{esc(c)}" aria-pressed="false">{esc(c)}</button>' for c in CATEGORIES if any(a["category"] == c for a in ARTS))}
  </div>
  <div class="cards">
{chr(10).join(card(a, "../").replace('<article class="card reveal">', f'<article class="card" data-cat="{esc(a["category"])}">') for a in ARTS)}
  </div>
</div></section></main>
<footer><div class="wrap"><span>© {datetime.date.today().year} Kamlesh Bhagatkar · <a href="../">Home</a></span></div></footer>
<script>
document.querySelectorAll('.chip').forEach(function(b){{b.addEventListener('click',function(){{
  var c=b.dataset.cat;document.querySelectorAll('.chip').forEach(function(x){{x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',x===b)}});
  document.querySelectorAll('.cards .card').forEach(function(k){{k.hidden=!(c==='all'||k.dataset.cat===c)}});}})}});
</script>
</body>
</html>
"""
write_if_changed(SITE / "articles/index.html", ARCHIVE)

# ---------------------------------------------------------------- publications page (whitepapers, articles, videos, media)
def entries(path, n):
    """Lines '- f1 | f2 | ...' from a content list file; returns lists of n fields (newest first)."""
    out = []
    f = SITE / path
    for line in (f.read_text().splitlines() if f.exists() else []):
        if line.startswith("- ") and "|" in line:
            parts = [x.strip() for x in line[2:].split("|")]
            if len(parts) == n:
                out.append(parts)
            else:
                print(f"note: {path}: skipped line with {len(parts)} fields: {line[:60]}")
    return out

def yt_id(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    return m[1] if m else None

VIDEOS = [(d, t, yt_id(u)) for d, t, u in entries("content/videos.md", 3) if yt_id(u)]
MEDIA = entries("content/media.md", 5)
assert yt_id("https://youtu.be/abcdefghijk") == yt_id("https://www.youtube.com/watch?v=abcdefghijk&t=3") == "abcdefghijk"

# Whitepapers: content/whitepapers/<slug>.md (front matter + abstract) and the PDF in downloads/whitepapers/<pdf>
def load_wp(path):
    m = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(), re.S)
    if not m:
        raise SystemExit(f"{path.name}: missing --- front matter ---")
    meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in m[1].splitlines() if ":" in l)}
    missing = [k for k in ("title", "date", "pages", "summary", "pdf") if not meta.get(k)]
    if missing:
        raise SystemExit(f"{path.name}: missing {', '.join(missing)}")
    meta["date_obj"] = datetime.date.fromisoformat(meta["date"])
    meta["slug"], meta["abstract"] = path.stem, markdown(m[2])
    meta["url"] = f"{BASE}whitepapers/{meta['slug']}.html"
    if not (SITE / "downloads/whitepapers" / meta["pdf"]).exists():
        print(f"WARNING: {path.name}: downloads/whitepapers/{meta['pdf']} not found")
    return meta

WPS = sorted((load_wp(p) for p in (SITE / "content/whitepapers").glob("*.md")), key=lambda w: w["date_obj"], reverse=True) \
    if (SITE / "content/whitepapers").exists() else []
for stale in (SITE / "whitepapers").glob("*.html") if (SITE / "whitepapers").exists() else []:
    if stale.stem not in {w["slug"] for w in WPS}:
        stale.unlink(); print("removed", stale.relative_to(SITE))

def wp_cover(w, prefix):
    img = f"images/whitepapers/{w['slug']}.jpg"  # real cover (page 1 of the PDF) when present, else the text cover
    if (SITE / img).exists():
        return (f'<a class="wpcover wpimg" href="{prefix}whitepapers/{w["slug"]}.html" tabindex="-1" aria-hidden="true">'
                f'<img src="{prefix}{img}" alt="" loading="lazy"></a>')
    return (f'<a class="wpcover" href="{prefix}whitepapers/{w["slug"]}.html" tabindex="-1" aria-hidden="true">'
            f'<span class="wpk">Whitepaper</span><span class="wpt">{esc(w["title"])}</span>'
            f'<span class="wpm">{esc(w["pages"])} pages · {w["date_obj"]:%B %Y}</span><span class="wpa">Kamlesh Bhagatkar</span></a>')

for w in WPS:
    pdf = f"../downloads/whitepapers/{esc(w['pdf'])}"
    img = f"images/whitepapers/{w['slug']}.jpg"
    og = (f'\n<meta property="og:url" content="{w["url"]}">\n<meta property="og:image" content="{BASE}images/og/whitepaper-{w["slug"]}.png">'
          '\n<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">'
          '\n<meta name="twitter:card" content="summary_large_image">\n<meta name="twitter:site" content="@KBhagatkar">'
          if (SITE / img).exists() else "")
    fig = (f'<a class="wpfig" href="{pdf}"><img src="../{img}" alt="Cover of the whitepaper {esc(w["title"])}"></a>\n'
           if (SITE / img).exists() else "")
    cite = f"Kamlesh Bhagatkar ({w['date_obj'].year}). {w['title']}. Whitepaper, {w['pages']} pp. kamleshbhagatkar.com."
    doi = w.get("doi", "")  # optional front matter, e.g. 10.5281/zenodo.123
    cite += f" https://doi.org/{doi}" if doi else ""
    ld = json.dumps({"@context": "https://schema.org", "@type": "Report", "name": w["title"], "abstract": w["summary"],
                     "datePublished": w["date"], "numberOfPages": w["pages"], "url": w["url"], "inLanguage": "en-IN",
                     **({"identifier": f"https://doi.org/{doi}", "sameAs": f"https://doi.org/{doi}"} if doi else {}),
                     "encoding": {"@type": "MediaObject", "contentUrl": BASE + f"downloads/whitepapers/{w['pdf']}", "encodingFormat": "application/pdf"},
                     "author": {"@type": "Person", "@id": BASE + "#person", "name": "Kamlesh Bhagatkar", "url": BASE}},
                    ensure_ascii=False).replace("</", "<\\/")
    write_if_changed(SITE / "whitepapers" / f"{w['slug']}.html", f"""<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(w['title'])} | Whitepaper by Kamlesh Bhagatkar</title>
<meta name="description" content="{esc(w['summary'])}">
<link rel="canonical" href="{w['url']}">
<meta name="citation_title" content="{esc(w['title'])}">
<meta name="citation_author" content="Bhagatkar, Kamlesh">
<meta name="citation_publication_date" content="{w['date_obj']:%Y/%m/%d}">
<meta name="citation_pdf_url" content="{BASE}downloads/whitepapers/{esc(w['pdf'])}">{f'\n<meta name="citation_doi" content="{esc(doi)}">' if doi else ''}
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(w['title'])}">
<meta property="og:description" content="{esc(w['summary'])}">{og}
{FONTS}
<link rel="stylesheet" href="../style.css">
<script type="application/ld+json">{ld}</script>
</head>
<body>
<nav class="nav" aria-label="Main"><div class="wrap">
  <a class="brand" href="../">Kamlesh Bhagatkar</a>
  <ul><li><a href="../#books">Books</a></li><li><a href="../articles/">Articles</a></li><li><a href="../publications/">Publications</a></li><li><a href="../#about">About</a></li><li><a href="../#contact">Contact</a></li></ul>
</div></nav>
<header class="article-head"><div class="wrap">
  <p class="art-meta"><span class="tag-pill">Whitepaper</span> {nice(w['date_obj'])} · {esc(w['pages'])} pages</p>
  <h1>{esc(w['title'])}</h1>
  <p class="by">By <a href="../" style="color:inherit">Kamlesh Bhagatkar</a>, author &amp; geopolitical analyst</p>
  <a class="btn primary dl-btn" href="{pdf}" download>{ICON} Download PDF ({esc(w['pages'])} pages)</a>
</div></header>
<main><article class="prose">
<p class="h">Abstract</p>
{fig}{w['abstract']}
<div class="cite"><p class="h">Cite as</p><p>{esc(cite)}</p></div>
<p class="dl-end"><a class="btn primary dl-btn" href="{pdf}" download>{ICON} Download PDF</a> <a class="dl" href="../publications/">All publications</a></p>
</article></main>
<footer><div class="wrap"><span>© {w['date_obj'].year} Kamlesh Bhagatkar · <a href="../">Home</a> · <a href="../publications/">Publications</a></span></div></footer>
</body>
</html>
""")

def video_card(d, t, vid):
    return (f'<article class="vcard"><button type="button" class="vplay" data-id="{vid}" aria-label="Play video: {esc(t)}">'
            f'<img src="https://i.ytimg.com/vi/{vid}/hqdefault.jpg" alt="" loading="lazy"><span class="vbtn" aria-hidden="true"></span></button>'
            f'<div class="vbody"><span class="tag">{nice(datetime.date.fromisoformat(d))}</span><h3>{esc(t)}</h3>'
            f'<a class="more" href="https://www.youtube.com/watch?v={vid}" rel="noopener">Watch on YouTube →</a></div></article>')

def soon(title, text):
    return (f'<div class="vsoon"><span class="soon-mark" aria-hidden="true"></span><div><h3>{title}</h3><p>{text}</p></div></div>')

if WPS:
    pub_wps = '<div class="wpgrid">' + "".join(
        f'<article class="wpcard">{wp_cover(w, "../")}<div class="vbody"><span class="tag">{nice(w["date_obj"])} · {esc(w["pages"])} pages</span>'
        f'<h3><a href="../whitepapers/{w["slug"]}.html">{esc(w["title"])}</a></h3><p>{esc(w["summary"])}</p>'
        + (f'<p class="wpdoi">DOI: <a href="https://doi.org/{esc(w["doi"])}" rel="noopener">{esc(w["doi"])}</a></p>' if w.get("doi") else "") +
        f'<div class="card-actions"><a class="more" href="../whitepapers/{w["slug"]}.html">Abstract →</a>'
        f'<a class="dl" href="../downloads/whitepapers/{esc(w["pdf"])}" download>{ICON}PDF</a></div></div></article>' for w in WPS) + "</div>"
else:
    pub_wps = soon("The first whitepaper is in preparation",
                   "Long-form research papers on India's security and strategic choices, around 50 pages each, free to download.")
counts = {c: sum(a["category"] == c for a in ARTS) for c in CATEGORIES}
pub_counts = " · ".join(f"{n} {c}" for c, n in counts.items() if n)
pub_articles = "".join(f'<li><a href="../articles/{a["slug"]}.html">{esc(a["title"])}</a> <span class="meta">{esc(a["category"])} · {nice(a["date_obj"])}</span></li>' for a in ARTS[:8])
pub_videos = ('<div class="vgrid">' + "".join(video_card(d, t, v) for d, t, v in VIDEOS) + "</div>") if VIDEOS else \
    soon("Video explainers are coming", "Short videos on the day's geopolitics and current affairs, from Nagpur. They will appear here as they are published.")
pub_media = "" if not MEDIA else ('<section class="pub-sec" id="media"><h2>Media &amp; published elsewhere</h2><ul class="plist">' + "".join(
    f'<li><a href="{esc(u)}" rel="noopener">{esc(t)}</a> <span class="meta">{esc(kind)} · {esc(outlet)} · {nice(datetime.date.fromisoformat(d))}</span></li>'
    for d, kind, outlet, t, u in MEDIA) + "</ul></section>")
pub_ld = json.dumps({"@context": "https://schema.org", "@graph": [
    {"@type": "VideoObject", "name": t, "uploadDate": d, "thumbnailUrl": f"https://i.ytimg.com/vi/{v}/hqdefault.jpg",
     "embedUrl": f"https://www.youtube-nocookie.com/embed/{v}", "contentUrl": f"https://www.youtube.com/watch?v={v}",
     "description": t, "creator": {"@id": BASE + "#person"}} for d, t, v in VIDEOS]}, ensure_ascii=False).replace("</", "<\\/")
ld_tag = f'<script type="application/ld+json">{pub_ld}</script>' if VIDEOS else ""
media_jump = '<a href="#media">Media</a>' if MEDIA else ""
counts_txt = (": " + pub_counts) if pub_counts else ""

PUBS = f"""<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Publications | Kamlesh Bhagatkar</title>
<meta name="description" content="Whitepapers, articles and videos by Kamlesh Bhagatkar, author and geopolitical analyst from Nagpur.">
<link rel="canonical" href="{BASE}publications/">
{social("Publications | Kamlesh Bhagatkar", "Whitepapers, articles and videos by Kamlesh Bhagatkar, author and geopolitical analyst from Nagpur.", BASE + "publications/")}
{FONTS}
<link rel="stylesheet" href="../style.css">
{ld_tag}
</head>
<body>
<nav class="nav" aria-label="Main"><div class="wrap">
  <a class="brand" href="../">Kamlesh Bhagatkar</a>
  <ul><li><a href="../#books">Books</a></li><li><a href="../articles/">Articles</a></li><li><a href="./">Publications</a></li><li><a href="../#about">About</a></li><li><a href="../#contact">Contact</a></li></ul>
</div></nav>
<header class="article-head"><div class="wrap">
  <h1>Publications</h1>
  <p class="by">Whitepapers, articles and videos by Kamlesh Bhagatkar.</p>
  <p class="pub-jump"><a href="#whitepapers">Whitepapers</a><a href="#articles">Articles</a><a href="#videos">Videos</a>{media_jump}</p>
</div></header>
<main><div class="wrap">
<section class="pub-sec" id="whitepapers"><h2>Whitepapers</h2>{pub_wps}</section>
<section class="pub-sec" id="articles"><h2>Articles</h2><p class="sub">{len(ARTS)} articles on this site{counts_txt}.</p>
  <ul class="plist">{pub_articles}</ul><p><a class="btn dark" href="../articles/">All articles →</a></p></section>
<section class="pub-sec" id="videos"><h2>Videos</h2>{pub_videos}</section>
{pub_media}
</div></main>
<footer><div class="wrap"><span>© {datetime.date.today().year} Kamlesh Bhagatkar · <a href="../">Home</a> · <a href="../articles/">Articles</a></span></div></footer>
<script>
document.querySelectorAll('.vplay').forEach(function(b){{b.addEventListener('click',function(){{
  var f=document.createElement('iframe');f.src='https://www.youtube-nocookie.com/embed/'+b.dataset.id+'?autoplay=1';
  f.title=b.getAttribute('aria-label');f.allow='accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture';f.allowFullscreen=true;
  b.replaceWith(f);}})}});
</script>
</body>
</html>
"""
write_if_changed(SITE / "publications/index.html", PUBS)

# home-page summary tiles
tiles = f"""
    <div class="ptiles">
      <a class="ptile" href="publications/#whitepapers"><b>{len(WPS) or 'Soon'}</b><span>Whitepapers</span></a>
      <a class="ptile" href="articles/"><b>{len(ARTS)}</b><span>Articles</span></a>
      <a class="ptile" href="publications/#videos"><b>{len(VIDEOS) or 'Soon'}</b><span>Videos</span></a>
    </div>
    <p class="all-link reveal"><a class="btn dark" href="publications/">All publications →</a></p>
    """
h2 = home.read_text()
assert "<!-- PUBS:START -->" in h2, "index.html needs the PUBS markers"
write_if_changed(home, re.sub(r"(<!-- PUBS:START -->).*?(<!-- PUBS:END -->)", lambda m: m[1] + tiles + m[2], h2, flags=re.S))

# ---------------------------------------------------------------- 404 page (GitHub Pages serves /404.html)
write_if_changed(SITE / "404.html", f"""<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found | Kamlesh Bhagatkar</title>
<meta name="robots" content="noindex">
{FONTS}
<link rel="stylesheet" href="/style.css">
</head>
<body>
<nav class="nav" aria-label="Main"><div class="wrap">
  <a class="brand" href="/">Kamlesh Bhagatkar</a>
  <ul><li><a href="/#books">Books</a></li><li><a href="/articles/">Articles</a></li><li><a href="/publications/">Publications</a></li><li><a href="/#contact">Contact</a></li></ul>
</div></nav>
<header class="article-head"><div class="wrap">
  <p class="art-meta"><span class="tag-pill">404</span></p>
  <h1>This page is not here</h1>
  <p class="by">It may have moved, or the link may be mistyped.</p>
</div></header>
<main><div class="prose">
<p>Try one of these instead:</p>
<ul><li><a href="/">Home</a></li><li><a href="/articles/">All articles</a></li><li><a href="/publications/">Publications</a></li><li><a href="/#books">Books</a></li></ul>
{"<p class='h'>Latest</p><ul>" + "".join(f'<li><a href="/articles/{a["slug"]}.html">{esc(a["title"])}</a></li>' for a in ARTS[:3]) + "</ul>" if ARTS else ""}
</div></main>
<footer><div class="wrap"><span>© {datetime.date.today().year} Kamlesh Bhagatkar · <a href="/">Home</a></span></div></footer>
</body>
</html>
""")

# ---------------------------------------------------------------- sitemap + RSS
latest = ARTS[0]["date"] if ARTS else datetime.date.today().isoformat()
urls = [(BASE, latest), (BASE + "articles/", latest), (BASE + "publications/", latest)] + [(a["url"], a["date"]) for a in ARTS] + [(w["url"], w["date"]) for w in WPS]
write_if_changed(SITE / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 + "".join(f"  <url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls) + "</urlset>\n")
items = "".join(f"""  <item><title>{esc(a['title'])}</title><link>{a['url']}</link><guid>{a['url']}</guid>
    <pubDate>{email.utils.format_datetime(datetime.datetime.combine(a['date_obj'], datetime.time(7, 0), datetime.timezone(datetime.timedelta(hours=5, minutes=30))))}</pubDate>
    <category>{esc(a['category'])}</category><description>{esc(a['summary'])}</description></item>\n""" for a in ARTS[:30])
write_if_changed(SITE / "feed.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Kamlesh Bhagatkar: articles</title><link>{BASE}</link>
  <description>Geopolitics and current affairs from Nagpur, by author and geopolitical analyst Kamlesh Bhagatkar.</description>
  <language>en-in</language>
{items}</channel></rss>
""")

# ---------------------------------------------------------------- PDFs (only when an article changed)
if "--no-pdf" in sys.argv:
    sys.exit()
chrome = next((c for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome"),
                           shutil.which("chromium"), shutil.which("chromium-browser")) if c and pathlib.Path(c).exists()), None)
if not chrome:
    print("WARNING: no Chrome found, PDFs not built"); sys.exit()

PDF_CSS = """
@page { size: A4; margin: 20mm 0 22mm;
  @bottom-left { content: 'Kamlesh Bhagatkar · Author & Geopolitical Analyst'; margin-left: 22mm; font: 500 7.5pt 'Oswald', sans-serif; letter-spacing: .16em; text-transform: uppercase; color: #8a857a }
  @bottom-right { content: 'kamleshbhagatkar.com  ·  ' counter(page); margin-right: 22mm; font: 500 7.5pt 'Oswald', sans-serif; letter-spacing: .16em; text-transform: uppercase; color: #8a857a } }
@page :first { margin-top: 0 }
* { box-sizing: border-box }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact }
.body, .author { margin-left: 22mm; margin-right: 22mm }
body { margin: 0; font: 11.2pt/1.62 'Alegreya', Georgia, serif; color: #1b1b1b }
.head { margin: 0 0 9mm; padding: 16mm 22mm 11mm; background: #141518; color: #f4efe4; position: relative; break-inside: avoid }
.head:after { content: ""; position: absolute; left: 22mm; bottom: 0; width: 34mm; height: 1.4mm; background: #c8321f }
.brand { display: flex; justify-content: space-between; font: 500 8.5pt 'Oswald', sans-serif; letter-spacing: .22em; text-transform: uppercase; color: #c9a45c }
.brand b { color: #f4efe4; font-weight: 500 }
.tag { display: inline-block; margin-top: 9mm; font: 600 8.5pt 'Oswald', sans-serif; letter-spacing: .2em; text-transform: uppercase; background: #c8321f; color: #fff; padding: .6mm 2.6mm }
h1 { font: 700 27pt/1.06 'Oswald', sans-serif; text-transform: uppercase; letter-spacing: .01em; margin: 4mm 0; max-width: 150mm }
.by { font: italic 11pt 'Alegreya', serif; color: #d8d1c2; margin: 0 }
.by strong { font-style: normal; color: #f4efe4 }
.hero { float: right; width: 52mm; margin: 1mm 22mm 4mm 7mm; break-inside: avoid }
.hero img { width: 100%; height: auto; display: block; border-left: 1.2mm solid #c8321f }
p, li { margin: 0 0 3.4mm; text-align: justify; hyphens: auto; orphans: 3; widows: 3 }
ul { padding-left: 5mm; margin: 0 0 3.4mm } li { text-align: left; margin-bottom: 1.4mm; font-size: 10pt }
blockquote { margin: 4mm 0; padding-left: 4mm; border-left: 1mm solid #c9a45c; font-style: italic }
.body > p:first-of-type:first-letter { float: left; font: 700 40pt/.82 'Oswald', sans-serif; color: #c8321f; margin: 1.4mm 2.4mm 0 0 }
p.h { font: 600 13.5pt 'Oswald', sans-serif; letter-spacing: .02em; color: #141518; margin: 6.5mm 0 2mm; text-align: left; break-after: avoid; padding-left: 3mm; border-left: 1mm solid #c8321f }
.author { display: flex; gap: 6mm; align-items: center; margin-top: 9mm; padding: 6mm; background: #f4efe4; break-inside: avoid; border-top: 1mm solid #c8321f }
.author img { width: 24mm; height: 24mm; border-radius: 50%; object-fit: cover; flex: none; border: .6mm solid #c9a45c }
.author p { margin: 0; font-size: 10pt; line-height: 1.5; text-align: left }
.author .who { font: 600 12pt 'Oswald', sans-serif; letter-spacing: .04em; margin-bottom: 1mm }
.author .site { font: 500 9pt 'Oswald', sans-serif; letter-spacing: .14em; text-transform: uppercase; color: #c8321f; margin-top: 2mm }
a { color: inherit; text-decoration: none }
"""
OUT = SITE / "downloads"
manifest_path = OUT / "manifest.json"
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
for a in ARTS:
    hero = f'<figure class="hero"><img src="{(SITE / a["image"]).as_uri()}" alt=""></figure>' if a.get("image") else ""
    doc = f"""<!doctype html><html lang="en-IN"><head><meta charset="utf-8"><title>{esc(a['title'])} | Kamlesh Bhagatkar</title>
{FONTS}<style>{PDF_CSS}</style></head><body>
<header class="head"><div class="brand"><b>Kamlesh Bhagatkar</b><span>kamleshbhagatkar.com</span></div>
<span class="tag">{esc(a['category'])}</span><h1>{esc(a['title'])}</h1>
<p class="by">By <strong>Kamlesh Bhagatkar</strong>, Author &amp; Geopolitical Analyst &middot; {nice(a['date_obj'])}</p></header>
{hero}<div class="body">{a['body']}</div>
<aside class="author"><img src="{(SITE / 'images/kamlesh-bhagatkar.jpg').as_uri()}" alt="">
<div><p class="who">Kamlesh Bhagatkar</p><p>Author and geopolitical analyst from Nagpur. Author of <em>RSS: 100 Years of Selfless Service</em> (2025); his next book, <em>Nineteen Days</em>, tells the story of Pahalgam and Operation Sindoor.</p>
<p class="site">kamleshbhagatkar.com</p></div></aside></body></html>"""
    digest = hashlib.sha256(doc.replace(SITE.as_uri(), "").encode()).hexdigest()[:16]  # path-independent, so CI and Mac agree
    pdf = OUT / f"{a['slug']}.pdf"
    if pdf.exists() and manifest.get(a["slug"]) == digest:
        continue
    OUT.mkdir(exist_ok=True)
    src = OUT / f".{a['slug']}.html"
    src.write_text(doc)
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                    "--allow-file-access-from-files", f"--print-to-pdf={pdf}", src.as_uri()], check=True, capture_output=True, timeout=180)
    src.unlink()
    manifest[a["slug"]] = digest
    print("built", pdf.relative_to(SITE))
OG_DIR = SITE / "images/og"
# whitepapers with a cover get a share image too, as images/og/whitepaper-<slug>.png
WP_OG = [dict(slug="whitepaper-" + w["slug"], image=f"images/whitepapers/{w['slug']}.jpg", category="Whitepaper", title=w["title"],
              # the cover stands whole on the right instead of being cropped behind the title
              css=".bg{inset:auto;right:64px;top:42px;width:auto;height:536px;box-shadow:0 14px 44px rgba(0,0,0,.55)}"
                  ".shade{display:none}.box{width:650px}h1{font-size:54px}") for w in WPS if (SITE / f"images/whitepapers/{w['slug']}.jpg").exists()]
for a in ARTS + WP_OG:
    bg = SITE / (a["image"] if a.get("image") else f"images/cards/{a['slug']}.svg")
    pos = a.get("image_position", "50% 35%")
    doc = f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>
html,body{{margin:0;width:1200px;height:630px;overflow:hidden;background:#121316}}
.bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:{pos}}}
.shade{{position:absolute;inset:0;background:linear-gradient(90deg,rgba(18,19,22,.94) 0%,rgba(18,19,22,.82) 48%,rgba(18,19,22,.25) 100%)}}
.box{{position:absolute;left:64px;top:56px;bottom:56px;width:700px;display:flex;flex-direction:column;color:#f4efe4;font-family:Oswald,sans-serif}}
.cat{{align-self:flex-start;background:#c8321f;color:#fff;font:600 22px Oswald;letter-spacing:.2em;text-transform:uppercase;padding:6px 16px}}
h1{{font:700 58px/1.05 Oswald;text-transform:uppercase;margin:28px 0 0}}
.by{{margin-top:auto;font:500 24px Oswald;letter-spacing:.22em;text-transform:uppercase;color:#c9a45c}}
.by b{{color:#f4efe4;font-weight:600}}
.bar{{position:absolute;left:0;bottom:0;width:100%;height:10px;background:#c8321f}}
{a.get('css', '')}</style></head><body><img class="bg" src="{bg.as_uri()}" alt=""><div class="shade"></div>
<div class="box"><span class="cat">{esc(a['category'])}</span><h1>{esc(a['title'])}</h1>
<p class="by"><b>Kamlesh Bhagatkar</b> · kamleshbhagatkar.com</p></div><div class="bar"></div></body></html>"""
    digest = hashlib.sha256(doc.replace(SITE.as_uri(), "").encode() + bg.read_bytes()).hexdigest()[:16]
    png = OG_DIR / f"{a['slug']}.png"
    if png.exists() and manifest.get("og:" + a["slug"]) == digest:
        continue
    OG_DIR.mkdir(parents=True, exist_ok=True)
    src = OUT / f".og-{a['slug']}.html"
    src.write_text(doc)
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=1200,630",
                    "--virtual-time-budget=8000", "--allow-file-access-from-files", f"--screenshot={png}", src.as_uri()],
                   check=True, capture_output=True, timeout=180)
    src.unlink()
    manifest["og:" + a["slug"]] = digest
    print("built", png.relative_to(SITE))
for stale in OG_DIR.glob("*.png") if OG_DIR.exists() else []:
    if stale.stem not in live | {a["slug"] for a in WP_OG}:
        stale.unlink(); print("removed", stale.relative_to(SITE))
manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
