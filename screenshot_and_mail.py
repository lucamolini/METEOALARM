#!/usr/bin/env python3
import os, asyncio, smtplib, ssl, re
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from pathlib import Path

URL = os.getenv("TARGET_URL", "https://meteoalarm.org/en/live/?t=day0&h=3,10,12,13#list")
OUT = os.getenv("SCREENSHOT_PATH", "meteoalarm.png")
TZ = os.getenv("LOCAL_TZ", "Europe/Rome")
FORCE_SEND = os.getenv("FORCE_SEND", "0") == "1"
SAVE_EML = os.getenv("SAVE_EML", "0") == "1"

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_TO = os.getenv("MAIL_TO")
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER)
REPLY_TO = os.getenv("REPLY_TO", MAIL_FROM)

def log(msg): print(f"[{datetime.utcnow().isoformat()}Z] {msg}")

def build_email(path: str) -> EmailMessage:
    now_local = datetime.now(ZoneInfo(TZ))
    subject = f"Meteoalarm – screenshot {now_local.strftime('%Y-%m-%d')}"
    body = f"""Ciao,
in allegato lo screenshot Meteoalarm di oggi ({now_local.strftime('%Y-%m-%d %H:%M')} {TZ}).
"""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO
    msg.set_content(body)
    with open(path, "rb") as f:
        data = f.read()
    msg.add_attachment(data, maintype="image", subtype="png", filename=Path(path).name)
    return msg

def send_email(msg: EmailMessage):
    ctx = ssl.create_default_context()
    log(f"Invio email via {SMTP_HOST}:{SMTP_PORT} come {SMTP_USER}, From={msg['From']} To={msg['To']}")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as server:
        server.starttls(context=ctx)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    log("Email inviata (SMTP ha accettato il messaggio).")

async def take_screenshot():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
        )
        page = await context.new_page()
        log(f"Apro URL: {URL}")
        await page.goto(URL, wait_until="networkidle", timeout=120_000)
        try:
            for label in ["Accept all", "Accept All", "I agree", "OK", "Agree", "Consent", "Accetta", "Accetta tutto"]:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if await btn.count() > 0:
                    await btn.first.click()
                    log(f"Chiuso banner cookie con bottone '{label}'")
                    break
        except Exception as e:
            log(f"Cookie banner: nessuna azione ({e})")
        await page.wait_for_timeout(3000)
        await page.screenshot(path=OUT, full_page=True)
        await browser.close()
        log(f"Screenshot salvato in {OUT}")

def main():
    now_local = datetime.now(ZoneInfo(TZ))
    log(f"Ora locale {TZ}: {now_local.strftime('%Y-%m-%d %H:%M:%S')} | UTC offset ~ {now_local.utcoffset()}")
    if not FORCE_SEND and now_local.hour != 8:
        log("Skip: non sono le 08 locali (usa FORCE_SEND=1 per test).")
        return

    required = [SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO]
    if any(v in (None, "") for v in required):
        missing = ["SMTP_HOST","SMTP_USER","SMTP_PASS","MAIL_TO"]
        log("ERRORE: variabili SMTP mancanti: " + ", ".join([n for n,v in zip(missing, required) if v in (None,'')]))
        raise SystemExit(1)

    # Best practice: From deve essere lo stesso dominio/account dell'SMTP
    if MAIL_FROM != SMTP_USER:
        log("ATTENZIONE: MAIL_FROM diverso da SMTP_USER. Alcuni provider potrebbero rifiutare/filtrare.")

    # Scatta e invia
    asyncio.run(take_screenshot())
    msg = build_email(OUT)
    if SAVE_EML:
        eml_path = "debug.eml"
        with open(eml_path, "wb") as f:
            f.write(bytes(msg))
        log(f"Salvato anche {eml_path} per debug")
    send_email(msg)

if __name__ == "__main__":
    main()
