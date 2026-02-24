from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

DB_PATH = Path(__file__).resolve().parent / "db" / "app.db"


def log(msg: str) -> None:
    print(msg, flush=True)


def normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def mask_token(token: str) -> str:
    if not token:
        return "(vazio)"
    if len(token) <= 6:
        return "****" + token
    return "****" + token[-6:]


def normalize_category_name(text: str) -> str:
    return (text or "").strip()


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


def get_rm_queries() -> Dict[str, str]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT coligadas, periodos, cursos, turmas, salas FROM rm_queries WHERE id = 1"
        )
        row = cur.fetchone()
        if not row:
            return {}
        return {
            "coligadas": row[0] or "",
            "periodos": row[1] or "",
            "cursos": row[2] or "",
            "turmas": row[3] or "",
            "salas": row[4] or "",
        }
    finally:
        conn.close()


def moodle_call(
    base_url: str,
    token: str,
    function: str,
    params: Dict[str, Any],
    force_get: bool = False,
) -> Any:
    base_url = normalize_base_url(base_url)
    url = base_url + "/webservice/rest/server.php"

    payload: Dict[str, Any] = {
        "wstoken": token,
        "wsfunction": function,
        "moodlewsrestformat": "json",
    }
    payload.update(params)

    log(f"Chamando Moodle: {function} em {url} (token {mask_token(token)})")

    def parse_or_raise(resp: requests.Response) -> Any:
        try:
            data = resp.json()
        except Exception:
            body_preview = resp.text[:400].replace("\n", " ").replace("\r", " ")
            raise RuntimeError(
                f"Resposta não é JSON (HTTP {resp.status_code}). Trecho: {body_preview}"
            )

        if isinstance(data, dict) and data.get("exception"):
            errorcode = data.get("errorcode")
            message = data.get("message")
            debuginfo = data.get("debuginfo")
            raise RuntimeError(
                f"{errorcode}: {message}" + (f" | debuginfo: {debuginfo}" if debuginfo else "")
            )
        return data

    if force_get:
        full_url = requests.Request("GET", url, params=payload).prepare().url
        safe_url = full_url.replace(token, "****")
        log(f"URL (GET): {safe_url}")
        resp = requests.get(url, params=payload, timeout=30)
        resp.raise_for_status()
        return parse_or_raise(resp)

    try:
        log("Método: POST")
        resp = requests.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        return parse_or_raise(resp)
    except Exception as exc:
        log(f"POST falhou ({exc}). Tentando GET...")
        full_url = requests.Request("GET", url, params=payload).prepare().url
        safe_url = full_url.replace(token, "****")
        log(f"URL (GET): {safe_url}")
        resp = requests.get(url, params=payload, timeout=30)
        resp.raise_for_status()
        return parse_or_raise(resp)


def test_token(base_url: str, token: str, force_get: bool) -> None:
    log("Testando token do Moodle (listando categorias raiz)...")
    moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {"criteria[0][key]": "parent", "criteria[0][value]": "0"},
        force_get=force_get,
    )
    log("Token válido para operações de curso/categoria.")


def find_category_id(
    base_url: str, token: str, name: str, parent_id: int, force_get: bool
) -> int | None:
    data = moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {"criteria[0][key]": "parent", "criteria[0][value]": str(parent_id)},
        force_get=force_get,
    )
    if isinstance(data, list) and data:
        target = name.strip()
        for item in data:
            if str(item.get("name", "")).strip() == target:
                return int(item.get("id"))
    return None


def create_category(
    base_url: str, token: str, name: str, parent_id: int, force_get: bool
) -> int:
    data = moodle_call(
        base_url,
        token,
        "core_course_create_categories",
        {"categories[0][name]": name, "categories[0][parent]": str(parent_id)},
        force_get=force_get,
    )
    if isinstance(data, list) and data:
        return int(data[0].get("id"))
    raise RuntimeError(f"Falha ao criar categoria (retorno inesperado): {data!r}")


def rm_connect() -> Optional["pyodbc.Connection"]:
    cfg = get_rm_config()
    if not cfg:
        return None

    host, db_name, username, password = cfg
    try:
        import pyodbc  # type: ignore
    except Exception:
        return None

    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={host};"
        f"DATABASE={db_name};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=10)


def fetch_cursos_rows() -> Tuple[List[tuple], List[str]]:
    queries = get_rm_queries()
    sql = (queries.get("cursos") or "").strip()
    if not sql:
        log("Consulta 'cursos' não configurada em rm_queries.")
        return ([], [])

    conn = rm_connect()
    if not conn:
        log("Config RM/pyodbc indisponível. Não foi possível conectar ao RM.")
        return ([], [])

    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [desc[0].lower() for desc in cur.description] if cur.description else []
        return (rows, cols)
    finally:
        conn.close()


