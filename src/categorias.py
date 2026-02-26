from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "app.db"


def log(msg: str) -> None:
    print(msg, flush=True)


def now() -> float:
    return time.monotonic()


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


def normalize_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def sql_in_list(values: Set[str]) -> str:
    cleaned: list[str] = []
    for v in sorted(values):
        v = normalize_numish(v)
        if not v:
            continue
        if v.isdigit():
            cleaned.append(v)
        else:
            cleaned.append("'" + v.replace("'", "''") + "'")
    return ", ".join(cleaned)


def normalize_extra_filter(extra_filter: str) -> str:
    s = (extra_filter or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("where "):
        s = s[6:].strip()
    elif low.startswith("and "):
        s = s[4:].strip()
    return s


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


def get_sala_modelo(sala_modelo_id: int) -> tuple[int, str, str, str] | None:
    """
    Retorna (platform_id, name, moodle_id, extra_filter).

    moodle_id = ID NUMÉRICO DO CURSO MODELO no Moodle (courseid).
    """
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT platform_id, name, moodle_id, extra_filter FROM salas_modelo WHERE id = ?",
            (sala_modelo_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return (int(row[0]), str(row[1] or ""), str(row[2] or ""), str(row[3] or ""))
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

    with pyodbc.connect(conn_str, timeout=30) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [desc[0].lower() for desc in cur.description] if cur.description else []
    return (columns, rows)


def col_index(columns: List[str], name: str) -> Optional[int]:
    name = name.lower()
    return columns.index(name) if name in columns else None


def moodle_call(base_url: str, token: str, function: str, params: Dict[str, Any]) -> Any:
    url = base_url.rstrip("/") + "/webservice/rest/server.php"
    payload = {
        "wstoken": token,
        "wsfunction": function,
        "moodlewsrestformat": "json",
    }
    payload.update(params)

    resp = requests.post(url, data=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"{data.get('errorcode')}: {data.get('message')}")
    return data


def test_token(base_url: str, token: str) -> None:
    log("Testando token do Moodle...")
    moodle_call(base_url, token, "core_webservice_get_site_info", {})
    log("Token válido.")


def assert_course_exists_by_id(base_url: str, token: str, courseid: int) -> None:
    data = moodle_call(
        base_url,
        token,
        "core_course_get_courses_by_field",
        {"field": "id", "value": str(int(courseid))},
    )
    ok = isinstance(data, dict) and isinstance(data.get("courses"), list) and bool(data["courses"])
    if not ok:
        raise RuntimeError("invalidcourseid: Curso modelo não encontrado no Moodle")


def find_root_category_id_by_name(base_url: str, token: str, name: str) -> int | None:
    """
    Localiza uma categoria raiz (parent=0) com nome exato.
    Se houver múltiplas, escolhe a que tem mais filhos diretos.
    Empate: escolhe a de maior id.
    """
    name = (name or "").strip()
    if not name:
        return None

    # Busca mais robusta: parent=0 e name=SALAS
    data = moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {
            "criteria[0][key]": "parent",
            "criteria[0][value]": "0",
            "criteria[1][key]": "name",
            "criteria[1][value]": name,
        },
    )

    cats = data if isinstance(data, list) else []
    roots: list[dict] = []

    for c in cats:
        try:
            if int(c.get("parent", -1)) == 0 and str(c.get("name", "")).strip() == name:
                roots.append(c)
        except Exception:
            continue

    if not roots:
        return None

    # Se só existe uma, retorna direto
    if len(roots) == 1:
        return int(roots[0].get("id"))

    # Se existem múltiplas, escolher a "melhor" (mais filhos diretos)
    def count_children(root_id: int) -> int:
        try:
            children = moodle_call(
                base_url,
                token,
                "core_course_get_categories",
                {"criteria[0][key]": "parent", "criteria[0][value]": str(int(root_id))},
            )
            if isinstance(children, list):
                return len(children)
        except Exception:
            pass
        return 0

    scored: list[tuple[int, int]] = []  # (children_count, root_id)
    for r in roots:
        try:
            rid = int(r.get("id"))
            scored.append((count_children(rid), rid))
        except Exception:
            continue

    if not scored:
        # fallback: maior id (mais recente)
        return int(max(int(r.get("id", 0)) for r in roots))

    # maior número de filhos; empate => maior id
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    chosen_children, chosen_id = scored[0]
    log(
        f"Aviso: existem múltiplas categorias raiz '{name}'. "
        f"Escolhendo id={chosen_id} (filhos={chosen_children})."
    )
    return int(chosen_id)


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
        {"categories[0][name]": name, "categories[0][parent]": str(parent_id)},
    )
    if isinstance(data, list) and data:
        return int(data[0].get("id"))
    raise RuntimeError("Falha ao criar categoria")


