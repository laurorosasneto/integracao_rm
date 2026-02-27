from __future__ import annotations

import argparse
import re
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


def slug_id_part(text: str) -> str:
    """
    Gera uma parte de idnumber segura:
    - upper
    - troca espaços por _
    - remove caracteres fora de A-Z0-9_-.
    - limita tamanho
    """
    s = (text or "").strip().upper()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Z0-9_-]+", "", s)
    s = re.sub(r"_{2,}", "_", s).strip("_")
    if not s:
        s = "X"
    return s[:40]


def idnumber_root() -> str:
    return "SALAS"


def idnumber_coligada(codcoligada: str) -> str:
    return f"{idnumber_root()}-{slug_id_part(codcoligada)}"[:100]


def idnumber_periodo(col_idnumber: str, catperiodo: str) -> str:
    return f"{col_idnumber}-PER-{slug_id_part(catperiodo)}"[:100]


def idnumber_modalidade(per_idnumber: str, modalidade: str) -> str:
    return f"{per_idnumber}-MOD-{slug_id_part(modalidade)}"[:100]


def idnumber_curso(mod_idnumber: str, curso: str) -> str:
    return f"{mod_idnumber}-CUR-{slug_id_part(curso)}"[:100]


def idnumber_turma(cur_idnumber: str, turma: str) -> str:
    return f"{cur_idnumber}-TUR-{slug_id_part(turma)}"[:100]


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
    payload = {"wstoken": token, "wsfunction": function, "moodlewsrestformat": "json"}
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


def find_root_category_by_idnumber(base_url: str, token: str, root_idnum: str) -> Optional[int]:
    """
    Localiza a raiz pelo IDNUMBER (regra do usuário).
    Ignora qualquer categoria apenas com name=SALAS.
    """
    data = moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {
            "criteria[0][key]": "parent",
            "criteria[0][value]": "0",
            "criteria[1][key]": "idnumber",
            "criteria[1][value]": root_idnum,
        },
    )
    if isinstance(data, list) and data:
        # se houver múltiplas, escolher a mais recente (maior id)
        ids = []
        for c in data:
            try:
                if int(c.get("parent", -1)) == 0 and str(c.get("idnumber", "")).strip() == root_idnum:
                    ids.append(int(c.get("id")))
            except Exception:
                continue
        return max(ids) if ids else None
    return None


def find_category_by_parent_and_idnumber(base_url: str, token: str, parent_id: int, idnumber: str) -> Optional[int]:
    data = moodle_call(
        base_url,
        token,
        "core_course_get_categories",
        {
            "criteria[0][key]": "parent",
            "criteria[0][value]": str(int(parent_id)),
            "criteria[1][key]": "idnumber",
            "criteria[1][value]": idnumber,
        },
    )
    if isinstance(data, list) and data:
        # idnumber é único dentro da nossa regra; se vier mais de um por inconsistência, pega maior id
        ids = []
        for c in data:
            try:
                if int(c.get("parent", -1)) == int(parent_id) and str(c.get("idnumber", "")).strip() == idnumber:
                    ids.append(int(c.get("id")))
            except Exception:
                continue
        return max(ids) if ids else None
    return None


def create_category(base_url: str, token: str, name: str, parent_id: int, idnumber: Optional[str]) -> int:
    """
    Cria categoria com idnumber. Se o WS do Moodle não aceitar idnumber, faz fallback sem idnumber.
    """
    params: Dict[str, Any] = {
        "categories[0][name]": name,
        "categories[0][parent]": str(int(parent_id)),
    }
    if idnumber:
        params["categories[0][idnumber]"] = idnumber

    try:
        data = moodle_call(base_url, token, "core_course_create_categories", params)
    except Exception as exc:
        # fallback: tenta criar sem idnumber se o ambiente não suportar o parâmetro
        if idnumber:
            log(f"Aviso: falha ao criar categoria com idnumber='{idnumber}'. Tentando sem idnumber. Detalhe: {exc}")
            data = moodle_call(
                base_url,
                token,
                "core_course_create_categories",
                {"categories[0][name]": name, "categories[0][parent]": str(int(parent_id))},
            )
        else:
            raise

    if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("id"):
        return int(data[0].get("id"))
    raise RuntimeError("Falha ao criar categoria (retorno inesperado)")


