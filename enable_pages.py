import os, time, requests
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(r"E:\deepseek harness\复现\arxiv_daily_paperBot")
load_dotenv(ROOT / ".env")
token = os.environ.get("GITHUB_TOKEN", "").strip()
if not token:
    raise SystemExit("GITHUB_TOKEN empty")

owner, repo = "tegardenshannon80-rgb", "arxiv-daily-paper-bot"
api = "https://api.github.com"
headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

r = requests.get(f"{api}/repos/{owner}/{repo}/pages", headers=headers, timeout=30)
print("GET pages:", r.status_code)
if r.status_code == 404:
    body = {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}}
    r = requests.post(f"{api}/repos/{owner}/{repo}/pages", headers=headers, json=body, timeout=30)
    print("POST pages:", r.status_code, r.text[:300])
else:
    print("existing:", r.text[:300])
    body = {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}}
    r = requests.put(f"{api}/repos/{owner}/{repo}/pages", headers=headers, json=body, timeout=30)
    print("PUT pages:", r.status_code, r.text[:300])

for i in range(12):
    time.sleep(10)
    r = requests.get(f"{api}/repos/{owner}/{repo}/pages", headers=headers, timeout=30)
    print("poll:", r.status_code, r.text[:200])
    if r.status_code == 200:
        data = r.json()
        if data.get("status") in ("built", "errored"):
            print("final:", data.get("status"), data.get("html_url"))
            break
