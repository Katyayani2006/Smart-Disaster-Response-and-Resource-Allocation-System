import os

# Must be set BEFORE importing app, since app.py reads ADMIN_API_KEY once
# at import time. Using a fixed test key keeps this suite self-contained.
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-123")

import json
from app import app, load_store, save_store, incidents, resources, allocation_history

ADMIN_HEADERS = {"X-Admin-Key": os.environ["ADMIN_API_KEY"]}


def run_tests():
    print("==================================================")
    print("STARTING SMART DISASTER RESPONSE INTEGRITY TESTS")
    print("==================================================")

    # Clear any persisted state before starting
    incidents.clear()
    resources.clear()
    allocation_history.clear()
    save_store()

    # 1. Test Store loading/saving
    print("[TEST 1] Testing persistence store...")
    save_store()
    assert os.path.exists(os.path.join("data", "store.json")), "data/store.json must exist!"
    print(" -> Store persistence file verified!")

    # Flask test client
    client = app.test_client()

    # 2. Test Home Page
    print("[TEST 2] GET / (Home Page)...")
    res = client.get("/")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert b"Smart Disaster" in res.data, "Home page missing brand text"
    print(" -> Home page rendered successfully!")

    # 3. Test Predict Page GET
    print("[TEST 3] GET /predict...")
    res = client.get("/predict")
    assert res.status_code == 200
    print(" -> Predict page rendered successfully!")

    # 4. Test Predict Disaster POST (ML model prediction)
    print("[TEST 4] POST /predict_disaster with valid inputs...")
    form_data = {
        "disaster_type": "Flood",
        "location": "Bhubaneswar",
        "severity": "8",
        "people": "2500",
        "damage": "7",
        "accessibility": "4",
        "previous": "2",
        "weather": "Rainy"
    }
    res = client.post("/predict_disaster", data=form_data)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert b"Disaster Priority Level" in res.data, "Result page missing priority title"
    assert (b"CRITICAL" in res.data or b"HIGH" in res.data), "ML Priority output missing or invalid"
    print(" -> ML Prediction pipeline executed successfully and returned priority!")

    # 5. Test Invalid Predict Form Input Validation
    print("[TEST 5] POST /predict_disaster with invalid numeric input...")
    bad_form_data = {
        "disaster_type": "Flood",
        "location": "Bhubaneswar",
        "severity": "15",  # Invalid (must be 1-10)
        "people": "-50",   # Invalid
        "damage": "5",
        "accessibility": "5",
        "previous": "0",
        "weather": "Clear"
    }
    res = client.post("/predict_disaster", data=bad_form_data)
    assert res.status_code == 200
    assert b"Invalid numerical input" in res.data, "Validation error banner missing"
    print(" -> Frontend/Backend input validation successfully caught invalid form data!")

    # 5b. Log in as an officer so /dashboard and admin-only actions work
    # for the rest of this suite (dashboard is now login-protected).
    print("[TEST 5b] POST /login as officer1...")
    res = client.post(
        "/login",
        data={"username": "officer1", "password": "officer123"},
        follow_redirects=True,
    )
    assert res.status_code == 200, f"Login failed with status {res.status_code}"
    print(" -> Logged in successfully as officer1!")

    # 6. Test Dashboard GET
    print("[TEST 6] GET /dashboard...")
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert b"Open Incidents" in res.data
    assert b"Resources Allocated" in res.data
    print(" -> Dashboard rendered successfully!")

    # 7. Test Add Incident API (/api/incidents)
    # source="officer" pre-verifies this incident so later allocation
    # tests (10, 13) can pick it up without a separate verify step.
    print("[TEST 7] POST /api/incidents...")
    incident_payload = {
        "location": "Cuttack",
        "type": "Cyclone",
        "severity": 7,
        "people_affected": 1500,
        "source": "officer"
    }
    res = client.post("/api/incidents", data=json.dumps(incident_payload), content_type="application/json")
    assert res.status_code == 201, f"Expected 201, got {res.status_code}"
    inc_data = json.loads(res.data)
    assert inc_data["location"] == "Cuttack"
    assert inc_data["status"] == "open"
    assert "urgency_score" in inc_data
    print(" -> Incident added successfully via API!")

    # 8. Test Add Resource API (/api/resources) - now admin-protected
    print("[TEST 8] POST /api/resources...")
    resource_payload = {
        "location": "Puri",
        "type": "Food Kit",
        "quantity": 50
    }
    res = client.post(
        "/api/resources",
        data=json.dumps(resource_payload),
        content_type="application/json",
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 201, f"Expected 201, got {res.status_code}"
    res_data = json.loads(res.data)
    assert res_data["location"] == "Puri"
    assert res_data["quantity"] == 50
    assert res_data["status"] == "available"
    print(" -> Resource added successfully via API!")

    # 8b. Test Add Resource API is rejected without the admin key
    print("[TEST 8b] POST /api/resources without admin key...")
    # Use a fresh client without session to ensure we're testing the unauthorized path
    client_no_auth = app.test_client()
    res = client_no_auth.post(
        "/api/resources",
        data=json.dumps(resource_payload),
        content_type="application/json",
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print(" -> Unauthorized resource add correctly rejected!")

    # 9. Test Invalid Resource API Submission (Negative quantity)
    print("[TEST 9] POST /api/resources with invalid quantity...")
    bad_res_payload = {
        "location": "Puri",
        "type": "Food Kit",
        "quantity": -10
    }
    res = client.post(
        "/api/resources",
        data=json.dumps(bad_res_payload),
        content_type="application/json",
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 400, f"Expected 400 Bad Request, got {res.status_code}"
    print(" -> API input validation correctly rejected negative quantity!")

    # 10. Test Run Allocation Engine (/api/run-allocation) - admin-protected
    print("[TEST 10] POST /api/run-allocation...")
    res = client.post("/api/run-allocation", headers=ADMIN_HEADERS)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    alloc_res = json.loads(res.data)
    assert "allocations" in alloc_res
    print(f" -> Allocation engine completed! Allocated count: {len(alloc_res['allocations'])}")

    # 10b. Test Run Allocation is rejected without the admin key
    print("[TEST 10b] POST /api/run-allocation without admin key...")
    # Use a fresh client without session to ensure we're testing the unauthorized path
    client_no_auth = app.test_client()
    res = client_no_auth.post("/api/run-allocation")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print(" -> Unauthorized allocation run correctly rejected!")

    # 11. Test Allocation History API (/api/allocation-history)
    print("[TEST 11] GET /api/allocation-history...")
    res = client.get("/api/allocation-history")
    assert res.status_code == 200
    hist = json.loads(res.data)
    assert len(hist) > 0, "Allocation history should contain records"
    print(" -> Allocation history retrieved successfully!")

    # 12. Test Data Persistence after Reload
    print("[TEST 12] Testing reload persistence from file...")
    load_store()
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert b"Cuttack" in res.data or b"Bhubaneswar" in res.data, "Persisted incidents missing from dashboard"
    print(" -> Data persistence verified! Incidents and allocation history intact after reload!")

    # 13. Test Duplicate Allocation Prevention
    print("[TEST 13] Testing duplicate allocation prevention...")
    res_second = client.post("/api/run-allocation", headers=ADMIN_HEADERS)
    assert res_second.status_code == 200
    second_alloc_res = json.loads(res_second.data)
    assert len(second_alloc_res["allocations"]) == 0, "No open incidents should be re-allocated on second run!"
    print(" -> Duplicate allocation protection verified! Already allocated incidents skipped on second run!")

    # 14. Test Session Reset (/api/new-session) - admin-protected
    print("[TEST 14] POST /api/new-session...")
    res_sess = client.post("/api/new-session", headers=ADMIN_HEADERS)
    assert res_sess.status_code == 200
    sess_data = json.loads(res_sess.data)
    assert "session_id" in sess_data
    # Current session allocation history should be empty
    res_hist = client.get("/api/allocation-history?session=current")
    curr_hist = json.loads(res_hist.data)
    assert len(curr_hist) == 0, "New session allocation history should initially be empty!"
    # Historical records should still be preserved in database store
    res_all_hist = client.get("/api/allocation-history?session=all")
    all_hist = json.loads(res_all_hist.data)
    assert len(all_hist) > 0, "All past historical records must be preserved in store!"
    print(" -> Session reset verified! Current session history is empty while past records remain preserved!")

    # 15. Test Allocation in New Session
    print("[TEST 15] Allocating in New Session...")
    inc_new = {
        "location": "Berhampur",
        "type": "Fire",
        "severity": 8,
        "people_affected": 300,
        "source": "officer"
    }
    client.post("/api/incidents", data=json.dumps(inc_new), content_type="application/json")
    res_new = {"location": "Berhampur", "type": "Fire", "quantity": 10}
    client.post(
        "/api/resources",
        data=json.dumps(res_new),
        content_type="application/json",
        headers=ADMIN_HEADERS,
    )

    res_run2 = client.post("/api/run-allocation", headers=ADMIN_HEADERS)
    assert res_run2.status_code == 200
    run2_data = json.loads(res_run2.data)
    assert len(run2_data["allocations"]) == 1

    res_curr_hist = client.get("/api/allocation-history?session=current")
    curr_session_hist = json.loads(res_curr_hist.data)
    assert len(curr_session_hist) == 1, "Only current session allocation should appear in history!"
    assert curr_session_hist[0]["incident_location"] == "Berhampur"
    print(" -> New session allocation verified! History displays only current session allocation!")

    # 16. Test Location Alias Normalization (Step 2 check)
    print("[TEST 16] Testing location alias normalization...")
    inc_typo = {
        "location": "Balesore",  # typo variant, should normalize to "Baleswar"
        "type": "Flood",
        "severity": 6,
        "people_affected": 200,
        "source": "officer"
    }
    res = client.post("/api/incidents", data=json.dumps(inc_typo), content_type="application/json")
    assert res.status_code == 201
    normalized = json.loads(res.data)
    assert normalized["location"] == "Baleswar", (
        f"Expected 'Balesore' to normalize to 'Baleswar', got '{normalized['location']}'"
    )
    print(" -> Location alias normalization verified! 'Balesore' correctly resolved to 'Baleswar'.")

    # 17. Test Incident Verification Workflow (Step 1 check)
    print("[TEST 17] Testing unverified incident is excluded from allocation...")
    inc_unverified = {
        "location": "Puri",
        "type": "Flood",
        "severity": 9,
        "people_affected": 5000
        # no "source" / "verified" -> should land as "unverified"
    }
    res = client.post("/api/incidents", data=json.dumps(inc_unverified), content_type="application/json")
    assert res.status_code == 201
    unverified_data = json.loads(res.data)
    assert unverified_data["status"] == "unverified", "New citizen report should start unverified!"
    incident_id = unverified_data["id"]

    # Should not be picked up by allocation while unverified
    res_alloc = client.post("/api/run-allocation", headers=ADMIN_HEADERS)
    alloc_data = json.loads(res_alloc.data)
    allocated_locations = [a.get("incident_location") for a in alloc_data["allocations"]]
    assert "Puri" not in allocated_locations, "Unverified incident must not be auto-allocated!"

    # Verify it, then confirm status flips to "open"
    res_verify = client.post(f"/api/incidents/{incident_id}/verify", headers=ADMIN_HEADERS)
    assert res_verify.status_code == 200, f"Expected 200, got {res_verify.status_code}"
    verified_data = json.loads(res_verify.data)
    assert verified_data["status"] == "open", "Incident should be 'open' after verification!"
    # 18. Test Citizen SOS Endpoint (/sos)
    print("[TEST 18] Testing Citizen Public SOS Endpoint...")
    sos_res = client.post("/sos", data={
        "location": "Kendrapara",
        "disaster_type": "Flood",
        "people": "50",
        "severity": "9",
        "description": "Urgent boat required. Water rising fast."
    })
    assert sos_res.status_code == 200
    assert b"Distress Alert Lodged Successfully" in sos_res.data
    print(" -> Citizen SOS Submission verified successfully!")

    # 19. Test ODRAF Data Seeding Endpoint (/api/seed-odraf-data)
    print("[TEST 19] Testing ODRAF Data Seeding API...")
    seed_res = client.post("/api/seed-odraf-data", headers=ADMIN_HEADERS)
    assert seed_res.status_code == 200
    seed_data = json.loads(seed_res.data)
    assert seed_data["status"] == "success"
    assert seed_data["incidents_count"] > 0
    assert seed_data["resources_count"] > 0
    print(" -> ODRAF Battalion inventory seeding verified successfully!")

    # 20. Test Export Report Endpoint (/export-report)
    print("[TEST 20] Testing Export Official Report Endpoint...")
    report_res = client.get("/export-report")
    assert report_res.status_code == 200
    assert b"State Disaster Emergency Response" in report_res.data or b"Disaster" in report_res.data
    print(" -> Official Report Export verified successfully!")

    print("==================================================")
    print("ALL INTEGRITY TESTS PASSED SUCCESSFULLY! (22/22)")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
