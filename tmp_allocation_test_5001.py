import json
import urllib.request as u


def post(url, data):
    req = u.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    with u.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))


def get(url):
    with u.urlopen(url) as resp:
        return json.loads(resp.read().decode('utf-8'))


if __name__ == '__main__':
    base = 'http://127.0.0.1:5001'
    incidents = [
        {'location': 'Bhubaneswar', 'type': 'Flood', 'severity': 7, 'people_affected': 300},
        {'location': 'Cuttack', 'type': 'Cyclone', 'severity': 6, 'people_affected': 200},
        {'location': 'Berhampur', 'type': 'Fire', 'severity': 8, 'people_affected': 100},
    ]
    resources = [
        {'location': 'Baleswar', 'type': 'Rescue Team', 'quantity': 5},
        {'location': 'Puri', 'type': 'Rescue Team', 'quantity': 5},
        {'location': 'Puri', 'type': 'Food Kit', 'quantity': 20},
    ]

    for i in incidents:
        print('POST incident', post(base + '/api/incidents', i))

    for r in resources:
        print('POST resource', post(base + '/api/resources', r))

    alloc = post(base + '/api/run-allocation', {})
    print('RUN ALLOCATION', json.dumps(alloc, indent=2))
    print('HISTORY', json.dumps(get(base + '/api/allocation-history'), indent=2))
