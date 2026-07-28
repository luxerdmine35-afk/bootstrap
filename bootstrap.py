import sys
import subprocess
import time
from datetime import datetime
from colorama import Fore, init
import os
import shutil
import hashlib
import requests
from cryptography.fernet import Fernet


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
            return sha256, enc_key, data.get("version", "unknown")
        except Exception as e:
            if attempt >= max_retry:
                break
            log(f"⚠️ Fetch launcher meta failed, retrying... ({attempt}/{max_retry}) [{e}]", Fore.YELLOW)
            time.sleep(delay)
            delay = min(delay * 1.6, 8)
    log("❌ Failed fetch launcher meta after retries", Fore.RED)
    sys.exit(1)


def fetch_launcher_ciphertext():
    for url in LAUNCHER_URLS:
        try:
            log(f"🌐 Trying {url}", Fore.CYAN)
            r = requests.get(url, timeout=10)
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
    expected_hash, enc_key, version = fetch_launcher_meta(server_url)

    ciphertext = fetch_launcher_ciphertext()
    try:
        plaintext_bytes = Fernet(enc_key.encode()).decrypt(ciphertext.encode())
    except Exception as e:
        log(f"❌ Failed to decrypt launcher: {e}", Fore.RED)
        os._exit(1)

    source = plaintext_bytes.decode("utf-8")
    actual_hash = hashlib.sha256(source.encode()).hexdigest()
    if actual_hash != expected_hash:
        time.sleep(2)
        log("❌ Integrity check failed", Fore.RED)
        os._exit(1)

    log(f"🚀 Running launcher v{version}...\n", Fore.MAGENTA)
    exec(source, {"__name__": "__main__"})


if __name__ == "__main__":
    main()