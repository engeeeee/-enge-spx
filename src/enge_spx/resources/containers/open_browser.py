import json
import os
import sys
import time
import urllib.request


def main():
    if len(sys.argv) != 2:
        raise SystemExit("A single authorization URL is required.")
    headers = {"Content-Type": "application/json", "X-SPX-Token": os.environ.get("SPX_BROWSER_TOKEN", "")}
    if os.environ.get("EWB_BROWSER_TOKEN"):
        headers["X-EWB-Token"] = os.environ["EWB_BROWSER_TOKEN"]
    request = urllib.request.Request("http://127.0.0.1:6081/open", data=json.dumps({"url": sys.argv[1]}).encode(), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(30):
        try:
            with opener.open(request, timeout=2) as response:
                if response.status == 204:
                    return
        except OSError:
            time.sleep(1)
    raise SystemExit("Shared browser unavailable. Open the viewer and retry; the host browser was not used.")


if __name__ == "__main__":
    main()
