require('dotenv').config();
const express = require('express');
const Database = require('better-sqlite3');
const cors = require('cors');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const API_KEY = process.env.API_KEY || 'somnus-key-2024';

const dbDir = path.join(__dirname, 'database');
if (!fs.existsSync(dbDir)) fs.mkdirSync(dbDir);

const db = new Database(path.join(dbDir, 'registros.db'));

db.exec(`
  CREATE TABLE IF NOT EXISTS registros (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    data_atendimento  TEXT    NOT NULL,
    nome_paciente     TEXT    NOT NULL,
    prontuario        TEXT    NOT NULL,
    tuss              TEXT    NOT NULL,
    instituicao       TEXT    NOT NULL,
    anestesista       TEXT    NOT NULL,
    cirurgiao         TEXT    NOT NULL,
    especialidade     TEXT    NOT NULL,
    valor             REAL,
    convenio          TEXT,
    status_pagamento  TEXT    NOT NULL DEFAULT 'Pendente',
    observacoes       TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
  );
  CREATE INDEX IF NOT EXISTS idx_data        ON registros(data_atendimento);
  CREATE INDEX IF NOT EXISTS idx_anestesista ON registros(anestesista);
  CREATE INDEX IF NOT EXISTS idx_instituicao ON registros(instituicao);
`);

app.use(cors({ origin: '*' }));
app.use(express.json());
app.use(express.static(path.join(__dirname)));

/* ── auth middleware ─────────────────────────────────── */
function auth(req, res, next) {
  const key = req.headers['x-api-key'] || req.query.api_key;
  if (key !== API_KEY) return res.status(401).json({ error: 'Não autorizado' });
  next();
}

/* ── POST /api/auth/verify ───────────────────────────── */
app.post('/api/auth/verify', (req, res) => {
  res.json({ valid: req.body.key === API_KEY });
});

/* ── POST /api/registros (público – formulário) ─────── */
app.post('/api/registros', (req, res) => {
  const required = [
    'data_atendimento', 'nome_paciente', 'prontuario', 'tuss',
    'instituicao', 'anestesista', 'cirurgiao', 'especialidade',
  ];
  for (const f of required) {
    if (!req.body[f]) return res.status(400).json({ error: `Campo obrigatório ausente: ${f}` });
  }

  const {
    data_atendimento, nome_paciente, prontuario, tuss,
    instituicao, anestesista, cirurgiao, especialidade,
    valor, convenio, status_pagamento, observacoes,
  } = req.body;

  const result = db.prepare(`
    INSERT INTO registros
      (data_atendimento, nome_paciente, prontuario, tuss,
       instituicao, anestesista, cirurgiao, especialidade,
       valor, convenio, status_pagamento, observacoes)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
  `).run(
    data_atendimento, nome_paciente, prontuario, tuss,
    instituicao, anestesista, cirurgiao, especialidade,
    valor ? Number(valor) : null,
    convenio || null,
    status_pagamento || 'Pendente',
    observacoes || null,
  );

  res.status(201).json({ id: result.lastInsertRowid, message: 'Registro salvo com sucesso' });
});

/* ── GET /api/registros (privado) ───────────────────── */
app.get('/api/registros', auth, (req, res) => {
  const { anestesista, instituicao, especialidade, status_pagamento, from, to, q, page = 1, limit = 50 } = req.query;

  const where = [];
  const p = [];

  if (anestesista)      { where.push('anestesista = ?');      p.push(anestesista); }
  if (instituicao)      { where.push('instituicao = ?');      p.push(instituicao); }
  if (especialidade)    { where.push('especialidade = ?');    p.push(especialidade); }
  if (status_pagamento) { where.push('status_pagamento = ?'); p.push(status_pagamento); }
  if (from)             { where.push('data_atendimento >= ?');p.push(from); }
  if (to)               { where.push('data_atendimento <= ?');p.push(to); }
  if (q)                { where.push('(nome_paciente LIKE ? OR prontuario LIKE ? OR tuss LIKE ?)'); p.push(`%${q}%`, `%${q}%`, `%${q}%`); }

  const clause = where.length ? 'WHERE ' + where.join(' AND ') : '';
  const offset = (Number(page) - 1) * Number(limit);

  const data  = db.prepare(`SELECT * FROM registros ${clause} ORDER BY data_atendimento DESC, id DESC LIMIT ? OFFSET ?`).all(...p, Number(limit), offset);
  const total = db.prepare(`SELECT COUNT(*) as c FROM registros ${clause}`).get(...p).c;

  res.json({ data, total, page: Number(page), limit: Number(limit), pages: Math.ceil(total / Number(limit)) });
});

