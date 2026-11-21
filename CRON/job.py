from datetime import datetime, timezone


if __name__ == "__main__":
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"Cron job completed at {timestamp}")
