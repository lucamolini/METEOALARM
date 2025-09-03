#!/usr/bin/env python3
import os, asyncio, smtplib, ssl, time, re
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from pathlib import Path

URL = os.getenv("TARGET_URL", "https://meteoalarm.org/en/live/?t=day0&h=3,10,12,13#list")
OUT = os.getenv("SCREENSHOT_PATH", "meteoalarm.png")
TZ = os.getenv("LOCAL_TZ", "Europe/Rome")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_TO = os.getenv("MAIL_TO")
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER)

SUBJECT = f"Meteoalarm – screenshot {datetime.now(ZoneInfo(TZ)).strftime('%Y-%m-%d')}"
BODY = """Ciao,
in allegato lo screenshot Meteoalarm di oggi.
"""

# --- invia mail ---
def send_email(path: str):
    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg.set_content(BODY)

    with open(path, "rb") as f:
        data = f.read()
    msg.add_attachment(data, maintype="image", subtype="png", filename=Path(path).name)

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=ctx)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

async def take_screenshot():
    # import playwight in funzione per evitare import costoso se non si invia
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2
        )
        page = await context.new_page()
        # carica pagina e attendi reti inattive
        await page.goto(URL, wait_until="networkidle", timeout=120_000)

        # prova a chiudere eventuale banner cookie / privacy, se presente
        try:
            # tentativi comuni
            for label in ["Accept all", "Accept All", "I agree", "OK", "Agree", "Consent", "Accetta", "Accetta tutto"]:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if await btn.count() > 0:
                    await btn.first.click()
                    break
        except Exception:
            pass

        # extra attesa per rendering mappa (app web dinamica)
        await page.wait_for_timeout(3000)

        # screenshot pagina intera (robusto contro cambi DOM)
        await page.screenshot(path=OUT, full_page=True)
        await browser.close()

def main():
    # invia SOLO alle 08:00 ora di Roma (tolleranza 10 minuti)
    now = datetime.now(ZoneInfo(TZ))
    if not (now.hour == 8):
        print(f"Skip: ora locale {now.strftime('%H:%M')} != 08:xx")
        return

    # controlla variabili SMTP
    required = [SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO]
    if any(v in (None, "") for v in required):
        raise SystemExit("Variabili SMTP mancanti. Vedi README/segreti del workflow.")

    # prendi screenshot e invia
    asyncio.run(take_screenshot())
    send_email(OUT)
    print("Email inviata con allegato:", OUT)

if __name__ == "__main__":
    main()
