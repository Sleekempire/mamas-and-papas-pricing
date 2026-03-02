import urllib.request
import json
import urllib.parse

# 1. Login
req = urllib.request.Request('http://127.0.0.1:8082/api/v1/auth/token', data=urllib.parse.urlencode({'username':'admin@pricing.internal', 'password':'Admin123!'}).encode())
token = json.loads(urllib.request.urlopen(req).read())['access_token']

# 2. Get Recommendations
req2 = urllib.request.Request('http://127.0.0.1:8082/api/v1/recommendations?limit=1', headers={'Authorization': 'Bearer ' + token})
rec = json.loads(urllib.request.urlopen(req2).read())['results'][0]

print(f"Product: {rec['description']}")
print(f"Current Price: £{rec['current_price']}")
print(f"Best Price: £{rec['recommended_price']}")
print(f"Expected Margin: £{rec['expected_margin']}")

# 3. Get Explanation
encoded_desc = urllib.parse.quote(rec['description'], safe='')
req3 = urllib.request.Request(f'http://127.0.0.1:8082/api/v1/recommendations/explanation/{encoded_desc}', headers={'Authorization': 'Bearer ' + token})
try:
    exp = json.loads(urllib.request.urlopen(req3).read())
    print(f"Explanation Narrative: {exp['narrative']}")
    print("API TEST SUCCESSFUL")
except Exception as e:
    print(f"FAILED TO GET EXPLANATION: {e}")