/* ── GET /api/dashboard/stats (privado) ─────────────── */
app.get('/api/dashboard/stats', auth, (req, res) => {
  const { from, to } = req.query;
  const where = [];
  const p = [];

  if (from) { where.push('data_atendimento >= ?'); p.push(from); }
  if (to)   { where.push('data_atendimento <= ?'); p.push(to); }

  const clause = where.length ? 'WHERE ' + where.join(' AND ') : '';

  // Current month baseline for KPI delta
  const thisMonth = new Date().toISOString().slice(0, 7);
  const lastMonth = new Date(new Date().setMonth(new Date().getMonth() - 1)).toISOString().slice(0, 7);

  res.json({
    total:          db.prepare(`SELECT COUNT(*) as v FROM registros ${clause}`).get(...p).v,
    totalValor:     db.prepare(`SELECT COALESCE(SUM(valor),0) as v FROM registros ${clause}`).get(...p).v,
    pendente:       db.prepare(`SELECT COALESCE(SUM(valor),0) as v FROM registros ${clause ? clause + " AND" : "WHERE"} status_pagamento = 'Pendente'`).get(...p, ).v,
    estesMes:       db.prepare(`SELECT COUNT(*) as v FROM registros WHERE strftime('%Y-%m', data_atendimento) = ?`).get(thisMonth).v,
    byAnestesista:  db.prepare(`SELECT anestesista as label, COUNT(*) as count, COALESCE(SUM(valor),0) as valor FROM registros ${clause} GROUP BY anestesista ORDER BY count DESC`).all(...p),
    byEspecialidade:db.prepare(`SELECT especialidade as label, COUNT(*) as count FROM registros ${clause} GROUP BY especialidade ORDER BY count DESC`).all(...p),
    byInstituicao:  db.prepare(`SELECT instituicao as label, COUNT(*) as count FROM registros ${clause} GROUP BY instituicao ORDER BY count DESC LIMIT 15`).all(...p),
    byMonth:        db.prepare(`SELECT strftime('%Y-%m', data_atendimento) as label, COUNT(*) as count, COALESCE(SUM(valor),0) as valor FROM registros ${clause} GROUP BY label ORDER BY label`).all(...p),
    byStatus:       db.prepare(`SELECT status_pagamento as label, COUNT(*) as count, COALESCE(SUM(valor),0) as valor FROM registros ${clause} GROUP BY status_pagamento`).all(...p),
  });
});

/* ── PATCH /api/registros/:id (privado) ─────────────── */
app.patch('/api/registros/:id', auth, (req, res) => {
  const allowed = ['valor', 'convenio', 'status_pagamento', 'observacoes'];
  const sets = [];
  const p = [];

  for (const k of allowed) {
    if (req.body[k] !== undefined) {
      sets.push(`${k} = ?`);
      p.push(req.body[k] === '' ? null : req.body[k]);
    }
  }
  if (!sets.length) return res.status(400).json({ error: 'Nenhum campo informado' });

  p.push(req.params.id);
  db.prepare(`UPDATE registros SET ${sets.join(', ')} WHERE id = ?`).run(...p);
  res.json({ message: 'Atualizado com sucesso' });
});

/* ── DELETE /api/registros/:id (privado) ────────────── */
app.delete('/api/registros/:id', auth, (req, res) => {
  db.prepare('DELETE FROM registros WHERE id = ?').run(req.params.id);
  res.json({ message: 'Registro excluído' });
});

app.listen(PORT, () => {
  console.log(`✓  Somnus API  →  http://localhost:${PORT}`);
  console.log(`✓  Formulário  →  http://localhost:${PORT}/index.html`);
  console.log(`✓  Dashboard   →  http://localhost:${PORT}/dashboard.html`);
});
