
import httpx, asyncio
async def main():
    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.post("http://127.0.0.1:8082/api/v1/auth/token", data={"username":"admin@pricing.internal", "password":"Admin123!"})
        if r.status_code != 200: print("Auth failed:", r.status_code, r.text); return
        token = r.json().get("access_token")
        with open("c:/Users/customer/Desktop/APP/MamasAndPapas_Final_Pricing_Dataset CSV.csv", "rb") as f:
            r2 = await client.post("http://127.0.0.1:8082/api/v1/upload-data", headers={"Authorization": "Bearer "+token}, files={"file": ("data.csv", f, "text/csv")})
            print("Upload:", r2.status_code)
        r3 = await client.post("http://127.0.0.1:8082/api/v1/train", headers={"Authorization": "Bearer "+token})
        print("Train:", r3.status_code, r3.text[:500])
        r4 = await client.post("http://127.0.0.1:8082/api/v1/run-optimisation", headers={"Authorization": "Bearer "+token}, params={"target_date": "2024-09-02"})
        print("Optimise:", r4.status_code, r4.text[:500])
asyncio.run(main())
