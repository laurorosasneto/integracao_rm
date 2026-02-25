from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------
# IMPORTANTE:
# Este core/db.py fica em: <raiz>/src/core/db.py
# Então para chegar na raiz do projeto: parents[2]
# (core -> src -> raiz)
# Isso garante que TODOS usem o mesmo banco: <raiz>/db/app.db
# --------------------------------------------------------------------
DB_PATH = Path(__file__).resolve().parents[2] / "db" / "app.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, coltype: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


def init_db() -> None:
    conn = _connect()
    try:
        # Preferências locais do app (ui_common.ConfigCard)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

        # Plataformas
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platforms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                token TEXT NOT NULL,
                coligadas TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

        # Config RM
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rm_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                host TEXT,
                database_name TEXT,
                username TEXT,
                password TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

        # Consultas RM
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rm_queries (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                coligadas TEXT,
                periodos TEXT,
                cursos TEXT,
                turmas TEXT,
                salas TEXT,
                alunos TEXT,
                professores TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        _ensure_column(conn, "rm_queries", "salas", "TEXT")
        _ensure_column(conn, "rm_queries", "alunos", "TEXT")
        _ensure_column(conn, "rm_queries", "professores", "TEXT")

        # Salas Modelo
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS salas_modelo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                moodle_id TEXT NOT NULL,
                extra_filter TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(platform_id) REFERENCES platforms(id) ON DELETE CASCADE
            )
            """
        )
        # compatibilidade: se a tabela já existia sem created_at
        _ensure_column(conn, "salas_modelo", "created_at", "TEXT")
        _ensure_column(conn, "salas_modelo", "updated_at", "TEXT")

        conn.commit()
    finally:
        conn.close()


# --------------------------
# Config (ui_common)
# --------------------------
def get_config(key: str) -> str:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute("SELECT value FROM config WHERE key = ?", (str(key),))
        row = cur.fetchone()
        return (row[0] or "") if row else ""
    finally:
        conn.close()


def set_config(key: str, value: str) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO config (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=datetime('now')
            """,
            (str(key), str(value)),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------
# Platforms (UI: PlatformsTab / InsercaoPessoasTab / combos)
# --------------------------
def list_platforms() -> List[Tuple[int, str, str, str, str]]:
    """
    Retorna: [(id, name, url, token, coligadas_csv), ...]
    Usado pela aba Plataformas.
    """
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT id, name, url, token, coligadas FROM platforms ORDER BY id ASC"
        )
        out: List[Tuple[int, str, str, str, str]] = []
        for row in cur.fetchall():
            out.append((int(row[0]), row[1] or "", row[2] or "", row[3] or "", row[4] or ""))
        return out
    finally:
        conn.close()


def list_platforms_for_select() -> List[Tuple[int, str]]:
    """
    Retorna: [(id, name), ...]
    Usado pelos combos (Salas Modelo, Estrutura).
    """
    init_db()
    conn = _connect()
    try:
        cur = conn.execute("SELECT id, name FROM platforms ORDER BY name COLLATE NOCASE ASC")
        return [(int(r[0]), r[1] or "") for r in cur.fetchall()]
    finally:
        conn.close()


