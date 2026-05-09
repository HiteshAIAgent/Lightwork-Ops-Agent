const Anthropic = require('@anthropic-ai/sdk');
const { Pool } = require('pg');

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

// ─── Database ─────────────────────────────────────────────────────────────────

let _pool = null;
function pool() {
  if (!_pool) {
    _pool = new Pool({
      connectionString: process.env.DATABASE_URL,
      ssl: { rejectUnauthorized: false },
      max: 1,
    });
  }
  return _pool;
}

async function query(sql, params = []) {
  const client = await pool().connect();
  try {
    const result = await client.query(sql, params);
    return result.rows;
  } finally {
    client.release();
  }
}

async function queryOne(sql, params = []) {
  const rows = await query(sql, params);
  return rows[0] || null;
}

async function exec(sql, params = []) {
  const client = await pool().connect();
  try {
    await client.query(sql, params);
  } finally {
    client.release();
  }
}

let dbInitialized = false;

async function initDb() {
  if (dbInitialized) return;
  for (const stmt of [
    `CREATE TABLE IF NOT EXISTS commitments (
      id SERIAL PRIMARY KEY,
      team TEXT NOT NULL,
      description TEXT NOT NULL,
      deadline TEXT NOT NULL,
      owner TEXT,
      priority TEXT NOT NULL DEFAULT 'medium',
      depends_on INTEGER REFERENCES commitments(id),
      created_at TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
    )`,
    `CREATE TABLE IF NOT EXISTS updates (
      id SERIAL PRIMARY KEY,
      commitment_id INTEGER NOT NULL REFERENCES commitments(id),
      status TEXT NOT NULL CHECK(status IN ('on_track','at_risk','missed','completed')),
      notes TEXT,
      updated_at TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
    )`,
    `CREATE TABLE IF NOT EXISTS alerts (
      id SERIAL PRIMARY KEY,
      from_role TEXT NOT NULL,
      to_team TEXT NOT NULL,
      message TEXT NOT NULL,
      resolved INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
    )`,
    `CREATE TABLE IF NOT EXISTS alert_responses (
      id SERIAL PRIMARY KEY,
      alert_id INTEGER NOT NULL REFERENCES alerts(id),
      response TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT TO_CHAR(NOW(),'YYYY-MM-DD HH24:MI:SS')
    )`,
    `ALTER TABLE commitments ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium'`,
    `ALTER TABLE commitments ADD COLUMN IF NOT EXISTS depends_on INTEGER REFERENCES commitments(id)`,
  ]) {
    await exec(stmt);
  }
  dbInitialized = true;
}

async function addCommitment(team, description, deadline, owner = null, priority = 'medium', dependsOn = null) {
  const row = await queryOne(
    'INSERT INTO commitments (team, description, deadline, owner, priority, depends_on) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id',
    [team, description, deadline, owner, priority, dependsOn]
  );
  return { id: row.id, team, description, deadline, owner, priority, depends_on: dependsOn };
}

async function logUpdate(commitmentId, status, notes = null) {
  const existing = await queryOne('SELECT id FROM commitments WHERE id = $1', [commitmentId]);
  if (!existing) return { error: `No commitment with id ${commitmentId}` };
  await exec('INSERT INTO updates (commitment_id, status, notes) VALUES ($1,$2,$3)', [commitmentId, status, notes]);
  return { ok: true, commitment_id: commitmentId, status };
}

async function getCommitments(team = null, status = null) {
  let q = `
    SELECT
      c.id, c.team, c.description, c.deadline, c.owner, c.priority, c.depends_on,
      dep.description AS dep_description,
      dep.team AS dep_team,
      dep.owner AS dep_owner,
      COALESCE(dep_u.status, 'no_update') AS dep_status,
      COALESCE(u.status, 'no_update') AS latest_status,
      u.notes AS latest_notes,
      u.updated_at AS last_updated
    FROM commitments c
    LEFT JOIN (
      SELECT commitment_id, status, notes, updated_at
      FROM updates
      WHERE id IN (SELECT MAX(id) FROM updates GROUP BY commitment_id)
    ) u ON c.id = u.commitment_id
    LEFT JOIN commitments dep ON c.depends_on = dep.id
    LEFT JOIN (
      SELECT commitment_id, status
      FROM updates
      WHERE id IN (SELECT MAX(id) FROM updates GROUP BY commitment_id)
    ) dep_u ON dep.id = dep_u.commitment_id
  `;
  const params = [];
  const conditions = [];
  if (team) { conditions.push(`c.team = $${params.length + 1}`); params.push(team); }
  if (status) {
    if (status === 'no_update') {
      conditions.push('u.status IS NULL');
    } else {
      conditions.push(`COALESCE(u.status,'no_update') = $${params.length + 1}`);
      params.push(status);
    }
  }
  if (conditions.length) q += ' WHERE ' + conditions.join(' AND ');
  q += ' ORDER BY c.deadline ASC';
  return query(q, params);
}