def fetch_coligadas_from_cursos_rows(rows: List[tuple], cols: List[str], allowed: set[str]) -> List[Tuple[str, str]]:
    def idx(name: str) -> Optional[int]:
        return cols.index(name) if name in cols else None

    i_cod = idx("codcoligada")
    i_nome = idx("coligada")
    if i_cod is None or i_nome is None:
        log("A consulta 'cursos' deve retornar as colunas CODCOLIGADA e COLIGADA.")
        return []

    seen: set[str] = set()
    out: List[Tuple[str, str]] = []
    for r in rows:
        cod = r[i_cod]
        nome = r[i_nome]
        if cod is None:
            continue
        cod_s = str(cod).strip()
        if allowed and cod_s not in allowed:
            continue
        if cod_s in seen:
            continue
        seen.add(cod_s)
        out.append((cod_s, "" if nome is None else str(nome).strip()))
    return out


def fetch_modalidades_for_coligada_periodo(
    rows: List[tuple],
    cols: List[str],
    codcoligada: str,
    idperlet: str,
) -> List[str]:
    """
    Extrai as modalidades (CATMODALIDADE) para uma coligada e um período (IDPERLET)
    a partir da consulta "cursos".
    """
    def idx(name: str) -> Optional[int]:
        return cols.index(name) if name in cols else None

    i_codcol = idx("codcoligada")
    i_idper = idx("idperlet")
    i_mod = idx("catmodalidade")

    if i_codcol is None or i_idper is None or i_mod is None:
        log("A consulta 'cursos' deve retornar CODCOLIGADA, IDPERLET e CATMODALIDADE.")
        return []

    target_col = str(codcoligada).strip()
    target_idp = str(idperlet).strip()

    seen: set[str] = set()
    mods: List[str] = []
    for r in rows:
        if str(r[i_codcol]).strip() != target_col:
            continue
        if str(r[i_idper]).strip() != target_idp:
            continue
        m = "" if r[i_mod] is None else str(r[i_mod]).strip()
        if not m:
            continue
        if m in seen:
            continue
        seen.add(m)
        mods.append(m)

    mods.sort(key=lambda s: s.lower())
    return mods


