# Donut Intel — User Guide (What Every Button Does)

This guide explains how to use the app, one screen at a time, in plain words.
Keep it nearby while you learn. To install the app first, read
`WINDOWS-INSTALL.md`.

---

## How the app is built (the big picture)

- You turn the app **on** by double‑clicking `start.bat`. That starts a
  **server** (a program that runs quietly in the background).
- You **use** the app in your **web browser** at `https://localhost:8800`.
- On the **left side** is a menu (a **sidebar**) with buttons that take you to
  different screens.
- The app remembers everything in a **database** (a big organized list) saved on
  your computer.

A few words you'll see a lot:

- **Source site / your store** — a website that belongs to you.
- **Competitor** — another store that sells what you sell.
- **Scan** — when the app visits a website and writes down its products.
- **Product** — one item you sell. A **variant** is a version of it (like a size).
- **System of Record (SoR)** — the one store you trust the most. The app treats
  **donut-equipment.com** as the "true" version, and lines the others up to it.

---

## The menu — all 12 screens

Below is every button in the sidebar, what it does, and how to use it.

---

### 📊 Dashboard — the home screen

**What it does:** Shows a quick summary of everything: how many products you
have, when the last scan ran, and a live list of what the app is doing right
now.

**What you'll see:**
- **Number cards** — total products, store listings, duplicates waiting for you,
  and new products found lately.
- **Products by store** — how many products come from each website.
- **Live log** — a window at the bottom that scrolls as the app works. You can
  filter it to show only normal messages, warnings, or serious problems.

---

### 🔍 Scans — start and watch scans

**What it does:** A **scan** is when the app visits your store websites and
collects their products and prices. This screen lets you start one and see the
history of past scans.

**How to use it:**
1. Click **Scans** in the menu.
2. Click the button to start a new source scan (it checks all your stores).
3. Watch it work. Each scan shows a status: **Running, Completed,** or **Failed.**
4. If a scan is still running, you can **Cancel** it.

> Good to know: at the end of every scan, the app automatically lines all your
> stores up to the System of Record, so the same product becomes **one shared
> record** instead of many copies.

---

### 🔁 Duplicates — clean up double listings

**What it does:** Sometimes the same product is listed twice **inside the same
store.** This screen shows those look‑alikes and lets you decide what to do.

**How to use it:**
1. Click **Duplicates** in the menu.
2. Each row shows two products that look alike, with a **match score** (0–100%).
   A higher score means they are more likely the same thing.
3. Click **Merge** to join them into one product.
4. Click **Reject** if they are really different and should stay separate.

> The app does **not** merge these for you. You choose, on purpose, so nothing is
> joined by mistake.

---

### 🔀 Store Compare — the same product across your stores

**What it does:** Shows one row per product, with a column for each of your
stores, so you can spot where a product is **missing** from a store or has a
**different price.**

**What you'll see at the top — the "Gaps" bar:** small buttons (chips), one per
store, that show how many products each store is **missing.** The System of
Record store is highlighted. **Click a chip** to filter the list to just the
products that store is missing.

**How to use it:**
1. Click **Store Compare** in the menu.
2. To compare just two stores, pick them in **"Compare store: Store A / Store
   B."**
3. Turn on **"Diffs only"** to see only products that differ between stores.
4. Use **"Missing from store"** to see products one store does not have.
5. Click a product to open it and copy a value from one store into the shared
   record.

---

### 🛍️ Shopify Sync — make a Shopify import file

**What it does:** Builds a spreadsheet file (CSV) you can upload into Shopify to
update your store's product information. Good for big, one‑time updates.

**How to use it:**
1. Click **Shopify Sync** in the menu.
2. Pick the store to copy **from.**
3. Choose which product fields to include.
4. Click to build the file, then upload it to Shopify.

> Needs your Shopify details in **Settings** to pull live data.

---

### ⚡ Live Sync — push changes straight into a Shopify store

