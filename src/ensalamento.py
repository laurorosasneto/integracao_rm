from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "app.db"

# Flag global de debug WS (habilitada por CLI)
DEBUG_WS: bool = False


def _force_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def log(msg: str) -> None:
    print(msg, flush=True)


def _redact_token(tok: str) -> str:
    tok = str(tok or "")
    if len(tok) <= 8:
        return "***"
    return tok[:4] + "..." + tok[-4:]


def _to_curl_equiv(url: str, payload: Dict[str, Any], timeout: int = 60) -> str:
    # Formato curl equivalente ao POST application/x-www-form-urlencoded
    parts = [
        f'curl -sS -X POST "{url}" \\',
    ]
    for k, v in payload.items():
        parts.append(f"  -d '{k}={v}' \\")
    parts.append(f"  --max-time {int(timeout)}")
    return "\n".join(parts)


def moodle_call(base_url: str, token: str, function: str, params: Dict[str, Any], dbg_label: Optional[str] = None) -> Any:
    url = base_url.rstrip("/") + "/webservice/rest/server.php"
    payload: Dict[str, Any] = {"wstoken": token, "wsfunction": function, "moodlewsrestformat": "json"}
    payload.update(params or {})

    if DEBUG_WS:
        label = (dbg_label or function).upper()
        safe_payload = dict(payload)
        safe_payload["wstoken"] = _redact_token(token)
        log("")
        log(f"[DEBUG_WS] {label} WS CALL: {function}")
        log(f"[DEBUG_WS] URL: {url}")
        log(f"[DEBUG_WS] PAYLOAD: {safe_payload}")
        # curl equivalente com token redigido
        curl_payload = dict(payload)
        curl_payload["wstoken"] = _redact_token(token)
        log("[DEBUG_WS] CURL_EQUIV:")
        log(_to_curl_equiv(url, curl_payload))

    resp = requests.post(url, data=payload, timeout=60)

    if DEBUG_WS:
        ct = resp.headers.get("Content-Type", "")
        body_preview = resp.text[:500].replace("\n", "\\n")
        log(f"[DEBUG_WS] HTTP {resp.status_code} Content-Type={ct}")
        log(f"[DEBUG_WS] BODY_PREVIEW(500): {body_preview}")

    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and data.get("exception"):
        err = f"{data.get('errorcode')}: {data.get('message')}"
        if data.get("debuginfo"):
            err += f" | debuginfo={data.get('debuginfo')}"
        raise RuntimeError(err + f" (wsfunction={function})")
    return data


def get_site_info(base_url: str, token: str) -> Dict[str, Any]:
    res = moodle_call(base_url, token, "core_webservice_get_site_info", {}, dbg_label="site_info")
    return res if isinstance(res, dict) else {}


