COINDESK RSS SCRAPE SCHEDULER
============================

1. PURPOSE
----------

rss_scrape_scheduler.py is an incremental news-ingestion job. Each time the
script runs, it downloads the 25 newest CoinDesk RSS entries, compares them
with the previous RSS snapshot, and scrapes only entries that have not appeared
in that snapshot.

The script performs one complete batch and then exits. It does not keep running
by itself. Cron, Windows Task Scheduler, APScheduler, Airflow, or another
scheduling service can execute it repeatedly.


2. REQUIRED FILES
-----------------

Share these files:

  rss_scrape_scheduler.py   Main ingestion job
  requirements.txt          Required Python packages
  RSS_SCRAPER_README.txt    This documentation

The JSON files do not need to be shared for a fresh installation. The script
creates them automatically. Share rss_history.json only if the other computer
must continue from the same RSS snapshot instead of treating its first feed as
new.


3. REQUIREMENTS
---------------

  Python 3.9 or newer
  Internet access
  Permission to read the CoinDesk RSS feed and public article pages

Python packages:

  feedparser
  requests
  trafilatura


4. FIRST-TIME SETUP
-------------------

Open a terminal inside the folder containing the shared files.

macOS/Linux:

  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install -r requirements.txt

Windows PowerShell:

  py -m venv .venv
  .venv\Scripts\Activate.ps1
  python -m pip install -r requirements.txt


5. RUN MANUALLY
---------------

Run this command from the project folder:

  python rss_scrape_scheduler.py

It prints each new article while scraping and ends with a summary similar to:

  {
    "rss_items": 25,
    "new_items": 3,
    "scrape_success": 2,
    "scrape_failed": 1
  }

On the first run, rss_history.json does not exist, so all available RSS entries
(up to 25) are considered new.


6. STEP-BY-STEP RUN SEQUENCE
----------------------------

Every invocation of run_scheduler() follows this sequence:

Step 1: Reset the current batch output

  scraped_news.json is replaced with an empty JSON list. This file represents
  only the current run, not every article collected in the past.

Step 2: Fetch the RSS feed

  The script requests:

  https://www.coindesk.com/arc/outboundfeeds/rss/

  It reads at most the newest 25 usable entries and extracts fields such as
  guid, title, RSS summary, URL, publication time, and categories.

Step 3: Save the temporary RSS snapshot

  The newest entries are written to rss_temp.json.

Step 4: Load the previous RSS snapshot

  The script reads rss_history.json. A missing history file is treated as an
  empty history. Invalid JSON stops the run instead of silently discarding the
  history.

Step 5: Detect new articles

  Each current entry is compared with history using both:

  a. RSS GUID/ID
  b. Normalized article URL

  URL normalization removes fragments and common tracking parameters such as
  utm_source, fbclid, and gclid. An entry is considered previously seen if
  either its GUID or its normalized URL matches history.

Step 6: Scrape only new articles

  For each new URL, the script downloads the public article page and uses
  trafilatura to extract the main article text. It also removes duplicate lines
  and a detected pagination tail.

  There is a two-second delay between article requests by default.

Step 7: Record success or failure

  Every processed item contains:

  full_body       Extracted article text, or null when extraction fails
  scrape_status   "success" or "failed"
  scrape_error    null on success or an error description on failure
  scraped_at      UTC timestamp for the scrape attempt

  scraped_news.json is checkpointed after every article. If the process stops
  unexpectedly, results completed during that run remain available.

Step 8: Advance RSS history

  After the full scraping loop completes, rss_history.json is replaced with the
  current 25-entry RSS snapshot.

Step 9: Print the summary

  The script reports the RSS count, new-item count, successful scrapes, and
  failed scrapes.


7. OUTPUT FILES
---------------

rss_temp.json

  The latest RSS data fetched during the current run. This is useful for
  inspection and debugging.

rss_history.json

  The RSS snapshot from the most recently completed run. It is used for the
  next comparison. This is a rolling 25-entry snapshot, not a permanent archive
  of every article ever processed.

