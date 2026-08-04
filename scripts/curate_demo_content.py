#!/usr/bin/env python3
"""Curadoria do conteúdo da demo pública — BE-12.

Porque é que isto existe: a demo tinha o LLM no caminho crítico do
primeiro contacto e demorava ~13,7s por pergunta, quando não estourava
de todo. Este comando move a geração para *offline*, deixando o primeiro
ecrã a servir conteúdo já pronto.

**A curadoria é deliberadamente um processo com humano no meio.** O
motivo é o próprio problema que estamos a resolver: quando a demo antiga
gerava ao vivo, produzia coisas como "resumo de alto nível — contagem de
linhas e tabelas mais usadas". Um comando que despejasse a saída do LLM
directamente na demo repetia esse erro mais depressa. Por isso são dois
passos separados:

    # 1. propõe — corre o motor e escreve candidatos para revisão
    python scripts/curate_demo_content.py --propose --vertical saas \\
        --out scripts/demo/proposed.json

    # 2. (um humano lê, corta, reescreve, e move para curated_content.json)

    # 3. aplica — valida e persiste
    python scripts/curate_demo_content.py --verify-sql        # dry-run
    python scripts/curate_demo_content.py --verify-sql --apply

Sem ``--apply`` não escreve nada, como os outros scripts deste repo.

``--verify-sql`` é o portão de qualidade que interessa: executa cada
``executed_sql`` e cada ``value_sql`` contra a base sintética real e
recusa aplicar o que rebentar. Conteúdo que afirme um número que o seu
próprio SQL não produz é pior do que não ter conteúdo nenhum — numa
demo comercial, um número errado que o prospect consegue conferir custa
a venda inteira. Os números dos ``stat_tiles`` e a série da sparkline
saem daí, não de valores escritos à mão que envelhecem em silêncio.

Formato JSON e não YAML de propósito: PyYAML não está declarado nas
dependências deste repo (só existe transitivamente), e o script tem de
poder correr dentro do container sem instalar nada.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# A consola do Windows abre em cp1252 e rebenta com UnicodeEncodeError
# no primeiro `✓` — o que transformava um relatório de erros úteis num
# traceback. Corrigir a codificação em vez de evitar os símbolos: o
# conteúdo curado é em português e tem acentos de qualquer maneira.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - stream sem reconfigure
        pass

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402
from src.models.demo_content import VERTICALS, DemoDataset, DemoInsight, DemoQA  # noqa: E402

DEFAULT_CONTENT = ROOT / "scripts" / "demo" / "curated_content.json"

# Nomes das connections sintéticas, de scripts/seed_demo_connections.py.
# Os IDs são mintados no seed e por isso não são fixos — a referência é
# pelo nome, e `DemoDataset.connection_ref` guarda o nome também.
DEMO_CONNECTION_NAMES = [
    "Demo — Sales",
    "Demo — Marketing",
    "Demo — Finance",
    "Demo — Web Analytics",
    "Demo — Product Usage",
]

# Termos que denunciam uma resposta sobre metadados em vez de sobre o
# negócio. É a regra editorial escrita em código: foi conteúdo deste
# género que arruinou a primeira impressão da demo antiga, e uma regra
# que só vive num comentário não impede ninguém de a violar às 2 da
# manhã antes de uma reunião.
METADATA_SMELL = (
    "row count",
    "number of rows",
    "most used table",
    "most-used table",
    "table count",
    "schema summary",
    "high-level summary",
    "contagem de linhas",
    "número de linhas",
    "resumo do esquema",
)


# ── ligação à base sintética ────────────────────────────────────────


def _demo_dsn() -> Optional[str]:
    host = os.environ.get("DEMO_PG_HOST", "")
    user = os.environ.get("DEMO_PG_USER", "")
    password = os.environ.get("DEMO_PG_PASSWORD", "")
    if not (host and user and password):
        return None
    port = os.environ.get("DEMO_PG_PORT", "5432")
    db = os.environ.get("DEMO_PG_DB", "postgres")
    ssl = os.environ.get("DEMO_PG_SSL_MODE", "require")
    return (
        f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
        f"?ssl={'require' if ssl != 'disable' else 'disable'}"
    )


class SqlVerifier:
    """Executa o SQL curado contra a base sintética real.

    Sem ela, o conteúdo é uma afirmação; com ela, é uma medição. É a
    diferença entre uma demo que aguenta ser inspeccionada e uma que não.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    async def scalar(self, sql: str) -> Any:
        async with self._engine.connect() as conn:
            return (await conn.execute(text(sql))).scalar()

    async def rows(self, sql: str, limit: int = 50) -> List[Dict[str, Any]]:
        async with self._engine.connect() as conn:
            res = await conn.execute(text(sql))
            cols = list(res.keys())
            return [dict(zip(cols, r)) for r in res.fetchmany(limit)]


