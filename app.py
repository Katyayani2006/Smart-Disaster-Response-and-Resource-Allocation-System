from flask import Flask, render_template, request, jsonify
import os
import joblib
import numpy as np
import json
import uuid
import zlib
import math

from datetime import datetime

app = Flask(__name__)
MODEL_PATH = os.path.join("models", "disaster_model.pkl")
model = None

if os.path.exists(MODEL_PATH):
    try:
        model = joblib.load(MODEL_PATH)
    except Exception as exc:
        print("Unable to load model:", exc)
        model = None

reports = []

# Data structures for new features
incidents = []  # List of incident objects with location, coordinates, etc.
resources = []  # List of available resources with location, type, quantity
allocation_history = []  # History of allocations

# Sample coordinates for common locations
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
}

startup_reset_done = False

def initialize_runtime_data():
    global reports, incidents, resources, allocation_history
    reports = []
    incidents = []
    resources = []
    allocation_history = []

# Ensure a fresh runtime state each time the app process starts.
initialize_runtime_data()

@app.before_request
def reset_runtime_data_on_first_request():
    global startup_reset_done
    if not startup_reset_done:
        initialize_runtime_data()
        startup_reset_done = True


def get_coordinates(location):
    """Get deterministic coordinates for any location string without changing the original input."""
    normalized = location.strip()
    # If no location was provided, do not return a default coordinate.
    # This prevents showing or using a hardcoded city when the user did not enter one.
    if not normalized:
        return None

    # If the user entered explicit coordinates, use them directly.
    try:
        parts = [p.strip() for p in normalized.replace(';', ',').split(',') if p.strip()]
        if len(parts) == 2:
            lat = float(parts[0])
            lng = float(parts[1])
            return {"lat": lat, "lng": lng}
    except ValueError:
        pass

    loc_key = normalized.lower()
    if loc_key in LOCATION_COORDS:
        return LOCATION_COORDS[loc_key]

    # Derive deterministic coordinates for any other location string.
    value = zlib.crc32(loc_key.encode("utf-8"))
    lat = 18.0 + ((value & 0xFFFF) / 65535.0) * 6.0
    lng = 82.0 + (((value >> 16) & 0xFFFF) / 65535.0) * 7.0
    return {"lat": lat, "lng": lng}


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points."""
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


@app.before_request
def clear_runtime_state():
    global startup_reset_done
    if not startup_reset_done:
        initialize_runtime_data()
        startup_reset_done = True


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/logout")
def logout():
    return render_template("logout.html")


@app.route("/predict")
def predict():
    return render_template("predict.html")


@app.route("/dashboard")
def dashboard():
    stats = {
        "total_disasters": len(reports),
        "critical_count": sum(1 for item in reports if item["priority"] == "CRITICAL"),
        "high_count": sum(1 for item in reports if item["priority"] == "HIGH"),
        "medium_count": sum(1 for item in reports if item["priority"] == "MEDIUM"),
        "low_count": sum(1 for item in reports if item["priority"] == "LOW"),
        "allocation_rate": 85,
        "open_incidents": len([i for i in incidents if i.get("status") == "open"]),
        "available_resources": sum(r.get("quantity", 0) for r in resources if r.get("status") == "available"),
        "last_refreshed": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return render_template("dashboard.html", reports=reports, stats=stats, incidents=json.dumps(incidents), 
                         resources=json.dumps(resources), allocation_history=json.dumps(allocation_history))


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/predict_disaster", methods=["POST"])
def predict_disaster():
    disaster_type = request.form.get("disaster_type", "")
    location = request.form.get("location", "")
    weather = request.form.get("weather", "")

    severity = int(request.form.get("severity", 1))
    people = int(request.form.get("people", 0))
    damage = int(request.form.get("damage", 1))
    accessibility = int(request.form.get("accessibility", 5))
    previous = int(request.form.get("previous", 0))

    priority = "MEDIUM"
    if model is not None:
        try:
            prediction = model.predict(np.array([[severity, people, damage, accessibility, previous]]))
            priority = prediction[0]
        except Exception:
            priority = "MEDIUM"
    else:
        score = severity * 3 + damage * 2 + people / 500 - accessibility + previous
        if score >= 35:
            priority = "CRITICAL"
        elif score >= 25:
            priority = "HIGH"
        else:
            priority = "MEDIUM"

    resources = []
    if priority == "CRITICAL":
        resources = [
            "10 Rescue Teams",
            "500 Food Kits",
            "5 Ambulances",
            "20 Doctors",
            "1000 Water Bottles",
            "5 Relief Camps"
        ]
    elif priority == "HIGH":
        resources = [
            "8 Rescue Teams",
            "300 Food Kits",
            "3 Ambulances",
            "10 Doctors",
            "600 Water Bottles"
        ]
    else:
        resources = [
            "3 Rescue Teams",
            "100 Food Kits",
            "1 Ambulance",
            "4 Doctors"
        ]

    new_report = {
        "type": disaster_type,
        "location": location,
        "severity": severity,
        "priority": priority,
        "people": people,
        "resources": ", ".join(resources),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    location_key = location.strip().lower()
    existing_index = next(
        (index for index, report in enumerate(reports)
         if report["location"].strip().lower() == location_key),
        None,
    )

    if existing_index is not None:
        reports[existing_index] = new_report
        for index in range(len(reports) - 1, -1, -1):
            if index != existing_index and reports[index]["location"].strip().lower() == location_key:
                reports.pop(index)
    else:
        reports.insert(0, new_report)
        if len(reports) > 5:
            reports.pop()

    # Also create a corresponding incident entry so the dashboard's
    # "Incidents Ranked by Urgency" uses the exact same user-provided data.
    try:
        coords = get_coordinates(location)
    except Exception:
        coords = None

    incident = {
        "id": str(uuid.uuid4()),
        "location": location,
        "type": disaster_type,
        "severity": int(severity),
        "people_affected": int(people),
        "status": "open",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "priority": priority,
    }

    if coords is not None:
        incident["lat"] = coords["lat"]
        incident["lng"] = coords["lng"]
    else:
        incident["lat"] = None
        incident["lng"] = None

    # Compute urgency score consistently with the API flow
    incident["urgency_score"] = calculate_urgency_score(incident)

    location_key = incident["location"].strip().lower()
    existing_incident_index = next(
        (index for index, inc in enumerate(incidents)
         if inc["location"].strip().lower() == location_key),
        None,
    )

    if existing_incident_index is not None:
        incident["id"] = incidents[existing_incident_index]["id"]
        incidents[existing_incident_index] = incident
    else:
        incidents.append(incident)

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
        resources=resources,
    )


# API Endpoints for Incidents
@app.route("/api/incidents", methods=["GET", "POST"])
def manage_incidents():
    if request.method == "POST":
        data = request.get_json()
        coords = get_coordinates(data.get("location", ""))

        incident = {
            "id": str(uuid.uuid4()),
            # Preserve the exact user-provided location string (do not normalize or replace)
            "location": data.get("location", ""),
            "type": data.get("type", ""),
            "severity": int(data.get("severity", 1)),
            "people_affected": int(data.get("people_affected", 0)),
            "status": "open",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Attach coordinates only when available; do not invent defaults for missing locations
        if coords is not None:
            incident["lat"] = coords["lat"]
            incident["lng"] = coords["lng"]
        else:
            incident["lat"] = None
            incident["lng"] = None

        # Preserve incident priority/rank if provided by the client
        if "priority" in data:
            incident["priority"] = data.get("priority")
        
        # Calculate urgency score
        incident["urgency_score"] = calculate_urgency_score(incident)
        if "priority" not in incident or not incident.get("priority"):
            incident["priority"] = derive_priority_from_score(incident["urgency_score"])

        location_key = incident["location"].strip().lower()

        # If the same city is submitted again, replace the previous incident for that city.
        if data.get("id"):
            for idx, inc in enumerate(incidents):
                if inc.get("id") == data.get("id"):
                    incidents[idx] = incident
                    break
            else:
                incidents.append(incident)
        else:
            existing_index = next(
                (index for index, inc in enumerate(incidents)
                 if inc["location"].strip().lower() == location_key),
                None,
            )
            if existing_index is not None:
                incident["id"] = incidents[existing_index]["id"]
                incidents[existing_index] = incident
            else:
                incidents.append(incident)

        # Also create a corresponding `report` entry so the Latest 5 Disaster Reports
        # shows the exact same user-provided incident when added via the dashboard.
        report_priority = incident.get("priority")
        if not report_priority:
            report_priority = derive_priority_from_score(incident.get("urgency_score", 0))

        new_report = {
            "type": incident.get("type", ""),
            "location": incident.get("location", ""),
            "severity": incident.get("severity", 1),
            "priority": report_priority,
            "people": incident.get("people_affected", 0),
            "resources": "",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        existing_report_index = next(
            (index for index, report in enumerate(reports)
             if report["location"].strip().lower() == location_key),
            None,
        )
        if existing_report_index is not None:
            reports[existing_report_index] = new_report
            for index in range(len(reports) - 1, -1, -1):
                if index != existing_report_index and reports[index]["location"].strip().lower() == location_key:
                    reports.pop(index)
        else:
            reports.insert(0, new_report)
            if len(reports) > 5:
                reports.pop()
        
        return jsonify(incident), 201
    
    return jsonify(incidents)


@app.route("/api/incidents/<incident_id>", methods=["DELETE"])
def delete_incident(incident_id):
    global incidents
    incidents = [i for i in incidents if i["id"] != incident_id]
    return jsonify({"status": "deleted"}), 200


# API Endpoints for Resources
@app.route("/api/resources", methods=["GET", "POST"])
def manage_resources():
    if request.method == "POST":
        data = request.get_json()
        coords = get_coordinates(data.get("location", ""))

        resource = {
            "id": str(uuid.uuid4()),
            # Preserve exact location string
            "location": data.get("location", ""),
            "type": data.get("type", ""),
            "quantity": int(data.get("quantity", 0)),
            "status": "available",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Attach coordinates only if available
        if coords is not None:
            resource["lat"] = coords["lat"]
            resource["lng"] = coords["lng"]
        else:
            resource["lat"] = None
            resource["lng"] = None

        # Support updates if an `id` is provided by the client.
        if data.get("id"):
            for idx, res in enumerate(resources):
                if res.get("id") == data.get("id"):
                    resources[idx] = resource
                    break
            else:
                resources.append(resource)
        else:
            # If a resource is submitted again for the same location, update the existing entry
            # instead of appending a duplicate. Preserve the exact input values while keeping
            # entries unique by normalized location.
            resource_location_key = resource["location"].strip().lower()
            existing_index = next(
                (index for index, res in enumerate(resources)
                 if res.get("location", "").strip().lower() == resource_location_key),
                None,
            )
            if existing_index is not None:
                resource["id"] = resources[existing_index]["id"]
                resources[existing_index] = resource
            else:
                resources.append(resource)
        
        return jsonify(resource), 201
    
    return jsonify(resources)


@app.route("/api/resources/<resource_id>", methods=["DELETE"])
def delete_resource(resource_id):
    global resources
    resources = [r for r in resources if r["id"] != resource_id]
    return jsonify({"status": "deleted"}), 200


# Allocation Algorithm
def calculate_urgency_score(incident):
    """Calculate urgency score for an incident"""
    severity = incident.get("severity", 1)
    people = incident.get("people_affected", 0)
    
    # Urgency score formula: (severity * 30) + (people / 10)
    urgency = (severity * 30) + (people / 10)
    
    return min(urgency, 100)  # Cap at 100


def derive_priority_from_score(score):
    if score >= 80:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 20:
        return "MEDIUM"
    return "LOW"


@app.route("/api/run-allocation", methods=["POST"])
def run_allocation():
    """Run the allocation algorithm"""
    allocation_result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "allocations": []
    }
    
    # Sort incidents by urgency score (highest first)
    sorted_incidents = sorted(incidents, key=lambda x: x.get("urgency_score", 0), reverse=True)
    
    # Simple allocation logic: match incidents to the nearest available resource
    for incident in sorted_incidents:
        # Only allocate incidents that are still open and have not been assigned before.
        if incident.get("status") != "open":
            continue

        available = [r for r in resources if r.get("status") == "available" and r.get("quantity", 0) > 0]
        if not available:
            continue

        best_resource = None
        best_distance = None

        for resource in available:
            # Only compute distance when both incident and resource have valid coordinates.
            if incident.get("lat") is not None and incident.get("lng") is not None and \
               resource.get("lat") is not None and resource.get("lng") is not None:
                distance = haversine_distance(
                    incident["lat"],
                    incident["lng"],
                    resource["lat"],
                    resource["lng"],
                )
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_resource = resource
            else:
                # If coordinates are missing, fall back to the first available resource (no fake distance).
                if best_resource is None:
                    best_resource = resource
                    best_distance = None

        if best_resource is None:
            continue

        incident_priority = incident.get("priority")
        if incident_priority is None:
            incident_priority = derive_priority_from_score(incident.get("urgency_score", 0))

        allocation = {
            "id": str(uuid.uuid4()),
            "incident_id": incident["id"],
            "incident_location": incident["location"],
            "incident_priority": incident_priority,
            "resource_id": best_resource["id"],
            "resource_location": best_resource["location"],
            "resource_type": best_resource["type"],
            "quantity_allocated": min(best_resource["quantity"], max(1, incident["people_affected"] // 100)),
            "urgency_score": incident.get("urgency_score", 0),
            "distance_km": round(best_distance, 2) if best_distance is not None else None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        allocation_result["allocations"].append(allocation)
        allocation_history.append(allocation)

        best_resource["quantity"] -= allocation["quantity_allocated"]
        if best_resource["quantity"] <= 0:
            best_resource["status"] = "depleted"

        incident["status"] = "allocated"
    
    # Return allocations plus current server-side incidents and resources so clients can refresh
    response_payload = {
        "allocations": allocation_result["allocations"],
        "timestamp": allocation_result["timestamp"],
        "incidents": incidents,
        "resources": resources,
        "allocation_history": allocation_history,
    }

    return jsonify(response_payload), 200


@app.route("/api/allocation-history", methods=["GET"])
def get_allocation_history():
    return jsonify(allocation_history)

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if __name__ == "__main__":
    app.run(debug=True)