scraped_news.json

  Only the articles detected as new during the current run, including their
  full extracted bodies and scrape statuses. It becomes [] when no new articles
  are found.

All three files are written atomically. The script first writes a temporary file
and then replaces the target, reducing the chance of incomplete JSON if writing
is interrupted.


8. USING THE RESULTS
--------------------

For database insertion or AI-model processing, normally select records where:

  article["scrape_status"] == "success"

Successful records contain full_body. Failed records remain in the batch so
errors can be monitored and diagnosed.

Do not treat scraped_news.json as a permanent database because it is cleared at
the start of every run. A downstream process should consume or copy successful
records before the next scheduled run.


9. AUTOMATIC SCHEDULING EXAMPLE
-------------------------------

The Python file is the job; an external scheduler decides when it runs.

Example cron entry for every 30 minutes on macOS/Linux:

  */30 * * * * cd /absolute/path/to/project && /absolute/path/to/project/.venv/bin/python rss_scrape_scheduler.py >> scheduler.log 2>&1

Replace /absolute/path/to/project with the actual folder. The computer must be
awake and connected to the internet at the scheduled time.

On Windows, create a task in Task Scheduler whose program is:

  C:\absolute\path\to\project\.venv\Scripts\python.exe

and whose argument is:

  C:\absolute\path\to\project\rss_scrape_scheduler.py

Set "Start in" to the project folder so the JSON files are created there.


10. CONFIGURATION
-----------------

The main settings are near the top of rss_scrape_scheduler.py:

  RSS_URL                     RSS source
  RSS_LIMIT                   Maximum entries per run (default: 25)
  RSS_TEMP_FILE               Temporary snapshot filename
  RSS_HISTORY_FILE            History snapshot filename
  SCRAPED_NEWS_FILE           Current scrape batch filename
  DELAY_BETWEEN_REQUESTS      Delay between pages (default: 2 seconds)

Because these are relative paths, run the script from its project folder. If a
scheduler uses another working directory, set its working directory explicitly
or change the constants to absolute paths.


11. IMPORTANT BEHAVIOR AND LIMITATIONS
--------------------------------------

  1. History stores only the previous 25-entry RSS snapshot. It is not an
     unlimited deduplication database.

  2. An article whose scrape attempt fails is still part of the new RSS history
     after the batch completes. Therefore, it is normally not retried on the
     immediately following run if its GUID or URL remains in that snapshot.

  3. Two scheduler instances should not run at the same time because they use
     the same JSON filenames. Configure the interval so one run finishes before
     the next begins.

  4. Website layout changes, access restrictions, timeouts, or anti-bot systems
     can cause individual scrape failures.

  5. Review the source website's terms, robots policy, and applicable rules
     before deploying frequent or large-scale scraping.


12. TROUBLESHOOTING
-------------------

ModuleNotFoundError:

  Activate the virtual environment and reinstall the packages:

  python -m pip install -r requirements.txt

No new articles:

  This is normal when all current GUIDs or URLs already exist in
  rss_history.json. scraped_news.json will contain [].

Invalid JSON history error:

  Inspect rss_history.json for corruption. Do not delete it unless starting a
  fresh history is intentional, because deletion makes the current RSS entries
  appear new again.

Network or HTTP errors:

  Confirm internet access and test the RSS URL in a browser. Individual article
  failures are recorded in scraped_news.json under scrape_error.

Files appear in the wrong folder:

  Run the script from the project folder or configure the scheduler's working
  directory. The current filenames are relative to the process's working
  directory.


13. QUICK TEST CHECKLIST
------------------------

  [ ] Create and activate the virtual environment.
  [ ] Install requirements.txt.
  [ ] Run python rss_scrape_scheduler.py.
  [ ] Confirm that all three JSON files appear.
  [ ] Review the printed summary.
  [ ] Open scraped_news.json and check scrape_status values.
  [ ] Run the script again and confirm already-seen RSS items are skipped.
  [ ] Configure the external scheduler only after manual tests succeed.

