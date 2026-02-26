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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True, type=int)
    parser.add_argument("--periodo", default="")
    parser.add_argument("--sala-modelo-id", type=int, default=None)
    parser.add_argument("--create-courses", default="1")  # flag do checkbox
    args = parser.parse_args()

    platform = get_platform(args.platform_id)
    if not platform:
        log("Plataforma não encontrada.")
        return 1

    platform_name, base_url, token, coligadas_csv = platform

    if args.create_courses != "1":
        log("Criação de salas desativada (--create-courses=0).")
        return 0

    if args.sala_modelo_id is None:
        log("Erro: selecione uma Sala Modelo.")
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
    sala_modelo_extra_filter = normalize_extra_filter(sm_extra)

    if not (sm_course_model_id or "").strip().isdigit():
        log("Erro: moodle_id da Sala Modelo deve ser o ID do curso modelo (/course/view.php?id=XXX).")
        return 2

    model_course_id = int(str(sm_course_model_id).strip())

    selected_catperiodo = normalize_str(args.periodo).replace("/", "-")
    filter_by_period = bool(selected_catperiodo) and selected_catperiodo.lower() != "todos"

    log("==== INÍCIO - SALAS (BACKFILL CLONE DO MODELO) ====")
    log(f"Arquivo em execução: {Path(__file__).resolve()}")
    log(f"Plataforma: {platform_name} (ID {args.platform_id})")
    log(f"Sala Modelo: {sala_modelo_name or '(sem nome)'} | Curso Modelo ID: {model_course_id}")
    log(f"Filtro Extra (Sala Modelo): {sala_modelo_extra_filter or '(vazio)'}")
    log(f"Período (CATPERIODO): {selected_catperiodo if filter_by_period else 'Todos'}")

    try:
        test_token(base_url, token)
        assert_course_exists_by_id(base_url, token, model_course_id)
    except Exception as exc:
        log(f"Falha em validações iniciais (token/curso modelo): {exc}")
        return 3

    root_id = find_root_category_id_by_name(base_url, token, "SALAS")
    if root_id is None:
        log("Categoria raiz 'SALAS' não existe; criando...")
        root_id = create_category(base_url, token, "SALAS", 0)
        log(f"Categoria raiz 'SALAS' criada (id={root_id}).")
    else:
        log(f"Categoria raiz 'SALAS' OK (id={root_id}).")

    allowed_coligadas = {normalize_numish(c) for c in (coligadas_csv or "").split(",") if normalize_numish(c)}
    if not allowed_coligadas:
        log("Nenhuma coligada selecionada na plataforma.")
        return 0

    sql_base = get_rm_query("cursos")
    if not sql_base:
        log("Erro: consulta RM (rm_queries.cursos) está vazia.")
        return 4

    sql_base = strip_sql(sql_base)
    sql_base = remove_last_order_by(sql_base)
    in_list = sql_in_list(allowed_coligadas)

    sql = "SELECT X.* FROM (" + sql_base + ") X " f"WHERE X.CODCOLIGADA IN ({in_list}) "
    if sala_modelo_extra_filter:
        sql += f"AND ({sala_modelo_extra_filter}) "

    log("Executando consulta RM (base Categorias/Turmas/Salas)...")
    t0 = now()
    columns, rows = rm_fetch(sql)
    log(f"Consulta RM concluída em {now() - t0:.3f}s ({len(rows)} linhas)")

    if not columns or not rows:
        log("Consulta RM não retornou dados.")
        return 0

    required = [
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

    idx: Dict[str, int] = {}
    missing: list[str] = []
    for k in required:
        i = col_index(columns, k)
        if i is None:
            missing.append(k.upper())
        else:
            idx[k] = i

    if missing:
        log("Erro: consulta RM precisa retornar colunas para Salas.")
        log("Faltando: " + ", ".join(missing))
        return 5

    # Cache de categorias
    cat_cache: Dict[Tuple[int, str], int | None] = {}

    def get_child(parent_id: int, name: str) -> int | None:
        key = (parent_id, name)
        if key in cat_cache:
            return cat_cache[key]
        cid = find_category_id(base_url, token, name, parent_id)
        cat_cache[key] = cid
        return cid

    created = 0
    updated = 0
    skipped_missing_category = 0
    missing_data = 0
    errors = 0

    seen_idnumbers: Set[str] = set()

    for r in rows:
        catperiodo = normalize_str(r[idx["catperiodo"]]).replace("/", "-")
        if filter_by_period and catperiodo != selected_catperiodo:
            continue

        codcoligada = normalize_numish(r[idx["codcoligada"]])
        if not codcoligada or codcoligada not in allowed_coligadas:
            continue

        coligada_nome = normalize_str(r[idx["coligada"]]).strip()
        catmodalidade = normalize_str(r[idx["catmodalidade"]]).strip()
        curso = normalize_str(r[idx["curso"]]).strip()
        codcurso = normalize_str(r[idx["codcurso"]]).strip()
        codturma = normalize_str(r[idx["codturma"]]).strip()

        fullname = normalize_str(r[idx["fullname"]]).strip()
        shortname = normalize_str(r[idx["shortname"]]).strip()
        idnumber = normalize_str(r[idx["idnumber"]]).strip()

        idperlet = normalize_str(r[idx["idperlet"]]).strip()
        idturmadisc = normalize_str(r[idx["idturmadisc"]]).strip()
        idhabilitacaofilial = normalize_str(r[idx["idhabilitacaofilial"]]).strip()

        if not (catperiodo and coligada_nome and catmodalidade and curso and codturma and fullname and shortname and idnumber):
            continue

        if idnumber in seen_idnumbers:
            continue
        seen_idnumbers.add(idnumber)

        # Localizar categoria da turma
        coligada_cat_name = f"{codcoligada}-{coligada_nome}".strip("-")

        coligada_id = get_child(root_id, coligada_cat_name)
        if not coligada_id:
            skipped_missing_category += 1
            continue

        periodo_id = get_child(coligada_id, catperiodo)
        if not periodo_id:
            skipped_missing_category += 1
            continue

        modalidade_id = get_child(periodo_id, catmodalidade)
        if not modalidade_id:
            skipped_missing_category += 1
            continue

        curso_id = get_child(modalidade_id, curso)
        if not curso_id:
            skipped_missing_category += 1
            continue

        turma_id = get_child(curso_id, codturma)
        if not turma_id:
            skipped_missing_category += 1
            continue

        customfields = {
            "tipocurso": catmodalidade,
            "codcurso": codcurso,
            "turma": codturma,
            "codcoligada": codcoligada,
            "idturmadisc": idturmadisc,
            "tipo": catmodalidade,
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
                updated += 1
                time.sleep(0.02)
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

            created += 1
            time.sleep(0.02)

        except Exception as exc:
            errors += 1
            log(f"Erro ao duplicar/atualizar sala (turma={codturma}, idnumber={idnumber}, shortname={shortname}): {exc}")

    log("==== RELATÓRIO - SALAS (BACKFILL CLONE DO MODELO) ====")
    log(f"Salas criadas (duplicadas): {created}")
    log(f"Salas atualizadas (já existiam): {updated}")
    log(f"Ignoradas por categoria (turma) não encontrada: {skipped_missing_category}")
    log(f"Ignoradas por dados incompletos: {missing_data}")
    log(f"Erros: {errors}")
    log("==== FIM - SALAS (BACKFILL CLONE DO MODELO) ====")

    return 0 if errors == 0 else 7


if __name__ == "__main__":
    raise SystemExit(main())