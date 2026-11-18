"""
Emergency SMS / WhatsApp alert system.
=======================================

WHY THIS EXISTS
----------------
Officers cannot watch the Control Dashboard 24/7. If a citizen submits an
SOS at 2 AM and no one is logged in, the incident can sit unseen for hours.
This module pages every on-call officer by SMS and/or WhatsApp the moment
a new SOS is lodged, so response time no longer depends on someone happening
to be looking at a screen.

HOW IT WORKS
------------
Powered by Twilio (https://www.twilio.com/), which is the most common way
to send both SMS and WhatsApp messages from a Python app, and has a free
trial tier suitable for a college project demo.

Two modes, chosen automatically - the app never crashes either way:

1. LIVE MODE
   Set these environment variables (see .env.example) and real messages
   are sent over the network:
       TWILIO_ACCOUNT_SID
       TWILIO_AUTH_TOKEN
       TWILIO_SMS_FROM          e.g. "+15017122661"   (a Twilio SMS number)
       TWILIO_WHATSAPP_FROM     e.g. "whatsapp:+14155238886" (Twilio Sandbox)

2. SIMULATION MODE (default, no setup required)
   If credentials are missing, or an officer's phone number is still the
   "+91XXXXXXXXXX" placeholder, nothing is sent over the network. Instead
   the alert is printed to the console and written to data/alert_log.json,
   so the full flow (including the Dashboard's "Alert Log" panel) can be
   demonstrated end-to-end without a paid phone number.

WHO GETS ALERTED
-----------------
The on-call officer list lives in data/officers.json and is managed from
the Dashboard's "Manage Data" tab (add/remove officer, toggle SMS/WhatsApp
per officer) or by editing the JSON file directly.
"""

import os
import json
from datetime import datetime

OFFICERS_FILE = os.path.join("data", "officers.json")
ALERT_LOG_FILE = os.path.join("data", "alert_log.json")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_SMS_FROM = os.environ.get("TWILIO_SMS_FROM", "")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")

# Priorities that should trigger an alert. CRITICAL/HIGH always page
# officers immediately; MEDIUM/LOW are still logged but can be tuned here.
ALERT_ON_PRIORITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def _twilio_configured():
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and (TWILIO_SMS_FROM or TWILIO_WHATSAPP_FROM))


_twilio_client = None
if _twilio_configured():
    try:
        from twilio.rest import Client
        _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        print(f"WARNING: Twilio could not be initialized ({exc}). Falling back to simulation mode.")
        _twilio_client = None


# --------------------------------------------------------------------------
# On-call officer contact list
# --------------------------------------------------------------------------

def _default_officers():
    return [
        {
            "id": "officer-1",
            "name": "Duty Officer (Night Shift)",
            "phone": "+91XXXXXXXXXX",
            "sms": True,
            "whatsapp": True,
        }
    ]


def load_officers():
    if os.path.exists(OFFICERS_FILE):
        try:
            with open(OFFICERS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    officers = _default_officers()
    save_officers(officers)
    return officers


def save_officers(officers):
    os.makedirs(os.path.dirname(OFFICERS_FILE), exist_ok=True)
    with open(OFFICERS_FILE, "w") as f:
        json.dump(officers, f, indent=2)


# --------------------------------------------------------------------------
# Alert log (so the Dashboard can show "who was notified, and how")
# --------------------------------------------------------------------------

def _log_alert(entry):
    log = []
    if os.path.exists(ALERT_LOG_FILE):
        try:
            with open(ALERT_LOG_FILE, "r") as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []
    log.insert(0, entry)
    log = log[:200]  # keep the log file bounded
    os.makedirs(os.path.dirname(ALERT_LOG_FILE), exist_ok=True)
    with open(ALERT_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def load_alert_log(limit=50):
    if os.path.exists(ALERT_LOG_FILE):
        try:
            with open(ALERT_LOG_FILE, "r") as f:
                return json.load(f)[:limit]
        except (json.JSONDecodeError, OSError):
            pass
    return []


# --------------------------------------------------------------------------
# Message building & sending
# --------------------------------------------------------------------------

def build_alert_message(incident):
    return (
        f"DISASTER ALERT [{incident.get('priority', 'N/A')}]\n"
        f"Type: {incident.get('type', 'Unknown')}\n"
        f"Location: {incident.get('location', 'Unknown')}\n"
        f"People affected: {incident.get('people_affected', 'N/A')}\n"
        f"Urgency score: {incident.get('urgency_score', 'N/A')}/100\n"
        f"SOS code: {incident.get('sos_code', incident.get('id', 'N/A'))}\n"
        f"Reported: {incident.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}\n"
        f"Open the Control Dashboard to verify and dispatch resources."
    )


def _is_placeholder_number(phone):
    return (not phone) or ("X" in phone.upper())


def _send_via_twilio(to_number, body, channel):
    from_number = TWILIO_WHATSAPP_FROM if channel == "whatsapp" else TWILIO_SMS_FROM
    to = f"whatsapp:{to_number}" if channel == "whatsapp" else to_number
    message = _twilio_client.messages.create(body=body, from_=from_number, to=to)
    return message.sid


def send_emergency_alerts(incident, officers=None):
    """
    Sends an SMS and/or WhatsApp alert to every on-call officer for a
    newly reported incident.

    This function NEVER raises - a notification failure must never block
    a citizen's SOS report from being saved. Every attempt (sent,
    simulated, or failed) is written to data/alert_log.json.
    """
    if incident.get("priority", "").upper() not in ALERT_ON_PRIORITIES:
        return {"mode": "skipped", "reason": "priority not in ALERT_ON_PRIORITIES", "sent": [], "failed": []}

    officers = officers if officers is not None else load_officers()
    message_body = build_alert_message(incident)
    results = {"mode": "live" if _twilio_client else "simulation", "sent": [], "failed": []}

    for officer in officers:
        phone = (officer.get("phone") or "").strip()
        channels = []
        if officer.get("sms", True):
            channels.append("sms")
        if officer.get("whatsapp", False):
            channels.append("whatsapp")

        for channel in channels:
            entry = {
                "officer": officer.get("name", "Unknown"),
                "phone": phone,
                "channel": channel,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "incident_id": incident.get("id"),
                "sos_code": incident.get("sos_code"),
            }

            can_send_live = _twilio_client is not None and not _is_placeholder_number(phone)
            if can_send_live:
                try:
                    sid = _send_via_twilio(phone, message_body, channel)
                    entry["status"] = "sent"
                    entry["provider_sid"] = sid
                    results["sent"].append(entry)
                except Exception as exc:
                    entry["status"] = "failed"
                    entry["error"] = str(exc)
                    results["failed"].append(entry)
            else:
                entry["status"] = "simulated"
                entry["note"] = (
                    "Twilio not configured" if _twilio_client is None else "Placeholder phone number"
                )
                results["sent"].append(entry)
                print(f"[SIMULATED {channel.upper()} ALERT] -> {officer.get('name')} ({phone}):\n{message_body}\n")

            _log_alert(entry)

    return results


def send_test_alert():
    """Sends a harmless test alert to every configured officer. Used by the
    Dashboard's 'Send Test Alert' button so staff can verify phone numbers
    and Twilio credentials work BEFORE relying on this during a real
    emergency."""
    fake_incident = {
        "id": "TEST",
        "sos_code": "TEST-ALERT",
        "priority": "CRITICAL",
        "type": "System Test",
        "location": "N/A (this is a test)",
        "people_affected": 0,
        "urgency_score": 0,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return send_emergency_alerts(fake_incident)