def ensure_category_by_idnumber(
    base_url: str,
    token: str,
    parent_id: int,
    name: str,
    idnumber: str,
    counters: Dict[str, Dict[str, int]],
    bucket: str,
) -> int:
    cid = find_category_by_parent_and_idnumber(base_url, token, parent_id, idnumber)
    if cid is not None:
        counters.setdefault(bucket, {}).setdefault("exists", 0)
        counters[bucket]["exists"] += 1
        return cid

    new_id = create_category(base_url, token, name, parent_id, idnumber)
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
    params: Dict[str, Any] = {
        "courseid": str(int(model_course_id)),
        "fullname": fullname,
        "shortname": shortname,
        "categoryid": str(int(categoryid)),
        "visible": str(int(visible)),
        "options[0][name]": "users",
        "options[0][value]": "0",
    }

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
        s_missing = counters.get("salas", {}).get("missing", 0)
        s_errors = counters.get("salas", {}).get("errors", 0)
        log("Relatório de Salas (clone do modelo):")
        log(f"- Criadas: {s_created}")
        log(f"- Atualizadas (já existiam): {s_updated}")
        log(f"- Ignoradas por dados incompletos: {s_missing}")
        log(f"- Erros: {s_errors}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    parser.add_argument("--periodo", default="")
    parser.add_argument("--create-categories", default="1")
    parser.add_argument("--create-courses", default="0")
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
    log("BUILD: 2026-02-26 / categorias.py / idnumber-ancora")
    log(f"Arquivo em execução: {Path(__file__).resolve()}")
    log(f"Plataforma: {platform_name} (ID {args.platform_id})")
    log(f"Período selecionado: {selected_catperiodo if filter_by_period else 'Todos'}")

    if not do_categories and not do_salas:
        log("Nada para executar.")
        return 0

    sala_modelo_course_model_id = ""
    sala_modelo_extra_filter = ""
    sala_modelo_name = ""

    if do_salas:
        if args.sala_modelo_id is None:
            log("Erro: para criar Salas é obrigatório informar --sala-modelo-id.")
            return 2

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

        if not sala_modelo_course_model_id.isdigit():
            log("Erro: o Curso Modelo ID (moodle_id) deve ser numérico.")
            return 2

    try:
        test_token(base_url, token)
        if do_salas:
            assert_course_exists_by_id(base_url, token, int(sala_modelo_course_model_id))
    except Exception as exc:
        log(f"Falha em validações iniciais: {exc}")
        return 3

    if not do_categories:
        log("Criação de categorias desativada.")
        return 0

    allowed_coligadas = {normalize_numish(c) for c in (coligadas_csv or "").split(",") if normalize_numish(c)}
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
    sql = "SELECT X.* FROM (" + sql_base + ") X " f"WHERE X.CODCOLIGADA IN ({in_list}) "
    if do_salas and sala_modelo_extra_filter:
        sql += f"AND ({sala_modelo_extra_filter}) "

    columns, rows = rm_fetch(sql)
    if not columns or not rows:
        log("Consulta RM não retornou dados.")
        return 0

    required = ["codcoligada", "coligada", "catperiodo", "catmodalidade", "curso", "codturma"]
    idx: Dict[str, int] = {}
    missing = []
    for k in required:
        i = col_index(columns, k)
        if i is None:
            missing.append(k.upper())
        else:
            idx[k] = i
    if missing:
        log("Erro: consulta base precisa conter colunas: " + ", ".join(missing))
        return 5

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
            log("Erro: consulta precisa retornar colunas para criar Salas. Faltando: " + ", ".join(missing_salas))
            return 5

    # 1) Root SALAS por IDNUMBER
    root_idnum = idnumber_root()
    log("Localizando categoria raiz por IDNUMBER='SALAS'...")
    root_id = find_root_category_by_idnumber(base_url, token, root_idnum)
    if root_id is None:
        log("Raiz não existe. Criando categoria raiz 'SALAS' com idnumber='SALAS'...")
        root_id = create_category(base_url, token, "SALAS", 0, root_idnum)
        log(f"Raiz criada. id={root_id}")
    else:
        log(f"Raiz encontrada. id={root_id}")

    # Mapas por RM
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
        log("Após filtros, não há dados para processar.")
        return 0

    counters: Dict[str, Dict[str, int]] = {}

    # Nível 2 - Coligadas (idnumber: SALAS-<CODCOLIGADA>)
    log("Nível 2 - Coligadas...")
    coligada_cat_ids: Dict[str, int] = {}
    coligada_idnums: Dict[str, str] = {}

    for codcol, col_nome in sorted(coligadas_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
        col_idnum = idnumber_coligada(codcol)
        col_name = f"{codcol}-{col_nome}".strip("-")
        cid = ensure_category_by_idnumber(base_url, token, root_id, col_name, col_idnum, counters, "coligadas")
        coligada_cat_ids[codcol] = cid
        coligada_idnums[codcol] = col_idnum
        time.sleep(0.01)

    # Nível 3 - Períodos (idnumber: <COL>-PER-<CATPERIODO>)
    log("Nível 3 - Períodos...")
    periodo_cat_ids: Dict[Tuple[str, str], int] = {}
    periodo_idnums: Dict[Tuple[str, str], str] = {}

    for codcol, periods in periodos_por_col.items():
        parent_col_id = coligada_cat_ids.get(codcol)
        parent_col_idnum = coligada_idnums.get(codcol)
        if not parent_col_id or not parent_col_idnum:
            continue

        for catperiodo in sorted(periods, reverse=True):
            per_idnum = idnumber_periodo(parent_col_idnum, catperiodo)
            pid = ensure_category_by_idnumber(base_url, token, parent_col_id, catperiodo, per_idnum, counters, "periodos")
            periodo_cat_ids[(codcol, catperiodo)] = pid
            periodo_idnums[(codcol, catperiodo)] = per_idnum
            time.sleep(0.01)

    # Nível 4 - Modalidades
    log("Nível 4 - Modalidades...")
    modalidade_cat_ids: Dict[Tuple[str, str, str], int] = {}
    modalidade_idnums: Dict[Tuple[str, str, str], str] = {}

    for (codcol, catperiodo), modalidades in modalidades_por_col_periodo.items():
        parent_per_id = periodo_cat_ids.get((codcol, catperiodo))
        parent_per_idnum = periodo_idnums.get((codcol, catperiodo))
        if not parent_per_id or not parent_per_idnum:
            continue

        for mod in sorted({m for m in modalidades if m.strip()}):
            mod_idnum = idnumber_modalidade(parent_per_idnum, mod)
            mid = ensure_category_by_idnumber(base_url, token, parent_per_id, mod, mod_idnum, counters, "modalidades")
            modalidade_cat_ids[(codcol, catperiodo, mod)] = mid
            modalidade_idnums[(codcol, catperiodo, mod)] = mod_idnum
            time.sleep(0.01)

    # Nível 5 - Cursos
    log("Nível 5 - Cursos...")
    curso_cat_ids: Dict[Tuple[str, str, str, str], int] = {}
    curso_idnums: Dict[Tuple[str, str, str, str], str] = {}

    for (codcol, catperiodo, mod), cursos in cursos_por_col_periodo_modalidade.items():
        parent_mod_id = modalidade_cat_ids.get((codcol, catperiodo, mod))
        parent_mod_idnum = modalidade_idnums.get((codcol, catperiodo, mod))
        if not parent_mod_id or not parent_mod_idnum:
            continue

        for curso_nome in sorted({c for c in cursos if c.strip()}):
            cur_idnum = idnumber_curso(parent_mod_idnum, curso_nome)
            cid = ensure_category_by_idnumber(base_url, token, parent_mod_id, curso_nome, cur_idnum, counters, "cursos")
            curso_cat_ids[(codcol, catperiodo, mod, curso_nome)] = cid
            curso_idnums[(codcol, catperiodo, mod, curso_nome)] = cur_idnum
            time.sleep(0.01)

    # Nível 6 - Turmas + (opcional) salas
    log("Nível 6 - Turmas..." + (" + Salas (clone)" if do_salas else ""))

    model_course_id = int(sala_modelo_course_model_id) if do_salas else 0

    for (codcol, catperiodo, mod, curso_nome), turmas in turmas_por_col_periodo_modalidade_curso.items():
        parent_cur_id = curso_cat_ids.get((codcol, catperiodo, mod, curso_nome))
        parent_cur_idnum = curso_idnums.get((codcol, catperiodo, mod, curso_nome))
        if not parent_cur_id or not parent_cur_idnum:
            continue

        for turma in sorted({t for t in turmas if t.strip()}):
            tur_idnum = idnumber_turma(parent_cur_idnum, turma)
            turma_id = ensure_category_by_idnumber(base_url, token, parent_cur_id, turma, tur_idnum, counters, "turmas")
            time.sleep(0.01)

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
                    existing = find_course_by_field(base_url, token, "idnumber", idnumber)
                    if not existing and shortname:
                        existing = find_course_by_field(base_url, token, "shortname", shortname)

                    if existing:
                        update_course_fields(
                            base_url=base_url,
                            token=token,
                            courseid=int(existing.get("id")),
                            fullname=fullname,
                            shortname=shortname,
                            idnumber=idnumber,
                            customfields=customfields,
                        )
                        counters.setdefault("salas", {}).setdefault("updated", 0)
                        counters["salas"]["updated"] += 1
                        time.sleep(0.01)
                        continue

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
                    time.sleep(0.01)

                except Exception as exc:
                    counters.setdefault("salas", {}).setdefault("errors", 0)
                    counters["salas"]["errors"] += 1
                    log(f"Erro ao duplicar/atualizar sala (turma={turma}, idnumber={idnumber}, shortname={shortname}): {exc}")

    summarize_counts(counters, did_salas=do_salas)
    log("==== FIM ====")
    return 0 if counters.get("salas", {}).get("errors", 0) == 0 else 7


if __name__ == "__main__":
    raise SystemExit(main())