def _format_value(raw: Any, fmt: Optional[str]) -> str:
    if raw is None:
        return "—"
    if fmt == "eur":
        return f"{float(raw):,.0f} €".replace(",", " ")
    if fmt == "pct":
        return f"{float(raw):.1f}%"
    if isinstance(raw, float):
        return f"{raw:,.1f}".replace(",", " ")
    return f"{raw:,}".replace(",", " ") if isinstance(raw, int) else str(raw)


# ── validação editorial ─────────────────────────────────────────────


def _editorial_problems(spec: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    insight = spec.get("insight") or {}
    qas = spec.get("qas") or []

    haystacks = [insight.get("title", ""), insight.get("summary", "")]
    haystacks += [q.get("question", "") for q in qas]
    for text_ in haystacks:
        low = text_.lower()
        for smell in METADATA_SMELL:
            if smell in low:
                problems.append(f"conteúdo sobre metadados ({smell!r}): {text_[:70]!r}")

    if not insight.get("executed_sql"):
        problems.append("o insight não tem executed_sql — sem 'ver o SQL' não há prova")
    if len(insight.get("stat_tiles") or []) > 3:
        problems.append("mais de 3 stat_tiles — não cabem no ecrã")

    suggested = [q for q in qas if q.get("is_suggested")]
    if len(suggested) < 3:
        problems.append(f"só {len(suggested)} perguntas sugeridas — o ecrã precisa de 3")
    if len(qas) <= len(suggested):
        problems.append("não há perguntas não-sugeridas — o fallback de /demo/ask fica sem alvos")
    for qa in qas:
        if not qa.get("answer_markdown"):
            problems.append(f"pergunta sem resposta: {qa.get('question', '')[:60]!r}")

    vertical = spec.get("vertical")
    if vertical not in VERTICALS:
        problems.append(f"vertical {vertical!r} não está em {VERTICALS}")
    return problems


# ── aplicação ───────────────────────────────────────────────────────


async def _upsert_dataset(db: AsyncSession, spec: Dict[str, Any]) -> DemoDataset:
    vertical, locale = spec["vertical"], spec.get("locale", "en")
    ds = (
        await db.execute(
            select(DemoDataset).where(
                DemoDataset.vertical == vertical, DemoDataset.locale == locale
            )
        )
    ).scalar_one_or_none()

    if ds is None:
        ds = DemoDataset(id=uuid.uuid4(), vertical=vertical, locale=locale)
        db.add(ds)

    ds.name = spec["name"]
    ds.description = spec.get("description")
    ds.connection_ref = spec.get("connection_ref")
    ds.is_default = bool(spec.get("is_default"))
    await db.flush()
    return ds


async def _replace_content(
    db: AsyncSession,
    ds: DemoDataset,
    spec: Dict[str, Any],
    verifier: Optional[SqlVerifier],
) -> None:
    """Substitui insight e QAs do dataset.

    Substituir em vez de acrescentar: o ficheiro curado é a fonte de
    verdade. Acumular deixaria conteúdo apagado do ficheiro a continuar
    a aparecer na demo, que é a pior classe de bug num sítio comercial —
    invisível para quem edita, visível para o prospect.
    """
    for row in (
        (await db.execute(select(DemoInsight).where(DemoInsight.dataset_id == ds.id)))
        .scalars()
        .all()
    ):
        await db.delete(row)
    for row in (await db.execute(select(DemoQA).where(DemoQA.dataset_id == ds.id))).scalars().all():
        await db.delete(row)
    await db.flush()

    ispec = spec["insight"]

    tiles: List[Dict[str, Any]] = []
    for tile in ispec.get("stat_tiles") or []:
        value = tile.get("value")
        if "value_sql" in tile:
            if verifier is None:
                # Sem verificação não se inventa um número: mostra-se
                # um traço. Um valor plausível mas não medido é
                # exactamente o que esta pipeline existe para impedir.
                value = "—"
            else:
                value = _format_value(await verifier.scalar(tile["value_sql"]), tile.get("format"))
        tiles.append({"label": tile["label"], "value": value})

    series = ispec.get("series")
    if verifier is not None and ispec.get("series_sql"):
        series = [
            {"t": str(r[list(r)[0]]), "v": float(r[list(r)[1]])}
            for r in await verifier.rows(ispec["series_sql"], limit=36)
        ]

    db.add(
        DemoInsight(
            id=uuid.uuid4(),
            dataset_id=ds.id,
            severity=ispec["severity"],
            severity_level=ispec.get("severity_level", "info"),
            agent_name=ispec["agent_name"],
            title=ispec["title"],
            summary=ispec["summary"],
            series=series,
            stat_tiles=tiles,
            sources=ispec.get("sources") or [],
            executed_sql=ispec.get("executed_sql"),
            position=0,
        )
    )

    for qspec in spec.get("qas") or []:
        db.add(
            DemoQA(
                id=uuid.uuid4(),
                dataset_id=ds.id,
                question=qspec["question"],
                answer_markdown=qspec["answer_markdown"],
                citations=qspec.get("citations") or [],
                chart_spec=qspec.get("chart_spec"),
                executed_sql=qspec.get("executed_sql"),
                position=qspec.get("position", 0),
                is_suggested=bool(qspec.get("is_suggested", True)),
                # `embedding` fica NULL. Não há hoje forma de o produzir
                # do lado do backend: `src/ai/embeddings.py` não existe,
                # e o fallback de /demo/ask apanha o ImportError e usa a
                # primeira sugerida. Funciona; só não é semântico. Ver
                # BE-15.
            )
        )
    await db.flush()


async def cmd_apply(content_path: Path, apply_changes: bool, verify_sql: bool) -> int:
    spec_doc = json.loads(content_path.read_text(encoding="utf-8"))
    datasets = spec_doc.get("datasets") or []
    if not datasets:
        print(f"✗ {content_path} não tem datasets.", file=sys.stderr)
        return 1

    verifier = None
    engine = None
    if verify_sql:
        dsn = _demo_dsn()
        if not dsn:
            print(
                "✗ --verify-sql pedido mas faltam DEMO_PG_HOST / DEMO_PG_USER /\n"
                "  DEMO_PG_PASSWORD. Sem eles não há como confirmar os números.\n"
                "  Corre sem --verify-sql para aplicar à mesma (os stat_tiles\n"
                "  calculados ficam a '—').",
                file=sys.stderr,
            )
            return 2
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(dsn, pool_pre_ping=True)
        verifier = SqlVerifier(engine)

    try:
        # Portão editorial antes de tocar na base.
        blocked = False
        for spec in datasets:
            problems = _editorial_problems(spec)
            if problems:
                blocked = True
                print(f"\n✗ {spec.get('vertical')}: {len(problems)} problema(s)")
                for p in problems:
                    print(f"    · {p}")
        if blocked:
            print("\nNada aplicado. Corrige o ficheiro curado.", file=sys.stderr)
            return 3

        # Portão de SQL.
        #
        # Verificar que o SQL *executa* não chega — foi a lição de correr
        # isto contra dados reais pela primeira vez. A pergunta sobre
        # facturas vencidas executava perfeitamente e devolvia zero
        # linhas, porque a base sintética não tem uma única factura em
        # atraso. Uma tabela vazia numa demo comercial é tão má como um
        # erro: o visitante conclui que o produto não encontrou nada.
        if verifier is not None:
            failures = 0
            for spec in datasets:
                for label, sql in _all_sql(spec):
                    try:
                        rows = await verifier.rows(sql, limit=2)
                    except Exception as exc:  # noqa: BLE001
                        print(f"✗ SQL falhou [{spec['vertical']} / {label}]: {exc}")
                        failures += 1
                        continue
                    if not rows:
                        print(
                            f"✗ SQL sem resultados [{spec['vertical']} / {label}] — "
                            "a demo mostraria um quadro vazio"
                        )
                        failures += 1
                # A série tem de variar. Uma sparkline constante ocupa
                # espaço no ecrã para não dizer nada, e quando a linha é
                # perfeitamente recta parece dados inventados — que é o
                # oposto do que a demo tem de provar.
                series_sql = (spec.get("insight") or {}).get("series_sql")
                if series_sql:
                    points = await verifier.rows(series_sql, limit=60)
                    values = {
                        str(p[list(p)[1]])
                        for p in points
                        if list(p)[1:] and p[list(p)[1]] is not None
                    }
                    if len(values) < 2:
                        print(
                            f"✗ série constante [{spec['vertical']}] — "
                            f"{len(points)} pontos, todos iguais"
                        )
                        failures += 1
                if failures == 0:
                    print(f"  ✓ SQL verificado: {spec['vertical']}")
            if failures:
                print(f"\nNada aplicado. {failures} problema(s) de SQL.", file=sys.stderr)
                return 4

        if not apply_changes:
            print("\n(dry-run) Tudo válido. Repete com --apply para persistir.")
            for spec in datasets:
                print(
                    f"  · {spec['vertical']}/{spec.get('locale', 'en')}: "
                    f"1 insight + {len(spec.get('qas') or [])} perguntas"
                )
            return 0

        async with AsyncSessionLocal() as db:
            for spec in datasets:
                ds = await _upsert_dataset(db, spec)
                await _replace_content(db, ds, spec, verifier)
                print(
                    f"  ✓ {spec['vertical']}/{ds.locale}: insight + "
                    f"{len(spec.get('qas') or [])} perguntas (dataset {ds.id})"
                )
            await db.commit()
        print("\nFeito.")
        return 0
    finally:
        if engine is not None:
            await engine.dispose()


def _all_sql(spec: Dict[str, Any]):
    ispec = spec.get("insight") or {}
    if ispec.get("executed_sql"):
        yield "insight", ispec["executed_sql"]
    if ispec.get("series_sql"):
        yield "insight.series", ispec["series_sql"]
    for tile in ispec.get("stat_tiles") or []:
        if tile.get("value_sql"):
            yield f"tile:{tile['label'][:28]}", tile["value_sql"]
    for qa in spec.get("qas") or []:
        if qa.get("executed_sql"):
            yield f"qa:{qa['question'][:28]}", qa["executed_sql"]


# ── proposta ────────────────────────────────────────────────────────


async def cmd_propose(vertical: str, out_path: Path, questions: List[str]) -> int:
    """Corre o motor sobre as connections da demo e escreve candidatos.

    **Não escreve na base.** A saída é um ficheiro para um humano ler,
    cortar e reescrever. É esse passo manual que separa isto da demo
    antiga, que servia o que o LLM calhasse dizer.
    """
    from src.ai.real_service import RealAIService
    from src.models.connection import DataConnection

    async with AsyncSessionLocal() as db:
        conns = (
            (
                await db.execute(
                    select(DataConnection).where(
                        DataConnection.name.in_(DEMO_CONNECTION_NAMES),
                        DataConnection.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    if not conns:
        print(
            "✗ Não há connections da demo. Corre scripts/seed_demo_connections.py.",
            file=sys.stderr,
        )
        return 1

    primary = conns[0]
    space_id = os.environ.get("DEMO_SPACE_ID", "default")
    svc = RealAIService()
    proposals: List[Dict[str, Any]] = []

    for q in questions:
        print(f"  … {q[:70]}")
        try:
            res = await svc.process_query(
                connection_id=str(primary.id),
                question=q,
                user_id="curation",
                space_id=space_id,
                connection_ids=[str(c.id) for c in conns],
                locale="en",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    ✗ {exc}")
            continue

        if res.get("error"):
            print(f"    ✗ motor: {res['error']}")
            continue

        proposals.append(
            {
                "question": q,
                "answer_markdown": res.get("answer", ""),
                "executed_sql": res.get("sql"),
                "citations": res.get("citations") or [],
                "_chosen_datasets": res.get("chosen_datasets"),
                "_num_rows": res.get("num_rows"),
                "_data_sample": (res.get("data_sample") or [])[:5],
                "is_suggested": False,
                "position": 99,
            }
        )

    out_path.write_text(
        json.dumps(
            {
                "_readme": [
                    "CANDIDATOS — não é conteúdo final.",
                    "Ler, cortar o que for sobre metadados, reescrever as respostas",
                    "em linguagem de negócio, escolher 3 para is_suggested, e mover",
                    "para scripts/demo/curated_content.json.",
                    "Os campos com _ são contexto para a revisão e são ignorados.",
                ],
                "vertical": vertical,
                "proposals": proposals,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n{len(proposals)}/{len(questions)} candidatos → {out_path}")
    print("Revê à mão antes de aplicar.")
    return 0


DEFAULT_PROPOSE_QUESTIONS = [
    "Which customers are most likely to churn, and what revenue is at stake?",
    "Which marketing channel actually produces revenue, not just leads?",
    "How much revenue is sitting in overdue invoices, and who owes it?",
    "What is the win rate, and how long does a deal take to close?",
    "Which features do healthy customers use that at-risk ones don't?",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--propose",
        action="store_true",
        help="Corre o motor e escreve candidatos para revisão humana. Não toca na base.",
    )
    parser.add_argument("--vertical", default="saas", help="Vertical a propor.")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "scripts" / "demo" / "proposed.json",
        help="Onde escrever os candidatos (--propose).",
    )
    parser.add_argument(
        "--content",
        type=Path,
        default=DEFAULT_CONTENT,
        help="Ficheiro curado a aplicar.",
    )
    parser.add_argument(
        "--verify-sql",
        action="store_true",
        help="Executa cada SQL contra a base sintética e recusa aplicar o que falhar. "
        "É também o que calcula os stat_tiles e a série.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persiste. Sem esta flag o comando é dry-run.",
    )
    args = parser.parse_args()

    # A verificação vive aqui e não no import de propósito: no topo do
    # módulo tornava o ficheiro impossível de importar num teste, e as
    # regras editoriais são precisamente a parte que tem de ser testada.
    if not os.environ.get("DATABASE_URL"):
        print("Define DATABASE_URL primeiro (source .env.local).", file=sys.stderr)
        return 1

    if args.propose:
        return asyncio.run(cmd_propose(args.vertical, args.out, DEFAULT_PROPOSE_QUESTIONS))
    return asyncio.run(cmd_apply(args.content, args.apply, args.verify_sql))


if __name__ == "__main__":
    sys.exit(main())
