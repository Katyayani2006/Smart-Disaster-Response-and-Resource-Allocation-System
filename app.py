from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import joblib
import pandas as pd
import json
import uuid
import math
import time
import requests
from functools import wraps
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from notifications import (
    send_emergency_alerts,
    send_test_alert,
    load_officers,
    save_officers,
    load_alert_log,
)

app = Flask(__name__)
MODEL_PATH = os.path.join("models", "disaster_model.pkl")
DATA_DIR = "data"
STORE_FILE = os.path.join(DATA_DIR, "store.json")

# Create data directory if it does not exist
os.makedirs(DATA_DIR, exist_ok=True)

# --- Lightweight admin access control ---------------------------------
# Protects state-changing officer/admin actions (delete, verify, run
# allocation, reset session) behind a shared secret passed in the
# "X-Admin-Key" request header. This is a stand-in for full user
# accounts with per-role permissions - before a real government
# deployment, replace it with proper login (e.g. Flask-Login) backed by
# a users table with roles like citizen/field_officer/district_admin.
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "changeme-admin-key")
if ADMIN_API_KEY == "changeme-admin-key":
    print(
        "WARNING: ADMIN_API_KEY is not set - using an insecure default. "
        "Set a real secret before deploying, e.g.:\n"
        "  export ADMIN_API_KEY='your-long-random-secret-here'"
    )

# --- Session-based login (roles: admin / officer / viewer) -------------
# Flask needs a secret key to sign session cookies securely.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-production")
if app.secret_key == "dev-secret-change-in-production":
    print(
        "WARNING: FLASK_SECRET_KEY is not set - using an insecure default. "
        "Set a real secret before deploying, e.g.:\n"
        "  export FLASK_SECRET_KEY='another-long-random-secret'"
    )

USERS_FILE = os.path.join(DATA_DIR, "users.json")


def _default_users():
    """Three demo accounts, one per role. Change these passwords before
    using this anywhere beyond a college demo."""
    return {
        "admin": {"password_hash": generate_password_hash("admin123"), "role": "admin"},
        "officer1": {"password_hash": generate_password_hash("officer123"), "role": "officer"},
        "viewer1": {"password_hash": generate_password_hash("viewer123"), "role": "viewer"},
    }


def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    users = _default_users()
    save_users(users)
    return users


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


users_db = load_users()


def login_required_page(view_func):
    """Protects a browser-rendered page: redirects to /login if not signed in."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


def is_admin_authorized():
    """True if a logged-in officer/admin session exists, OR a valid
    X-Admin-Key header is supplied. The header path exists so the
    automated test suite keeps working without simulating a browser
    login - real humans should always use the login page.
    """
    if session.get("role") in ("admin", "officer"):
        return True
    return request.headers.get("X-Admin-Key", "") == ADMIN_API_KEY


def require_admin(view_func):
    """Decorator: blocks the request unless logged in as officer/admin, or a valid X-Admin-Key header is sent."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_admin_authorized():
            return jsonify({"error": "Unauthorized. Please log in as an officer or admin."}), 401
        return view_func(*args, **kwargs)

    return wrapper


# Generate a unique Session / Run ID for the active application instance
CURRENT_SESSION_ID = str(uuid.uuid4())

model = None
model_error = None

if os.path.exists(MODEL_PATH):
    try:
        model = joblib.load(MODEL_PATH)
    except Exception as exc:
        model_error = f"Unable to load model from {MODEL_PATH}: {str(exc)}"
        print(model_error)
        model = None
else:
    model_error = f"Model file missing at {MODEL_PATH}. Please train the model using train_model.py."
    print(model_error)

# Global in-memory state, synchronized with data/store.json
reports = []
incidents = []
resources = []
allocation_history = []


def load_store():
    """Load persistent state from data/store.json if it exists."""
    global reports, incidents, resources, allocation_history
    if os.path.exists(STORE_FILE):
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                reports = data.get("reports", [])
                incidents = data.get("incidents", [])
                resources = data.get("resources", [])
                allocation_history = data.get("allocation_history", [])
        except Exception as err:
            print("Error reading store.json:", err)
            reports, incidents, resources, allocation_history = [], [], [], []
    else:
        reports, incidents, resources, allocation_history = [], [], [], []


def save_store():
    """Persist current state to data/store.json."""
    data = {
        "reports": reports,
        "incidents": incidents,
        "resources": resources,
        "allocation_history": allocation_history,
    }
    try:
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as err:
        print("Error saving store.json:", err)


# Load store on startup
load_store()

