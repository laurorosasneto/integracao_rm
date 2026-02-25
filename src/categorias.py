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


def ensure_category(base_url: str, token: str, name: str, parent_id: int) -> tuple[int, bool]:
    """
    Garante que uma categoria (name) exista sob (parent_id) e retorna (id, created).
    """
    existing = find_category_id(base_url, token, name, parent_id)
    if existing is not None:
        return (existing, False)
    return (create_category(base_url, token, name, parent_id), True)


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


def _chunks(items: List[str], size: int) -> List[List[str]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


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

    selected_catperiodo = normalize_str(args.periodo).replace("/", "-")
    filter_by_period = bool(selected_catperiodo) and selected_catperiodo.lower() != "todos"

    log("============================================================")
    log("INÍCIO DA EXECUÇÃO - INTEGRAÇÃO RM → MOODLE (CATEGORIAS)")
    log("============================================================")
    log(f"Plataforma: {platform_name} (ID {args.platform_id})")
    log(f"Moodle URL: {url.rstrip('/')}")
    log(f"Criar categorias: {'SIM' if args.create_categories == '1' else 'NÃO'}")
    log(f"Filtro de Período (CATPERIODO): {selected_catperiodo if filter_by_period else 'Todos'}")

    try:
        test_token(url, token)
    except Exception as exc:
        log(f"Falha no token/site info: {exc}")
        return 2

    if args.create_categories != "1":
        log("Criação de categorias desativada. Nada a fazer.")
        log("FIM DA EXECUÇÃO")
        return 0

    allowed_coligadas = {c.strip() for c in (coligadas_csv or "").split(",") if c.strip()}
    if not allowed_coligadas:
        log("Nenhuma coligada selecionada na plataforma. Nada a fazer.")
        log("FIM DA EXECUÇÃO")
        return 0

    allowed_sorted = sorted(allowed_coligadas, key=lambda x: int(x) if x.isdigit() else x)
    log(f"Coligadas permitidas ({len(allowed_sorted)}): {', '.join(allowed_sorted)}")

    sql_cursos = get_rm_query("cursos")
    if not sql_cursos:
        log("Consulta RM 'cursos' está vazia. Cole na aba Consultas RM > Categorias.")
        log("FIM DA EXECUÇÃO")
        return 3

    log("------------------------------------------------------------")
    log("SQL RM (cursos/categorias) usada nesta execução:")
    log("------------------------------------------------------------")
    log(sql_cursos)

    t0 = now_ms()
    log("------------------------------------------------------------")
    log("Executando consulta RM: cursos/categorias...")
    columns, rows = rm_fetch(sql_cursos)
    dt_rm = now_ms() - t0
    log(f"Consulta RM concluída em {ms_to_s(dt_rm)} | Linhas retornadas: {len(rows)}")

    if not columns or not rows:
        log("Consulta RM 'cursos/categorias' não retornou dados.")
        log("FIM DA EXECUÇÃO")
        return 3

    idx_codcol = col_index(columns, "codcoligada")
    idx_coligada = col_index(columns, "coligada")
    idx_codperlet = col_index(columns, "periodo") or col_index(columns, "codperlet") or col_index(columns, "catperiodo")
    idx_idperlet = col_index(columns, "idperlet")
    idx_catmodalidade = col_index(columns, "catmodalidade")
    idx_curso = col_index(columns, "curso")

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

    if missing:
        log(
            "A consulta 'cursos/categorias' deve retornar as colunas: "
            "CODCOLIGADA, COLIGADA, CODPERLET (ou PERIODO/CATPERIODO), IDPERLET, CATMODALIDADE, CURSO."
        )
        log("Faltando: " + ", ".join(missing))
        log("FIM DA EXECUÇÃO")
        return 3

    # Estruturas (já filtradas)
    coligadas_map: Dict[str, str] = {}
    periodos_por_col: Dict[str, Set[str]] = {}
    modalidades_por_col_periodo: Dict[Tuple[str, str], Set[str]] = {}
    cursos_por_col_periodo_modalidade: Dict[Tuple[str, str, str], Set[str]] = {}

    # Contadores de diagnóstico (sem mudar lógica)
    seen_total = 0
    skip_coligada = 0
    skip_periodo = 0
    skip_catperiodo_empty = 0
    skip_modalidade_empty = 0
    skip_curso_empty = 0
    kept = 0

    for r in rows:
        seen_total += 1
        codcol = normalize_str(r[idx_codcol])
        coligada_nome = normalize_str(r[idx_coligada])
        catperiodo = normalize_str(r[idx_codperlet]).replace("/", "-")
        _idperlet = normalize_str(r[idx_idperlet])
        catmodalidade = normalize_str(r[idx_catmodalidade])
        curso = normalize_str(r[idx_curso])

        if not codcol or codcol not in allowed_coligadas:
            skip_coligada += 1
            continue

        if filter_by_period and catperiodo != selected_catperiodo:
            skip_periodo += 1
            continue

        if not catperiodo:
            skip_catperiodo_empty += 1
            continue
        if not catmodalidade:
            skip_modalidade_empty += 1
            continue
        if not curso:
            skip_curso_empty += 1
            continue

        kept += 1

        if codcol not in coligadas_map:
            coligadas_map[codcol] = coligada_nome

        periodos_por_col.setdefault(codcol, set()).add(catperiodo)
        modalidades_por_col_periodo.setdefault((codcol, catperiodo), set()).add(catmodalidade)
        cursos_por_col_periodo_modalidade.setdefault((codcol, catperiodo, catmodalidade), set()).add(curso)

    log("------------------------------------------------------------")
    log("RESUMO DOS FILTROS (APÓS CONSULTA RM):")
    log("------------------------------------------------------------")
    log(f"Linhas totais RM: {seen_total}")
    log(f"Linhas mantidas (após filtros): {kept}")
    log(f"Descartadas por coligada não permitida: {skip_coligada}")
    log(f"Descartadas por período (CATPERIODO) diferente: {skip_periodo}")
    log(f"Descartadas por CATPERIODO vazio: {skip_catperiodo_empty}")
    log(f"Descartadas por CATMODALIDADE vazio: {skip_modalidade_empty}")
    log(f"Descartadas por CURSO vazio: {skip_curso_empty}")

    total_periodos = sum(len(v) for v in periodos_por_col.values())
    total_modalidades = sum(len(v) for v in modalidades_por_col_periodo.values())
    total_cursos_unicos = sum(len(v) for v in cursos_por_col_periodo_modalidade.values())

    log("------------------------------------------------------------")
    log("RESUMO DO QUE SERÁ PROCESSADO (ITENS ÚNICOS):")
    log("------------------------------------------------------------")
    log(f"Coligadas: {len(coligadas_map)}")
    log(f"Períodos (CATPERIODO): {total_periodos}")
    log(f"Modalidades: {total_modalidades}")
    log(f"Cursos: {total_cursos_unicos}")

    if not coligadas_map:
        log("Após filtros, não há coligadas/períodos para processar. Verifique coligadas selecionadas e o período.")
        log("FIM DA EXECUÇÃO")
        return 0

    # Contadores de criação/encontro no Moodle
    created_root = 0
    created_coligadas = 0
    existing_coligadas = 0
    created_periodos = 0
    existing_periodos = 0
    created_modalidades = 0
    existing_modalidades = 0
    created_cursos = 0
    existing_cursos = 0

    t1 = now_ms()
    try:
        log("------------------------------------------------------------")
        log("INICIANDO SINCRONIZAÇÃO NO MOODLE (CATEGORIAS):")
        log("------------------------------------------------------------")

        # 1) raiz SALAS
        log("Nível 1: Raiz 'SALAS'")
        root_id = find_category_id(url, token, "SALAS", 0)
        if root_id is None:
            root_id = create_category(url, token, "SALAS", 0)
            created_root += 1
            log(f"- Criada: SALAS (id={root_id})")
        else:
            log(f"- Já existe: SALAS (id={root_id})")

        # 2) Coligadas
        log("Nível 2: Coligadas")
        coligada_cat_ids: Dict[str, int] = {}
        for codcol, col_nome in sorted(coligadas_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
            cat_name = f"{codcol}-{col_nome}".strip("-")
            cid, created = ensure_category(url, token, cat_name, root_id)
            coligada_cat_ids[codcol] = cid
            if created:
                created_coligadas += 1
                log(f"- Criada: {cat_name} (id={cid})")
            else:
                existing_coligadas += 1
                log(f"- Já existe: {cat_name} (id={cid})")
            time.sleep(0.05)

        # 3) Períodos
        log("Nível 3: Períodos (CATPERIODO)")
        periodo_cat_ids: Dict[Tuple[str, str], int] = {}
        for codcol, periods in periodos_por_col.items():
            parent_col_id = coligada_cat_ids.get(codcol)
            if not parent_col_id:
                continue
            for catperiodo in sorted(periods, reverse=True):
                pid, created = ensure_category(url, token, catperiodo, parent_col_id)
                periodo_cat_ids[(codcol, catperiodo)] = pid
                if created:
                    created_periodos += 1
                    log(f"  - Criado: {codcol} > {catperiodo} (id={pid})")
                else:
                    existing_periodos += 1
                    log(f"  - Já existe: {codcol} > {catperiodo} (id={pid})")
                time.sleep(0.05)

        # 4) Modalidades
        log("Nível 4: Modalidades")
        modalidade_cat_ids: Dict[Tuple[str, str, str], int] = {}
        for (codcol, catperiodo), modalidades in modalidades_por_col_periodo.items():
            parent_per_id = periodo_cat_ids.get((codcol, catperiodo))
            if not parent_per_id:
                log(f"  - Aviso: período não encontrado para CODCOLIGADA={codcol} CATPERIODO={catperiodo}. Pulando modalidades.")
                continue

            mods = sorted({m for m in modalidades if m.strip()})
            if not mods:
                continue

            log(f"  - Processando: {codcol} > {catperiodo} ({len(mods)} modalidades)")
            for mod in mods:
                mid, created = ensure_category(url, token, mod, parent_per_id)
                modalidade_cat_ids[(codcol, catperiodo, mod)] = mid
                if created:
                    created_modalidades += 1
                    log(f"    * Criada: {mod} (id={mid})")
                else:
                    existing_modalidades += 1
                    log(f"    * Já existe: {mod} (id={mid})")
                time.sleep(0.05)

        # 5) Cursos
        log("Nível 5: Cursos")
        for (codcol, catperiodo, mod), cursos in cursos_por_col_periodo_modalidade.items():
            parent_mod_id = modalidade_cat_ids.get((codcol, catperiodo, mod))
            if not parent_mod_id:
                log(f"  - Aviso: modalidade não encontrada para CODCOLIGADA={codcol} CATPERIODO={catperiodo} MODALIDADE={mod}. Pulando cursos.")
                continue

            cursos_clean = sorted({c for c in cursos if c.strip()})
            if not cursos_clean:
                continue

            log(f"  - Processando: {codcol} > {catperiodo} > {mod} ({len(cursos_clean)} cursos)")
            for curso_nome in cursos_clean:
                cid, created = ensure_category(url, token, curso_nome, parent_mod_id)
                if created:
                    created_cursos += 1
                    log(f"    + Criado: {curso_nome} (id={cid})")
                else:
                    existing_cursos += 1
                    log(f"    + Já existe: {curso_nome} (id={cid})")
                time.sleep(0.05)

        dt_moodle = now_ms() - t1
        log("============================================================")
        log("RELATÓRIO DE CONCLUSÃO")
        log("============================================================")
        log("Filtros usados:")
        log(f"- Plataforma: {platform_name} (ID {args.platform_id})")
        log(f"- Coligadas ({len(allowed_sorted)}): {', '.join(allowed_sorted)}")
        log(f"- Período (CATPERIODO): {selected_catperiodo if filter_by_period else 'Todos'}")
        log("")
        log("Consulta RM:")
        log(f"- Linhas retornadas: {len(rows)}")
        log(f"- Linhas mantidas após filtros: {kept}")
        log(f"- Tempo RM: {ms_to_s(dt_rm)}")
        log("")
        log("Itens únicos processados:")
        log(f"- Coligadas: {len(coligadas_map)}")
        log(f"- Períodos: {total_periodos}")
        log(f"- Modalidades: {total_modalidades}")
        log(f"- Cursos: {total_cursos_unicos}")
        log("")
        log("Moodle (criados vs já existentes):")
        log(f"- Raiz SALAS: criados={created_root}")
        log(f"- Coligadas: criados={created_coligadas} | já existiam={existing_coligadas}")
        log(f"- Períodos: criados={created_periodos} | já existiam={existing_periodos}")
        log(f"- Modalidades: criados={created_modalidades} | já existiam={existing_modalidades}")
        log(f"- Cursos: criados={created_cursos} | já existiam={existing_cursos}")
        log("")
        log(f"Tempo Moodle: {ms_to_s(dt_moodle)}")
        log("Execução concluída com sucesso.")
        return 0

    except Exception as exc:
        log("============================================================")
        log("FALHA NA EXECUÇÃO")
        log("============================================================")
        log(f"Erro ao criar categorias: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())