async function getStaleCommitments(daysAhead = 7) {
  const today = new Date().toISOString().split('T')[0];
  const cutoff = new Date(Date.now() + daysAhead * 86400000).toISOString().split('T')[0];
  const staleSince = new Date(Date.now() - 7 * 86400000).toISOString().split('T')[0];
  return query(`
    SELECT c.id, c.team, c.description, c.deadline, c.owner, c.priority,
      COALESCE(u.status, 'no_update') AS latest_status,
      u.updated_at AS last_updated,
      CASE WHEN c.deadline < $1 THEN 1 ELSE 0 END AS overdue
    FROM commitments c
    LEFT JOIN (
      SELECT commitment_id, status, updated_at
      FROM updates
      WHERE id IN (SELECT MAX(id) FROM updates GROUP BY commitment_id)
    ) u ON c.id = u.commitment_id
    WHERE c.deadline <= $2
      AND COALESCE(u.status,'no_update') NOT IN ('completed','missed')
      AND (u.updated_at IS NULL OR u.updated_at < $3)
    ORDER BY c.deadline ASC
  `, [today, cutoff, staleSince]);
}

async function updateCommitment(id, { description, deadline, owner, priority } = {}) {
  const existing = await queryOne('SELECT id FROM commitments WHERE id = $1', [id]);
  if (!existing) return { error: `No commitment with id ${id}` };
  const fields = {};
  if (description != null) fields.description = description;
  if (deadline != null) fields.deadline = deadline;
  if (owner != null) fields.owner = owner;
  if (priority != null) fields.priority = priority;
  if (Object.keys(fields).length) {
    const keys = Object.keys(fields);
    const sets = keys.map((k, i) => `${k} = $${i + 1}`).join(', ');
    await exec(
      `UPDATE commitments SET ${sets} WHERE id = $${keys.length + 1}`,
      [...Object.values(fields), id]
    );
  }
  return { ok: true, id };
}

async function createAlert(fromRole, toTeam, message) {
  const row = await queryOne(
    'INSERT INTO alerts (from_role, to_team, message) VALUES ($1,$2,$3) RETURNING id',
    [fromRole, toTeam, message]
  );
  return { id: row.id, from_role: fromRole, to_team: toTeam, message };
}

async function getAlerts(team = null, includeResolved = false) {
  let q = `
    SELECT a.id, a.from_role, a.to_team, a.message, a.resolved, a.created_at,
           r.response, r.created_at AS responded_at
    FROM alerts a
    LEFT JOIN alert_responses r ON a.id = r.alert_id
  `;
  const params = [];
  const conditions = [];
  if (team) { conditions.push(`a.to_team = $${params.length + 1}`); params.push(team); }
  if (!includeResolved) conditions.push('a.resolved = 0');
  if (conditions.length) q += ' WHERE ' + conditions.join(' AND ');
  q += ' ORDER BY a.created_at DESC';
  return query(q, params);
}

async function respondToAlert(alertId, response) {
  await exec('INSERT INTO alert_responses (alert_id, response) VALUES ($1,$2)', [alertId, response]);
  await exec('UPDATE alerts SET resolved = 1 WHERE id = $1', [alertId]);
  return { ok: true, alert_id: alertId };
}

// ─── Agent ────────────────────────────────────────────────────────────────────

function getSystemPrompt() {
  const today = new Date().toISOString().split('T')[0];
  return `You are an operations assistant for LightWork AI, a PropTech startup building Felicity — an AI agent for property management operations. You help the Founder's Associate monitor cross-team commitments and delivery.

Today's date: ${today}

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

When adding a new commitment blocked by another, use depends_on_id to link them. Always be direct and flag blockers clearly. Always use YYYY-MM-DD for dates.`;
}

const AGENT_TOOLS = [
  {
    name: 'add_commitment',
    description: 'Add a new team commitment or deliverable with a deadline.',
    input_schema: {
      type: 'object',
      properties: {
        team: { type: 'string', description: 'Team name — Engineering, Commercial, Product, or Operations.' },
        description: { type: 'string', description: 'What the team is committing to deliver.' },
        deadline: { type: 'string', description: 'Deadline in YYYY-MM-DD format.' },
        owner: { type: 'string', description: 'Optional name of the person responsible.' },
        priority: { type: 'string', enum: ['high', 'medium', 'low'], description: 'Priority level.' },
        depends_on_id: { type: 'integer', description: 'Optional ID of another commitment this one is blocked by. Use 0 for none.' },
      },
      required: ['team', 'description', 'deadline'],
    },
  },
  {
    name: 'log_update',
    description: 'Log a status update for a commitment.',
    input_schema: {
      type: 'object',
      properties: {
        commitment_id: { type: 'integer', description: 'ID of the commitment to update.' },
        status: { type: 'string', enum: ['on_track', 'at_risk', 'missed', 'completed'], description: 'Current status.' },
        notes: { type: 'string', description: 'Optional context about the current status.' },
      },
      required: ['commitment_id', 'status'],
    },
  },
  {
    name: 'list_commitments',
    description: 'List commitments with their latest status and dependency links.',
    input_schema: {
      type: 'object',
      properties: {
        team: { type: 'string', description: 'Filter by team name. Leave empty for all teams.' },
        status: { type: 'string', description: 'Filter by status. Leave empty for all.' },
      },
    },
  },
  {
    name: 'get_stale_commitments',
    description: 'Find commitments approaching their deadline with no update logged in the past 7 days.',
    input_schema: {
      type: 'object',
      properties: {
        days_ahead: { type: 'integer', description: 'How many days ahead to look for approaching deadlines. Default is 7.' },
      },
    },
  },
];

