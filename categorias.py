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


def mask_token(token: str) -> str:
    if not token:
        return "(vazio)"
    if len(token) <= 6:
        return "****" + token
    return "****" + token[-6:]


def normalize_base_url(base_url: str) -> str:
    # Remove espaços e barra final, evita erros por "url " no sqlite
    return base_url.strip().rstrip("/")


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


def get_coligadas_query() -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT coligadas FROM rm_queries WHERE id = 1")
        row = cur.fetchone()
        return row[0] if row and row[0] else ""
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

    # Sempre logar a URL (sem token) e assinatura do token
    safe_sig = mask_token(token)
    log(f"Chamando Moodle: {function} em {url} (token {safe_sig})")

    def parse_or_raise(resp: requests.Response) -> Any:
        # Tenta JSON; se falhar, mostra um trecho do body para diagnosticar redirect/WAF/html
        try:
            data = resp.json()
        except Exception:
            body_preview = resp.text[:400].replace("\n", " ").replace("\r", " ")
            raise RuntimeError(
                f"Resposta não é JSON (HTTP {resp.status_code}). Trecho: {body_preview}"
            )

        if isinstance(data, dict) and data.get("exception"):
            # Mostra tudo (sem token) para diagnóstico
            errorcode = data.get("errorcode")
            message = data.get("message")
            debuginfo = data.get("debuginfo")
            raise RuntimeError(
                f"{errorcode}: {message}" + (f" | debuginfo: {debuginfo}" if debuginfo else "")
            )
        return data

    # Se quiser replicar exatamente o navegador, force_get=True
    if force_get:
        full_url = requests.Request("GET", url, params=payload).prepare().url
        safe_url = full_url.replace(token, "****")
        log(f"URL (GET): {safe_url}")
        resp = requests.get(url, params=payload, timeout=30)
        resp.raise_for_status()
        return parse_or_raise(resp)

    # Fluxo padrão: tenta POST e, se der erro, tenta GET
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
    log("Testando token do Moodle...")
    moodle_call(base_url, token, "core_webservice_get_site_info", {}, force_get=force_get)
    log("Token válido.")


def find_category_id(
    base_url: str,
    token: str,
    name: str,
    parent_id: int,
    force_get: bool,
) -> int | None:
    # Mais robusto: busca por parent e filtra localmente por name
    data = moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {
            "criteria[0][key]": "parent",
            "criteria[0][value]": str(parent_id),
        },
        force_get=force_get,
    )

    if isinstance(data, list) and data:
        for item in data:
            if str(item.get("name", "")).strip() == name.strip():
                return int(item.get("id"))
    return None


def create_category(
    base_url: str,
    token: str,
    name: str,
    parent_id: int,
    force_get: bool,
) -> int:
    data = moodle_call(
        base_url,
        token,
        "core_course_create_categories",
        {
            "categories[0][name]": name,
            "categories[0][parent]": str(parent_id),
        },
        force_get=force_get,
    )
    if isinstance(data, list) and data:
        return int(data[0].get("id"))
    raise RuntimeError(f"Falha ao criar categoria (retorno inesperado): {data!r}")


def fetch_coligadas_map() -> Dict[str, str]:
    cfg = get_rm_config()
    sql = get_coligadas_query().strip()
    if not cfg or not sql:
        return {}

    host, db_name, username, password = cfg
    try:
        import pyodbc  # type: ignore
    except Exception:
        return {}

    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={host};"
        f"DATABASE={db_name};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )
    mapping: Dict[str, str] = {}
    with pyodbc.connect(conn_str, timeout=10) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [desc[0].lower() for desc in cur.description] if cur.description else []

    if not rows or not columns:
        return mapping

    def col_index(name: str) -> int | None:
        return columns.index(name) if name in columns else None

    idx_cod = col_index("codcoligada")
    idx_nome = col_index("nomefantasia") or col_index("coligada") or col_index("nome")
    if idx_cod is None or idx_nome is None:
        return mapping

    for row in rows:
        cod = row[idx_cod]
        nome = row[idx_nome]
        if cod is None:
            continue
        mapping[str(cod)] = "" if nome is None else str(nome)
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    parser.add_argument("--periodo", default="Todos")
    parser.add_argument("--create-categories", default="1")
    parser.add_argument("--force-get", action="store_true", help="Força GET (igual ao teste do navegador)")
    args = parser.parse_args()

    platform = get_platform(args.platform_id)
    if not platform:
        log("Plataforma não encontrada.")
        return 1

    name, url, token, coligadas = platform
    url = normalize_base_url(url)

    log(f"Plataforma: {name} (ID {args.platform_id})")
    log(f"URL base: {url}")
    log(f"Token (assinatura): {mask_token(token)}")
    log(f"Período: {args.periodo}")
    log(f"Criar categorias: {'Sim' if args.create_categories == '1' else 'Não'}")
    log(f"Forçar GET: {'Sim' if args.force_get else 'Não'}")

    try:
        test_token(url, token, force_get=args.force_get)
    except Exception as exc:
        log(f"Falha no token/site info: {exc}")
        return 2

    if args.create_categories != "1":
        log("Criação de categorias desativada.")
        return 0

    coligadas_list = [c.strip() for c in coligadas.split(",") if c.strip()]
    if not coligadas_list:
        log("Nenhuma coligada selecionada na plataforma.")
        return 0

    col_map = fetch_coligadas_map()

    try:
        log("Verificando categoria raiz 'SALAS'...")
        root_id = find_category_id(url, token, "SALAS", 0, force_get=args.force_get)
        if root_id is None:
            log("Criando categoria raiz 'SALAS'...")
            root_id = create_category(url, token, "SALAS", 0, force_get=args.force_get)
            log(f"Categoria 'SALAS' criada (id={root_id}).")
        else:
            log(f"Categoria 'SALAS' já existe (id={root_id}).")

        log("Criando categorias de Coligada (se não existirem)...")
        for cod in coligadas_list:
            nome = col_map.get(cod, name)
            cat_name = f"{cod}-{nome}"
            existing = find_category_id(url, token, cat_name, root_id, force_get=args.force_get)
            if existing:
                log(f"- {cat_name} já existe (id={existing}).")
                continue
            new_id = create_category(url, token, cat_name, root_id, force_get=args.force_get)
            log(f"- {cat_name} criada (id={new_id}).")
            time.sleep(0.1)

    except Exception as exc:
        log(f"Erro ao criar categorias: {exc}")
        return 3

    log("Execução concluída.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())