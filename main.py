import db
from agent import run

HELP = """
Commands (natural language — just type what you want):
  "Engineering needs to ship the integration by 2025-04-14"
  "Log that commitment 1 is at risk — blocked on API access"
  "Give me the weekly summary"
  "Check for stale commitments"
  "List all at-risk commitments"
  "Mark commitment 3 as completed"
"""


def main():
    db.init_db()
    print("LightWork Ops Agent  (type 'help' or 'quit')\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break
        if user_input.lower() == "help":
            print(HELP)
            continue

        response = run(user_input)
        print(f"\nAgent: {response}\n")


if __name__ == "__main__":
    main()
