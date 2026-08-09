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

    for i, incident in enumerate(incidents, 1):
        print(f'POST incident{i}')
        print(post('http://127.0.0.1:5000/api/incidents', incident))

    for i, resource in enumerate(resources, 1):
        print(f'POST resource{i}')
        print(post('http://127.0.0.1:5000/api/resources', resource))

    print('RUN ALLOCATION')
    alloc = post('http://127.0.0.1:5000/api/run-allocation', {})
    print(json.dumps(alloc, indent=2))
    print('HISTORY')
    print(json.dumps(get('http://127.0.0.1:5000/api/allocation-history'), indent=2))
