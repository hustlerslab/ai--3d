"""Steps 4 and 5 on a fresh project, clicks only."""
import asyncio, base64, json, subprocess, sys, time
from pathlib import Path
import httpx, websockets
CHROME = r"C:/Users/user/AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe"
OUT = Path(sys.argv[1]); PROJECT = sys.argv[2]

async def main():
    proc = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9330",
        "--window-size=1400,3200", "--hide-scrollbars", "--no-first-run",
        "--user-data-dir=" + str(OUT/"_s45"), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try: tabs = httpx.get("http://127.0.0.1:9330/json", timeout=2).json(); break
            except Exception: time.sleep(0.5)
        ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
        async with websockets.connect(ws_url, max_size=90_000_000) as ws:
            n = 0
            async def call(m, **p):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": m, "params": p})); mine = n
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == mine: return r.get("result", {})
            async def js(e):
                r = await call("Runtime.evaluate", expression=e, awaitPromise=True, returnByValue=True)
                return r.get("result", {}).get("value")
            async def click(t):
                return await js("(()=>{const b=[...document.querySelectorAll('button')]"
                    f".find(x=>x.textContent.trim().includes({json.dumps(t)}) && !x.disabled);"
                    "if(!b) return false; b.scrollIntoView({block:'center'}); b.click(); return true;})()")
            async def until(expr, timeout, label):
                t0 = time.monotonic()
                while time.monotonic() - t0 < timeout:
                    if await js(expr): return round(time.monotonic() - t0)
                    await asyncio.sleep(6)
                raise TimeoutError(f"{label} after {timeout}s")
            async def shot(name):
                r = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
                (OUT/name).write_bytes(base64.b64decode(r["data"]))

            await call("Page.enable"); await call("Runtime.enable")
            await call("Page.navigate", url="http://localhost:3001/"); await asyncio.sleep(4)
            await js(f"sessionStorage.setItem('allure.studio.project','{PROJECT}')")
            await call("Page.navigate", url="http://localhost:3001/"); await asyncio.sleep(9)
            print("resumed on:", await js("document.querySelector('h2')?.textContent"), flush=True)
            await click("Review & Refine"); await asyncio.sleep(7)
            print("STEP 4 now on :", await js("document.querySelector('h2')?.textContent"), flush=True)

            print("  clicked 'Plan the space':", await click("Plan the space"), flush=True)
            secs = await until("document.body.innerText.includes('Confirm what gets built')", 1800, "element review")
            print(f"  element review appeared after {secs}s", flush=True)
            print("  crops shown   :", await js("document.querySelectorAll('img[src*=scene_crops]').length"))
            print("  broken crops  :", await js(
                "[...document.images].filter(i=>i.src.indexOf('scene_crops')>-1&&(!i.complete||i.naturalWidth===0)).length"))
            print("  flagged line  :", await js(
                "[...document.querySelectorAll('span')].map(s=>s.textContent).find(t=>t&&t.includes('flagged'))"))
            await shot("s4_review.png")

            # Confirm the pieces that passed the check, exactly as a user would.
            built = await js("(()=>{let n=0;document.querySelectorAll('li').forEach(li=>{"
                "if(li.textContent.includes('looks right')){const b=[...li.querySelectorAll('button')]"
                ".find(x=>x.textContent.trim()==='Build'); if(b){b.click(); n++;}}}); return n;})()")
            print(f"  clicked Build on {built} piece(s) that passed the check", flush=True)
            await asyncio.sleep(1)
            print("  clicked Save decisions:", await click("Save decisions"), flush=True)
            await asyncio.sleep(6)
            print("  next-button label:", await js(
                "[...document.querySelectorAll('button')].map(b=>b.textContent.trim())"
                ".find(t=>t.includes('plan the space')||t.includes('Confirm at least'))"))
            await shot("s4_confirmed.png")

            print("  clicked Build-and-plan:", await click("and plan the space"), flush=True)
            secs = await until("document.querySelector('h2')?.textContent.includes('Plan your 3D space')", 2400, "step 5")
            print(f"STEP 5 reached after {secs}s", flush=True)
            await asyncio.sleep(25)
            print("  3D canvas present :", await js("!!document.querySelector('canvas')"))
            print("  web GLBs fetched  :", await js(
                "performance.getEntriesByType('resource').filter(r=>r.name.indexOf('assets-web')>-1).length"))
            print("  runtime error     :", await js("document.body.innerText.includes('Runtime TypeError')"))
            await shot("s5_plan.png")
    finally:
        proc.terminate()
asyncio.run(main())
