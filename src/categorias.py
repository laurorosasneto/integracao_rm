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
        cur = conn.execute(
            "SELECT coligadas, periodos, cursos, turmas, salas FROM rm_queries WHERE id = 1"
        )
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
        resp = requests.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log(f"POST falhou: {exc}. Tentando GET...")
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


def get_categories_by_name(base_url: str, token: str, name: str) -> list[dict]:
    data = moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {
            "criteria[0][key]": "name",
            "criteria[0][value]": name,
        },
    )
    return data if isinstance(data, list) else []


def find_root_category_id_by_name(base_url: str, token: str, name: str) -> int | None:
    """
    Encontra categoria com `name` cujo parent == 0 (raiz).
    Se houver múltiplas, escolhe a de menor id (determinístico).
    """
    cats = get_categories_by_name(base_url, token, name)

    roots: list[dict] = []
    non_roots: list[dict] = []

    for c in cats:
        try:
            parent = int(c.get("parent", -1))
            if parent == 0:
                roots.append(c)
            else:
                non_roots.append(c)
        except Exception:
            continue

    if non_roots:
        try:
            ids = [str(int(x.get("id"))) for x in non_roots if x.get("id") is not None]
        except Exception:
            ids = []
        if ids:
            log(f"Aviso: existe(m) categoria(s) chamada(s) '{name}' que NÃO são raiz (parent!=0): ids={ids}. Elas serão ignoradas como root.")

    if not roots:
        return None

    roots_sorted = sorted(roots, key=lambda x: int(x.get("id", 10**18)))
    chosen = roots_sorted[0]

    if len(roots_sorted) > 1:
        ids = [str(int(x.get("id"))) for x in roots_sorted if x.get("id") is not None]
        log(f"Aviso: existem múltiplas categorias raiz chamadas '{name}': ids={ids}. Usando id={int(chosen.get('id'))}.")

    return int(chosen.get("id"))


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


def ensure_category(base_url: str, token: str, name: str, parent_id: int, counters: Dict[str, Dict[str, int]], bucket: str) -> int:
    """
    Garante categoria sob um parent específico, contabilizando:
    - counters[bucket]["exists"]
    - counters[bucket]["created"]
    """
    existing = find_category_id(base_url, token, name, parent_id)
    if existing is not None:
        counters.setdefault(bucket, {}).setdefault("exists", 0)
        counters[bucket]["exists"] += 1
        return existing

    new_id = create_category(base_url, token, name, parent_id)
    counters.setdefault(bucket, {}).setdefault("created", 0)
    counters[bucket]["created"] += 1
    return new_id


def rm_connect() -> Optional[Tuple[str, str, str, str]]:
    return get_rm_config()


def rm_fetch(sql: str) -> Tuple[List[str], List[tuple]]:
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


