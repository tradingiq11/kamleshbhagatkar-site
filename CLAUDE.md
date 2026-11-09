# kamleshbhagatkar.com: instructions for Claude

Static author website for Kamlesh Bhagatkar, author and geopolitical analyst (Nagpur, Bharat).
Articles are Markdown files in `content/articles/`. `tools/build_site.py` turns them into pages, PDFs, home cards, the archive, the sitemap and the RSS feed.
A GitHub Action (`.github/workflows/build.yml`) runs the build and deploys the site on every push to `main`.

**Never edit generated files by hand:** `articles/*.html`, `downloads/*`, `sitemap.xml`, `feed.xml`, or the block between `<!-- ARTICLES:START -->` and `<!-- ARTICLES:END -->` in `index.html`.

## Daily task: write two articles for approval

Run this when asked for "today's articles" (the scheduled 7:00 IST job does this every day).

1. **Date.** Use today's date in India (IST, UTC+5:30) as `YYYY-MM-DD`.
2. **Read the rules first:** `content/WRITING-RULES.md` (voice, topics, sourcing, red lines) and `content/HUMANIZER.md` (style pass). Both are binding.
3. **Avoid repeats.** Read the titles of the 15 newest files in `content/articles/`. Do not cover the same story again unless there is a real new development, and then say what is new.
4. **Research.** Search the news of the last 36 hours. Pick:
   - **A. Geopolitics:** India's foreign or security relations, or a world event and what it means for Bharat.
   - **B. Current Affairs (India only):** an Indian story of national importance: something that happened in India or was decided by an Indian authority (Union or state government, Parliament, RBI, ISRO, an Indian court, an Indian regulator or institution). Topics: policy, economy, governance, infrastructure, science and space, a court ruling already delivered. Never a foreign or world story, even one with an India angle; world events belong in Geopolitics.
   Every fact, number, date, name and quote must come from a source you actually opened. Prefer primary sources (PIB, MEA, ministries, RBI, ISRO, Parliament, UN, foreign governments), then established outlets. A key claim needs two independent sources, or one primary source.
5. **Write** each article in 750 to 1,000 words, following `content/WRITING-RULES.md`. End with `## Sources`, a list of `[Outlet: headline](url)` for every source used.
6. **Fact-check pass.** List every factual claim in the draft and check it against the opened source. Delete or soften any claim you cannot match. Opinions must read as opinions.
7. **Humanizer pass.** Apply `content/HUMANIZER.md` in file mode to each article. Keep every checked fact; do not add new ones.
8. **Save** as `content/articles/<date>-<short-slug>.md` (lowercase, hyphens, at most 6 words) using the front matter in `tools/build_site.py`: `title`, `date`, `category` (`Geopolitics` or `Current Affairs`), `summary` (one line, at most 25 words), `description` (one sentence for Google that names Kamlesh Bhagatkar). No `image` field.
9. **Validate:** `python3 tools/build_site.py --check` must print `OK`. Fix and repeat until it does. Do not run the full build or commit generated files; the Action does that after approval.
10. **Open a pull request for approval. Never merge it yourself and never push to `main`.**
    - Branch `daily/<date>`. Commit only the new `.md` files.
    - Commit identity: `git -c user.name="Kamlesh Bhagatkar" -c user.email="349884432+tradingiq11@users.noreply.github.com" commit -m "Daily articles: <date>"`.
    - PR title: `Daily articles: <date>`. PR body, in plain language for reading on a phone:
      - for each article: title, category, word count, the summary, and a list of the 5 to 8 most important claims, each with its source link;
      - anything uncertain or left out, and why;
      - the line: "Approve = tap **Merge pull request**. Changes = comment on the PR. Reject = **Close pull request**."
    - Write links as plain Markdown `[text](https://...)` with nothing around the URL (no backticks or quotes). After creating the PR, read its body back and fix any link that is wrapped in backticks or quotes.
11. If you cannot find a topic that meets the rules, or the sources do not hold up, write only the article that does, or none, and open the PR (or an issue if there is nothing to review) explaining why. A missing article is better than a weak one.

## Editing an existing article
Edit its `.md` file and push or open a PR. The build regenerates the page and its PDF.
