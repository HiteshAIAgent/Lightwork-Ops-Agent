import db

def seed():
    with db._conn() as conn:
        if db.USE_POSTGRES:
            db._exec(conn, "TRUNCATE updates, alert_responses, alerts, commitments RESTART IDENTITY CASCADE")
        else:
            conn.execute("DELETE FROM updates")
            conn.execute("DELETE FROM commitments")
            try:
                conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('commitments', 'updates')")
            except Exception:
                pass

    db.init_db()

    # Insert blocking/upstream tasks FIRST so their IDs are stable for depends_on references
    # id 1  — Operations: ICO sign-off (blocks Engineering WhatsApp)
    # id 2  — Engineering: Reapit CRM bug (blocks Commercial onboardings)
    # id 3  — Engineering: WhatsApp integration (depends on id 1)
    # id 4  — Engineering: AWS migration (blocks Operations pre-checks)
    # id 5  — Commercial: Rightmove RFP
    # id 6  — Product: Onboarding redesign
    # id 7  — Operations: AWS pre-checks (depends on id 4)
    # id 8  — Product: Compliance module (depends on id 3)
    # id 9  — Commercial: Onboard Valor & Marsh (depends on id 2)
    # id 10 — Product: Escalation logic v2
    # id 11 — Commercial: Greenfield pilot
    # id 12 — Commercial: Wright Letting renewal
    # id 13 — Engineering: Voice transcription
    # id 14 — Operations: Board pack

    rows = [
        # team, description, deadline, owner, priority, depends_on
        ("Operations",  "Obtain ICO sign-off for WhatsApp data processing channel",               "2026-05-11", "Nina Patel",      "high",   None),
        ("Engineering", "Fix Reapit CRM sync bug causing duplicate work orders",                  "2026-05-12", "Priya Patel",     "high",   None),
        ("Engineering", "Ship Felicity WhatsApp integration for maintenance triage",              "2026-05-13", "Marcus Williams", "high",   1),
        ("Engineering", "Migrate staging environment to new AWS region (EU-West-2)",              "2026-05-16", "Tom Bradley",     "high",   None),
        ("Commercial",  "Submit response to Rightmove partnership RFP",                           "2026-05-14", "Alex Rivera",     "high",   None),
        ("Product",     "Complete onboarding flow redesign from Wright Letting feedback",         "2026-05-15", "Arun Sharma",     "high",   None),
        ("Operations",  "Complete AWS migration pre-checks for ISO 27001 audit",                  "2026-05-15", "David Kim",       "high",   4),
        ("Product",     "Deliver Felicity compliance module (gas safety renewals) for beta",      "2026-05-19", "Lisa Park",       "high",   3),
        ("Commercial",  "Onboard Valor Estates and Marsh & Co onto Felicity",                     "2026-05-20", "Ben Clarke",      "high",   2),
        ("Product",     "Define and document Felicity escalation logic v2",                       "2026-05-21", "James O'Brien",   "high",   None),
        ("Commercial",  "Close pilot agreement with Greenfield Property Management",              "2026-05-23", "Sophie Turner",   "high",   None),
        ("Commercial",  "Renew contract with Wright Letting (expires 31 May)",                    "2026-05-26", "Sophie Turner",   "medium", None),
        ("Engineering", "Build Felicity voice transcription for missed call handling",            "2026-05-28", "Tom Bradley",     "medium", None),
        ("Operations",  "Prepare board pack for June investor update",                            "2026-05-30", "David Kim",       "medium", None),
    ]

    ids = []
    for team, desc, deadline, owner, priority, dep in rows:
        r = db.add_commitment(team, desc, deadline, owner, priority, dep)
        ids.append(r['id'])

    updates = [
        (ids[0],  "at_risk",   "Deadline in 2 days. Legal paperwork submitted but DPO review still pending. Engineering cannot launch WhatsApp channel without this sign-off."),
        (ids[1],  "at_risk",   "Bug identified: duplicate work orders being created on Reapit sync. Two Commercial onboardings (Valor Estates, Marsh & Co) are frozen until resolved. Priya investigating root cause."),
        (ids[2],  "at_risk",   "Development complete but blocked on ICO sign-off from Operations (Nina Patel). Cannot go live until data processing approval received."),
        (ids[3],  "at_risk",   "Operations flagged this late — required before ISO 27001 audit window. Tom Bradley has started but timeline is tight. No contingency plan yet."),
        (ids[4],  "at_risk",   "No one was assigned until today. Alex Rivera picking up. Submission deadline is 14 May — very limited time to write a strong response."),
        (ids[5],  "at_risk",   "Design signed off by Wright Letting. Dev resource not yet allocated — James O'Brien to assign engineer by EOD today or deadline will slip."),
        (ids[6],  "at_risk",   "Deadline is 15 May but depends on Engineering finishing AWS migration (deadline 16 May). Deadlines are inverted — David Kim flagged to Sarah Chen."),
        (ids[7],  "at_risk",   "Blocked by WhatsApp integration not yet live. Beta clients (3 letting agencies) are waiting. Every day of delay pushes back gas safety renewal workflows."),
        (ids[8],  "at_risk",   "Both Valor Estates and Marsh & Co are chasing daily. Onboarding frozen due to Reapit CRM sync bug. Risk of clients churning before they go live."),
        (ids[9],  "at_risk",   "Commercial team is receiving complaints about Felicity over-escalating to human agents. Urgent — James O'Brien to lead. Affects NPS scores."),
        (ids[10], "at_risk",   "Legal review extended — counterpart redlined 3 clauses (liability cap, data processing, SLA). Commercial and legal working through responses. Target close by 23 May."),
        (ids[11], "at_risk",   "Renewal call not yet booked. Deal expires 31 May. Sophie Turner to reach out this week. Account is at mild risk — Wright Letting gave critical UX feedback last month."),
        (ids[12], "at_risk",   "Engineer (Tom Bradley) on annual leave until 19 May. Work scoped and ready to begin on return. May need to de-prioritise AWS migration work to hit 28 May deadline."),
        (ids[13], "at_risk",   "No owner assigned. Last board pack was criticised for being thin on metrics. David Kim to own — needs input from Commercial (pipeline) and Product (product usage data)."),
    ]

    for cid, status, notes in updates:
        db.log_update(cid, status, notes)

    print(f"Seeded {len(rows)} commitments.")

if __name__ == "__main__":
    seed()
