from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "app.db"


def _force_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def log(msg: str) -> None:
    print(msg, flush=True)


def now() -> float:
    return time.monotonic()


def normalize_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def normalize_numish(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    try:
        f = float(s.replace(",", "."))
        i = int(f)
        if abs(f - i) < 1e-9:
            return str(i)
    except Exception:
        pass
    return s


def strip_sql(sql: str) -> str:
    sql = (sql or "").strip()
    if sql.endswith(";"):
        sql = sql[:-1].strip()
    return sql



def remove_last_order_by(sql: str) -> str:
    lower = sql.lower()
    pos = lower.rfind("order by")
    if pos == -1:
        return sql
    return sql[:pos].strip()


def sql_in_list(values: Set[str]) -> str:
    cleaned: List[str] = []
    for v in sorted(values):
        v = normalize_numish(v)
        if not v:
            continue
        if v.isdigit():
            cleaned.append(v)
        else:
            cleaned.append("'" + v.replace("'", "''") + "'")
    return ", ".join(cleaned)


def build_filtered_sql(sql_base: str, allowed_coligadas: Set[str], idperlet: str) -> str:
    """Aplica filtros automáticos (coligada + IDPERLET) usando wrapper SELECT * FROM (..) X."""
    sql_base = strip_sql(sql_base)
    sql_base = remove_last_order_by(sql_base)
    in_list = sql_in_list(allowed_coligadas)
    if not in_list:
        return sql_base

    where = [f"X.CODCOLIGADA IN ({in_list})"]
    if idperlet:
        # aceita apenas numérico
        if not str(idperlet).isdigit():
            raise RuntimeError("IDPERLET inválido (precisa ser numérico).")
        where.append(f"X.IDPERLET = {idperlet}")

    return "SELECT * FROM (" + sql_base + ") X WHERE " + " AND ".join(where)
def get_platform(platform_id: int) -> tuple[str, str, str, str] | None:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT name, url, token, coligadas FROM platforms WHERE id = ?",
            (platform_id,),
        )
        row = cur.fetchone()
        return (row[0], row[1], row[2], row[3] or "") if row else None
    finally:
        conn.close()


def get_rm_config() -> tuple[str, str, str, str] | None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT host, database_name, username, password FROM rm_config WHERE id = 1"
        )
        row = cur.fetchone()
        return (row[0], row[1], row[2], row[3]) if row else None
    finally:
        conn.close()


def get_rm_query(key: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT coligadas, periodos, cursos, turmas, salas, alunos, professores FROM rm_queries WHERE id = 1"
        )
        row = cur.fetchone()
        if not row:
            return ""
        cols = ["coligadas", "periodos", "cursos", "turmas", "salas", "alunos", "professores"]
        data = dict(zip(cols, row))
        return (data.get(key) or "").strip()
    finally:
        conn.close()


def rm_fetch(sql: str) -> Tuple[List[str], List[tuple]]:
    cfg = get_rm_config()
    if not cfg or not sql.strip():
        return ([], [])

    host, db_name, username, password = cfg

    try:
        import pyodbc  # type: ignore
    except Exception as exc:
        log(f"pyodbc não disponível: {exc}")
        return ([], [])

    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={host};"
        f"DATABASE={db_name};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )

    with pyodbc.connect(conn_str, timeout=60) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [desc[0].lower() for desc in cur.description] if cur.description else []
    return (columns, rows)


