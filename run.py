"""Starts the Acme ERP (target system) and the AI Employee console."""
import subprocess
import sys
import time
import urllib.request

from aiemployee import config, ui_server

erp = subprocess.Popen([sys.executable, "erp/server.py"])
for _ in range(50):
    try:
        urllib.request.urlopen(config.ERP_URL + "/login", timeout=1)
        break
    except Exception:
        time.sleep(0.1)
try:
    ui_server.serve()
finally:
    erp.terminate()
