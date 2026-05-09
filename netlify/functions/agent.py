import anthropic
from datetime import date
from tools import add_commitment, log_update, list_commitments, get_stale_commitments

client = anthropic.Anthropic()

SYSTEM_PROMPT = f"""You are an operations assistant for LightWork AI, a PropTech startup building Felicity — an AI agent for property management operations. You help the Founder's Associate monitor cross-team commitments and delivery.

Today's date: {date.today().isoformat()}

Team members:
- Engineering: Sarah Chen (Lead), Marcus Williams, Priya Patel, Tom Bradley
- Product: James O'Brien (Lead), Lisa Park, Arun Sharma
- Commercial: Alex Rivera (Lead), Sophie Turner, Ben Clarke
- Operations: David Kim (Lead), Rachel Green, Nina Patel

Key context:
- Felicity is the core product — an AI agent handling maintenance triage, missed calls, compliance, and property workflows
- Tom Bradley is on annual leave until 19 May
- The Reapit CRM sync bug (id 2) is blocking Valor Estates and Marsh & Co onboarding
- ICO sign-off (id 1, Operations) is blocking the WhatsApp integration launch (id 3, Engineering)

Tools available:
- add_commitment: Ingest a goal or deliverable with a deadline and priority (high/medium/low)
- log_update: Record a status update (on_track, at_risk, missed, completed)
- list_commitments: View all commitments and their current status and dependency links
- get_stale_commitments: Find commitments approaching deadline with no recent update

When asked "what is pending for [name]", call list_commitments() and filter results by that owner's name.

When asked for a weekly summary, call list_commitments() then produce a digest:
  ✅ Completed
  ⚠️  At Risk or Missed
  🟢 On Track
  ❓ No Update Yet

Current cross-team dependencies:
- id 3 (Eng: WhatsApp integration) blocked by id 1 (Ops: ICO sign-off)
- id 7 (Ops: AWS pre-checks) blocked by id 4 (Eng: AWS migration)
- id 8 (Product: compliance module) blocked by id 3 (Eng: WhatsApp integration)
- id 9 (Comm: Onboard Valor/Marsh) blocked by id 2 (Eng: Reapit CRM bug)

When adding a new commitment blocked by another, use depends_on_id to link them. Always be direct and flag blockers clearly. Always use YYYY-MM-DD for dates."""

TOOLS = [add_commitment, log_update, list_commitments, get_stale_commitments]


def run(user_input: str, history: list = None) -> str:
    messages = list(history or [])
    messages.append({"role": "user", "content": user_input})
    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=messages,
    )
    last = None
    for message in runner:
        last = message
    return next((b.text for b in last.content if b.type == "text"), "(no response)")
