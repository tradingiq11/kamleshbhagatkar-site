"""Daily alerts and the Monday posting report, as GitHub issues. Run by .github/workflows/alerts.yml.

- LinkedIn key: repo variable LINKEDIN_TOKEN_DATE (YYYY-MM-DD, the day the token was made). Its token lasts 60 days,
  so from day 53 an issue asks for a new one (once; skipped while that issue is open).
- Monday (IST): a report of which recent articles reached which site, from content/syndicated.json.
"""
import datetime, json, os, pathlib, re, subprocess, sys

SITE = pathlib.Path(__file__).resolve().parent.parent
TODAY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).date()  # IST
SITES = ["blogger", "wpcom", "tumblr", "writeas", "linkedin", "facebook", "pinterest", "bluesky", "mastodon", "telegram"]


def issue(title, body):
    if "--dry-run" in sys.argv:
        print(f"[dry run] issue: {title}\n{body}"); return
    open_ = subprocess.run(["gh", "issue", "list", "--state", "open", "--search", f'"{title}" in:title', "--json", "title"],
                           capture_output=True, text=True, check=True).stdout
    if title in open_:
        print("already open:", title); return
    subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=True)


def linkedin_due(made, today):
    """Day the alert starts (53 days after the token was made) and the expiry day."""
    return made + datetime.timedelta(days=53), made + datetime.timedelta(days=60)


assert linkedin_due(datetime.date(2026, 1, 1), None)[1] == datetime.date(2026, 3, 2)

made = os.environ.get("LINKEDIN_TOKEN_DATE", "").strip()
if made:
    start, expires = linkedin_due(datetime.date.fromisoformat(made), TODAY)
    if TODAY >= start:
        issue(f"LinkedIn key expires {expires:%d %b %Y}",
              "The LinkedIn posting key lasts 60 days. Make a new one (ask Claude: \"renew LinkedIn key\"), save it as the "
              "LINKEDIN_ACCESS_TOKEN secret, and set the repo variable LINKEDIN_TOKEN_DATE to today's date. Then close this issue.")

if TODAY.weekday() == 0 or "--report" in sys.argv:
    state = json.loads((SITE / "content/syndicated.json").read_text()) if (SITE / "content/syndicated.json").exists() else {}
    recent = sorted(p.stem for p in (SITE / "content/articles").glob("*.md")
                    if re.match(r"\d{4}-\d{2}-\d{2}", p.stem) and (TODAY - datetime.date.fromisoformat(p.stem[:10])).days <= 7)
    rows = [f"| {s} | {sum(a in state.get(s, []) for a in recent)} |" for s in SITES]  # only articles under 3 days old are posted, so no "of N"
    issue(f"Weekly posting report: {TODAY:%d %b %Y}",
          f"Articles from the last 7 days: {len(recent)}.\n\n| Site | Posted this week |\n|---|---|\n" + "\n".join(rows) +
          "\n\n0 means the site's key is not saved yet, or posting failed (see the Actions log). Close this issue after reading.")