**What it does:** Copies product information **from one Shopify store (the
source) into another (the destination),** through Shopify's live connection.
**Only the destination store is changed. The source is never touched.**

It is a **5‑step wizard.** A bar at the top shows where you are:
**Set up → Preview → Review & approve → Apply → Done.**

**Step 1 — Set up:**
- At the top is a **"How Live Sync works"** box and a live **"Your plan"** line
  that shows exactly what will happen as you make choices.
- **Pick a Source** (the store you trust) and a **Destination** (the store that
  gets changed). Click **Fetch catalog** on a store to load its products.
- **"What to Sync":** small buttons for each field (Title, Description, Vendor,
  Product Type, Tags, Variants & Pricing, Images, Collections). Each has a
  **checkbox under it.** Tick the fields you want to copy.
- **"Include new products"** also creates products the destination is missing.
- **"Include deletes"** (red, **CRITICAL**) removes products the destination has
  but the source does not. Off by default. Be careful with this one.
- Keep **"Transaction warnings"** ON. It makes you approve changes before they
  happen.
- Click **"Compare Stores & Preview Changes."** This only looks — it writes
  nothing yet.

**Step 2 — Preview:** the app reads both stores and works out the differences.

**Step 3 — Review & approve:** you see a list of every proposed change.
- Each change shows the old value → the new value, plus any warnings.
- Use the **dropdown** to filter by **product characteristic** (Title,
  Description, Images, Tags, Variants & pricing, and so on).
- Use the buttons to **Approve shown / Reject shown** (just what the filter
  shows) or **Approve all / Reject all.**
- The round button on each row turns it ✓ (yes), ✗ (no), or ? (not decided).

**Step 4 — Apply:** click **"Apply N Approved Change(s) to [store]."** Only the
ones you approved are written to the destination store. This is a **real change**
to that live store.

**Step 5 — Done:** shows how many changes worked and any errors.

---

### 🔄 Source Sync — keep your own stores matching

**What it does:** Compares your own websites with each other and helps you fix
differences, so all your stores carry the same products at the same info.

**How to use it:**
1. Click **Source Sync** in the menu.
2. Pick the stores to compare.
3. Review the differences (missing products in one list, price gaps in another).
4. **Approve** the changes you want, **Reject** the ones you don't.
5. Run the cycle to apply the approved changes.

---

### 🏛️ System of Record — pick your "true" store

**What it does:** Lets you choose the one store that is the master copy
(**donut-equipment.com** by default). Every other store is compared against it.

**What you'll see:** tabs for **Missing** (the master has it, this store doesn't),
**Differing** (same product, different info), **Matching** (already the same),
and **Fuzzy** (close but not an exact match).

> Because of this, the **price you see as the main price** for a product always
> comes from the System of Record store.

---

### ⏰ Scheduler — let the app run by itself

**What it does:** Runs tasks automatically on a timetable, so you don't have to
remember. Example: "Scan all my stores every morning at 9 AM."

**How to make a scheduled job:**
1. Click **Scheduler** in the menu.
2. Click **New Job.**
3. Give it a name and pick a job type (like Source Scan or Export).
4. Choose **when:** Daily, Weekly, Monthly, or a custom time.
5. Click **Save.** It now runs by itself. You can also click **Run Now** to do it
   right away.

> The app must be **on** (the server window open) for scheduled jobs to run.

---

### 📋 Reports — make a printable summary

**What it does:** Builds a report you can read on screen or save. Types include:
- **Summary** — an overview of your catalog.
- **Price Disparity** — products where a competitor's price is very different.
- **Competitor Profile** — everything known about one competitor.
- **Price Comparison** — the price history of one product.

**How to use it:** pick a report type, fill in any details it asks for, click
**Generate,** then **Download** to save it.

---

### 📤 Export — save your data as a spreadsheet

**What it does:** Downloads your product list as a file you can open in Excel or
Google Sheets.

**How to use it:**
1. Click **Export** in the menu.
2. Pick a format: **CSV** (works in Excel and Google Sheets), **XLSX** (Excel),
   or **TXT** (plain text).
