import json
import os

QUEUE_FILE = "pending_queue.json"

def clean_ghosts():
    if not os.path.exists(QUEUE_FILE):
        print(f"File {QUEUE_FILE} not found.")
        return

    with open(QUEUE_FILE, "r") as f:
        queue = json.load(f)

    original_count = len(queue)
    # Remove US500, UNKNOWN, SPX, and SPX500 entries as requested
    ghost_symbols = ["US500", "UNKNOWN", "SPX", "SPX500"]
    cleaned_queue = [item for item in queue if item.get('symbol') not in ghost_symbols]
    
    removed_count = original_count - len(cleaned_queue)
    
    with open(QUEUE_FILE, "w") as f:
        json.dump(cleaned_queue, f, indent=2)
    
    print(f"Successfully removed {removed_count} US500 ghost entries.")
    print(f"Remaining entries: {len(cleaned_queue)}")

if __name__ == "__main__":
    clean_ghosts()