def ensure_category(
    base_url: str,
    token: str,
    name: str,
    parent_id: int,
    counters: Dict[str, Dict[str, int]],
    bucket: str,
) -> int:
    existing = find_category_id(base_url, token, name, parent_id)
    if existing is not None:
        counters.setdefault(bucket, {}).setdefault("exists", 0)
        counters[bucket]["exists"] += 1
        return existing

    new_id = create_category(base_url, token, name, parent_id)
    counters.setdefault(bucket, {}).setdefault("created", 0)
    counters[bucket]["created"] += 1
    return new_id


def find_course_by_field(base_url: str, token: str, field: str, value: str) -> dict | None:
    value = (value or "").strip()
    if not value:
        return None
    data = moodle_call(
        base_url,
        token,
        "core_course_get_courses_by_field",
        {"field": field, "value": value},
    )
    if isinstance(data, dict) and isinstance(data.get("courses"), list) and data["courses"]:
        return data["courses"][0]
    return None


def duplicate_course_from_model_minimal(
    base_url: str,
    token: str,
    model_course_id: int,
    categoryid: int,
    fullname: str,
    shortname: str,
    visible: int = 1,
) -> int:
    """
    Ajuste crítico: enviar SOMENTE users=0.
    Não enviar badges/blocks/etc. para evitar invalidextparam.
    """
    params: Dict[str, Any] = {
        "courseid": str(int(model_course_id)),
        "fullname": fullname,
        "shortname": shortname,
        "categoryid": str(int(categoryid)),
        "visible": str(int(visible)),
        "options[0][name]": "users",
        "options[0][value]": "0",
    }

    log(
        "Duplicando curso modelo com options: [users=0] | "
        f"model_course_id={model_course_id} | categoryid={categoryid} | shortname={shortname}"
    )

    data = moodle_call(base_url, token, "core_course_duplicate_course", params)

    if isinstance(data, dict) and "id" in data:
        return int(data["id"])
    if isinstance(data, list) and data and isinstance(data[0], dict) and "id" in data[0]:
        return int(data[0]["id"])
    raise RuntimeError("Falha ao duplicar curso (retorno inesperado)")


def update_course_fields(
    base_url: str,
    token: str,
    courseid: int,
    fullname: str,
    shortname: str,
    idnumber: str,
    customfields: Dict[str, str],
) -> None:
    params: Dict[str, Any] = {
        "courses[0][id]": str(int(courseid)),
        "courses[0][fullname]": fullname,
        "courses[0][shortname]": shortname,
        "courses[0][idnumber]": idnumber,
    }

    idx_cf = 0
    for cf_shortname, cf_value in customfields.items():
        cf_shortname = (cf_shortname or "").strip()
        cf_value = (cf_value or "").strip()
        if not cf_shortname or cf_value == "":
            continue
        params[f"courses[0][customfields][{idx_cf}][shortname]"] = cf_shortname
        params[f"courses[0][customfields][{idx_cf}][value]"] = cf_value
        idx_cf += 1

    moodle_call(base_url, token, "core_course_update_courses", params)


