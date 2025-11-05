# sec_rep.py
import requests
from prettytable import PrettyTable

SERVER_URL = "http://127.0.0.1:5000"

def fetch_and_display_audit():
    try:
        r = requests.get(f"{SERVER_URL}/status"); r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"❌ Could not reach server: {e}")
        return

    print("\n================= PQC STATUS =================")
    print("SYSTEM:", data["system_status"])
    print("KEY ID:", data["server_key_id"])
    print("AGENTS:", data["registered_agents"])
    stats = data["stats"]
    print("STATS :", stats)
    print("----------------------------------------------")

    tbl = PrettyTable(["Metric", "Value"])
    for k, v in stats.items():
        tbl.add_row([k, v])
    print(tbl)
    print("==============================================")

if __name__ == "__main__":
    fetch_and_display_audit()
