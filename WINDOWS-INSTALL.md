# Donut Intel — Windows Install Guide

This guide shows you how to put the Donut Intel app on a Windows computer.
You do **not** need to be a computer expert. If you can follow steps and copy
files, you can do this. Read the steps in order the first time.

It takes about **20–30 minutes**, and most of that is just waiting for things
to download.

**You do NOT need to install anything first.** The app's setup program
downloads and installs everything it needs — including Python — all by itself.
All you need is Windows and an internet connection.

---

## What this app does (in one sentence)

It is like a smart helper that visits store websites, writes down what every
product costs, and shows you when someone is selling the same thing cheaper
than you.

---

## What you need first

| Thing | What is okay |
|---|---|
| Windows | Windows 10 or Windows 11, the **64‑bit** kind |
| Memory (RAM) | 4 GB is okay, 8 GB is better |
| Free disk space | About 5 GB |
| Internet | Yes — needed to set up and to scan websites |
| Web browser | Edge, Chrome, or Firefox (already on your PC) |
| Anything else? | **No.** Setup installs Python and everything else for you. |

**How to check if your Windows is 64‑bit:** Click the **Start** button, type
`About your PC`, and press Enter. Look for **"System type."** It should say
**64‑bit**.

---

## Step 1 — Put the app files on your computer

You were given a ZIP file called `DonutIntel-Windows.zip`.

1. **Right‑click the ZIP file → "Extract All…"**, type `C:\` as the place to
   put it, and click **Extract.**
2. Open **File Explorer** (the yellow folder on your taskbar) and go to
   `C:\DonutIntel`. You should see files like `setup.bat`, `start.bat`,
   `stop.bat`, and folders named `backend` and `frontend`. Your product
   database is already included, in the `data` folder.

> You can put the folder somewhere else if you want. Just remember where it is.

---

## Step 2 — Run the one‑time setup

This installs **everything** the app needs, automatically:

- Finds **Python** on your computer — or downloads it, installs it, and adds
  it to the Windows **PATH** setting if you don't have it
- Installs all the app's helper software
- Downloads the browser engines the app uses to read websites
- Creates security certificates (if needed)
- Puts a **Donut Intel** shortcut on your **Desktop**

You only do this once:

1. In the `C:\DonutIntel` folder, **double‑click `setup.bat`.**
2. If Windows shows a blue **"Windows protected your PC"** message, click
   **More info → Run anyway.**
3. A black window opens and starts working. **This takes 10–20 minutes** on a
   new computer because it downloads files. Do not close the window. Just wait.
4. When it says **"Setup finished!"**, you are done. Look for the new
   **Donut Intel** icon on your Desktop.

> **If anything stops halfway:** just double‑click `setup.bat` again. It is
> safe to run as many times as needed — it skips what is already done and
> finishes the rest. If it says a download failed, check the internet
> connection and run it once more.

---

## Step 3 — Set your password (and a few settings)

The app keeps its settings in a text file called `settings.yaml`.

1. In File Explorer, open the folder `C:\DonutIntel\config`.
2. **Right‑click `settings.yaml` → "Open with" → Notepad.**
3. Change these two things:

   **a) Your login password.** Find:
   ```
   auth:
     enabled: true
     username: admin
     password: changeme
   ```
   Change `changeme` to a password only you know.

   **b) The secret key.** Find the line with `secret_key:` and replace the value
   with any random mix of **at least 32 letters and numbers** you make up.
   Example (do not copy this exact one): `xK9mP2qL7nR4vT1wY8sA5jB3hC6dE0fZ`.

4. Press **Ctrl+S** to save. Close Notepad.

> ⚠️ Keep `settings.yaml` private. It holds your passwords and keys. Do not
> email it or post it online. (Your store connection keys are already filled
> in — they came with the ZIP.)

---

## Step 4 — Start the app

1. **Double‑click the `Donut Intel` shortcut on your Desktop** (or
   double‑click `start.bat` in `C:\DonutIntel`).
2. A black window opens and says the app is running, and shows an address like
   **https://localhost:8800**.
3. **Leave this window open.** Closing it turns the app off. (You can make it
   small with the minus button.)
4. Your web browser should open the app by itself after a few seconds. If it
   does not, open your browser and type the address from the black window.

---

## Step 5 — Get past the safety warning (this is normal)

The app uses a security lock it made itself, so your browser shows a warning
the first time. **This is safe** — the app is only on your own computer.

- **Chrome:** click **"Advanced" → "Proceed to localhost (unsafe)."**
- **Edge:** click **"Advanced" → "Continue to localhost (unsafe)."**
- **Firefox:** click **"Advanced…" → "Accept the Risk and Continue."**

You only do this once per browser.

---

## Step 6 — Log in

1. Type the **username** (`admin`) and the **password** you set in Step 3.
2. Click **Sign In.** The dashboard opens. You're in! 🎉

Now open the **`WINDOWS-USER-GUIDE.md`** file to learn what every button does.

---

## Step 7 — Stop the app

Two easy ways:

- **Double‑click `stop.bat`,** OR
- Click the black "server" window and press **Ctrl+C.**

It is good to stop the app before you turn the computer off.

---

## Quick reference card

| I want to… | Do this |
|---|---|
| Set up the app (one time) | Double‑click `setup.bat` |
| Turn the app on | Double‑click the **Donut Intel** Desktop shortcut (or `start.bat`) |
| Turn the app off | Double‑click `stop.bat` |
| Open the app | Browser → `https://localhost:8800` |
| Log in | `admin` + your password |

If anything goes wrong, see the **Troubleshooting** part of
`WINDOWS-USER-GUIDE.md`.
