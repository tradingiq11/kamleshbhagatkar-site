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
    essay: yes                       (optional; personal essays may skip the Sources list)
    ---
    Body in simple Markdown: paragraphs, ## headings, - lists, > quotes, *italic*, **bold**, [text](https://url).
    End with a "## Sources" list of links.
"""
import datetime, email.utils, hashlib, html, json, pathlib, re, shutil, subprocess, sys

SITE = pathlib.Path(__file__).resolve().parent.parent
BASE = "https://kamleshbhagatkar.com/"
CATEGORIES = ["Geopolitics", "Current Affairs", "Defence", "RSS at 100"]
ICON = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m0 0l-5-5m5 5l5-5M4 21h16"/></svg>')
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link href="https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,400;0,700;1,400&family=Oswald:wght@500;600;700&display=swap" rel="stylesheet">')
AUTHOR_BOX = ('Kamlesh Bhagatkar is an author and geopolitical analyst from Nagpur. His first book, <i>RSS: 100 Years of Selfless Service – '
              'Engineers of Glorious Bharat</i> (2025), is available on <a href="https://www.amazon.com/dp/B0F6JMSHDH" rel="noopener">Amazon</a>. '
              'His next book, <i>Nineteen Days</i>, on Pahalgam and Operation Sindoor, is coming soon.')

# ---------------------------------------------------------------- markdown subset
def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{html.escape(m[2])}" rel="noopener">{m[1]}</a>', t)
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

def esc(t): return html.escape(t, quote=True)
def nice(d): return f"{d.day} {d:%B %Y}"
def cat_class(c): return "cat-" + re.sub(r"[^a-z]+", "-", c.lower()).strip("-")

# ---------------------------------------------------------------- article pages
PAGE = """<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | Kamlesh Bhagatkar</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta name="author" content="Kamlesh Bhagatkar">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og_image}">
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
  <ul><li><a href="../#books">Books</a></li><li><a href="./">Articles</a></li><li><a href="../#about">About</a></li><li><a href="../#contact">Contact</a></li></ul>
</div></nav>
<header class="article-head"><div class="wrap">
  <p class="art-meta"><span class="tag-pill">{cat}</span> {nice_date} · {mins} min read</p>
  <h1>{title}</h1>
  <p class="by">By <a href="../" style="color:inherit">Kamlesh Bhagatkar</a>, author &amp; geopolitical analyst</p>
  <a class="btn primary dl-btn" href="../downloads/{slug}.pdf" download>{icon} Download PDF</a>
</div></header>
<main><article class="prose">
{body}

<p class="author-box">{author_box}</p>
<p class="dl-end"><a class="btn primary dl-btn" href="../downloads/{slug}.pdf" download>{icon} Download PDF</a> <a class="dl" href="./">All articles</a></p>
</article></main>
<footer><div class="wrap">© {year} Kamlesh Bhagatkar · <a href="../">Home</a> · <a href="./">Articles</a> · <a href="https://www.amazon.com/dp/B0F6JMSHDH" rel="noopener">Buy the book</a></div></footer>
</body>
</html>
"""

def write_if_changed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
        print("wrote", path.relative_to(SITE))

live = {a["slug"] for a in ARTS}
for stale in [*(SITE / "articles").glob("*.html"), *(SITE / "downloads").glob("*.pdf")]:
    if stale.stem not in live and stale.name != "index.html":  # article was deleted: remove its page and PDF
        stale.unlink(); print("removed", stale.relative_to(SITE))

for a in ARTS:
    og = BASE + a.get("image", "images/kamlesh-bhagatkar.jpg")
    ld = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": a["title"], "description": a["description"],
                     "url": a["url"], "datePublished": a["date"], "image": og, "inLanguage": "en-IN", "articleSection": a["category"],
                     "author": {"@type": "Person", "@id": BASE + "#person", "name": "Kamlesh Bhagatkar", "url": BASE},
                     "publisher": {"@id": BASE + "#person"}, "mainEntityOfPage": a["url"]}, ensure_ascii=False)
    write_if_changed(SITE / "articles" / f"{a['slug']}.html", PAGE.format(
        title=esc(a["title"]), desc=esc(a["description"]), url=a["url"], og_image=og, base=BASE, date=a["date"], fonts=FONTS,
        ld=ld.replace("</", "<\\/"), cat=esc(a["category"]), nice_date=nice(a["date_obj"]), mins=max(1, round(a["words"] / 220)),
        slug=a["slug"], icon=ICON, body=a["body"], author_box=AUTHOR_BOX, year=a["date_obj"].year))

# ---------------------------------------------------------------- cards (home + archive)
def card(a, prefix):
    if a.get("image"):
        pos = f' style="object-position:{esc(a["image_position"])}"' if a.get("image_position") else ""
        img = f'<img src="{prefix}{esc(a["image"])}" alt="" loading="lazy"{pos}>'
        cls = "card-img"
    else:
        img = f'<span class="typo-cat">{esc(a["category"])}</span><span class="typo-date">{nice(a["date_obj"])}</span>'
        cls = f"card-img card-typo {cat_class(a['category'])}"
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
<link rel="alternate" type="application/rss+xml" title="Kamlesh Bhagatkar: articles" href="{BASE}feed.xml">
{FONTS}
<link rel="stylesheet" href="../style.css">
</head>
<body>
<nav class="nav" aria-label="Main"><div class="wrap">
  <a class="brand" href="../">Kamlesh Bhagatkar</a>
  <ul><li><a href="../#books">Books</a></li><li><a href="./">Articles</a></li><li><a href="../#about">About</a></li><li><a href="../#contact">Contact</a></li></ul>
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
<footer><div class="wrap">© {datetime.date.today().year} Kamlesh Bhagatkar · <a href="../">Home</a></div></footer>
<script>
document.querySelectorAll('.chip').forEach(function(b){{b.addEventListener('click',function(){{
  var c=b.dataset.cat;document.querySelectorAll('.chip').forEach(function(x){{x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',x===b)}});
  document.querySelectorAll('.cards .card').forEach(function(k){{k.hidden=!(c==='all'||k.dataset.cat===c)}});}})}});
</script>
</body>
</html>
"""
write_if_changed(SITE / "articles/index.html", ARCHIVE)

# ---------------------------------------------------------------- sitemap + RSS
latest = ARTS[0]["date"] if ARTS else datetime.date.today().isoformat()
urls = [(BASE, latest), (BASE + "articles/", latest)] + [(a["url"], a["date"]) for a in ARTS]
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
manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