def create_platform(name: str, url: str, token: str, coligadas: str) -> int:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO platforms (name, url, token, coligadas, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (name, url, token, coligadas or ""),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def update_platform(platform_id: int, name: str, url: str, token: str, coligadas: str) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE platforms
               SET name = ?,
                   url = ?,
                   token = ?,
                   coligadas = ?,
                   updated_at = datetime('now')
             WHERE id = ?
            """,
            (name, url, token, coligadas or "", int(platform_id)),
        )
        conn.commit()
    finally:
        conn.close()


def delete_platform(platform_id: int) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute("DELETE FROM platforms WHERE id = ?", (int(platform_id),))
        conn.commit()
    finally:
        conn.close()


def get_platform_coligadas(platform_id: int) -> str:
    """
    Retorna o CSV de coligadas da plataforma.
    Usado na aba Estrutura para filtrar períodos.
    """
    init_db()
    conn = _connect()
    try:
        cur = conn.execute("SELECT coligadas FROM platforms WHERE id = ?", (int(platform_id),))
        row = cur.fetchone()
        return (row[0] or "") if row else ""
    finally:
        conn.close()


def get_platforms() -> List[Dict[str, Any]]:
    """
    Retorna lista de dicts.
    Usado em ui_incercao_pessoas_tab.py (InsercaoPessoasTab).
    """
    rows = list_platforms()
    out: List[Dict[str, Any]] = []
    for pid, name, url, token, coligadas in rows:
        out.append(
            {
                "id": pid,
                "name": name,
                "url": url,
                "token": token,
                "coligadas": coligadas or "",
            }
        )
    return out


# --------------------------
# RM Config
# --------------------------
def get_rm_config() -> Optional[Tuple[str, str, str, str]]:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT host, database_name, username, password FROM rm_config WHERE id = 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        return (row[0] or "", row[1] or "", row[2] or "", row[3] or "")
    finally:
        conn.close()


def set_rm_config(host: str, database_name: str, username: str, password: str) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO rm_config (id, host, database_name, username, password, updated_at)
            VALUES (1, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                host=excluded.host,
                database_name=excluded.database_name,
                username=excluded.username,
                password=excluded.password,
                updated_at=datetime('now')
            """,
            (host, database_name, username, password),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------
# RM Queries
# --------------------------
def get_rm_queries() -> Optional[Dict[str, str]]:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT coligadas, periodos, cursos, turmas, salas, alunos, professores
              FROM rm_queries
             WHERE id = 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None

        keys = ["coligadas", "periodos", "cursos", "turmas", "salas", "alunos", "professores"]
        data = dict(zip(keys, row))
        return {k: (data.get(k) or "") for k in keys}
    finally:
        conn.close()


def set_rm_queries(values: Dict[str, str]) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO rm_queries (
                id, coligadas, periodos, cursos, turmas, salas, alunos, professores, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                coligadas=excluded.coligadas,
                periodos=excluded.periodos,
                cursos=excluded.cursos,
                turmas=excluded.turmas,
                salas=excluded.salas,
                alunos=excluded.alunos,
                professores=excluded.professores,
                updated_at=datetime('now')
            """,
            (
                values.get("coligadas", "") or "",
                values.get("periodos", "") or "",
                values.get("cursos", "") or "",
                values.get("turmas", "") or "",
                values.get("salas", "") or "",
                values.get("alunos", "") or "",
                values.get("professores", "") or "",
            ),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------
# Salas Modelo
# --------------------------
def list_salas_modelo() -> List[Tuple[int, str, int, str, str, str, str, str]]:
    """
    Retorna:
    (id, created_at, platform_id, platform_name, name, moodle_id, extra_filter, updated_at)
    Exatamente como a UI espera.
    """
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT
                sm.id,
                COALESCE(sm.created_at, '') AS created_at,
                sm.platform_id,
                COALESCE(p.name, '') AS platform_name,
                sm.name,
                sm.moodle_id,
                COALESCE(sm.extra_filter, '') AS extra_filter,
                COALESCE(sm.updated_at, '') AS updated_at
            FROM salas_modelo sm
            LEFT JOIN platforms p ON p.id = sm.platform_id
            ORDER BY sm.id ASC
            """
        )
        out: List[Tuple[int, str, int, str, str, str, str, str]] = []
        for r in cur.fetchall():
            out.append(
                (
                    int(r[0]),
                    r[1] or "",
                    int(r[2]),
                    r[3] or "",
                    r[4] or "",
                    r[5] or "",
                    r[6] or "",
                    r[7] or "",
                )
            )
        return out
    finally:
        conn.close()


def create_sala_modelo(platform_id: int, name: str, moodle_id: str, extra_filter: str) -> int:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO salas_modelo (platform_id, name, moodle_id, extra_filter, created_at, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (int(platform_id), name, moodle_id, extra_filter or ""),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def update_sala_modelo(
    sala_modelo_id: int,
    platform_id: int,
    name: str,
    moodle_id: str,
    extra_filter: str,
) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE salas_modelo
               SET platform_id = ?,
                   name = ?,
                   moodle_id = ?,
                   extra_filter = ?,
                   updated_at = datetime('now')
             WHERE id = ?
            """,
            (int(platform_id), name, moodle_id, extra_filter or "", int(sala_modelo_id)),
        )
        conn.commit()
    finally:
        conn.close()


def delete_sala_modelo(sala_modelo_id: int) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute("DELETE FROM salas_modelo WHERE id = ?", (int(sala_modelo_id),))
        conn.commit()
    finally:
        conn.close()