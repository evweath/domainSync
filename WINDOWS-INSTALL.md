# Donut Intel — Windows Install Guide

This guide shows you how to put the Donut Intel app on a Windows computer.
You do **not** need to be a computer expert. If you can follow steps and copy
files, you can do this. Read the steps in order the first time.

It takes about **20–30 minutes**, and most of that is just waiting for things
to download.

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

**How to check if your Windows is 64‑bit:** Click the **Start** button, type
`About your PC`, and press Enter. Look for **"System type."** It should say
**64‑bit**.

---

## Step 1 — Install Python

**Python** is the engine that makes the app run. You install it once.

1. Open this web page:
   **https://www.python.org/downloads/windows/**
2. Find **Python 3.12** (or 3.11). Click the link that says
   **"Windows installer (64‑bit)."**
3. When it finishes downloading, look in your **Downloads** folder. The file is
   named something like `python-3.12.x-amd64.exe`. **Double‑click it.**
4. ⚠️ **VERY IMPORTANT:** On the first screen, check the box at the bottom that
   says **"Add python.exe to PATH."** This is easy to miss. If you skip it,
   nothing will work later.
5. Click the big button **"Install Now."** If Windows asks for permission, click
   **Yes.**
6. Wait 1–3 minutes. When you see **"Setup was successful,"** click **Close.**

**Check that it worked:** Press the **Windows key**, type `cmd`, and press
Enter. A black window opens (this is called **Command Prompt**). Type this and
press Enter:

```
python --version
```

If you see something like `Python 3.12.3`, Python is installed. 🎉 You can close
the black window.

> If it says **"python is not recognized,"** the "Add to PATH" box was not
> checked. Uninstall Python from **Settings → Apps**, then install it again and
> check that box.

---

## Step 2 — Put the app files on your computer

You were given a folder of app files (often a ZIP file).

1. The easiest spot is the **C: drive**. Make a folder there called
   `DonutIntel`, so the path is `C:\DonutIntel`.
2. If you have a ZIP file, **right‑click it → "Extract All…"**, type `C:\` as the
   place to put it, and click **Extract.**
3. Open **File Explorer** (the yellow folder on your taskbar) and go to
   `C:\DonutIntel`. You should see files like `setup.bat`, `start.bat`,
   `stop.bat`, and folders named `backend` and `frontend`.

> You can put the folder somewhere else if you want. Just remember where it is.

---

## Step 3 — Run the one‑time setup

This installs the rest of the app's helper software for you. You only do it once.

1. Open the `C:\DonutIntel` folder in File Explorer.
2. **Double‑click `setup.bat`.**
3. A black window opens and starts working. **This takes 5–15 minutes** because
   it downloads files. Do not close the window. Just wait.
4. When it says **"Setup finished!"**, you are done with this step.

> **No `setup.bat` file?** You can do the same thing by hand: open Command
> Prompt, type `cd C:\DonutIntel`, press Enter, then type `python setup_env.py`
> and press Enter.

---

## Step 4 — Set your password (and a few settings)

The app keeps its settings in a text file called `settings.yaml`.

1. In File Explorer, open the folder `C:\DonutIntel\config`.
2. **Right‑click `settings.yaml` → "Open with" → Notepad.**
3. Change these three things:

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

   **c) The browser type (for Windows).** Find:
   ```
   browser:
     default_profile: safari_mac
   ```
   Change it to:
   ```
   browser:
     default_profile: chrome_windows
   ```

4. Press **Ctrl+S** to save. Close Notepad.

> ⚠️ Keep `settings.yaml` private. It holds your passwords and keys. Do not email
> it or post it online.

**Optional:** If you use Shopify, or have keys for search/AI services, you can
add them in this file now — or later, from the app's **Settings** screen.

---

## Step 5 — Start the app

1. In `C:\DonutIntel`, **double‑click `start.bat`.**
2. A black window opens and says the app is running, and shows an address like
   **https://localhost:8800**.
3. **Leave this window open.** Closing it turns the app off. (You can make it
   small with the minus button.)
4. Your web browser should open the app by itself after a few seconds. If it
   does not, open your browser and type the address from the black window.

---

## Step 6 — Get past the safety warning (this is normal)

The app uses a security lock it made itself, so your browser shows a warning the
first time. **This is safe** — the app is only on your own computer.

- **Chrome:** click **"Advanced" → "Proceed to localhost (unsafe)."**
- **Edge:** click **"Advanced" → "Continue to localhost (unsafe)."**
- **Firefox:** click **"Advanced…" → "Accept the Risk and Continue."**

You only do this once per browser.

---

## Step 7 — Log in

1. Type the **username** (`admin`) and the **password** you set in Step 4.
2. Click **Sign In.** The dashboard opens. You're in! 🎉

Now open the **`WINDOWS-USER-GUIDE.md`** file to learn what every button does.

---

## Step 8 — Stop the app

Two easy ways:

- **Double‑click `stop.bat`,** OR
- Click the black "server" window and press **Ctrl+C.**

It is good to stop the app before you turn the computer off.

---

## Quick reference card

| I want to… | Do this |
|---|---|
| Set up the app (one time) | Double‑click `setup.bat` |
| Turn the app on | Double‑click `start.bat` |
| Turn the app off | Double‑click `stop.bat` |
| Open the app | Browser → `https://localhost:8800` |
| Log in | `admin` + your password |

If anything goes wrong, see the **Troubleshooting** part of
`WINDOWS-USER-GUIDE.md`.