def strip_sql(sql: str) -> str:
    sql = (sql or "").strip()
    sql = re.sub(r"^\s*--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].strip()
    return sql


def remove_last_order_by(sql: str) -> str:
    s = (sql or "").strip()
    if not s:
        return s
    lower = s.lower()
    pos = lower.rfind("order by")
    if pos == -1:
        return s
    return s[:pos].strip()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cohort_map (
            platform_id INTEGER NOT NULL,
            cohort_name TEXT NOT NULL,
            cohort_name_norm TEXT NOT NULL,
            cohort_id INTEGER NOT NULL,
            idnumber TEXT,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (platform_id, cohort_name_norm)
        )
        """
    )
    conn.commit()
    return conn


def get_platform(conn: sqlite3.Connection, platform_id: int) -> Tuple[str, str]:
    cur = conn.execute("SELECT url, token FROM platforms WHERE id = ?", (platform_id,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Plataforma não encontrada: id={platform_id}")
    return str(row[0] or ""), str(row[1] or "")


def get_platform_coligadas(conn: sqlite3.Connection, platform_id: int) -> List[int]:
    cur = conn.execute("SELECT coligadas FROM platforms WHERE id = ?", (platform_id,))
    row = cur.fetchone()
    if not row:
        return []
    raw = str(row[0] or "").strip()
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            continue
    return out


def get_rm_config(conn: sqlite3.Connection) -> Tuple[str, str, str, str]:
    cur = conn.execute("SELECT host, database_name, username, password FROM rm_config WHERE id = 1")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Configuração do RM não encontrada (aba TOTVS RM).")
    return str(row[0] or ""), str(row[1] or ""), str(row[2] or ""), str(row[3] or "")


def get_rm_query(conn: sqlite3.Connection, key: str) -> str:
    cur = conn.execute(
        """
        SELECT coligadas, periodos, cursos, turmas, salas, alunos, professores,
               ensalamento_alunos, ensalamento_professores
          FROM rm_queries
         WHERE id = 1
        """
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Consultas RM não encontradas (aba Consultas RM).")

    keys = [
        "coligadas",
        "periodos",
        "cursos",
        "turmas",
        "salas",
        "alunos",
        "professores",
        "ensalamento_alunos",
        "ensalamento_professores",
    ]
    data = dict(zip(keys, row))
    return strip_sql(str(data.get(key, "") or ""))


def _has_where(sql: str) -> bool:
    return bool(re.search(r"\bwhere\b", sql, flags=re.IGNORECASE))


def build_filtered_sql_for_ensalamento(sql: str, coligadas: List[int], idperlet: Optional[int]) -> str:
    sql = strip_sql(sql)
    if not sql:
        return ""
    sql = remove_last_order_by(sql)

    clauses: List[str] = []
    if coligadas:
        in_list = ",".join(str(int(c)) for c in coligadas)
        clauses.append(f"STURMADISC.CODCOLIGADA IN ({in_list})")
    if idperlet is not None:
        # Regra do projeto: filtro SEMPRE por IDPERLET para alunos e professores.
        # Para evitar ambiguidade (SPLETIVO.IDPERLET vs STURMADISC.IDPERLET), fixamos em STURMADISC.IDPERLET.
        clauses.append(f"STURMADISC.IDPERLET = {int(idperlet)}")

    if clauses:
        if _has_where(sql):
            sql = sql + " AND " + " AND ".join(clauses)
        else:
            sql = sql + " WHERE " + " AND ".join(clauses)

    return sql


def rm_fetch_rows(rm_config: Tuple[str, str, str, str], sql: str) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    host, db_name, username, password = rm_config
    try:
        import pyodbc  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"pyodbc não disponível: {exc}")

    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={host};"
        f"DATABASE={db_name};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )

    with pyodbc.connect(conn_str, timeout=20) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    return cols, [tuple(r) for r in rows]


def _idx(cols: List[str], name: str) -> int:
    try:
        return cols.index(name)
    except ValueError:
        return -1


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except Exception:
            return None
    return None


def _normalize_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def _make_idnumber_from_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\s+", " ", s).strip()
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-").upper()
    base = re.sub(r"-{2,}", "-", base)
    if not base:
        base = f"COHORT-{int(time.time())}"
    return base[:100]


def cohort_map_get(conn: sqlite3.Connection, platform_id: int, cohort_name: str) -> Optional[Tuple[int, Optional[str]]]:
    norm = _normalize_name(cohort_name)
    cur = conn.execute(
        "SELECT cohort_id, idnumber FROM cohort_map WHERE platform_id = ? AND cohort_name_norm = ?",
        (int(platform_id), norm),
    )
    row = cur.fetchone()
    if not row:
        return None
    return int(row[0]), (str(row[1]) if row[1] is not None else None)


def cohort_map_set(conn: sqlite3.Connection, platform_id: int, cohort_name: str, cohort_id: int, idnumber: Optional[str]) -> None:
    norm = _normalize_name(cohort_name)
    conn.execute(
        """
        INSERT INTO cohort_map(platform_id, cohort_name, cohort_name_norm, cohort_id, idnumber, updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(platform_id, cohort_name_norm)
        DO UPDATE SET
            cohort_name=excluded.cohort_name,
            cohort_id=excluded.cohort_id,
            idnumber=excluded.idnumber,
            updated_at=excluded.updated_at
        """,
        (int(platform_id), cohort_name.strip(), norm, int(cohort_id), idnumber, int(time.time())),
    )
    conn.commit()


def search_cohort_by_query(base_url: str, token: str, query: str) -> List[Dict[str, Any]]:
    res = moodle_call(
        base_url,
        token,
        "core_cohort_search_cohorts",
        {
            "query": query,
            "contextid": 1,  # sistema
            "includes": "all",
            "limitfrom": 0,
            "limitnum": 200,
        },
        dbg_label="cohort_search",
    )
    if isinstance(res, dict):
        cohorts = res.get("cohorts") or []
        if isinstance(cohorts, list):
            return [c for c in cohorts if isinstance(c, dict)]
    return []


def ensure_cohort(
    conn: sqlite3.Connection,
    platform_id: int,
    base_url: str,
    token: str,
    cohort_name: str,
    mem_cache: Dict[str, int],
) -> Optional[int]:
    cohort_name = (cohort_name or "").strip()
    if not cohort_name:
        return None

    name_norm = _normalize_name(cohort_name)
    if name_norm in mem_cache:
        return mem_cache[name_norm]

    idnumber = _make_idnumber_from_name(cohort_name)

    # 2) Busca por nome
    try:
        items = search_cohort_by_query(base_url, token, cohort_name)
        for c in items:
            n = str(c.get("name") or "").strip()
            if _normalize_name(n) == name_norm and c.get("id"):
                cid = int(c["id"])
                mem_cache[name_norm] = cid
                cohort_map_set(conn, platform_id, cohort_name, cid, str(c.get("idnumber") or idnumber))
                return cid
    except Exception:
        pass

    # 3) Busca por idnumber
    try:
        items = search_cohort_by_query(base_url, token, idnumber)
        for c in items:
            cidnum = str(c.get("idnumber") or "").strip().upper()
            if cidnum == idnumber and c.get("id"):
                cid = int(c["id"])
                mem_cache[name_norm] = cid
                cohort_map_set(conn, platform_id, cohort_name, cid, cidnum)
                return cid
    except Exception:
        pass

    # 4) Cache persistente
    cached = cohort_map_get(conn, platform_id, cohort_name)
    if cached:
        cid, _ = cached
        mem_cache[name_norm] = cid
        return cid

    # 5) Criar
    created = moodle_call(
        base_url,
        token,
        "core_cohort_create_cohorts",
        {
            "cohorts[0][categorytype][type]": "system",
            "cohorts[0][categorytype][value]": 0,
            "cohorts[0][name]": cohort_name,
            "cohorts[0][idnumber]": idnumber,
            "cohorts[0][description]": "",
            "cohorts[0][descriptionformat]": 1,
            "cohorts[0][visible]": 1,
        },
        dbg_label="cohort_create",
    )

    if isinstance(created, list) and created and isinstance(created[0], dict) and created[0].get("id"):
        cid = int(created[0]["id"])
        mem_cache[name_norm] = cid
        cohort_map_set(conn, platform_id, cohort_name, cid, idnumber)
        return cid

    return None


def _ws_error_means_function_not_available(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("wsfunction=" in s) and ("not available" in s or "não está disponível" in s or "nao esta disponivel" in s)


def check_cohort_ws_available(base_url: str, token: str) -> Tuple[bool, str]:
    try:
        moodle_call(base_url, token, "core_cohort_get_cohorts", {}, dbg_label="cohort_get_1")
        return True, "Cohorts: WS disponível para este token."
    except Exception as exc:
        if _ws_error_means_function_not_available(exc):
            return False, "AVISO: cohorts desabilitado automaticamente. Motivo: serviço/token não expõe core_cohort_get_cohorts."
        return False, f"AVISO: cohorts desabilitado automaticamente. Motivo: sem permissão/erro ao chamar core_cohort_get_cohorts: {exc}"


def _is_invalidparameter(exc: Exception) -> bool:
    s = str(exc).lower()
    return "invalidparameter" in s or "invalid_parameter" in s


def diag_cohort_add_invalidparameter(base_url: str, token: str, cohort_id: int, user_id: int) -> str:
    """
    Quando core_cohort_add_cohort_members retorna invalidparameter, este DIAG tenta provar:
      - cohort existe
      - user existe
    Se ambos existem, a causa mais provável é PERMISSÃO/CAPABILITY/CONTEXTO.
    """
    cohort_exists = False
    user_exists = False

    try:
        cohorts = moodle_call(base_url, token, "core_cohort_get_cohorts", {}, dbg_label="diag_cohort_get")
        if isinstance(cohorts, list):
            for c in cohorts:
                if isinstance(c, dict) and int(c.get("id") or 0) == int(cohort_id):
                    cohort_exists = True
                    break
    except Exception:
        pass

    try:
        ures = moodle_call(
            base_url,
            token,
            "core_user_get_users_by_field",
            {"field": "id", "values[0]": int(user_id)},
            dbg_label="diag_user_by_id",
        )
        if isinstance(ures, list) and ures:
            try:
                user_exists = int(ures[0].get("id") or 0) == int(user_id)
            except Exception:
                user_exists = False
    except Exception:
        pass

    if cohort_exists and user_exists:
        return (
            "DIAG: cohortid e userid existem (confirmado via WS). "
            "Causa mais provável: permissões/capability/contexto para adicionar membros em cohort. "
            "Garanta que o usuário do token tenha moodle/cohort:assign (e moodle/cohort:view) no CONTEXTO SISTEMA "
            "ou no contexto onde o cohort está, e que a função core_cohort_add_cohort_members esteja no serviço."
        )

    if not cohort_exists and user_exists:
        return "DIAG: userid existe, mas cohortid não foi encontrado na listagem WS. Verifique se o cohortid é válido/visível ao token."

    if cohort_exists and not user_exists:
        return "DIAG: cohortid existe, mas userid não foi encontrado via WS. Verifique se o usuário existe/está acessível ao token."

    return "DIAG: não foi possível confirmar existência de cohortid/userid via WS (token pode estar limitado). Verifique permissões e se os IDs são válidos."


def add_user_to_cohort(
    base_url: str,
    token: str,
    cohort_id: int,
    user_id: int,
    membership_cache: Set[Tuple[int, int]],
) -> None:
    key = (int(cohort_id), int(user_id))
    if key in membership_cache:
        return

    # chamada padrão REST (o que o Moodle espera) - estrutura com cohorttype/usertype
    try:
        moodle_call(
            base_url,
            token,
            "core_cohort_add_cohort_members",
            {
                "members[0][cohorttype][type]": "id",
                "members[0][cohorttype][value]": str(int(cohort_id)),
                "members[0][usertype][type]": "id",
                "members[0][usertype][value]": str(int(user_id)),
            },
            dbg_label="cohort_add_member",
        )
        membership_cache.add(key)
        return
    except Exception as exc:
        if _is_invalidparameter(exc):
            diag = diag_cohort_add_invalidparameter(base_url, token, int(cohort_id), int(user_id))
            raise RuntimeError(f"{exc} | {diag}")
        raise


def get_course_id_by_shortname(base_url: str, token: str, shortname: str, cache: Dict[str, int]) -> Optional[int]:
    shortname = (shortname or "").strip()
    if not shortname:
        return None
    if shortname in cache:
        return cache[shortname]

    res = moodle_call(
        base_url,
        token,
        "core_course_get_courses_by_field",
        {"field": "shortname", "value": shortname},
        dbg_label="course_get_by_field",
    )
    if isinstance(res, dict):
        courses = res.get("courses") or []
        if courses:
            cid = int(courses[0].get("id"))
            cache[shortname] = cid
            return cid
    return None


def get_user_id_by_username(base_url: str, token: str, username: str, cache: Dict[str, int]) -> Optional[int]:
    username = (username or "").strip()
    if not username:
        return None
    if username in cache:
        return cache[username]

    res = moodle_call(
        base_url,
        token,
        "core_user_get_users_by_field",
        {"field": "username", "values[0]": username},
        dbg_label="user_get_by_username",
    )
    if isinstance(res, list) and res:
        uid = int(res[0].get("id"))
        cache[username] = uid
        return uid
    return None


def _status_means_enabled(status: Any) -> bool:
    if status is None:
        return True
    if isinstance(status, bool):
        return bool(status)

    s = str(status).strip().lower()
    if s == "":
        return True

    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s) == 0
        except Exception:
            return True

    if "disable" in s or "inactiv" in s:
        return False
    if "enable" in s or "activ" in s:
        return True

    return True


def course_has_enabled_manual_enrol(base_url: str, token: str, course_id: int, label: str, shortname: str) -> bool:
    try:
        res = moodle_call(
            base_url,
            token,
            "core_enrol_get_course_enrolment_methods",
            {"courseid": int(course_id)},
            dbg_label="enrol_methods",
        )
    except Exception as exc:
        log(
            f"[{label}] AVISO: não foi possível consultar métodos de inscrição via WS "
            f"(curso='{shortname}', id={course_id}). Vou tentar matricular mesmo. Detalhe: {exc}"
        )
        return True

    if not isinstance(res, list):
        log(
            f"[{label}] AVISO: retorno inesperado ao listar métodos de inscrição "
            f"(curso='{shortname}', id={course_id}). Vou tentar matricular mesmo."
        )
        return True

    found_manual = False
    for m in res:
        enrol_type = str(m.get("type") or m.get("enrol") or "").strip().lower()
        if enrol_type == "manual":
            found_manual = True
            if _status_means_enabled(m.get("status")):
                return True
            return False

    if not found_manual:
        log(
            f"[{label}] AVISO: WS não listou 'manual' em métodos de inscrição "
            f"(curso='{shortname}', id={course_id}). Vou tentar matricular mesmo."
        )
        return True

    return True


def enrol_user(base_url: str, token: str, course_id: int, user_id: int, role_id: int, suspend: int) -> None:
    moodle_call(
        base_url,
        token,
        "enrol_manual_enrol_users",
        {
            "enrolments[0][roleid]": int(role_id),
            "enrolments[0][userid]": int(user_id),
            "enrolments[0][courseid]": int(course_id),
            "enrolments[0][suspend]": int(suspend),
        },
        dbg_label="enrol_user",
    )


def verify_course_enrolments(base_url: str, token: str, course_id: int, expected_user_ids: Set[int]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {uid: {"enrolled": False} for uid in expected_user_ids}
    try:
        enrolled = moodle_call(
            base_url,
            token,
            "core_enrol_get_enrolled_users",
            {"courseid": int(course_id)},
            dbg_label="enrolled_users",
        )
    except Exception:
        return out

    if not isinstance(enrolled, list):
        return out

    for u in enrolled:
        try:
            uid = int(u.get("id"))
        except Exception:
            continue
        if uid in out:
            out[uid]["enrolled"] = True
    return out


def main() -> int:
    global DEBUG_WS
    _force_utf8_stdout()

    parser = argparse.ArgumentParser(description="Ensalamento (matrícula + cohorts) no Moodle a partir de SQL do RM.")
    parser.add_argument("--platform-id", type=int, required=True)
    parser.add_argument("--idperlet", type=str, default="")
    parser.add_argument("--ensalamento-alunos", type=int, default=1)
    parser.add_argument("--ensalamento-professores", type=int, default=0)
    parser.add_argument("--debug-ws", type=int, default=0)
    args = parser.parse_args()

    DEBUG_WS = bool(int(args.debug_ws or 0))

    start = time.time()

    idperlet: Optional[int] = None
    if str(args.idperlet or "").strip():
        idperlet = _parse_int(args.idperlet)
        if idperlet is None:
            log(f"ERRO: idperlet inválido '{args.idperlet}'. Deve ser numérico (IDPERLET).")
            log("RESUMO_FINAL: Processo interrompido por parâmetro inválido (idperlet).")
            return 2

    conn = connect_db()
    try:
        base_url, token = get_platform(conn, args.platform_id)
        if not base_url or not token:
            raise RuntimeError("Plataforma está sem URL/token.")

        coligadas = get_platform_coligadas(conn, args.platform_id)
        rm_config = get_rm_config(conn)

        log("Validando token do Moodle...")
        siteinfo = get_site_info(base_url, token)
        log("Token OK.")

        ws_userid = siteinfo.get("userid")
        ws_username = siteinfo.get("username")
        ws_fullname = siteinfo.get("fullname")
        log(f"WS identity: userid={ws_userid} username={ws_username} fullname={ws_fullname}")

        modes: List[Tuple[str, str]] = []
        if args.ensalamento_alunos:
            modes.append(("ensalamento_alunos", "ALUNOS"))
        if args.ensalamento_professores:
            modes.append(("ensalamento_professores", "PROFESSORES"))
        if not modes:
            log("Nenhum modo selecionado. Encerrando.")
            log("RESUMO_FINAL: Nenhum modo selecionado.")
            return 0

        cohorts_enabled, cohorts_msg = check_cohort_ws_available(base_url, token)
        log(cohorts_msg)

        cohort_cache: Dict[str, int] = {}
        membership_cache: Set[Tuple[int, int]] = set()
        course_cache: Dict[str, int] = {}
        user_cache: Dict[str, int] = {}

        stats: Dict[int, Dict[str, Any]] = {}
        course_name_by_id: Dict[int, str] = {}

        total_rows = 0
        total_success = 0
        total_fail = 0
        total_role_invalid = 0
        total_manual_disabled = 0
        total_cohort_memberships_ok = 0
        total_cohort_memberships_fail = 0
        cohorts_skip_count = 0

        for query_key, label in modes:
            sql_raw = get_rm_query(conn, query_key)
            if not sql_raw:
                log(f"[{label}] Consulta vazia. Nada a executar.")
                continue

            sql = build_filtered_sql_for_ensalamento(sql_raw, coligadas, idperlet)
            # Pedido: no debug do ensalamento, mostrar APENAS o SQL final usado para filtrar
            # (sem prefixos/labels ao lado). Vale para ALUNOS e PROFESSORES.
            if DEBUG_WS and label in ("PROFESSORES", "ALUNOS"):
                log(sql)
            if not sql:
                log(f"[{label}] SQL inválido após filtros.")
                continue

            log("")
            log(f"[{label}] Carregando ensalamento no RM (filtros: coligada + IDPERLET)...")
            cols, rows = rm_fetch_rows(rm_config, sql)
            total_rows += len(rows)
            log(f"[{label}] Linhas retornadas: {len(rows)}")

            icourse = _idx(cols, "courseid")
            iuser = _idx(cols, "userid")
            irole = _idx(cols, "roleid")
            isusp = _idx(cols, "suspend")
            if icourse < 0 or iuser < 0 or irole < 0 or isusp < 0:
                missing = [n for n, i in [("courseid", icourse), ("userid", iuser), ("roleid", irole), ("suspend", isusp)] if i < 0]
                raise RuntimeError(f"[{label}] Consulta deve retornar colunas obrigatórias: {', '.join(missing)}")

            ic1 = _idx(cols, "cohort1")
            ic2 = _idx(cols, "cohort2")
            ic3 = _idx(cols, "cohort3")

            for line_no, r in enumerate(rows, start=1):
                course_shortname = str(r[icourse] or "").strip()
                username = str(r[iuser] or "").strip()

                role_id = _parse_int(r[irole])
                if role_id is None:
                    total_fail += 1
                    total_role_invalid += 1
                    log(f"[{label}] ERRO: roleid inválido (precisa ser numérico). Valor='{r[irole]}'. Linha {line_no}.")
                    continue

                suspend = _parse_int(r[isusp]) or 0

                course_id = get_course_id_by_shortname(base_url, token, course_shortname, course_cache)
                if not course_id:
                    total_fail += 1
                    log(f"[{label}] ERRO: curso não encontrado (shortname='{course_shortname}'). Linha {line_no}.")
                    continue
                course_name_by_id[course_id] = course_shortname

                user_id = get_user_id_by_username(base_url, token, username, user_cache)
                if not user_id:
                    total_fail += 1
                    log(f"[{label}] ERRO: usuário não encontrado (username='{username}'). Linha {line_no}.")
                    continue

                # Cohorts por linha
                for ci in [ic1, ic2, ic3]:
                    if ci < 0:
                        continue
                    cname = str(r[ci] or "").strip()
                    if not cname:
                        continue

                    if not cohorts_enabled:
                        cohorts_skip_count += 1
                        continue

                    cid: Optional[int] = None
                    try:
                        cid = ensure_cohort(
                            conn=conn,
                            platform_id=int(args.platform_id),
                            base_url=base_url,
                            token=token,
                            cohort_name=cname,
                            mem_cache=cohort_cache,
                        )
                        if cid:
                            add_user_to_cohort(base_url, token, cid, user_id, membership_cache)
                            total_cohort_memberships_ok += 1
                            log(f"[{label}] Cohort membro OK: '{cname}' (cohortid={cid}) <= user '{username}' (userid={user_id})")
                    except Exception as exc:
                        if _ws_error_means_function_not_available(exc):
                            cohorts_enabled = False
                            cohorts_skip_count += 1
                            log(f"[{label}] AVISO: cohorts desabilitado no meio da execução: função não disponível no serviço/token. Detalhe: {exc}")
                        else:
                            total_cohort_memberships_fail += 1
                            log(f"[{label}] ERRO: inserir em cohort '{cname}' para user '{username}': {exc} | cohortid={cid if cid else 'N/A'} userid={user_id}")

                manual_ok = course_has_enabled_manual_enrol(base_url, token, course_id, label, course_shortname)
                if not manual_ok:
                    total_fail += 1
                    total_manual_disabled += 1
                    log(f"[{label}] ERRO: WS confirmou 'manual' desabilitado no curso '{course_shortname}' (id={course_id}). Linha {line_no}.")
                    continue

                try:
                    enrol_user(base_url, token, course_id, user_id, role_id, suspend)
                except Exception as exc:
                    total_fail += 1
                    log(f"[{label}] ERRO: matrícula falhou (curso='{course_shortname}', user='{username}', roleid={role_id}): {exc}")
                    st = stats.setdefault(course_id, {"ok": 0, "fail": 0, "users_ok": set()})
                    st["fail"] += 1
                    continue

                total_success += 1
                log(f"[{label}] OK: matrícula aplicada (curso='{course_shortname}', user='{username}', roleid={role_id}, suspend={suspend}).")
                st = stats.setdefault(course_id, {"ok": 0, "fail": 0, "users_ok": set()})
                st["ok"] += 1
                st["users_ok"].add(int(user_id))

        log("")
        log("Verificando matrículas (por curso)...")
        verified_ok = 0
        verified_fail = 0
        for course_id, st in stats.items():
            expected = set(st["users_ok"])
            if not expected:
                continue
            vmap = verify_course_enrolments(base_url, token, int(course_id), expected)
            course_shortname = course_name_by_id.get(int(course_id), str(course_id))
            ok_course = sum(1 for uid in expected if vmap.get(uid, {}).get("enrolled"))
            fail_course = len(expected) - ok_course
            verified_ok += ok_course
            verified_fail += fail_course
            log(f"- Curso '{course_shortname}' (id={course_id}): verificados {ok_course} OK, {fail_course} FALHA.")

        log("")
        log("Relatório por curso (sucesso x falha):")
        for course_id, st in sorted(stats.items(), key=lambda x: course_name_by_id.get(int(x[0]), str(x[0]))):
            course_shortname = course_name_by_id.get(int(course_id), str(course_id))
            log(f"- {course_shortname} (id={course_id}): OK={st['ok']} | FALHA={st['fail']}")

        elapsed = max(0.1, time.time() - start)
        resumo = (
            f"Processo concluído. Linhas: {total_rows}. OK: {total_success}. Falhas: {total_fail}. "
            f"Roleid inválido: {total_role_invalid}. Manual desabilitado (confirmado WS): {total_manual_disabled}. "
            f"Cohort-members OK: {total_cohort_memberships_ok}, FALHA: {total_cohort_memberships_fail}, "
            f"SKIP(cohorts off): {cohorts_skip_count}. "
            f"Verificação OK={verified_ok}, FALHA={verified_fail}. Tempo: {elapsed:.1f}s."
        )
        log("")
        log("RESUMO_FINAL: " + resumo)
        return 0

    except Exception as exc:
        log("")
        log(f"ERRO FATAL: {exc}")
        log("RESUMO_FINAL: Processo interrompido por erro fatal. Verifique o debug para detalhes.")
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())