#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
screenshot_and_mail.py

- Scatta uno screenshot della pagina Meteoalarm (o di TARGET_URL)
- Invia l'immagine via email come allegato
- Invio giornaliero alle 08:00 ora di Europe/Rome (a meno che FORCE_SEND=1)

ENV supportate:
  TARGET_URL       (default: meteoalarm live)
  SCREENSHOT_PATH  (default: meteoalarm.png)
  LOCAL_TZ         (default: Europe/Rome)
  FORCE_SEND       (0/1) -> invia anche se non è l'ora prevista
  SAVE_EML         (0/1) -> salva una copia .eml per debug
  SMTP_HOST        (obblig.)
  SMTP_PORT        (default: 587)
  SMTP_USER        (obblig.)
  SMTP_PASS        (obblig.)
  MAIL_TO          (obblig.)
  MAIL_FROM        (default: SMTP_USER)
  REPLY_TO         (default: MAIL_FROM)
  SMTP_SECURE      ("", "ssl", "starttls") -> "" = auto (465->ssl, altrimenti starttls)
  SMTP_DEBUG       (0/1) -> transcript SMTP nei log

Dipendenze:
  pip install playwright==1.46.0
  python -m playwright install --with-deps chromium
"""

import os
import re
import ssl
import asyncio
import smtplib
import socket
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

# -------------------- Config da ENV --------------------
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

SMTP_SECURE = os.getenv("SMTP_SECURE", "").lower()  # "", "ssl", "starttls"
SMTP_DEBUG = int(os.getenv("SMTP_DEBUG", "0"))      # 0/1

# -------------------- Utility --------------------
def log(msg: str) -> None:
    print(f"[{datetime.utcnow().isoformat()}Z] {msg}", flush=True)


# -------------------- Email --------------------
def build_email(path: str) -> EmailMessage:
    now_local = datetime.now(ZoneInfo(TZ))
    subject = f"Meteoalarm – screenshot {now_local.strftime('%Y-%m-%d')}"
    body = (
        f"Ciao,\n"
        f"in allegato lo screenshot Meteoalarm (https://meteoalarm.org/) di oggi "
        f"({now_local.strftime('%Y-%m-%d %H:%M')} {TZ}).\n"
    )

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


def send_email(msg: EmailMessage) -> None:
    host = SMTP_HOST
    port = SMTP_PORT

    # Auto-detect modalità se non specificata
    if SMTP_SECURE in ("ssl", "starttls"):
        mode = SMTP_SECURE
    elif port == 465:
        mode = "ssl"
    else:
        mode = "starttls"

    # Info DNS
    try:
        ip = socket.gethostbyname(host) if host else "unresolved"
    except Exception:
        ip = "unresolved"

    log(f"Invio email via {host}:{port} (ip={ip}) mode={mode} "
        f"as {SMTP_USER}, From={msg['From']} To={msg['To']}")

    attempts = 3
    delay = 3
    last_err = None

    for i in range(1, attempts + 1):
        try:
            if mode == "ssl":
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, timeout=60, context=ctx) as server:
                    if SMTP_DEBUG:
                        server.set_debuglevel(1)
                    server.login(SMTP_USER, SMTP_PASS)
                    server.send_message(msg)
            else:
                ctx = ssl.create_default_context()
                with smtplib.SMTP(host, port, timeout=60) as server:
                    if SMTP_DEBUG:
                        server.set_debuglevel(1)
                    server.ehlo()
                    server.starttls(context=ctx)
                    server.ehlo()
                    server.login(SMTP_USER, SMTP_PASS)
                    server.send_message(msg)

            log("Email inviata (SMTP ha accettato il messaggio).")
            return
        except Exception as e:
            last_err = e
            log(f"Tentativo {i}/{attempts} fallito: {repr(e)}")
            time.sleep(delay)
            delay *= 2

    raise SystemExit(f"Invio fallito dopo {attempts} tentativi: {repr(last_err)}")


# -------------------- Screenshot --------------------
async def take_screenshot() -> None:
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

        # Cookie banner: prova a chiuderlo con varie etichette comuni
        try:
            labels = [
                "Accept all", "Accept All", "I agree", "OK",
                "Agree", "Consent", "Accetta", "Accetta tutto",
            ]
            for label in labels:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if await btn.count() > 0:
                    await btn.first.click()
                    log(f"Chiuso banner cookie con bottone '{label}'")
                    break
        except Exception as e:
            log(f"Cookie banner: nessuna azione ({e})")

        # Attendi un minimo per rendering dinamico
        await page.wait_for_timeout(6000)

        await page.screenshot(path=OUT, full_page=True)
        await browser.close()
        log(f"Screenshot salvato in {OUT}")


# -------------------- Main --------------------
def main() -> None:
    now_local = datetime.now(ZoneInfo(TZ))
    log(f"Ora locale {TZ}: {now_local.strftime('%Y-%m-%d %H:%M:%S')} | UTC offset ~ {now_local.utcoffset()}")

    # Gate sull'orario locale
    if not FORCE_SEND and now_local.hour != 8:
        log("Skip: non sono le 08 locali (usa FORCE_SEND=1 per test).")
        return

    # Controllo variabili SMTP
    required_vals = [SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO]
    required_names = ["SMTP_HOST", "SMTP_USER", "SMTP_PASS", "MAIL_TO"]
    if any(v in (None, "") for v in required_vals):
        missing = ", ".join(n for n, v in zip(required_names, required_vals) if v in (None, ""))
        log(f"ERRORE: variabili SMTP mancanti: {missing}")
        raise SystemExit(1)

    # Best practice: MAIL_FROM allineato a SMTP_USER per DMARC/SPF
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