# Known coordinate lookup table (fast local overrides - checked before any
# network geocoding call, and reliable for local landmarks like campus areas
# that public geocoders might not resolve well)
LOCATION_COORDS = {
    "baripada": {"lat": 21.94, "lng": 86.73},
    "patia": {"lat": 20.3588, "lng": 85.8333},
    "lakeside": {"lat": 20.305, "lng": 85.835},
    "bhubaneswar": {"lat": 20.2961, "lng": 85.8245},
    "cuttack": {"lat": 20.4625, "lng": 85.8830},
    "rourkela": {"lat": 22.2500, "lng": 84.8333},
    "berhampur": {"lat": 19.3150, "lng": 84.7941},
    "baleswar": {"lat": 21.4964, "lng": 86.9290},
    "puri": {"lat": 19.8135, "lng": 85.8312},
    "kendrapara": {"lat": 20.5015, "lng": 86.4222},
    "jagatsinghpur": {"lat": 20.2647, "lng": 86.1716},
    "bhadrak": {"lat": 21.0544, "lng": 86.4967},
    "chatrapur": {"lat": 19.3551, "lng": 84.9859},
    "jharsuguda": {"lat": 21.8554, "lng": 84.0062},
    "koraput": {"lat": 18.8135, "lng": 82.7123},
    "sambalpur": {"lat": 21.4669, "lng": 83.9812},
    "paradeep": {"lat": 20.3164, "lng": 86.6114},
    "angul": {"lat": 20.8400, "lng": 85.1000},
    "mayurbhanj": {"lat": 21.9333, "lng": 86.7333},
    "kandhamal": {"lat": 20.2333, "lng": 84.2333},
}

LOCATION_ALIASES = {
    "balesore": "Baleswar",
    "balasore": "Baleswar",
    "baleshwar": "Baleswar",
    "bhubaneshwar": "Bhubaneswar",
    "bhubaneswer": "Bhubaneswar",
    "bbsr": "Bhubaneswar",
    "berhampore": "Berhampur",
    "brahmapur": "Berhampur",
    "cuttak": "Cuttack",
    "katak": "Cuttack",
    "rourkella": "Rourkela",
    "kendrapada": "Kendrapara",
    "jagatsinghapur": "Jagatsinghpur",
    "paradip": "Paradeep",
    "chhatrapur": "Chatrapur",
}


def normalize_location(location):
    """Resolve spelling variants/typos to one canonical location name.

    This runs before the location string touches storage, matching, or
    geocoding, so an incident reported at "Balesore" and a resource
    logged at "Baleswar" are recognized as the same place. Falls back to
    the cleaned input (extra whitespace collapsed) if no alias exists.
    """
    if not location:
        return location
    cleaned = " ".join(location.strip().split())
    return LOCATION_ALIASES.get(cleaned.lower(), cleaned)


GEOCODE_CACHE_FILE = os.path.join(DATA_DIR, "geocode_cache.json")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_last_geocode_call = 0.0


