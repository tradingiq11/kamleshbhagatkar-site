"""Add new videos from the YouTube channel feed to content/videos.md (newest first).
Run by .github/workflows/videos.yml; prints how many were added. Never fails the job on a network error."""
import pathlib, re, sys, urllib.request
import xml.etree.ElementTree as ET

CHANNEL_ID = "UC6CUphPIsCIc8uR65m-RWfQ"  # youtube.com/@kamleshbhagatkar
FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
FILE = pathlib.Path(__file__).resolve().parent.parent / "content/videos.md"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

def clean(title):
    """One-line title without '|', which separates fields in videos.md."""
    return re.sub(r"\s*\|\s*", " — ", " ".join(title.split())).strip(" —")

def new_lines(feed_xml, known_text):
    out = []
    for e in ET.fromstring(feed_xml).findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        if not vid or vid in known_text:
            continue
        link = e.find("a:link", NS).get("href")
        out.append(f"- {e.findtext('a:published', namespaces=NS)[:10]} | {clean(e.findtext('a:title', namespaces=NS))} | {link}")
    return out

def insert(text, lines):
    """Put lines above the first existing entry, or at the end if there is none."""
    rows = text.splitlines()
    at = next((i for i, r in enumerate(rows) if r.startswith("- ")), None)
    if at is None:
        rows += ([""] if rows and rows[-1] else []) + lines
    else:
        rows[at:at] = lines
    return "\n".join(rows) + "\n"

assert clean("A | B  #shorts") == "A — B #shorts"
assert insert("# V\n\n- old\n", ["- new"]) == "# V\n\n- new\n- old\n"
assert insert("# V\n", ["- new"]) == "# V\n\n- new\n"

if __name__ == "__main__":
    try:
        with urllib.request.urlopen(FEED, timeout=30) as r:
            feed = r.read()
    except OSError as err:
        print(f"note: could not read the YouTube feed ({err}); nothing changed")
        sys.exit(0)
    text = FILE.read_text()
    lines = new_lines(feed, text)
    if lines:
        FILE.write_text(insert(text, lines))
    print(f"added {len(lines)} video(s)")