def summarize_counts(counters: Dict[str, Dict[str, int]], did_salas: bool) -> None:
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

    if did_salas:
        s_created = counters.get("salas", {}).get("created", 0)
        s_updated = counters.get("salas", {}).get("updated", 0)
        s_skipped = counters.get("salas", {}).get("skipped", 0)
        s_missing = counters.get("salas", {}).get("missing", 0)
        s_errors = counters.get("salas", {}).get("errors", 0)
        log("Relatório de Salas (clone do modelo):")
        log(f"- Criadas: {s_created}")
        log(f"- Atualizadas (já existiam): {s_updated}")
        log(f"- Ignoradas (já existiam e sem update necessário): {s_skipped}")
        log(f"- Ignoradas por dados incompletos: {s_missing}")
        log(f"- Erros: {s_errors}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    parser.add_argument("--periodo", default="")
    parser.add_argument("--create-categories", default="1")
    parser.add_argument("--create-courses", default="0")  # criar salas (clonar modelo)
    parser.add_argument("--sala-modelo-id", type=int, default=None)
    args = parser.parse_args()

    platform = get_platform(args.platform_id)
    if not platform:
        log("Plataforma não encontrada.")
        return 1

    platform_name, base_url, token, coligadas_csv = platform

    selected_catperiodo = normalize_str(args.periodo).replace("/", "-")
    filter_by_period = bool(selected_catperiodo) and selected_catperiodo.lower() != "todos"

    do_categories = args.create_categories == "1"
    do_salas = args.create_courses == "1"

    log("==== INÍCIO - CATEGORIAS/TURMAS" + (" + SALAS (CLONE MODELO)" if do_salas else "") + " ====")
    log("BUILD: 2026-02-25 / categorias.py / categorias+turmas " + ("+ salas (clone users=0)" if do_salas else "") + " / NO-BADGES")
    log(f"Arquivo em execução: {Path(__file__).resolve()}")
    log(f"Plataforma: {platform_name} (ID {args.platform_id})")
    log(f"Período selecionado: {selected_catperiodo if filter_by_period else 'Todos'}")
    log(f"Criar categorias/turmas: {'Sim' if do_categories else 'Não'}")
    log(f"Criar salas por clone do modelo: {'Sim' if do_salas else 'Não'}")

    if not do_categories and not do_salas:
        log("Nada para executar (create-categories=0 e create-courses=0).")
        return 0

    if do_salas and args.sala_modelo_id is None:
        log("Erro: para criar Salas é obrigatório informar --sala-modelo-id.")
        return 2

    sala_modelo_course_model_id = ""
    sala_modelo_extra_filter = ""
    sala_modelo_name = ""

    if do_salas:
        sm = get_sala_modelo(int(args.sala_modelo_id))
        if not sm:
            log(f"Sala Modelo id={args.sala_modelo_id} não encontrada.")
            return 2
        sm_platform_id, sm_name, sm_course_model_id, sm_extra = sm
        if int(sm_platform_id) != int(args.platform_id):
            log("Erro: Sala Modelo não pertence à plataforma selecionada.")
            return 2

        sala_modelo_name = (sm_name or "").strip()
        sala_modelo_course_model_id = (sm_course_model_id or "").strip()
        sala_modelo_extra_filter = normalize_extra_filter(sm_extra)

        log(f"Sala Modelo: {sala_modelo_name or '(sem nome)'} | Curso Modelo ID: {sala_modelo_course_model_id}")
        log(f"Filtro Extra (Sala Modelo): {sala_modelo_extra_filter or '(vazio)'}")

        if not sala_modelo_course_model_id.isdigit():
            log("Erro: o Curso Modelo ID (moodle_id) deve ser numérico (ID do curso no Moodle).")
            return 2

    try:
        test_token(base_url, token)
        if do_salas:
            assert_course_exists_by_id(base_url, token, int(sala_modelo_course_model_id))
    except Exception as exc:
        log(f"Falha em validações iniciais (token/curso modelo): {exc}")
        return 3

    if not do_categories:
        log("Criação de categorias desativada (create-categories=0).")
        return 0

    allowed_coligadas = {normalize_numish(c) for c in (coligadas_csv or "").split(",") if normalize_numish(c)}
    log(f"Filtro - Coligadas permitidas (platform): {sorted(allowed_coligadas)}")
    if not allowed_coligadas:
        log("Nenhuma coligada selecionada na plataforma.")
        return 0

    sql_base = get_rm_query("cursos")
    if not sql_base:
        log("Erro: a consulta RM (rm_queries.cursos) está vazia.")
        return 4

    sql_base = strip_sql(sql_base)
    sql_base = remove_last_order_by(sql_base)

    in_list = sql_in_list(allowed_coligadas)
    if not in_list:
        log("Lista de coligadas inválida (IN vazio).")
        return 4

    sql = "SELECT X.* FROM (" + sql_base + ") X " f"WHERE X.CODCOLIGADA IN ({in_list}) "
    if do_salas and sala_modelo_extra_filter:
        sql += f"AND ({sala_modelo_extra_filter}) "

    log("SQL RM (base Categorias/Turmas/Salas) após filtros automáticos:")
    log(sql)

    t0 = now()
    log("Executando consulta RM: Categorias/Turmas/Salas")
    columns, rows = rm_fetch(sql)
    log(f"Consulta RM concluída em {now() - t0:.3f}s ({len(rows)} linhas)")

    if not columns or not rows:
        log("Consulta RM não retornou dados.")
        return 0

    # Requisitos mínimos para categorias/turmas
    required = ["codcoligada", "coligada", "catperiodo", "catmodalidade", "curso", "codturma"]
    missing = []
    idx: Dict[str, int] = {}
    for k in required:
        i = col_index(columns, k)
        if i is None:
            missing.append(k.upper())
        else:
            idx[k] = i
    if missing:
        log("Erro: a consulta base precisa conter as colunas:")
        log(", ".join([x.upper() for x in required]))
        log("Faltando: " + ", ".join(missing))
        return 5

    # Requisitos para salas (clone do modelo)
    idx_salas: Dict[str, int] = {}
    if do_salas:
        required_salas = [
            "catperiodo",
            "idperlet",
            "codcoligada",
            "coligada",
            "catmodalidade",
            "curso",
            "codcurso",
            "codturma",
            "idturmadisc",
            "fullname",
            "shortname",
            "idnumber",
            "idhabilitacaofilial",
        ]
        missing_salas: list[str] = []
        for k in required_salas:
            i = col_index(columns, k)
            if i is None:
                missing_salas.append(k.upper())
            else:
                idx_salas[k] = i
        if missing_salas:
            log("Erro: a consulta precisa retornar as colunas para criar Salas (clone do modelo).")
            log("Faltando: " + ", ".join(missing_salas))
            return 5

    # Root SALAS
    log("Verificando categoria raiz 'SALAS' (parent=0)...")
    root_id = find_root_category_id_by_name(base_url, token, "SALAS")
    if root_id is None:
        log("Criando categoria raiz 'SALAS'...")
        root_id = create_category(base_url, token, "SALAS", 0)
        log(f"Categoria raiz 'SALAS' criada (id={root_id}).")
    else:
        log(f"Categoria raiz 'SALAS' OK (id={root_id}).")

    # Agrupar estrutura + registros de salas por turma
    coligadas_map: Dict[str, str] = {}
    periodos_por_col: Dict[str, Set[str]] = {}
    modalidades_por_col_periodo: Dict[Tuple[str, str], Set[str]] = {}
    cursos_por_col_periodo_modalidade: Dict[Tuple[str, str, str], Set[str]] = {}
    turmas_por_col_periodo_modalidade_curso: Dict[Tuple[str, str, str, str], Set[str]] = {}

    salas_por_turma: Dict[Tuple[str, str, str, str, str], List[Dict[str, str]]] = {}
    seen_idnumbers_by_turma: Dict[Tuple[str, str, str, str, str], Set[str]] = {}

    for r in rows:
        codcol = normalize_numish(r[idx["codcoligada"]])
        coligada_nome = normalize_str(r[idx["coligada"]]).strip()
        catperiodo = normalize_str(r[idx["catperiodo"]]).replace("/", "-").strip()
        catmodalidade = normalize_str(r[idx["catmodalidade"]]).strip()
        curso_nome = normalize_str(r[idx["curso"]]).strip()
        codturma = normalize_str(r[idx["codturma"]]).strip()

        if not codcol or codcol not in allowed_coligadas:
            continue
        if filter_by_period and catperiodo != selected_catperiodo:
            continue
        if not (coligada_nome and catperiodo and catmodalidade and curso_nome and codturma):
            continue

        coligadas_map.setdefault(codcol, coligada_nome)
        periodos_por_col.setdefault(codcol, set()).add(catperiodo)
        modalidades_por_col_periodo.setdefault((codcol, catperiodo), set()).add(catmodalidade)
        cursos_por_col_periodo_modalidade.setdefault((codcol, catperiodo, catmodalidade), set()).add(curso_nome)
        turmas_por_col_periodo_modalidade_curso.setdefault((codcol, catperiodo, catmodalidade, curso_nome), set()).add(codturma)

        if do_salas:
            idnumber = normalize_str(r[idx_salas["idnumber"]]).strip()
            if not idnumber:
                continue
            tkey = (codcol, catperiodo, catmodalidade, curso_nome, codturma)
            seen = seen_idnumbers_by_turma.setdefault(tkey, set())
            if idnumber in seen:
                continue
            seen.add(idnumber)

            rec = {
                "catperiodo": catperiodo,
                "idperlet": normalize_str(r[idx_salas["idperlet"]]).strip(),
                "codcoligada": codcol,
                "coligada": coligada_nome,
                "catmodalidade": catmodalidade,
                "curso": curso_nome,
                "codcurso": normalize_str(r[idx_salas["codcurso"]]).strip(),
                "codturma": codturma,
                "idturmadisc": normalize_str(r[idx_salas["idturmadisc"]]).strip(),
                "fullname": normalize_str(r[idx_salas["fullname"]]).strip(),
                "shortname": normalize_str(r[idx_salas["shortname"]]).strip(),
                "idnumber": idnumber,
                "idhabilitacaofilial": normalize_str(r[idx_salas["idhabilitacaofilial"]]).strip(),
            }
            salas_por_turma.setdefault(tkey, []).append(rec)

    if not coligadas_map:
        log("Após filtros, não há coligadas/períodos para processar.")
        return 0

    counters: Dict[str, Dict[str, int]] = {}

    # Criar hierarquia
    log("Nível 2 - Coligadas...")
    coligada_cat_ids: Dict[str, int] = {}
    for codcol, col_nome in sorted(coligadas_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
        cat_name = f"{codcol}-{col_nome}".strip("-")
        cid = ensure_category(base_url, token, cat_name, root_id, counters, "coligadas")
        coligada_cat_ids[codcol] = cid
        time.sleep(0.02)

    log("Nível 3 - Períodos...")
    periodo_cat_ids: Dict[Tuple[str, str], int] = {}
    for codcol, periods in periodos_por_col.items():
        parent_col_id = coligada_cat_ids.get(codcol)
        if not parent_col_id:
            continue
        for catperiodo in sorted(periods, reverse=True):
            pid = ensure_category(base_url, token, catperiodo, parent_col_id, counters, "periodos")
            periodo_cat_ids[(codcol, catperiodo)] = pid
            time.sleep(0.02)

    log("Nível 4 - Modalidades...")
    modalidade_cat_ids: Dict[Tuple[str, str, str], int] = {}
    for (codcol, catperiodo), modalidades in modalidades_por_col_periodo.items():
        parent_per_id = periodo_cat_ids.get((codcol, catperiodo))
        if not parent_per_id:
            continue
        for mod in sorted({m for m in modalidades if m.strip()}):
            mid = ensure_category(base_url, token, mod, parent_per_id, counters, "modalidades")
            modalidade_cat_ids[(codcol, catperiodo, mod)] = mid
            time.sleep(0.02)

    log("Nível 5 - Cursos...")
    curso_cat_ids: Dict[Tuple[str, str, str, str], int] = {}
    for (codcol, catperiodo, mod), cursos in cursos_por_col_periodo_modalidade.items():
        parent_mod_id = modalidade_cat_ids.get((codcol, catperiodo, mod))
        if not parent_mod_id:
            continue
        for curso_nome in sorted({c for c in cursos if c.strip()}):
            cid = ensure_category(base_url, token, curso_nome, parent_mod_id, counters, "cursos")
            curso_cat_ids[(codcol, catperiodo, mod, curso_nome)] = cid
            time.sleep(0.02)

    # Turmas + Salas turma-a-turma
    log("Nível 6 - Turmas..." + (" (clonando Salas a partir do Modelo)" if do_salas else ""))

    model_course_id = int(sala_modelo_course_model_id) if do_salas else 0

    for (codcol, catperiodo, mod, curso_nome), turmas in turmas_por_col_periodo_modalidade_curso.items():
        parent_curso_id = curso_cat_ids.get((codcol, catperiodo, mod, curso_nome))
        if not parent_curso_id:
            continue

        for turma in sorted({t for t in turmas if t.strip()}):
            turma_id = ensure_category(base_url, token, turma, parent_curso_id, counters, "turmas")
            time.sleep(0.02)

            if not do_salas:
                continue

            tkey = (codcol, catperiodo, mod, curso_nome, turma)
            registros = salas_por_turma.get(tkey) or []
            if not registros:
                continue

            for rec in registros:
                fullname = (rec.get("fullname") or "").strip()
                shortname = (rec.get("shortname") or "").strip()
                idnumber = (rec.get("idnumber") or "").strip()
                codcurso = (rec.get("codcurso") or "").strip()
                idturmadisc = (rec.get("idturmadisc") or "").strip()
                idperlet = (rec.get("idperlet") or "").strip()
                idhabilitacaofilial = (rec.get("idhabilitacaofilial") or "").strip()

                if not (fullname and shortname and idnumber):
                    counters.setdefault("salas", {}).setdefault("missing", 0)
                    counters["salas"]["missing"] += 1
                    continue

                customfields = {
                    "tipocurso": mod,
                    "codcurso": codcurso,
                    "turma": turma,
                    "codcoligada": codcol,
                    "idturmadisc": idturmadisc,
                    "tipo": mod,
                    "idperlet": idperlet,
                    "idhabilitacaofilial": idhabilitacaofilial,
                }

                try:
                    # 1) Se já existe por idnumber, atualiza e segue
                    existing = find_course_by_field(base_url, token, "idnumber", idnumber)
                    if not existing and shortname:
                        # fallback: se por algum motivo idnumber não foi setado anteriormente, tenta pelo shortname
                        existing = find_course_by_field(base_url, token, "shortname", shortname)

                    if existing:
                        course_id = int(existing.get("id"))
                        update_course_fields(
                            base_url=base_url,
                            token=token,
                            courseid=course_id,
                            fullname=fullname,
                            shortname=shortname,
                            idnumber=idnumber,
                            customfields=customfields,
                        )
                        counters.setdefault("salas", {}).setdefault("updated", 0)
                        counters["salas"]["updated"] += 1
                        time.sleep(0.02)
                        continue

                    # 2) Não existe: duplica do modelo e atualiza campos complementares
                    new_course_id = duplicate_course_from_model_minimal(
                        base_url=base_url,
                        token=token,
                        model_course_id=model_course_id,
                        categoryid=int(turma_id),
                        fullname=fullname,
                        shortname=shortname,
                        visible=1,
                    )

                    update_course_fields(
                        base_url=base_url,
                        token=token,
                        courseid=new_course_id,
                        fullname=fullname,
                        shortname=shortname,
                        idnumber=idnumber,
                        customfields=customfields,
                    )

                    counters.setdefault("salas", {}).setdefault("created", 0)
                    counters["salas"]["created"] += 1
                    time.sleep(0.02)

                except Exception as exc:
                    counters.setdefault("salas", {}).setdefault("errors", 0)
                    counters["salas"]["errors"] += 1
                    log(
                        f"Erro ao duplicar/atualizar sala (turma={turma}, idnumber={idnumber}, shortname={shortname}): {exc}"
                    )

    summarize_counts(counters, did_salas=do_salas)
    log("==== FIM - CATEGORIAS/TURMAS" + (" + SALAS (CLONE MODELO)" if do_salas else "") + " ====")

    return 0 if counters.get("salas", {}).get("errors", 0) == 0 else 7


if __name__ == "__main__":
    raise SystemExit(main())