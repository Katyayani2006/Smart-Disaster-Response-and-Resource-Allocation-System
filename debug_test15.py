import os, json
os.environ.setdefault('ADMIN_API_KEY', 'test-admin-key-123')
from app import app, CURRENT_SESSION_ID as initial_session_id
import app as app_module

ADMIN_HEADERS = {'X-Admin-Key': os.environ['ADMIN_API_KEY']}
client = app.test_client()

# Login as officer
client.post('/login', data={'username': 'officer1', 'password': 'officer1'})

# Simulate test 14-15: new session then allocation
print('=== Before new session ===')
print('Current session ID before:', app_module.CURRENT_SESSION_ID)

client.post('/api/new-session', headers=ADMIN_HEADERS)
print('=== After new session ===')
print('Current session ID after:', app_module.CURRENT_SESSION_ID)

# Add new incident with source=officer
inc_new = {'location': 'Berhampur', 'type': 'Fire', 'severity': 8, 'people_affected': 300, 'source': 'officer'}
r_inc = client.post('/api/incidents', data=json.dumps(inc_new), content_type='application/json')
print('Incident created:', r_inc.status_code)
inc_data = json.loads(r_inc.data)
print('Incident status:', inc_data.get('status'))

# Add new resource
res_new = {'location': 'Berhampur', 'type': 'Fire', 'quantity': 10}
r_res = client.post('/api/resources', data=json.dumps(res_new), content_type='application/json', headers=ADMIN_HEADERS)
print('Resource created:', r_res.status_code)
res_data = json.loads(r_res.data)
print('Resource status:', res_data.get('status'))

# Check open incidents
print('=== Open incidents ===')
for i in app_module.incidents:
    status = i.get('status')
    loc = i['location']
    typ = i['type']
    print(f'  {loc} ({typ}): status={status}')

# Run allocation
print('=== Running allocation ===')
r_alloc = client.post('/api/run-allocation', headers=ADMIN_HEADERS)
alloc_data = json.loads(r_alloc.data)
print(f'Allocations returned: {len(alloc_data["allocations"])}')
for alloc in alloc_data['allocations']:
    print(f'  {alloc["incident_location"]} <- {alloc["resource_location"]}')