3. Pick which columns to include.
4. Click **Export.** The file saves to your Downloads folder (and the app's
   `exports` folder).

---

### ⚙️ Settings — change how the app works

**What it does:** Change most settings right in the browser, without editing
files. Changes take effect right away.

Common things you can change here:
- **Login** — username, password, and whether login is required.
- **Stores** — add or edit your source websites and their Shopify keys.
- **Database** — see where your data is saved and back it up.
- **Scraping** — how fast or slow the app visits websites.
- **AI** — turn on smart product categories (needs an Anthropic key).
- **Lists** — websites to ignore, and known manufacturer sites.

---

## Command‑line tools (for advanced users only)

You do **not** need these for normal use — the screens above do everything. But
if you like typing commands, open Command Prompt, type `cd C:\DonutIntel`, press
Enter, then run any of these. (Each one uses the app's private Python at
`.venv\Scripts\python`.)

| Command | What it does |
|---|---|
| `.venv\Scripts\python cli.py scan` | Scan all your stores now |
| `.venv\Scripts\python cli.py competitor-scan` | Scan competitor websites |
| `.venv\Scripts\python cli.py yahoo-scan` | Look up prices on Yahoo Shopping |
| `.venv\Scripts\python cli.py import-competitors --file C:\list.txt` | Add many competitors from a text file |
| `.venv\Scripts\python cli.py dedup` | Find duplicate products |
| `.venv\Scripts\python cli.py stats` | Show counts (products, scans, etc.) |
| `.venv\Scripts\python cli.py export` | Export your data to a file |
| `.venv\Scripts\python cli.py report` | Build a report |
| `.venv\Scripts\python cli.py schedule` | Manage scheduled jobs |

> There are also two repair tools for advanced cleanup —
> `repair-match-links` and `force-dedup`. Only use these if you know what they
> do or you are told to.

---

## Troubleshooting (when something goes wrong)

**"python is not recognized."**
Python was installed without the "Add to PATH" box. Uninstall Python from
**Settings → Apps**, install it again, and check that box. Then run `setup.bat`.

**`start.bat` says "the app is not set up yet."**
You skipped the install step. Double‑click `setup.bat` first and wait for it to
finish.

**The browser shows "Your connection is not private."**
This is normal. Click **Advanced**, then **Proceed / Continue to localhost.**
(See the install guide for each browser.)

**The page won't load at all.**
Make sure the black **server window** is still open (that is the app running).
If you closed it, double‑click `start.bat` again.

**Scans come back empty.**
Websites sometimes block too many quick visits. Wait about an hour and try
again. This is usually not a bug.

**I forgot my password.**
Open `C:\DonutIntel\config\settings.yaml` in Notepad and read or change the
`password:` line, then save.

**Where is my data saved?**
In `C:\DonutIntel\data`. To make a copy, stop the app first, then copy that
folder somewhere safe.

**How do I move the app to another computer?**
Copy the whole `C:\DonutIntel` folder. On the new PC, install Python (Step 1),
then run `setup.bat` once.

---

## Glossary — words and what they mean

- **API key** — a secret code that lets the app talk to another service (like
  Shopify). It works like a password.
- **Browser** — the program you use to view websites (Chrome, Edge, Firefox).
- **Command Prompt** — a black window where you type commands instead of clicking.
- **Database** — the organized list where the app keeps all your data.
- **Destination** — in Live Sync, the store that **gets changed.**
- **Localhost** — your own computer. `localhost:8800` means "this computer,
  door number 8800."
- **Scan** — the app visiting a website to collect products and prices.
- **Server** — the part of the app that runs in the background (the black
  window). It must stay open while you use the app.
- **Source** — in Live Sync, the store you copy **from** (it is never changed).
- **System of Record (SoR)** — your most‑trusted store; the app treats
  donut-equipment.com as the master copy.
- **Variant** — a version of a product, like a size or color.
- **YAML** — the simple text format used by the `settings.yaml` file.
