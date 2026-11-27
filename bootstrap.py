import sys
import subprocess
import time
from datetime import datetime
from colorama import Fore, init
import os
import shutil
import hashlib
from cryptography.fernet import Fernet
import requests


def get_pip_cmd():
    candidates = [[sys.executable, "-m", "pip"], ["pip"], ["pip3"]]
    for cmd in candidates:
        try:
            subprocess.check_output(cmd + ["--version"], stderr=subprocess.DEVNULL)
            return cmd
        except Exception:
            continue
    return None


REQUIRED_PACKAGES = ["requests", "colorama", "cryptography"]


def ensure_env():
    pip_cmd = get_pip_cmd()
    if not pip_cmd:
        log("❌ pip not found, please install pip manually", Fore.RED)
        sys.exit(1)
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
        except ImportError:
            log(f"📦 Installing {pkg}...", Fore.YELLOW)
            try:
                subprocess.check_call(pip_cmd + ["install", pkg])
                log(f"✅ {pkg} installed", Fore.GREEN)
            except Exception as e:
                log(f"❌ Failed to install {pkg}: {e}", Fore.RED)
                sys.exit(1)


def brutal_cleaner(base="."):
    targets = ["__pycache__", ".pytest_cache"]
    removed = 0
    for root, dirs, files in os.walk(base):
        for d in dirs:
            if d in targets:
                path = os.path.join(root, d)
                try:
                    shutil.rmtree(path)
                    removed += 1
                except:
                    pass
        for f in files:
            if f.endswith(".pyc"):
                try:
                    os.remove(os.path.join(root, f))
                    removed += 1
                except:
                    pass
    log(f"🧹 Cleaner removed {removed} junk items", Fore.GREEN)


def pip_cache_clean():
    try:
        pip_cmd = get_pip_cmd()
        subprocess.call(pip_cmd + ["cache", "purge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("🔥 pip cache purged", Fore.GREEN)
    except:
        pass


init(autoreset=True)
LAUNCHER_URLS = ["https://raw.githubusercontent.com/LIVEXORD/url/refs/heads/main/launcher.py.enc"]
LAUNCHER_API_URL = "https://api.github.com/repos/LIVEXORD/url/contents/launcher.py.enc?ref=main"
SERVER_URL_SOURCE = "https://raw.githubusercontent.com/LIVEXORD/url/refs/heads/main/url.txt"


def now_ts():
    return datetime.now().strftime("[%Y:%m:%d ~ %H:%M:%S] |")


def log(message, color=Fore.RESET):
    safe_message = str(message).encode("utf-8", "backslashreplace").decode("utf-8")
    print(Fore.LIGHTBLACK_EX + now_ts() + " " + color + safe_message + Fore.RESET)


def fetch_server_url(max_retry=5):
    """Same pattern used by the main launcher -- reads url.txt from GitHub."""
    delay = 1.5
    for attempt in range(1, max_retry + 1):
        try:
            r = requests.get(SERVER_URL_SOURCE, timeout=10)
            r.raise_for_status()
            url = r.text.strip().rstrip("/")
            if not url.startswith("http"):
                raise Exception("invalid url content")
            return url
        except Exception as e:
            if attempt >= max_retry:
                break
            log(f"⚠️ Fetch server URL failed, retrying... ({attempt}/{max_retry}) [{e}]", Fore.YELLOW)
            time.sleep(delay)
            delay = min(delay * 1.6, 8)
    log("❌ Failed fetch server URL after retries", Fore.RED)
    sys.exit(1)


def fetch_launcher_meta(server_url, max_retry=5):
    """Fetch version, sha256 (of plaintext), and enc_key from server -- nothing hardcoded."""
    delay = 1.5
    meta_url = f"{server_url}/launcher/meta"
    for attempt in range(1, max_retry + 1):
        try:
            r = requests.get(meta_url, timeout=10)
            r.raise_for_status()
            data = r.json()
            sha256 = data.get("sha256")
            enc_key = data.get("enc_key")
            if not sha256 or not enc_key:
                raise Exception("meta is empty / not yet published by server")
            return (sha256, enc_key, data.get("version", "unknown"))
        except Exception as e:
            if attempt >= max_retry:
                break
            log(f"⚠️ Fetch launcher meta failed, retrying... ({attempt}/{max_retry}) [{e}]", Fore.YELLOW)
            time.sleep(delay)
            delay = min(delay * 1.6, 8)
    log("❌ Failed fetch launcher meta after retries", Fore.RED)
    sys.exit(1)


def fetch_launcher_ciphertext(prefer_fresh=False):
    # raw.githubusercontent.com cache 300 dtk dan mengabaikan query string;
    # api.github.com (media type raw) cache hanya 60 dtk -> dipakai saat retry.
    sources = [(u, None) for u in LAUNCHER_URLS]
    if prefer_fresh:
        sources.insert(0, (LAUNCHER_API_URL, {"Accept": "application/vnd.github.raw"}))
    for url, headers in sources:
        try:
            log(f"🌐 Trying {url}", Fore.CYAN)
            r = requests.get(url, timeout=10, headers=headers)
            if r.status_code == 200 and len(r.text.strip()) > 100:
                log("✅ Launcher ciphertext fetched successfully", Fore.GREEN)
                return r.text.strip()
            else:
                log(f"⚠️ Bad response ({r.status_code})", Fore.YELLOW)
        except Exception as e:
            log(f"⚠️ Fetch error: {e}", Fore.RED)
        time.sleep(1)
    raise RuntimeError("Failed to fetch launcher ciphertext")


def main():
    ensure_env()
    brutal_cleaner()
    pip_cache_clean()
    log("🌐 Resolving server URL...", Fore.CYAN)
    server_url = fetch_server_url()
    log("🔑 Fetching launcher integrity metadata...", Fore.CYAN)
    # raw.githubusercontent.com meng-cache ~5 menit: ciphertext lama + meta baru
    # (atau sebaliknya) membuat dekripsi/hash gagal sesaat. Ambil ulang meta dan
    # ciphertext bersama (ciphertext dari api.github.com, cache 60 dtk) sebelum menyerah.
    source = version = None
    last_err = "unknown"
    for attempt in range(1, 7):
        expected_hash, enc_key, version = fetch_launcher_meta(server_url)
        ciphertext = fetch_launcher_ciphertext(prefer_fresh=attempt > 1)
        try:
            plaintext_bytes = Fernet(enc_key.encode()).decrypt(ciphertext.encode())
            candidate = plaintext_bytes.decode("utf-8")
            if hashlib.sha256(candidate.encode()).hexdigest() != expected_hash:
                raise ValueError("integrity hash mismatch")
            source = candidate
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt >= 6:
                break
            wait = min(10 * attempt, 60)
            log(f"⚠️ Launcher decrypt/verify failed (stale cache?), refetching in {wait}s... ({attempt}/6)", Fore.YELLOW)
            time.sleep(wait)
    if source is None:
        log(f"❌ Failed to decrypt/verify launcher after retries: {last_err}", Fore.RED)
        os._exit(1)
    log(f"🚀 Running launcher v{version}...\n", Fore.MAGENTA)
    exec(source, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