def _load_geocode_cache():
    if os.path.exists(GEOCODE_CACHE_FILE):
        try:
            with open(GEOCODE_CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_geocode_cache(cache):
    try:
        with open(GEOCODE_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass


_geocode_cache = _load_geocode_cache()


def _geocode_online(location):
    """Look up real-world coordinates via OpenStreetMap's Nominatim API.

    Nominatim's usage policy asks for max 1 request/second and a
    descriptive User-Agent, so calls are throttled and cached to disk.
    Returns None if the location can't be resolved or the API is
    unreachable (e.g. no internet access) - callers should treat None
    as "unknown location" rather than guessing a fake point.
    """
    global _last_geocode_call

    loc_key = location.strip().lower()
    if loc_key in _geocode_cache:
        return _geocode_cache[loc_key]

    elapsed = time.time() - _last_geocode_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "SmartDisasterResponse/1.0"},
            timeout=5,
        )
        _last_geocode_call = time.time()
        resp.raise_for_status()
        results = resp.json()
        if results:
            coords = {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
            _geocode_cache[loc_key] = coords
            _save_geocode_cache(_geocode_cache)
            return coords
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass

    return None


def get_coordinates(location):
    """Resolve a location string to real-world coordinates.

    Order of resolution:
      1. Explicit "lat, lng" input, used as-is.
      2. Local override table (fast, offline-safe, for known landmarks).
      3. Live geocoding via OpenStreetMap Nominatim (cached to disk).
    Returns None (not a fake coordinate) if the location cannot be
    resolved, so the frontend can show it as "unlocated" instead of
    plotting a misleading marker.
    """
    if not location or not location.strip():
        return None

    normalized = location.strip()
    try:
        parts = [p.strip() for p in normalized.replace(";", ",").split(",") if p.strip()]
        if len(parts) == 2:
            lat = float(parts[0])
            lng = float(parts[1])
            return {"lat": lat, "lng": lng}
    except ValueError:
        pass

    loc_key = normalized.lower()
    if loc_key in LOCATION_COORDS:
        return LOCATION_COORDS[loc_key]

    return _geocode_online(normalized)


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate Great Circle distance in km between two coordinate points."""
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def calculate_urgency_score(incident):
    """Calculate unified urgency score combining priority rank, severity, and people affected.

    Returns the numeric score AND a breakdown dict explaining exactly how
    that score was built, so the allocation engine's decisions can be
    justified to a reviewer instead of being a black box.
    """
    priority = incident.get("priority", "MEDIUM")
    severity = incident.get("severity", 1)
    people = incident.get("people_affected", 0)

    base_scores = {
        "CRITICAL": 90.0,
        "HIGH": 70.0,
        "MEDIUM": 40.0,
        "LOW": 10.0,
    }
    base_component = base_scores.get(str(priority).upper(), 40.0)
    severity_component = round(severity * 0.8, 1)
    people_component = round(min(10.0, people / 500.0), 1)
    score = min(100.0, round(base_component + severity_component + people_component, 1))

    breakdown = {
        "base_priority_points": base_component,
        "severity_points": severity_component,
        "people_affected_points": people_component,
        "total": score,
    }
    return score, breakdown


def derive_priority_from_score(score):
    if score >= 80:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


# Routes
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = users_db.get(username)
        if user and check_password_hash(user["password_hash"], password):
            session["username"] = username
            session["role"] = user["role"]
            next_page = request.args.get("next") or url_for("dashboard")
            return redirect(next_page)
        return render_template("login.html", error="Invalid username or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/predict")
def predict():
    return render_template("predict.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/dashboard")
@login_required_page
def dashboard():
    # Mathematical calculation of dashboard statistics from actual data
    available_qty = sum(r.get("quantity", 0) for r in resources if r.get("status") == "available")
    
    # Filter allocation history for current session run
    current_session_allocations = [a for a in allocation_history if a.get("session_id") == CURRENT_SESSION_ID]
    allocated_qty = sum(a.get("quantity_allocated", 0) for a in current_session_allocations)
    total_qty = available_qty + allocated_qty
    
    allocation_rate = round((allocated_qty / total_qty * 100), 1) if total_qty > 0 else 0.0

    stats = {
        "total_disasters": len(incidents),
        "critical_count": sum(1 for item in incidents if item.get("priority") == "CRITICAL"),
        "high_count": sum(1 for item in incidents if item.get("priority") == "HIGH"),
        "medium_count": sum(1 for item in incidents if item.get("priority") == "MEDIUM"),
        "low_count": sum(1 for item in incidents if item.get("priority") == "LOW"),
        "allocation_rate": allocation_rate,
        "open_incidents": sum(1 for i in incidents if i.get("status") == "open"),
        "available_resources": available_qty,
        "last_refreshed": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": CURRENT_SESSION_ID,
    }

    return render_template(
        "dashboard.html",
        reports=reports,
        stats=stats,
        incidents=json.dumps(incidents),
        resources=json.dumps(resources),
        allocation_history=json.dumps(current_session_allocations),
        session_id=CURRENT_SESSION_ID,
        current_user=session.get("username"),
        current_role=session.get("role"),
    )


@app.route("/predict_disaster", methods=["POST"])
def predict_disaster():
    # Frontend/Backend Form Input Validation
    disaster_type = request.form.get("disaster_type", "").strip()
    location = normalize_location(request.form.get("location", "").strip())
    weather = request.form.get("weather", "").strip()

    if not disaster_type or not location:
        return render_template("predict.html", error="Disaster Type and Location are required fields.")

    try:
        severity = int(request.form.get("severity", 1))
        people = int(request.form.get("people", 0))
        damage = int(request.form.get("damage", 1))
        accessibility = int(request.form.get("accessibility", 5))
        previous = int(request.form.get("previous", 0))

        if not (1 <= severity <= 10):
            raise ValueError("Severity must be between 1 and 10.")
        if not (1 <= damage <= 10):
            raise ValueError("Infrastructure damage must be between 1 and 10.")
        if not (1 <= accessibility <= 10):
            raise ValueError("Accessibility must be between 1 and 10.")
        if people < 0 or previous < 0:
            raise ValueError("People affected and previous occurrences must be non-negative.")
    except ValueError as err:
        return render_template("predict.html", error=f"Invalid numerical input: {str(err)}")

    # ML Model Prediction
    if model is None:
        error_msg = model_error or "ML model (models/disaster_model.pkl) is missing or could not be loaded."
        return render_template("predict.html", error=error_msg)

    try:
        features_df = pd.DataFrame(
            [[severity, people, damage, accessibility, previous]],
            columns=["severity", "people", "damage", "accessibility", "previous"],
        )
        prediction = model.predict(features_df)
        priority = str(prediction[0]).upper()

        # --- Priority score transparency ---
        # Confidence: how sure the model is about THIS specific prediction.
        # predict_proba() returns one probability per class the model
        # knows about (e.g. 87% CRITICAL, 13% HIGH) - this is what lets
        # you answer "how confident is the system?" in your viva instead
        # of just showing a bare label.
        confidence_breakdown = []
        try:
            proba = model.predict_proba(features_df)[0]
            for class_label, prob in sorted(
                zip(model.classes_, proba), key=lambda pair: pair[1], reverse=True
            ):
                confidence_breakdown.append(
                    {"label": str(class_label).upper(), "confidence": round(float(prob) * 100, 1)}
                )
        except Exception:
            confidence_breakdown = []

        # Feature importance: which inputs the trained model relies on
        # most heavily OVERALL (this is a global measure from training,
        # not specific to this one prediction - RandomForest doesn't give
        # a clean per-prediction breakdown - but it still answers "why
        # does severity matter more than accessibility?" honestly).
        feature_importance = []
        try:
            importances = model.feature_importances_
            feature_labels = [
                "Severity",
                "People Affected",
                "Infrastructure Damage",
                "Accessibility",
                "Previous Occurrences",
            ]
            for label, importance in sorted(
                zip(feature_labels, importances), key=lambda pair: pair[1], reverse=True
            ):
                feature_importance.append({"label": label, "importance": round(float(importance) * 100, 1)})
        except Exception:
            feature_importance = []

    except Exception as exc:
        return render_template("predict.html", error=f"Prediction error from ML model: {str(exc)}")

    # Tailored resource recommendations
    resource_list = []
    if priority == "CRITICAL":
        resource_list = [
            "10 Rescue Teams",
            "500 Food Kits",
            "5 Ambulances",
            "20 Doctors",
            "1000 Water Bottles",
            "5 Relief Camps",
        ]
    elif priority == "HIGH":
        resource_list = [
            "8 Rescue Teams",
            "300 Food Kits",
            "3 Ambulances",
            "10 Doctors",
            "600 Water Bottles",
        ]
    elif priority == "MEDIUM":
        resource_list = [
            "4 Rescue Teams",
            "150 Food Kits",
            "2 Ambulances",
            "5 Doctors",
            "300 Water Bottles",
        ]
    else:
        resource_list = [
            "2 Rescue Teams",
            "50 Food Kits",
            "1 Ambulance",
            "2 Doctors",
        ]

    # Create/update disaster report record
    new_report = {
        "type": disaster_type,
        "location": location,
        "severity": severity,
        "priority": priority,
        "people": people,
        "resources": ", ".join(resource_list),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    location_key = location.lower()
    existing_index = next(
        (idx for idx, rep in enumerate(reports) if rep["location"].strip().lower() == location_key),
        None,
    )
    if existing_index is not None:
        reports[existing_index] = new_report
    else:
        reports.insert(0, new_report)
        if len(reports) > 10:
            reports.pop()

    # Create/update incident record for resource allocation system
    coords = get_coordinates(location)
    incident = {
        "id": str(uuid.uuid4()),
        "location": location,
        "type": disaster_type,
        "severity": severity,
        "people_affected": people,
        "status": "open",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "priority": priority,
        "lat": coords["lat"] if coords else None,
        "lng": coords["lng"] if coords else None,
    }
    incident["urgency_score"], incident["urgency_breakdown"] = calculate_urgency_score(incident)

    existing_incident_idx = next(
        (idx for idx, inc in enumerate(incidents) if inc["location"].strip().lower() == location_key),
        None,
    )
    if existing_incident_idx is not None:
        incident["id"] = incidents[existing_incident_idx]["id"]
        incidents[existing_incident_idx] = incident
    else:
        incidents.append(incident)

    # Persist updated state
    save_store()

    return render_template(
        "result.html",
        disaster_type=disaster_type,
        location=location,
        severity=severity,
        people=people,
        damage=damage,
        accessibility=accessibility,
        previous=previous,
        weather=weather,
        priority=priority,
        resources=resource_list,
        confidence_breakdown=confidence_breakdown,
        feature_importance=feature_importance,
    )


# API Endpoints for Incidents
@app.route("/api/incidents", methods=["GET", "POST"])
def manage_incidents():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        location = normalize_location(str(data.get("location", "")).strip())
        disaster_type = str(data.get("type", "")).strip()

        if not location:
            return jsonify({"error": "Location name is required."}), 400
        if not disaster_type:
            return jsonify({"error": "Disaster type is required."}), 400

        try:
            severity = int(data.get("severity", 5))
            people = int(data.get("people_affected", 0))
            if not (1 <= severity <= 10):
                return jsonify({"error": "Severity must be between 1 and 10."}), 400
            if people < 0:
                return jsonify({"error": "People affected cannot be negative."}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Severity and People Affected must be valid integers."}), 400

        coords = get_coordinates(location)
        
        # Predict priority if ML model is available
        priority = data.get("priority")
        if not priority and model is not None:
            try:
                features_df = pd.DataFrame(
                    [[severity, people, 5, 5, 0]],
                    columns=["severity", "people", "damage", "accessibility", "previous"],
                )
                pred = model.predict(features_df)
                priority = str(pred[0]).upper()
            except Exception:
                priority = "MEDIUM"

        # New reports start unverified — they won't be picked up by the
        # allocation engine until a field officer confirms them via
        # /api/incidents/<id>/verify. Pass "source": "officer" or
        # "verified": true to skip this step for trusted/manual entries.
        report_source = str(data.get("source", "citizen")).strip().lower()
        is_pre_verified = bool(data.get("verified", False)) or report_source == "officer"

        incident = {
            "id": data.get("id") or str(uuid.uuid4()),
            "location": location,
            "type": disaster_type,
            "severity": severity,
            "people_affected": people,
            "status": "open" if is_pre_verified else "unverified",
            "verified": is_pre_verified,
            "source": report_source,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lat": coords["lat"] if coords else None,
            "lng": coords["lng"] if coords else None,
            "priority": priority or "MEDIUM",
        }
        incident["urgency_score"], incident["urgency_breakdown"] = calculate_urgency_score(incident)

        location_key = location.lower()
        existing_index = next(
            (idx for idx, inc in enumerate(incidents) if inc["location"].strip().lower() == location_key or inc.get("id") == incident["id"]),
            None,
        )
        if existing_index is not None:
            incident["id"] = incidents[existing_index]["id"]
            incidents[existing_index] = incident
        else:
            incidents.append(incident)

        # Update reports as well for consistent dashboard view
        new_report = {
            "type": disaster_type,
            "location": location,
            "severity": severity,
            "priority": incident["priority"],
            "people": people,
            "resources": "Pending Allocation",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        rep_idx = next((idx for idx, rep in enumerate(reports) if rep["location"].strip().lower() == location_key), None)
        if rep_idx is not None:
            reports[rep_idx] = new_report
        else:
            reports.insert(0, new_report)

        save_store()
        return jsonify(incident), 201

    return jsonify(incidents)


@app.route("/api/incidents/<incident_id>", methods=["DELETE"])
@require_admin
def delete_incident(incident_id):
    global incidents, reports
    incident_to_delete = next((i for i in incidents if i["id"] == incident_id), None)
    if incident_to_delete:
        loc_key = incident_to_delete["location"].strip().lower()
        incidents = [i for i in incidents if i["id"] != incident_id]
        reports = [r for r in reports if r["location"].strip().lower() != loc_key]
        save_store()
        return jsonify({"status": "deleted"}), 200
    return jsonify({"error": "Incident not found"}), 404


@app.route("/api/incidents/<incident_id>/verify", methods=["POST"])
@require_admin
def verify_incident(incident_id):
    """Mark an unverified incident as confirmed, making it eligible for allocation."""
    incident = next((i for i in incidents if i["id"] == incident_id), None)
    if not incident:
        return jsonify({"error": "Incident not found"}), 404

    if incident.get("status") != "unverified":
        return jsonify({"error": "Incident is not pending verification."}), 400

    incident["status"] = "open"
    incident["verified"] = True
    incident["verified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_store()
    return jsonify(incident), 200


# API Endpoints for Resources
@app.route("/api/resources", methods=["GET", "POST"])
def manage_resources():
    if request.method == "POST":
        # Only adding/updating resources requires admin access - GET stays
        # public so the dashboard and live map can still display resources.
        if not is_admin_authorized():
            return jsonify({"error": "Unauthorized. Please log in as an officer or admin."}), 401

        data = request.get_json(silent=True) or {}
        location = normalize_location(str(data.get("location", "")).strip())
        res_type = str(data.get("type", "")).strip()

        if not location:
            return jsonify({"error": "Resource location is required."}), 400
        if not res_type:
            return jsonify({"error": "Resource type is required."}), 400

        try:
            quantity = int(data.get("quantity", 0))
            if quantity <= 0:
                return jsonify({"error": "Resource quantity must be greater than 0."}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Resource quantity must be a valid positive integer."}), 400

        coords = get_coordinates(location)
        resource = {
            "id": data.get("id") or str(uuid.uuid4()),
            "location": location,
            "type": res_type,
            "quantity": quantity,
            "status": "available",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lat": coords["lat"] if coords else None,
            "lng": coords["lng"] if coords else None,
        }

        # Check existing by ID or matching location + type
        loc_key = location.lower()
        res_type_key = res_type.lower()
        existing_idx = next(
            (idx for idx, r in enumerate(resources) if r.get("id") == resource["id"] or (r["location"].strip().lower() == loc_key and r["type"].strip().lower() == res_type_key)),
            None,
        )

        if existing_idx is not None:
            resource["id"] = resources[existing_idx]["id"]
            resources[existing_idx] = resource
        else:
            resources.append(resource)

        save_store()
        return jsonify(resource), 201

    return jsonify(resources)


@app.route("/api/resources/<resource_id>", methods=["DELETE"])
@require_admin
def delete_resource(resource_id):
    global resources
    resources = [r for r in resources if r["id"] != resource_id]
    save_store()
    return jsonify({"status": "deleted"}), 200


# Allocation Engine Route
@app.route("/api/run-allocation", methods=["POST"])
@require_admin
def run_allocation():
    """Execute resource allocation algorithm matching open incidents to available resources."""
    new_allocations = []

    # Sort open incidents by urgency score descending
    open_incidents = [i for i in incidents if i.get("status") == "open"]
    open_incidents.sort(key=lambda x: x.get("urgency_score", 0), reverse=True)

    for incident in open_incidents:
        # Find all available resources with quantity > 0
        available_res = [r for r in resources if r.get("status") == "available" and r.get("quantity", 0) > 0]
        if not available_res:
            break

        best_resource = None
        best_distance = None

        # Prioritize location proximity
        for res in available_res:
            if (incident.get("lat") is not None and incident.get("lng") is not None and
                    res.get("lat") is not None and res.get("lng") is not None):
                dist = haversine_distance(incident["lat"], incident["lng"], res["lat"], res["lng"])
                if best_distance is None or dist < best_distance:
                    best_distance = dist
                    best_resource = res
            else:
                if best_resource is None:
                    best_resource = res
                    best_distance = None

        if best_resource is None:
            continue

        # Calculate allocation amount
        required_qty = max(1, incident.get("people_affected", 0) // 100)
        allocated_qty = min(best_resource["quantity"], required_qty)

        allocation = {
            "id": str(uuid.uuid4()),
            "session_id": CURRENT_SESSION_ID,
            "incident_id": incident["id"],
            "incident_location": incident["location"],
            "incident_priority": incident.get("priority", "MEDIUM"),
            "resource_id": best_resource["id"],
            "resource_location": best_resource["location"],
            "resource_type": best_resource["type"],
            "quantity_allocated": allocated_qty,
            "urgency_score": incident.get("urgency_score", 0),
            "distance_km": round(best_distance, 2) if best_distance is not None else None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        new_allocations.append(allocation)
        allocation_history.append(allocation)

        # Update resource quantity and status
        best_resource["quantity"] -= allocated_qty
        if best_resource["quantity"] <= 0:
            best_resource["quantity"] = 0
            best_resource["status"] = "depleted"

        # Update incident status to allocated
        incident["status"] = "allocated"

    save_store()

    current_session_allocations = [a for a in allocation_history if a.get("session_id") == CURRENT_SESSION_ID]

    return jsonify({
        "allocations": new_allocations,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "incidents": incidents,
        "resources": resources,
        "allocation_history": current_session_allocations,
        "session_id": CURRENT_SESSION_ID,
    }), 200


@app.route("/api/allocation-history", methods=["GET"])
def get_allocation_history():
    scope = request.args.get("session", "current")
    if scope == "all":
        return jsonify(allocation_history)
    current_allocs = [a for a in allocation_history if a.get("session_id") == CURRENT_SESSION_ID]
    return jsonify(current_allocs)


@app.route("/api/new-session", methods=["POST"])
@require_admin
def start_new_session():
    global CURRENT_SESSION_ID
    CURRENT_SESSION_ID = str(uuid.uuid4())
    save_store()
    return jsonify({
        "status": "success",
        "session_id": CURRENT_SESSION_ID,
        "allocation_history": []
    }), 200


@app.route("/sos", methods=["GET", "POST"])
def citizen_sos():
    """Public SOS emergency distress reporting portal for disaster-affected citizens."""
    if request.method == "POST":
        location = normalize_location(request.form.get("location", "").strip())
        disaster_type = request.form.get("disaster_type", "Flood").strip()
        description = request.form.get("description", "").strip()
        contact = request.form.get("contact", "").strip()

        try:
            people = int(request.form.get("people", 1))
            severity = int(request.form.get("severity", 8))
        except ValueError:
            people = 1
            severity = 8

        if not location:
            return render_template("sos.html", error="Location is required for emergency dispatch.")

        coords = get_coordinates(location)

        # ML or heuristic priority estimation
        priority = "CRITICAL" if severity >= 8 or people >= 50 else ("HIGH" if severity >= 5 else "MEDIUM")
        if model is not None:
            try:
                features_df = pd.DataFrame(
                    [[severity, people, 7, 3, 0]],
                    columns=["severity", "people", "damage", "accessibility", "previous"],
                )
                pred = model.predict(features_df)
                priority = str(pred[0]).upper()
            except Exception:
                pass

        sos_id = "SOS-" + str(uuid.uuid4())[:8].upper()
        incident = {
            "id": str(uuid.uuid4()),
            "sos_code": sos_id,
            "location": location,
            "type": disaster_type,
            "severity": severity,
            "people_affected": people,
            "status": "open",
            "verified": True,
            "source": "citizen_sos",
            "contact": contact,
            "description": description,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lat": coords["lat"] if coords else None,
            "lng": coords["lng"] if coords else None,
            "priority": priority,
        }
        incident["urgency_score"], incident["urgency_breakdown"] = calculate_urgency_score(incident)

        # Append to incidents
        incidents.append(incident)

        # Append to reports
        reports.insert(0, {
            "type": f"CITIZEN SOS ({disaster_type})",
            "location": location,
            "severity": severity,
            "priority": priority,
            "people": people,
            "resources": "Emergency Dispatch Pending",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

        save_store()

        # --- SMS / WhatsApp alert -----------------------------------
        # Page every on-call officer immediately. This runs regardless
        # of whether anyone is currently logged into the Dashboard, so
        # a midnight SOS does not sit unseen for hours. A failure here
        # must never block the citizen's report from being recorded,
        # hence the try/except.
        alert_status = None
        try:
            alert_status = send_emergency_alerts(incident)
        except Exception as exc:
            print(f"WARNING: Emergency alert dispatch failed: {exc}")
            alert_status = {"mode": "error", "sent": [], "failed": [{"error": str(exc)}]}

        return render_template(
            "sos.html", success=True, sos_code=sos_id, incident=incident, alert_status=alert_status
        )

    return render_template("sos.html")


@app.route("/api/seed-emergency-data", methods=["POST"])
@app.route("/api/seed-odraf-data", methods=["POST"])
@require_admin
def seed_odraf_data():
    """Populates realistic emergency response inventory and active disaster incidents."""
    global incidents, resources, reports

    # Rapid Response Equipment & Inventory
    odraf_resources = [
        {"location": "Cuttack", "type": "Inflatable Motor Boat", "quantity": 15},
        {"location": "Cuttack", "type": "Hydraulic Concrete Cutter", "quantity": 10},
        {"location": "Cuttack", "type": "Medical First Responder (MFR) Kit", "quantity": 30},
        {"location": "Chatrapur", "type": "Inflatable Motor Boat", "quantity": 12},
        {"location": "Chatrapur", "type": "High-Tower Inflatable Light", "quantity": 8},
        {"location": "Chatrapur", "type": "Satellite Communication System", "quantity": 5},
        {"location": "Jharsuguda", "type": "Hydraulic Concrete Cutter", "quantity": 8},
        {"location": "Jharsuguda", "type": "Mobile Water Purification Unit", "quantity": 6},
        {"location": "Baleswar", "type": "Inflatable Motor Boat", "quantity": 10},
        {"location": "Baleswar", "type": "Food & Ration Packets", "quantity": 500},
        {"location": "Puri", "type": "Medical First Responder (MFR) Kit", "quantity": 25},
        {"location": "Puri", "type": "Inflatable Motor Boat", "quantity": 8},
        {"location": "Kendrapara", "type": "Mobile Water Purification Unit", "quantity": 5},
    ]

    # Clear current and seed resources
    resources.clear()
    for res in odraf_resources:
        loc = res["location"]
        coords = get_coordinates(loc)
        resources.append({
            "id": str(uuid.uuid4()),
            "location": loc,
            "type": res["type"],
            "quantity": res["quantity"],
            "status": "available",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lat": coords["lat"] if coords else None,
            "lng": coords["lng"] if coords else None,
        })

    # Seed Realistic Disaster Incidents
    odraf_incidents = [
        {"location": "Puri", "type": "Cyclone", "severity": 9, "people": 3500, "priority": "CRITICAL"},
        {"location": "Kendrapara", "type": "Coastal Surge Flood", "severity": 8, "people": 2200, "priority": "HIGH"},
        {"location": "Baripada", "type": "Flash Flood", "severity": 6, "people": 1100, "priority": "MEDIUM"},
        {"location": "Cuttack", "type": "Mahanadi River Inundation", "severity": 7, "people": 1800, "priority": "HIGH"},
    ]

    incidents.clear()
    reports.clear()
    for inc in odraf_incidents:
        loc = inc["location"]
        coords = get_coordinates(loc)
        item = {
            "id": str(uuid.uuid4()),
            "location": loc,
            "type": inc["type"],
            "severity": inc["severity"],
            "people_affected": inc["people"],
            "status": "open",
            "verified": True,
            "source": "emergency_command",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lat": coords["lat"] if coords else None,
            "lng": coords["lng"] if coords else None,
            "priority": inc["priority"],
        }
        item["urgency_score"], item["urgency_breakdown"] = calculate_urgency_score(item)
        incidents.append(item)

        reports.append({
            "type": inc["type"],
            "location": loc,
            "severity": inc["severity"],
            "priority": inc["priority"],
            "people": inc["people"],
            "resources": "Pending Tactical Dispatch",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    save_store()
    return jsonify({
        "status": "success",
        "message": "Rapid response inventory data and active disaster incidents successfully pre-loaded!",
        "incidents_count": len(incidents),
        "resources_count": len(resources),
    }), 200


# --------------------------------------------------------------------------
# SMS / WhatsApp on-call officer alerts
# --------------------------------------------------------------------------

@app.route("/api/officers", methods=["GET", "POST"])
@require_admin
def manage_officers():
    """GET: list on-call officers. POST: add a new on-call officer.

    Body (POST, JSON or form): name, phone, sms (bool), whatsapp (bool).
    Phone must be in international format, e.g. +919876543210.
    """
    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        name = (payload.get("name") or "").strip()
        phone = (payload.get("phone") or "").strip()
        if not name or not phone:
            return jsonify({"error": "name and phone are required"}), 400

        officers = load_officers()
        officers.append({
            "id": "officer-" + str(uuid.uuid4())[:8],
            "name": name,
            "phone": phone,
            "sms": str(payload.get("sms", True)).lower() not in ("false", "0", ""),
            "whatsapp": str(payload.get("whatsapp", False)).lower() in ("true", "1", "on"),
        })
        save_officers(officers)
        return jsonify({"status": "success", "officers": officers}), 201

    return jsonify({"officers": load_officers()}), 200


@app.route("/api/officers/<officer_id>", methods=["DELETE"])
@require_admin
def delete_officer(officer_id):
    """Removes an on-call officer from the alert list."""
    officers = load_officers()
    remaining = [o for o in officers if o.get("id") != officer_id]
    if len(remaining) == len(officers):
        return jsonify({"error": "Officer not found"}), 404
    save_officers(remaining)
    return jsonify({"status": "success", "officers": remaining}), 200


@app.route("/api/test-alert", methods=["POST"])
@require_admin
def trigger_test_alert():
    """Sends a harmless test SMS/WhatsApp alert to every on-call officer,
    so staff can verify phone numbers and Twilio credentials work BEFORE
    relying on this system during a real emergency."""
    try:
        result = send_test_alert()
        return jsonify({"status": "success", "result": result}), 200
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500


@app.route("/api/alert-log", methods=["GET"])
@require_admin
def get_alert_log():
    """Returns the most recent SMS/WhatsApp alert attempts (sent, simulated,
    or failed), so the Dashboard can show an audit trail of who was
    notified and how."""
    return jsonify({"alert_log": load_alert_log()}), 200


@app.route("/export-report")
@login_required_page
def export_report():
    """Generates official printable/exportable disaster command summary report."""

    current_session_allocations = [a for a in allocation_history if a.get("session_id") == CURRENT_SESSION_ID]
    return render_template(
        "report.html",
        incidents=incidents,
        resources=resources,
        allocations=current_session_allocations,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        session_id=CURRENT_SESSION_ID,
    )


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if __name__ == "__main__":
    app.run(debug=True, port=5000)