def summarize_counts(counters: Dict[str, Dict[str, int]]) -> None:
    log("Relatório de criação (por nível):")
    order = ["coligadas", "periodos", "modalidades", "cursos", "turmas"]
    labels = {
        "coligadas": "Nível 2 - Coligadas",
        "periodos": "Nível 3 - Períodos",
        "modalidades": "Nível 4 - Modalidades",
        "cursos": "Nível 5 - Cursos",
        "turmas": "Nível 6 - Turmas",
    }
    for k in order:
        created = counters.get(k, {}).get("created", 0)
        exists = counters.get(k, {}).get("exists", 0)
        log(f"- {labels[k]}: criadas={created} | já existiam={exists}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    parser.add_argument("--periodo", default="")  # CATPERIODO (ou vazio/"Todos")
    parser.add_argument("--create-categories", default="1")
    args = parser.parse_args()

    platform = get_platform(args.platform_id)
    if not platform:
        log("Plataforma não encontrada.")
        return 1

    platform_name, url, token, coligadas_csv = platform

    log("==== INÍCIO DA EXECUÇÃO ====")
    log(f"Plataforma: {platform_name} (ID {args.platform_id})")
    log(f"Período selecionado (CATPERIODO): {args.periodo or 'Todos'}")
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
    log(f"Filtro - Coligadas permitidas (platform): {sorted(allowed_coligadas)}")
    if not allowed_coligadas:
        log("Nenhuma coligada selecionada na plataforma.")
        return 0

    sql_cursos = get_rm_query("cursos")
    if not sql_cursos:
        log("Consulta RM 'cursos' está vazia. Cole na aba Consultas RM > Categorias.")
        return 3

    log("SQL RM (cursos/categorias):")
    log(sql_cursos)

    t0 = now_ms()
    log("Executando consulta RM: cursos/categorias")
    columns, rows = rm_fetch(sql_cursos)
    log(f"Consulta RM cursos/categorias concluída em {ms_to_s(now_ms() - t0)} ({len(rows)} linhas)")

    if not columns or not rows:
        log("Consulta RM 'cursos/categorias' não retornou dados.")
        return 3

    idx_codcol = col_index(columns, "codcoligada")
    idx_coligada = col_index(columns, "coligada")
    idx_codperlet = col_index(columns, "periodo") or col_index(columns, "codperlet") or col_index(columns, "catperiodo")
    idx_idperlet = col_index(columns, "idperlet")
    idx_catmodalidade = col_index(columns, "catmodalidade")
    idx_curso = col_index(columns, "curso")
    idx_codturma = col_index(columns, "codturma")

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
    if idx_curso is None:
        missing.append("CURSO")
    if idx_codturma is None:
        missing.append("CODTURMA")

    if missing:
        log(
            "A consulta 'cursos/categorias' deve retornar as colunas: "
            "CODCOLIGADA, COLIGADA, CODPERLET (ou PERIODO/CATPERIODO), IDPERLET, CATMODALIDADE, CURSO, CODTURMA."
        )
        log("Faltando: " + ", ".join(missing))
        return 3

    selected_catperiodo = normalize_str(args.periodo).replace("/", "-")
    filter_by_period = bool(selected_catperiodo) and selected_catperiodo.lower() != "todos"
    log(f"Filtro - CATPERIODO aplicado: {selected_catperiodo if filter_by_period else '(nenhum)'}")

    # Estruturas
    coligadas_map: Dict[str, str] = {}
    periodos_por_col: Dict[str, Set[str]] = {}
    modalidades_por_col_periodo: Dict[Tuple[str, str], Set[str]] = {}
    cursos_por_col_periodo_modalidade: Dict[Tuple[str, str, str], Set[str]] = {}
    turmas_por_col_periodo_modalidade_curso: Dict[Tuple[str, str, str, str], Set[str]] = {}

    for r in rows:
        codcol = normalize_str(r[idx_codcol])
        coligada_nome = normalize_str(r[idx_coligada])
        catperiodo = normalize_str(r[idx_codperlet]).replace("/", "-")
        _idperlet = normalize_str(r[idx_idperlet])
        catmodalidade = normalize_str(r[idx_catmodalidade])
        curso = normalize_str(r[idx_curso])
        codturma = normalize_str(r[idx_codturma])

        if not codcol or codcol not in allowed_coligadas:
            continue
        if filter_by_period and catperiodo != selected_catperiodo:
            continue
        if not catperiodo or not catmodalidade or not curso or not codturma:
            continue

        if codcol not in coligadas_map:
            coligadas_map[codcol] = coligada_nome

        periodos_por_col.setdefault(codcol, set()).add(catperiodo)
        modalidades_por_col_periodo.setdefault((codcol, catperiodo), set()).add(catmodalidade)
        cursos_por_col_periodo_modalidade.setdefault((codcol, catperiodo, catmodalidade), set()).add(curso)
        turmas_por_col_periodo_modalidade_curso.setdefault((codcol, catperiodo, catmodalidade, curso), set()).add(codturma)

    log("Resumo do que será processado (após filtros):")
    log(f"- Coligadas: {len(coligadas_map)}")
    log(f"- Períodos (total somado): {sum(len(v) for v in periodos_por_col.values())}")
    log(f"- Modalidades (pares coligada+período): {len(modalidades_por_col_periodo)}")
    log(f"- Grupos de curso (coligada+período+modalidade): {len(cursos_por_col_periodo_modalidade)}")
    log(f"- Grupos de turma (coligada+período+modalidade+curso): {len(turmas_por_col_periodo_modalidade_curso)}")

    if not coligadas_map:
        log("Após filtros, não há coligadas/períodos para processar.")
        return 0

    counters: Dict[str, Dict[str, int]] = {}

    try:
        log("Verificando categoria raiz 'SALAS' (parent=0)...")
        root_id = find_root_category_id_by_name(url, token, "SALAS")
        if root_id is None:
            log("Criando categoria raiz 'SALAS'...")
            root_id = create_category(url, token, "SALAS", 0)
            log(f"Categoria raiz 'SALAS' criada (id={root_id}).")
        else:
            log(f"Categoria raiz 'SALAS' OK (id={root_id}).")

        # Nível 2: Coligadas
        log("Nível 2 - Coligadas...")
        coligada_cat_ids: Dict[str, int] = {}
        for codcol, col_nome in sorted(coligadas_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
            cat_name = f"{codcol}-{col_nome}".strip("-")
            cid = ensure_category(url, token, cat_name, root_id, counters, "coligadas")
            coligada_cat_ids[codcol] = cid
            time.sleep(0.03)

        # Nível 3: Períodos
        log("Nível 3 - Períodos...")
        periodo_cat_ids: Dict[Tuple[str, str], int] = {}
        for codcol, periods in periodos_por_col.items():
            parent_col_id = coligada_cat_ids.get(codcol)
            if not parent_col_id:
                continue
            for catperiodo in sorted(periods, reverse=True):
                pid = ensure_category(url, token, catperiodo, parent_col_id, counters, "periodos")
                periodo_cat_ids[(codcol, catperiodo)] = pid
                time.sleep(0.03)

        # Nível 4: Modalidades
        log("Nível 4 - Modalidades...")
        modalidade_cat_ids: Dict[Tuple[str, str, str], int] = {}
        for (codcol, catperiodo), modalidades in modalidades_por_col_periodo.items():
            parent_per_id = periodo_cat_ids.get((codcol, catperiodo))
            if not parent_per_id:
                continue
            for mod in sorted({m for m in modalidades if m.strip()}):
                mid = ensure_category(url, token, mod, parent_per_id, counters, "modalidades")
                modalidade_cat_ids[(codcol, catperiodo, mod)] = mid
                time.sleep(0.03)

        # Nível 5: Cursos
        log("Nível 5 - Cursos...")
        curso_cat_ids: Dict[Tuple[str, str, str, str], int] = {}
        for (codcol, catperiodo, mod), cursos in cursos_por_col_periodo_modalidade.items():
            parent_mod_id = modalidade_cat_ids.get((codcol, catperiodo, mod))
            if not parent_mod_id:
                continue
            for curso_nome in sorted({c for c in cursos if c.strip()}):
                cid = ensure_category(url, token, curso_nome, parent_mod_id, counters, "cursos")
                curso_cat_ids[(codcol, catperiodo, mod, curso_nome)] = cid
                time.sleep(0.03)

        # Nível 6: Turmas
        log("Nível 6 - Turmas...")
        for (codcol, catperiodo, mod, curso_nome), turmas in turmas_por_col_periodo_modalidade_curso.items():
            parent_curso_id = curso_cat_ids.get((codcol, catperiodo, mod, curso_nome))
            if not parent_curso_id:
                continue
            for turma in sorted({t for t in turmas if t.strip()}):
                _tid = ensure_category(url, token, turma, parent_curso_id, counters, "turmas")
                time.sleep(0.03)

        summarize_counts(counters)
        log("==== FIM DA EXECUÇÃO (OK) ====")
        return 0

    except Exception as exc:
        log(f"Erro ao criar categorias: {exc}")
        summarize_counts(counters)
        log("==== FIM DA EXECUÇÃO (ERRO) ====")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())