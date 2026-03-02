import httpx
import asyncio

async def test_api():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000/api/v1") as client:
        # 1. Health check
        res = await client.get("http://127.0.0.1:8000/health")
        print("Health:", res.status_code, res.json())

        # 2. Login as admin
        res = await client.post("/auth/token", data={"username": "admin@pricing.internal", "password": "Admin123!"})
        print("Login:", res.status_code, res.json())
        token = res.json().get("access_token")
        
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Test optimization
        res = await client.post("/run-optimisation", headers=headers)
        print("Optimization (no data):", res.status_code, res.json())

if __name__ == "__main__":
    asyncio.run(test_api())
