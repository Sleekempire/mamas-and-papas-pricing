import httpx, asyncio, time
async def main():
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post("http://127.0.0.1:8082/api/v1/auth/token", data={"username":"admin@pricing.internal", "password":"Admin123!"})
        if r.status_code != 200: return
        token = r.json().get("access_token")
        for i in range(40):
            try:
                r4 = await client.post("http://127.0.0.1:8082/api/v1/run-optimisation", headers={"Authorization": "Bearer "+token}, params={"target_date": "2024-09-02"})
                if r4.status_code == 200:
                    print("Optimise success!")
                    break
                print(f"Waiting for model... {r4.status_code}")
            except Exception as e:
                print("Error:", e)
            time.sleep(15)
asyncio.run(main())
