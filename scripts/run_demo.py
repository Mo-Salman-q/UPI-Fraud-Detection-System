"""
scripts/run_demo.py
-------------------
Local demo helper script.

Usage:
    python scripts/run_demo.py

Actions:
    1. Reads PORT from the environment (default: 8000).
    2. Detects the machine's LAN IP address.
    3. Prints clear URLs for testing on phone and laptop.
    4. Runs the FastAPI app via uvicorn on 0.0.0.0:<PORT>.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv(_repo_root / ".env")
except ImportError:
    pass


def get_lan_ip() -> str:
    """
    Detect the machine's primary LAN IP address on Wi-Fi or Ethernet.
    Uses UDP socket to external IP to determine the outbound network interface.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not send actual packets; determines outbound interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def print_banner(lan_ip: str, port: int) -> None:
    local_base = f"http://localhost:{port}"
    network_base = f"http://{lan_ip}:{port}"

    banner = f"""
======================================================================
                  SENTINEL AI — LOCAL DEMO RUNNER                    
======================================================================

  [Laptop URLs]
    - UPI Customer App  : {local_base}/upi/
    - Admin Console     : {local_base}/admin-ui/
    - API Documentation : {local_base}/docs
    - Health Endpoint   : {local_base}/health

  [Phone URLs (Connect phone to same Wi-Fi or Laptop Hotspot)]
    - UPI Customer App  : {network_base}/upi/
    - Admin Console     : {network_base}/admin-ui/

  [LAN Info]
    - Laptop LAN IP     : {lan_ip}
    - Port              : {port}

  [Troubleshooting Tips]
    1. Phone cannot open link?
       -> Make sure phone and laptop are on the SAME Wi-Fi network.
       -> If using Mobile Hotspot, disable "AP Isolation" / "Client Isolation".
    2. Windows Firewall:
       -> Click "Allow access" for Python on Private Networks.
       -> Or allow incoming TCP port {port} in Windows Defender Firewall.

======================================================================
Starting FastAPI server on 0.0.0.0:{port} ...
Press Ctrl+C to stop.
"""
    print(banner)


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    lan_ip = get_lan_ip()
    print_banner(lan_ip, port)

    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )


if __name__ == "__main__":
    main()