def fetch_periodo_for_coligada(codcoligada: str, codperlet_value: str) -> Optional[Tuple[str, str]]:
    """
    Dada uma coligada (CODCOLIGADA) e o VALUE do seletor (CODPERLET),
    encontra na query "periodos" o (IDPERLET, PERIODO) correspondente.
    """
    queries = get_rm_queries()
    sql = (queries.get("periodos") or "").strip()
    if not sql:
        log("Consulta 'periodos' não configurada em rm_queries.")
        return None

    conn = rm_connect()
    if not conn:
        log("Config RM/pyodbc indisponível. Não foi possível conectar ao RM.")
        return None

    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [desc[0].lower() for desc in cur.description] if cur.description else []
    finally:
        conn.close()

    if not rows or not cols:
        return None

    def idx(name: str) -> Optional[int]:
        return cols.index(name) if name in cols else None

    i_codcol = idx("codcoligada")
    i_codper = idx("codperlet")
    i_label = idx("periodo")
    i_idper = idx("idperlet")

    if i_codcol is None or i_codper is None or i_label is None or i_idper is None:
        log("A consulta 'periodos' deve retornar CODCOLIGADA, CODPERLET, PERIODO e IDPERLET.")
        return None

    target_col = str(codcoligada).strip()
    target_codper = str(codperlet_value).strip()

    for r in rows:
        if str(r[i_codcol]).strip() != target_col:
            continue
        if str(r[i_codper]).strip() != target_codper:
            continue
        idperlet = "" if r[i_idper] is None else str(r[i_idper]).strip()
        label = "" if r[i_label] is None else str(r[i_label]).strip()
        if not idperlet:
            return None
        return (idperlet, label)

    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    # VALUE do seletor: CODPERLET
    parser.add_argument("--periodo", default="Todos")
    parser.add_argument("--create-categories", default="1")
    parser.add_argument("--force-get", action="store_true", help="Força GET (compatibilidade)")
    args = parser.parse_args()

    platform = get_platform(args.platform_id)
    if not platform:
        log("Plataforma não encontrada.")
        return 1

    platform_name, url, token, coligadas_csv = platform
    url = normalize_base_url(url)

    periodo_value = (args.periodo or "").strip()
    criar_periodo = bool(periodo_value) and periodo_value.lower() != "todos"

    log(f"Plataforma: {platform_name} (ID {args.platform_id})")
    log(f"URL base: {url}")
    log(f"Token (assinatura): {mask_token(token)}")
    log(f"Período (VALUE/CODPERLET): {periodo_value}")
    log(f"Criar categorias: {'Sim' if args.create_categories == '1' else 'Não'}")
    log(f"Forçar GET: {'Sim' if args.force_get else 'Não'}")

    try:
        test_token(url, token, force_get=args.force_get)
    except Exception as exc:
        log(f"Falha no token/site: {exc}")
        return 2

    if args.create_categories != "1":
        log("Criação de categorias desativada.")
        return 0

    allowed = {c.strip() for c in (coligadas_csv or "").split(",") if c.strip()}
    if not allowed:
        log("Nenhuma coligada selecionada na plataforma.")
        return 0

    # Carrega a consulta cursos uma vez (para extrair coligadas e modalidades)
    cursos_rows, cursos_cols = fetch_cursos_rows()
    if not cursos_rows or not cursos_cols:
        log("Consulta 'cursos' não retornou dados/colunas.")
        return 0

    # 2º nível: coligadas via cursos (CODCOLIGADA + COLIGADA)
    coligadas = fetch_coligadas_from_cursos_rows(cursos_rows, cursos_cols, allowed)
    if not coligadas:
        log("Nenhuma coligada encontrada via consulta 'cursos' (ou colunas ausentes).")
        return 0

    try:
        # 1) SALAS
        log("Verificando categoria raiz 'SALAS'...")
        root_id = find_category_id(url, token, "SALAS", 0, force_get=args.force_get)
        if root_id is None:
            log("Criando categoria raiz 'SALAS'...")
            root_id = create_category(url, token, "SALAS", 0, force_get=args.force_get)
            log(f"Categoria 'SALAS' criada (id={root_id}).")
        else:
            log(f"Categoria 'SALAS' já existe (id={root_id}).")

        log("Criando COLIGADAS (2º), PERÍODO (3º) e MODALIDADE (4º) conforme seleção...")

        if not criar_periodo:
            log("Período = 'Todos' (ou vazio). Não serão criados níveis 3 (Período) e 4 (Modalidade).")

        for codcoligada, coligada_nome in coligadas:
            coligada_nome = normalize_category_name(coligada_nome) or codcoligada
            col_cat_name = f"{codcoligada}-{coligada_nome}"

            col_id = find_category_id(url, token, col_cat_name, root_id, force_get=args.force_get)
            if col_id is None:
                col_id = create_category(url, token, col_cat_name, root_id, force_get=args.force_get)
                log(f"- Coligada criada: {col_cat_name} (id={col_id}).")
                time.sleep(0.1)
            else:
                log(f"- Coligada já existe: {col_cat_name} (id={col_id}).")

            if not criar_periodo:
                continue

            per = fetch_periodo_for_coligada(codcoligada, periodo_value)
            if not per:
                log(f"  - Período CODPERLET={periodo_value} não encontrado para CODCOLIGADA={codcoligada}. Pulando.")
                continue

            idperlet, periodo_label = per
            periodo_label = normalize_category_name(periodo_label) or periodo_value

            # 3º nível: Período (nome = PERIODO)
            per_id = find_category_id(url, token, periodo_label, col_id, force_get=args.force_get)
            if per_id is None:
                per_id = create_category(url, token, periodo_label, col_id, force_get=args.force_get)
                log(f"  - Período criado: {periodo_label} (IDPERLET={idperlet}) (id={per_id}).")
                time.sleep(0.1)
            else:
                log(f"  - Período já existe: {periodo_label} (IDPERLET={idperlet}) (id={per_id}).")

            # 4º nível: Modalidades (nome = CATMODALIDADE), filtradas por CODCOLIGADA + IDPERLET
            modalidades = fetch_modalidades_for_coligada_periodo(
                cursos_rows, cursos_cols, codcoligada, idperlet
            )
            if not modalidades:
                log(f"    - Nenhuma modalidade encontrada (CODCOLIGADA={codcoligada}, IDPERLET={idperlet}).")
                continue

            log(f"    - Criando Modalidades ({len(modalidades)}) abaixo do Período...")
            for mod in modalidades:
                mod_name = normalize_category_name(mod)
                if not mod_name:
                    continue
                mod_id = find_category_id(url, token, mod_name, per_id, force_get=args.force_get)
                if mod_id is None:
                    mod_id = create_category(url, token, mod_name, per_id, force_get=args.force_get)
                    log(f"      - Modalidade criada: {mod_name} (id={mod_id}).")
                    time.sleep(0.05)
                else:
                    log(f"      - Modalidade já existe: {mod_name} (id={mod_id}).")

        log("Execução concluída.")
        return 0

    except Exception as exc:
        log(f"Erro ao criar categorias: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())