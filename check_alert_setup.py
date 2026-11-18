"""
Run this from the project folder (next to app.py):

    python check_alert_setup.py

It tells you exactly why alerts are in SIMULATION mode and what to fix.
It never prints your secret keys.
"""
import os
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[OK] python-dotenv installed")
except ImportError:
    print("[FIX] python-dotenv missing -> run: pip install python-dotenv")

print("[OK] .env file found" if os.path.exists(".env")
      else "[FIX] No .env file in this folder. Copy .env.example to .env and fill it in.")

problems = 0
for var in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"):
    val = os.environ.get(var, "")
    if not val or "xxxx" in val.lower() or val.startswith("your_"):
        print(f"[FIX] {var} is empty or still the example value")
        problems += 1
    else:
        print(f"[OK] {var} is set")

sms_from = os.environ.get("TWILIO_SMS_FROM", "")
wa_from = os.environ.get("TWILIO_WHATSAPP_FROM", "")
if not sms_from and not wa_from:
    print("[FIX] Set TWILIO_SMS_FROM (your Twilio number) and/or TWILIO_WHATSAPP_FROM")
    problems += 1
else:
    print(f"[OK] From-number set (SMS: {bool(sms_from)}, WhatsApp: {bool(wa_from)})")

try:
    import twilio  # noqa: F401
    print("[OK] twilio package installed")
except ImportError:
    print("[FIX] twilio package missing -> run: pip install twilio")
    problems += 1

try:
    with open(os.path.join("data", "officers.json")) as f:
        officers = json.load(f)
    real = [o for o in officers if o.get("phone") and "X" not in o["phone"].upper()]
    if not real:
        print("[FIX] Every officer phone in data/officers.json is still a +91XXXXXXXXXX placeholder.")
        print("      Put YOUR real number, e.g. +919876543210 (must be verified in Twilio for trial accounts)")
        problems += 1
    else:
        print(f"[OK] {len(real)} officer(s) with a real phone number")
except Exception as exc:
    print(f"[FIX] Could not read data/officers.json: {exc}")
    problems += 1

print()
if problems == 0:
    print("Everything looks correct. Restart the app (python app.py) and submit an SOS.")
    print("The banner should now say the officers were notified via SMS/WhatsApp.")
else:
    print(f"{problems} thing(s) to fix above. Fix them, restart the app, and try again.")