def moodle_call(base_url: str, token: str, function: str, params: Dict[str, Any]) -> Any:
    url = base_url.rstrip("/") + "/webservice/rest/server.php"
    payload = {
        "wstoken": token,
        "wsfunction": function,
        "moodlewsrestformat": "json",
    }
    payload.update(params)

    resp = requests.post(url, data=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    # Moodle erro padrão:
    # {"exception": "...", "errorcode":"...", "message":"...", "debuginfo":"..."}
    if isinstance(data, dict) and data.get("exception"):
        msg = f"{data.get('errorcode')}: {data.get('message')}"
        dbg = data.get("debuginfo")
        if dbg:
            msg += f" | debuginfo: {dbg}"
        raise RuntimeError(msg)

    return data


def test_token(base_url: str, token: str) -> None:
    log("Testando token do Moodle...")
    moodle_call(base_url, token, "core_webservice_get_site_info", {})
    log("Token válido.")


def _idx(columns: List[str], name: str) -> Optional[int]:
    name = name.lower()
    return columns.index(name) if name in columns else None


# -------------------------
# Validações e normalizações
# -------------------------
_EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_auth(auth: str) -> str:
    """
    auth precisa ser um método de autenticação válido no Moodle.
    Seu SQL usa 'rm' — isso costuma dar invalidparameter se não existir plugin auth_rm.
    Aqui normalizamos para 'manual' quando não for um valor seguro.
    """
    a = (auth or "").strip().lower()
    allowed = {
        "manual",
        "email",
        "nologin",
        "ldap",
        "oauth2",
        "cas",
        "shibboleth",
        "pam",
        "radius",
        "mnet",
        "lti",
        "webservice",
        "saml2",
    }
    return a if a in allowed else "manual"


# -------------------------
# Política de senha (local)
# -------------------------
_RX_LOWER = re.compile(r"[a-z]")
_RX_UPPER = re.compile(r"[A-Z]")
_RX_DIGIT = re.compile(r"\d")
_RX_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def password_is_ok(pw: str) -> bool:
    if not pw or len(pw) < 8:
        return False
    if not _RX_LOWER.search(pw):
        return False
    if not _RX_UPPER.search(pw):
        return False
    if not _RX_DIGIT.search(pw):
        return False
    if not _RX_SPECIAL.search(pw):
        return False
    return True


def generate_password_from_username(username: str) -> str:
    u = re.sub(r"\s+", "", username or "")
    base = f"Rm{u}#Aa1"
    if len(base) < 8:
        base += "Xy2!"
    if not password_is_ok(base):
        base = "Rm#Aa1Xy2!"
    return base


def _extract_customfield_value(user_obj: Dict[str, Any], field_type: str) -> str:
    """
    Moodle costuma retornar customfields como lista de dicts.
    Vamos tentar extrair por type/shortname de forma resiliente.
    """
    cfs = user_obj.get("customfields") or []
    if not isinstance(cfs, list):
        return ""
    ft = (field_type or "").strip().lower()
    for cf in cfs:
        if not isinstance(cf, dict):
            continue
        # Alguns Moodles retornam "type", outros "shortname"
        t = str(cf.get("type") or cf.get("shortname") or "").strip().lower()
        if t == ft:
            return str(cf.get("value") or "").strip()
    return ""


def _row_to_desired_user(columns: List[str], row: tuple) -> Optional[Dict[str, Any]]:
    """
    Converte uma linha do RM em um "estado desejado" para o Moodle.
    Campos esperados do RM:
      CODCOLIGADA (obrigatório para filtro)
      USERNAME, AUTH, PASSWORD, FIRSTNAME, LASTNAME, EMAIL, CPF/profile_field_CPF
    """
    i_codcol = _idx(columns, "codcoligada")
    i_username = _idx(columns, "username")
    i_auth = _idx(columns, "auth")
    i_password = _idx(columns, "password")
    i_firstname = _idx(columns, "firstname")
    i_lastname = _idx(columns, "lastname")
    i_email = _idx(columns, "email")

    i_cpf = _idx(columns, "cpf")
    if i_cpf is None:
        i_cpf = _idx(columns, "profile_field_cpf")

    if i_codcol is None or i_username is None or i_firstname is None or i_lastname is None or i_email is None:
        return None

    codcol = normalize_numish(row[i_codcol])
    username = normalize_str(row[i_username])
    firstname = normalize_str(row[i_firstname])
    lastname = normalize_str(row[i_lastname])
    email = normalize_str(row[i_email])

    auth_raw = normalize_str(row[i_auth]) if i_auth is not None else "manual"
    auth = normalize_auth(auth_raw)

    raw_password = normalize_str(row[i_password]) if i_password is not None else ""
    cpf = normalize_str(row[i_cpf]) if i_cpf is not None else ""

    if not codcol or not username or not firstname or not lastname or not email:
        return None
    if not _EMAIL_RX.match(email):
        return None

    desired: Dict[str, Any] = {
        "codcoligada": codcol,
        "username": username,
        "auth": auth,
        "firstname": firstname,
        "lastname": lastname,
        "email": email,
        "cpf": cpf,
        "raw_password": raw_password,
    }
    return desired


def _fetch_people(kind: str, allowed_coligadas: Set[str], idperlet: str, debug_ws: bool) -> Tuple[List[str], List[tuple]]:
    sql_base = strip_sql(get_rm_query(kind))
    if not sql_base:
        return ([], [])

    # Aplica filtros automáticos diretamente no SQL:
    # - CODCOLIGADA IN (<coligadas da plataforma>)
    # - IDPERLET = <selecionado> (quando informado)
    sql_final = build_filtered_sql(sql_base, allowed_coligadas, idperlet)

    # Debug pedido: quando habilitado, mostrar APENAS o SQL final usado (sem rótulos ao lado).
    if debug_ws:
        log(sql_final)

    log(f"Executando consulta RM: {kind.capitalize()} (com filtros automáticos)")
    t0 = now()
    cols, rows = rm_fetch(sql_final)
    log(f"Consulta RM ({kind.capitalize()}) concluída em {now() - t0:.3f}s ({len(rows)} linhas)")

    return (cols, rows)


# -------------------------
# Moodle: buscar existentes
# -------------------------
def moodle_get_users_by_usernames(base_url: str, token: str, usernames: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Busca usuários existentes no Moodle por username, em lote.
    Retorna dict: username_lower -> user_obj
    """
    if not usernames:
        return {}

    params: Dict[str, Any] = {"field": "username"}
    for i, u in enumerate(usernames):
        params[f"values[{i}]"] = u

    data = moodle_call(base_url, token, "core_user_get_users_by_field", params)
    out: Dict[str, Dict[str, Any]] = {}

    if isinstance(data, list):
        for u in data:
            if not isinstance(u, dict):
                continue
            un = str(u.get("username") or "").strip()
            if un:
                out[un.lower()] = u

    return out


def moodle_create_user(base_url: str, token: str, desired: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Cria usuário. Se a senha do RM não passa na política, gera senha forte e força troca no 1º login.
    """
    username = desired["username"]
    auth = desired.get("auth", "manual")
    firstname = desired["firstname"]
    lastname = desired["lastname"]
    email = desired["email"]
    cpf = desired.get("cpf", "") or ""

    raw_pw = desired.get("raw_password", "") or ""
    password = raw_pw if password_is_ok(raw_pw) else generate_password_from_username(username)
    force_change = not password_is_ok(raw_pw)

    params: Dict[str, Any] = {
        "users[0][username]": username,
        "users[0][auth]": auth,
        "users[0][password]": password,
        "users[0][firstname]": firstname,
        "users[0][lastname]": lastname,
        "users[0][email]": email,
    }

    if cpf:
        params["users[0][customfields][0][type]"] = "CPF"
        params["users[0][customfields][0][value]"] = cpf

    if force_change:
        params["users[0][preferences][0][type]"] = "auth_forcepasswordchange"
        params["users[0][preferences][0][value]"] = "1"

    try:
        moodle_call(base_url, token, "core_user_create_users", params)
        if force_change:
            return True, "criado (senha gerada; troca no 1º login)"
        return True, "criado"
    except Exception as exc:
        # fallback: se customfields CPF causar invalidparameter, tenta sem CPF
        msg = str(exc)
        if "invalidparameter" in msg.lower() and cpf:
            try:
                params.pop("users[0][customfields][0][type]", None)
                params.pop("users[0][customfields][0][value]", None)
                moodle_call(base_url, token, "core_user_create_users", params)
                if force_change:
                    return True, "criado (sem CPF; senha gerada; troca no 1º login)"
                return True, "criado (sem CPF)"
            except Exception as exc2:
                return False, f"falha ao criar: {exc2}"
        return False, f"falha ao criar: {exc}"


def moodle_update_user(base_url: str, token: str, user_id: int, desired: Dict[str, Any], existing: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Atualiza SOMENTE se algo mudou (firstname/lastname/email/auth/CPF).
    """
    desired_firstname = desired["firstname"]
    desired_lastname = desired["lastname"]
    desired_email = desired["email"]
    desired_auth = desired.get("auth", "manual")
    desired_cpf = (desired.get("cpf") or "").strip()

    cur_firstname = str(existing.get("firstname") or "").strip()
    cur_lastname = str(existing.get("lastname") or "").strip()
    cur_email = str(existing.get("email") or "").strip()
    cur_auth = str(existing.get("auth") or "").strip().lower()

    cur_cpf = _extract_customfield_value(existing, "CPF")

    changes: List[str] = []
    if desired_firstname != cur_firstname:
        changes.append("primeiro nome")
    if desired_lastname != cur_lastname:
        changes.append("sobrenome")
    if desired_email != cur_email:
        changes.append("e-mail")
    if desired_auth != cur_auth:
        changes.append("auth")
    # CPF só considera se veio preenchido do RM
    if desired_cpf and desired_cpf != cur_cpf:
        changes.append("CPF")

    if not changes:
        return True, "inalterado"

    params: Dict[str, Any] = {
        "users[0][id]": str(int(user_id)),
        "users[0][firstname]": desired_firstname,
        "users[0][lastname]": desired_lastname,
        "users[0][email]": desired_email,
        "users[0][auth]": desired_auth,
    }

    # CPF (pode falhar se campo não existir)
    if desired_cpf:
        params["users[0][customfields][0][type]"] = "CPF"
        params["users[0][customfields][0][value]"] = desired_cpf

    try:
        moodle_call(base_url, token, "core_user_update_users", params)
        return True, "atualizado (" + ", ".join(changes) + ")"
    except Exception as exc:
        msg = str(exc)
        # fallback: se CPF causar invalidparameter, tenta sem CPF
        if "invalidparameter" in msg.lower() and desired_cpf:
            try:
                params.pop("users[0][customfields][0][type]", None)
                params.pop("users[0][customfields][0][value]", None)
                moodle_call(base_url, token, "core_user_update_users", params)
                return True, "atualizado (" + ", ".join([c for c in changes if c != "CPF"]) + "; sem CPF)"
            except Exception as exc2:
                return False, f"falha ao atualizar: {exc2}"
        return False, f"falha ao atualizar: {exc}"


def process_kind(
    base_url: str,
    token: str,
    kind: str,
    allowed_coligadas: Set[str],
    idperlet: str,
    debug_ws: bool,
) -> Dict[str, Any]:
    # IMPORTANTE: idperlet/debug_ws vêm do argparse (escopo do main). Não usar variáveis globais.
    cols, rows = _fetch_people(kind, allowed_coligadas, idperlet, debug_ws)

    desired_rows: List[Dict[str, Any]] = []
    ignored = 0

    for r in rows:
        d = _row_to_desired_user(cols, r)
        if d:
            desired_rows.append(d)
        else:
            ignored += 1

    log(f"Registros do RM considerados ({kind}): {len(desired_rows)}")
    if ignored:
        log(f"Registros ignorados ({kind}) por dados inválidos (ex.: email/campos obrigatórios): {ignored}")

    # Pré-carrega existentes por lotes de 200 usernames
    usernames = [d["username"] for d in desired_rows]
    existing_map: Dict[str, Dict[str, Any]] = {}
    batch = 200
    t0 = now()
    for i in range(0, len(usernames), batch):
        chunk = usernames[i : i + batch]
        m = moodle_get_users_by_usernames(base_url, token, chunk)
        existing_map.update(m)
    log(f"Busca no Moodle por usuários existentes concluída em {now() - t0:.3f}s.")

    created = 0
    updated = 0
    unchanged = 0
    failed = 0

    # processa em ordem (mantém “lógica” determinística)
    for d in desired_rows:
        username = d["username"]
        key = username.lower()
        existing = existing_map.get(key)

        if not existing:
            ok, msg = moodle_create_user(base_url, token, d)
            if ok:
                created += 1
                log(f"Usuário {username}: {msg}.")
            else:
                failed += 1
                log(f"Usuário {username}: {msg}.")
            continue

        user_id = int(existing.get("id") or 0)
        if user_id <= 0:
            failed += 1
            log(f"Usuário {username}: falha (Moodle retornou usuário sem id).")
            continue

        ok, msg = moodle_update_user(base_url, token, user_id, d, existing)
        if ok and msg == "inalterado":
            unchanged += 1
        elif ok:
            updated += 1
        else:
            failed += 1

        log(f"Usuário {username}: {msg}.")

    return {
        "kind": kind,
        "rm_total": len(rows),
        "considered": len(desired_rows),
        "ignored": ignored,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "failed": failed,
    }


def main() -> int:
    _force_utf8_stdout()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    parser.add_argument("--periodo", default="")  # compat (antigo)
    parser.add_argument("--idperlet", default="")
    parser.add_argument("--debug-ws", default="0")
    parser.add_argument("--insert-alunos", default="1")
    parser.add_argument("--insert-professores", default="0")
    args = parser.parse_args()

    platform = get_platform(args.platform_id)
    if not platform:
        log("Plataforma não encontrada.")
        return 1

    platform_name, base_url, token, coligadas_csv = platform
    periodo = normalize_str(args.periodo).replace("/", "-")  # compat (antigo)
    idperlet = normalize_numish(args.idperlet)
    DEBUG_WS = args.debug_ws == "1"
    do_alunos = args.insert_alunos == "1"
    do_prof = args.insert_professores == "1"

    log("==== INÍCIO - INSERÇÃO DE PESSOAS ====")
    log(f"Arquivo em execução: {Path(__file__).resolve()}")
    log(f"Plataforma: {platform_name} (ID {args.platform_id})")
    log(f"Período (IDPERLET): {idperlet or 'Todos'}")
    log(f"Inserir alunos: {'Sim' if do_alunos else 'Não'}")
    log(f"Inserir professores: {'Sim' if do_prof else 'Não'}")

    if not do_alunos and not do_prof:
        log("Nada a fazer (nenhum tipo selecionado).")
        return 0

    try:
        test_token(base_url, token)
    except Exception as exc:
        log(f"Falha no token/site info: {exc}")
        return 2

    allowed_coligadas = {normalize_numish(c) for c in (coligadas_csv or "").split(",") if normalize_numish(c)}
    if not allowed_coligadas:
        log("Nenhuma coligada selecionada na plataforma.")
        return 0

    results: List[Dict[str, Any]] = []
    t_all = now()

    try:
        if do_alunos:
            results.append(process_kind(base_url, token, "alunos", allowed_coligadas, idperlet, DEBUG_WS))
        if do_prof:
            results.append(process_kind(base_url, token, "professores", allowed_coligadas, idperlet, DEBUG_WS))
    except Exception as exc:
        log(f"Falha geral na execução: {exc}")
        return 3

    elapsed = now() - t_all

    # Consolida
    total_created = sum(r["created"] for r in results)
    total_updated = sum(r["updated"] for r in results)
    total_unchanged = sum(r["unchanged"] for r in results)
    total_ignored = sum(r["ignored"] for r in results)
    total_failed = sum(r["failed"] for r in results)

    log("==== RELATÓRIO FINAL ====")
    for r in results:
        kind = r["kind"]
        log(
            f"{kind.capitalize()}: considerados={r['considered']} | criados={r['created']} | "
            f"atualizados={r['updated']} | inalterados={r['unchanged']} | ignorados={r['ignored']} | falhas={r['failed']}"
        )

    # Linha “parseável” pelo UI
    log(
        "RESUMO_FINAL: "
        f"criadas={total_created} atualizadas={total_updated} inalteradas={total_unchanged} "
        f"ignoradas={total_ignored} falhas={total_failed} tempo={elapsed:.1f}s"
    )

    log("==== FIM - INSERÇÃO DE PESSOAS ====")
    return 0 if total_failed == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())