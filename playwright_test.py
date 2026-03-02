import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # intercept console logs
        page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
        
        # go to page
        await page.goto("http://localhost:3000/login.html")
        await page.fill("input[type=email]", "admin@pricing.internal")
        await page.fill("input[type=password]", "Admin123!")
        await page.click("button:has-text('Sign In')")
        
        # wait for dashboard
        await page.wait_for_selector("#page-overview")
        print("Logged in")
        
        # go to simulator
        await page.click("#nav-simulator")
        await page.wait_for_selector("#sim-sku-select")
        await page.wait_for_timeout(1000)
        
        options = await page.locator("#sim-sku-select option").count()
        print(f"Simulator options count: {options}")
        
        # select an option
        if options > 1:
            await page.locator("#sim-sku-select").select_option(index=1)
            await page.wait_for_timeout(1000)
            
            val = await page.locator("#sim-price").text_content()
            print(f"Simulator price value: {val}")
        
        await browser.close()

asyncio.run(run())