async function callTool(name, input) {
  switch (name) {
    case 'add_commitment':
      return addCommitment(
        input.team, input.description, input.deadline,
        input.owner || null, input.priority || 'medium',
        input.depends_on_id ? parseInt(input.depends_on_id) : null
      );
    case 'log_update':
      return logUpdate(parseInt(input.commitment_id), input.status, input.notes || null);
    case 'list_commitments':
      return getCommitments(input.team || null, input.status || null);
    case 'get_stale_commitments':
      return getStaleCommitments(input.days_ahead ? parseInt(input.days_ahead) : 7);
    default:
      return { error: `Unknown tool: ${name}` };
  }
}

async function runAgent(userInput, history = []) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY is not set');
  const client = new Anthropic({ apiKey });
  const messages = [...history, { role: 'user', content: userInput }];

  while (true) {
    const response = await client.messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 4096,
      system: getSystemPrompt(),
      tools: AGENT_TOOLS,
      messages,
    });

    if (response.stop_reason !== 'tool_use') {
      const text = response.content.find(b => b.type === 'text');
      return text ? text.text : '(no response)';
    }

    messages.push({ role: 'assistant', content: response.content });
    const toolResults = [];
    for (const block of response.content) {
      if (block.type === 'tool_use') {
        const result = await callTool(block.name, block.input);
        toolResults.push({
          type: 'tool_result',
          tool_use_id: block.id,
          content: JSON.stringify(result),
        });
      }
    }
    messages.push({ role: 'user', content: toolResults });
  }
}

// ─── Routes ───────────────────────────────────────────────────────────────────

async function route(method, path, body, qs) {
  if (method === 'GET' && path === '/commitments')
    return getCommitments(qs.team || null, qs.status || null);

  if (method === 'GET' && path === '/alerts')
    return getAlerts(qs.team || null, false);

  if (method === 'POST' && path === '/chat')
    return { response: await runAgent(body.message || '', body.history || []) };

  if (method === 'POST' && path === '/commitments') {
    const result = await addCommitment(
      body.team, body.description, body.deadline,
      body.owner || null, body.priority || 'medium',
      body.depends_on || null
    );
    if (body.notes) await logUpdate(result.id, 'on_track', body.notes);
    return result;
  }

  if (method === 'PATCH' && path.startsWith('/commitments/')) {
    const id = parseInt(path.split('/').pop());
    const result = {};
    if (body.description || body.deadline || body.owner != null || body.priority)
      result.commitment = await updateCommitment(id, body);
    if (body.status) {
      result.update = await logUpdate(id, body.status, body.notes || null);
    } else if (body.notes) {
      const all = await getCommitments();
      const c = all.find(x => x.id === id);
      if (c) {
        const st = c.latest_status !== 'no_update' ? c.latest_status : 'on_track';
        result.update = await logUpdate(id, st, body.notes);
      }
    }
    return result;
  }

  if (method === 'POST' && path === '/alerts')
    return createAlert(body.from_role, body.to_team, body.message);

  if (method === 'POST' && path.endsWith('/respond')) {
    const alertId = parseInt(path.split('/').slice(-2)[0]);
    return respondToAlert(alertId, body.response);
  }

  return { error: 'not found' };
}

// ─── Handler ──────────────────────────────────────────────────────────────────

exports.handler = async (event) => {
  const method = event.httpMethod || 'GET';
  const path = (event.path || '/').replace(/\/$/, '') || '/';
  const qs = event.queryStringParameters || {};

  let body = {};
  if (event.body) {
    try { body = JSON.parse(event.body); } catch (_) {}
  }

  if (method === 'OPTIONS')
    return { statusCode: 200, headers: CORS, body: '' };

  try {
    await initDb();
    const result = await route(method, path, body, qs);
    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', ...CORS },
      body: JSON.stringify(result),
    };
  } catch (e) {
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json', ...CORS },
      body: JSON.stringify({ error: e.message }),
    };
  }
};
