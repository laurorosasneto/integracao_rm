from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, Set

import requests

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "app.db"


def log(msg: str) -> None:
    print(msg, flush=True)


def now_ms() -> float:
    return time.monotonic()


def ms_to_s(ms: float) -> str:
    return f"{ms:.3f}s"


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
    """
    rm_queries tem colunas: coligadas, periodos, cursos, turmas, salas
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT coligadas, periodos, cursos, turmas, salas FROM rm_queries WHERE id = 1")
        row = cur.fetchone()
        if not row:
            return ""
        cols = ["coligadas", "periodos", "cursos", "turmas", "salas"]
        data = dict(zip(cols, row))
        return (data.get(key) or "").strip()
    finally:
        conn.close()


def moodle_call(base_url: str, token: str, function: str, params: Dict[str, Any]) -> Any:
    url = base_url.rstrip("/") + "/webservice/rest/server.php"
    payload = {
        "wstoken": token,
        "wsfunction": function,
        "moodlewsrestformat": "json",
    }
    payload.update(params)

    try:
        log(f"Chamando Moodle: {function} em {url} (token oculto)")
        resp = requests.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log(f"POST falhou: {exc}. Tentando GET...")
        safe_params = dict(payload)
        safe_params["wstoken"] = "****"
        safe_url = requests.Request("GET", url, params=safe_params).prepare().url
        log(f"URL (GET): {safe_url}")
        resp = requests.get(url, params=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"{data.get('errorcode')}: {data.get('message')}")
    return data


def test_token(base_url: str, token: str) -> None:
    log("Testando token do Moodle...")
    moodle_call(base_url, token, "core_webservice_get_site_info", {})
    log("Token válido.")


def find_category_id(base_url: str, token: str, name: str, parent_id: int) -> int | None:
    data = moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {
            "criteria[0][key]": "parent",
            "criteria[0][value]": str(parent_id),
            "criteria[1][key]": "name",
            "criteria[1][value]": name,
        },
    )
    if isinstance(data, list) and data:
        return int(data[0].get("id"))
    return None


def create_category(base_url: str, token: str, name: str, parent_id: int) -> int:
    data = moodle_call(
        base_url,
        token,
        "core_course_create_categories",
        {
            "categories[0][name]": name,
            "categories[0][parent]": str(parent_id),
        },
    )
    if isinstance(data, list) and data:
        return int(data[0].get("id"))
    raise RuntimeError("Falha ao criar categoria")


def rm_connect() -> Optional[Tuple[str, str, str, str]]:
    cfg = get_rm_config()
    if not cfg:
        return None
    return cfg


def rm_fetch(sql: str) -> Tuple[List[str], List[tuple]]:
    """
    Executa SQL no RM e retorna (columns_lower, rows)
    """
    cfg = rm_connect()
    if not cfg or not sql.strip():
        return ([], [])

    host, db_name, username, password = cfg

    try:
        import pyodbc  # type: ignore
    except Exception:
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

    with pyodbc.connect(conn_str, timeout=20) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [desc[0].lower() for desc in cur.description] if cur.description else []
    return (columns, rows)


def col_index(columns: List[str], name: str) -> Optional[int]:
    name = name.lower()
    return columns.index(name) if name in columns else None


def normalize_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    parser.add_argument("--periodo", default="")  # agora é IDPERLET (ou vazio/"Todos")
    parser.add_argument("--create-categories", default="1")
    args = parser.parse_args()

    platform = get_platform(args.platform_id)
    if not platform:
        log("Plataforma não encontrada.")
        return 1

    name, url, token, coligadas_csv = platform

    log(f"Plataforma: {name} (ID {args.platform_id})")
    log(f"Período selecionado (IDPERLET): {args.periodo}")
    log(f"Criar categorias: {'Sim' if args.create_categories == '1' else 'Não'}")

    try:
        test_token(url, token)
    except Exception as exc:
        log(f"Falha no token/site info: {exc}")
        return 2

    if args.create_categories != "1":
        log("Criação de categorias desativada.")
        return 0

    allowed_coligadas = {c.strip() for c in (coligadas_csv or "").split(",") if c.strip()}
    if not allowed_coligadas:
        log("Nenhuma coligada selecionada na plataforma.")
        return 0

    # Consulta base: categorias/cursos
    sql_cursos = get_rm_query("cursos")
    if not sql_cursos:
        log("Consulta RM 'cursos' está vazia. Cole na aba Consultas RM > Categorias.")
        return 3

    t0 = now_ms()
    log("Executando consulta RM: cursos/categorias")
    columns, rows = rm_fetch(sql_cursos)
    log(f"Consulta RM cursos/categorias concluída em {ms_to_s(now_ms() - t0)} ({len(rows)} linhas)")

    if not columns or not rows:
        log("Consulta RM 'cursos/categorias' não retornou dados.")
        return 3

    # Índices obrigatórios na consulta cursos/categorias
    idx_codcol = col_index(columns, "codcoligada")
    idx_coligada = col_index(columns, "coligada")
    idx_codperlet = col_index(columns, "periodo") or col_index(columns, "codperlet") or col_index(columns, "catperiodo")
    idx_idperlet = col_index(columns, "idperlet")
    idx_catmodalidade = col_index(columns, "catmodalidade")

    missing = []
    if idx_codcol is None:
        missing.append("CODCOLIGADA")
    if idx_coligada is None:
        missing.append("COLIGADA")
    if idx_codperlet is None:
        missing.append("CODPERLET/PERIODO/CATPERIODO")
    if idx_idperlet is None:
        missing.append("IDPERLET")
    if idx_catmodalidade is None:
        missing.append("CATMODALIDADE")

    if missing:
        log("A consulta 'cursos/categorias' deve retornar as colunas: CODCOLIGADA, COLIGADA, CODPERLET (ou PERIODO/CATPERIODO), IDPERLET, CATMODALIDADE.")
        log("Faltando: " + ", ".join(missing))
        return 3

    # Filtra por IDPERLET selecionado
    selected_idperlet = normalize_str(args.periodo)
    filter_by_period = bool(selected_idperlet) and selected_idperlet.lower() != "todos"

    # Estruturas:
    coligadas_map: Dict[str, str] = {}
    periodos_por_col: Dict[str, Set[str]] = {}  # codcoligada -> set(CODPERLET)
    modalidades_por_col_periodo: Dict[Tuple[str, str], Set[str]] = {}  # (codcol, codperlet) -> set(modalidades)

    for r in rows:
        codcol = normalize_str(r[idx_codcol])
        coligada_nome = normalize_str(r[idx_coligada])
        codperlet = normalize_str(r[idx_codperlet]).replace("/", "-")
        idperlet = normalize_str(r[idx_idperlet])
        catmodalidade = normalize_str(r[idx_catmodalidade])

        if not codcol or codcol not in allowed_coligadas:
            continue

        if filter_by_period and idperlet != selected_idperlet:
            continue

        if codcol not in coligadas_map:
            coligadas_map[codcol] = coligada_nome

        if codperlet:
            periodos_por_col.setdefault(codcol, set()).add(codperlet)
            modalidades_por_col_periodo.setdefault((codcol, codperlet), set()).add(catmodalidade)

    if not coligadas_map:
        log("Após filtros, não há coligadas/períodos para processar. Verifique coligadas selecionadas e o período.")
        return 0

    try:
        # 1) raiz SALAS
        log("Verificando categoria raiz 'SALAS'...")
        root_id = find_category_id(url, token, "SALAS", 0)
        if root_id is None:
            log("Criando categoria raiz 'SALAS'...")
            root_id = create_category(url, token, "SALAS", 0)
            log(f"Categoria 'SALAS' criada (id={root_id}).")
        else:
            log(f"Categoria 'SALAS' já existe (id={root_id}).")

        # 2) Coligadas (2º nível)
        log("Criando categorias de Coligada (2º nível)...")
        coligada_cat_ids: Dict[str, int] = {}
        for codcol, col_nome in sorted(coligadas_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
            cat_name = f"{codcol}-{col_nome}".strip("-")
            existing = find_category_id(url, token, cat_name, root_id)
            if existing:
                coligada_cat_ids[codcol] = existing
                log(f"- Coligada já existe: {cat_name} (id={existing}).")
            else:
                new_id = create_category(url, token, cat_name, root_id)
                coligada_cat_ids[codcol] = new_id
                log(f"- Coligada criada: {cat_name} (id={new_id}).")
            time.sleep(0.05)

        # 3) Período (3º nível) — nome = CODPERLET
        log("Criando categorias de Período (3º nível)...")
        periodo_cat_ids: Dict[Tuple[str, str], int] = {}

        for codcol, periods in periodos_por_col.items():
            parent_id = coligada_cat_ids.get(codcol)
            if not parent_id:
                continue

            for codperlet in sorted(periods, reverse=True):
                period_name = codperlet
                if not period_name:
                    continue

                existing = find_category_id(url, token, period_name, parent_id)
                if existing:
                    periodo_cat_ids[(codcol, codperlet)] = existing
                    log(f"  - Período já existe: {codcol} > {period_name} (id={existing})")
                else:
                    new_id = create_category(url, token, period_name, parent_id)
                    periodo_cat_ids[(codcol, codperlet)] = new_id
                    log(f"  - Período criado: {codcol} > {period_name} (id={new_id})")
                time.sleep(0.05)

        # 4) Modalidade (4º nível)
        log("Criando categorias de Modalidade (4º nível)...")
        total_modalidades = 0

        for (codcol, codperlet), modalidades in modalidades_por_col_periodo.items():
            parent_id = periodo_cat_ids.get((codcol, codperlet))
            if not parent_id:
                log(f"  - Aviso: período não criado/encontrado para CODCOLIGADA={codcol} CODPERLET={codperlet}. Pulando modalidades.")
                continue

            mods = sorted({m for m in modalidades if m.strip()})
            if not mods:
                continue

            log(f"  - Processando modalidades: CODCOLIGADA={codcol} CODPERLET={codperlet} ({len(mods)} itens)")
            for mod in mods:
                existing = find_category_id(url, token, mod, parent_id)
                if existing:
                    log(f"    * Modalidade já existe: {mod} (id={existing})")
                else:
                    new_id = create_category(url, token, mod, parent_id)
                    log(f"    * Modalidade criada: {mod} (id={new_id})")
                total_modalidades += 1
                time.sleep(0.05)

        log(f"Total de modalidades processadas: {total_modalidades}")
        log("Execução concluída.")
        return 0

    except Exception as exc:
        log(f"Erro ao criar categorias: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
