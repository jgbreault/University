"""SQLite cache and run ledger for V2 extraction experiments.

SQLite is deliberately a derived cache. The verifier still reads and writes
JSON artifacts; this store only avoids repeated OCR/retrieval/model work and
lets the dashboard compare runs quickly.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "v2_cache_1"
DEFAULT_DB_RELATIVE = Path("outputs") / "v2_runs" / "verification_runs.sqlite"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_db_path(root: Path) -> Path:
    return root / DEFAULT_DB_RELATIVE


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_json(data: Any) -> str:
    return hash_text(stable_json(data))


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(*parts: Any) -> str:
    return hash_text("\x1f".join(str(part) for part in parts))


def model_params_hash(params: dict[str, Any]) -> str:
    return hash_json(params)


class V2Store:
    """Small sqlite-backed cache with explicit stale-key hashes."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row
        self.init_schema()

    def close(self) -> None:
        self.connection.close()

    def init_schema(self) -> None:
        cur = self.connection.cursor()
        cur.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY,
              city TEXT NOT NULL,
              output_dir TEXT NOT NULL,
              created_at TEXT NOT NULL,
              pdf_hash TEXT NOT NULL,
              config_hash TEXT NOT NULL,
              prompt_hash TEXT NOT NULL,
              model_id TEXT NOT NULL,
              model_params_hash TEXT NOT NULL,
              source_repair_version TEXT NOT NULL,
              verifier_version TEXT NOT NULL,
              metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_chunks (
              cache_key TEXT PRIMARY KEY,
              city TEXT NOT NULL,
              pdf_hash TEXT NOT NULL,
              config_hash TEXT NOT NULL,
              chunk_id TEXT NOT NULL,
              page INTEGER,
              section TEXT,
              heading TEXT,
              parent_text TEXT,
              child_text TEXT,
              table_title TEXT,
              row_header TEXT,
              column_header TEXT,
              cell_value TEXT,
              text TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_source_chunks_run
              ON source_chunks(city, pdf_hash, config_hash);
            CREATE TABLE IF NOT EXISTS evidence_packs (
              cache_key TEXT PRIMARY KEY,
              city TEXT NOT NULL,
              pdf_hash TEXT NOT NULL,
              config_hash TEXT NOT NULL,
              discovery_hash TEXT NOT NULL,
              pack_id TEXT NOT NULL,
              page INTEGER,
              section TEXT,
              lane TEXT NOT NULL,
              source_text TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_packs_run
              ON evidence_packs(city, pdf_hash, config_hash, discovery_hash);
            CREATE TABLE IF NOT EXISTS model_outputs (
              cache_key TEXT PRIMARY KEY,
              run_id TEXT,
              city TEXT NOT NULL,
              model_id TEXT NOT NULL,
              model_params_hash TEXT NOT NULL,
              prompt_hash TEXT NOT NULL,
              pack_id TEXT NOT NULL,
              raw_json TEXT NOT NULL,
              parsed_ok INTEGER NOT NULL,
              latency_ms INTEGER NOT NULL,
              input_chars INTEGER NOT NULL,
              output_chars INTEGER NOT NULL,
              cost_estimate REAL NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_model_outputs_lookup
              ON model_outputs(city, model_id, model_params_hash, prompt_hash, pack_id);
            CREATE TABLE IF NOT EXISTS artifacts (
              run_id TEXT NOT NULL,
              artifact_name TEXT NOT NULL,
              path TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(run_id, artifact_name)
            );
            CREATE TABLE IF NOT EXISTS metrics (
              run_id TEXT NOT NULL,
              metric_name TEXT NOT NULL,
              metric_value REAL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(run_id, metric_name)
            );
            CREATE TABLE IF NOT EXISTS examiner_findings (
              finding_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              severity TEXT NOT NULL,
              category TEXT NOT NULL,
              file_path TEXT,
              line_start INTEGER,
              line_end INTEGER,
              claim TEXT NOT NULL,
              evidence TEXT NOT NULL,
              suggestion TEXT NOT NULL,
              advisory_only INTEGER NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        self.connection.commit()

    def record_run(
        self,
        *,
        run_id: str,
        city: str,
        output_dir: Path,
        pdf_hash: str,
        config_hash: str,
        prompt_hash: str,
        model_id: str,
        model_params_hash: str,
        source_repair_version: str,
        verifier_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO runs(
              run_id, city, output_dir, created_at, pdf_hash, config_hash,
              prompt_hash, model_id, model_params_hash, source_repair_version,
              verifier_version, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                city,
                str(output_dir),
                utc_now(),
                pdf_hash,
                config_hash,
                prompt_hash,
                model_id,
                model_params_hash,
                source_repair_version,
                verifier_version,
                stable_json(metadata or {}),
            ),
        )
        self.connection.commit()

    def upsert_source_chunks(
        self,
        *,
        city: str,
        pdf_hash: str,
        config_hash: str,
        chunks: Iterable[dict[str, Any]],
    ) -> None:
        now = utc_now()
        rows = []
        for chunk in chunks:
            key = cache_key(city, pdf_hash, config_hash, chunk.get("chunk_id"), chunk.get("text"))
            metadata = {**(chunk.get("metadata") or {}), "evidence_type": chunk.get("evidence_type")}
            rows.append(
                (
                    key,
                    city,
                    pdf_hash,
                    config_hash,
                    str(chunk.get("chunk_id") or ""),
                    chunk.get("page"),
                    str(chunk.get("section") or ""),
                    str(chunk.get("heading") or ""),
                    str(chunk.get("parent_text") or ""),
                    str(chunk.get("child_text") or ""),
                    str(chunk.get("table_title") or ""),
                    str(chunk.get("row_header") or ""),
                    str(chunk.get("column_header") or ""),
                    str(chunk.get("cell_value") or ""),
                    str(chunk.get("text") or ""),
                    stable_json(metadata),
                    now,
                )
            )
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO source_chunks(
              cache_key, city, pdf_hash, config_hash, chunk_id, page, section,
              heading, parent_text, child_text, table_title, row_header,
              column_header, cell_value, text, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()

    def get_source_chunks(self, *, city: str, pdf_hash: str, config_hash: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM source_chunks
            WHERE city = ? AND pdf_hash = ? AND config_hash = ?
            ORDER BY page, chunk_id
            """,
            (city, pdf_hash, config_hash),
        ).fetchall()
        return [_source_chunk_from_row(row) for row in rows]

    def upsert_evidence_packs(
        self,
        *,
        city: str,
        pdf_hash: str,
        config_hash: str,
        discovery_hash: str,
        packs: Iterable[dict[str, Any]],
    ) -> None:
        now = utc_now()
        rows = []
        for pack in packs:
            key = cache_key(city, pdf_hash, config_hash, discovery_hash, pack.get("pack_id"), pack.get("source_text"))
            rows.append(
                (
                    key,
                    city,
                    pdf_hash,
                    config_hash,
                    discovery_hash,
                    str(pack.get("pack_id") or ""),
                    pack.get("page"),
                    str(pack.get("section") or ""),
                    str(pack.get("lane") or ""),
                    str(pack.get("source_text") or ""),
                    stable_json({k: v for k, v in pack.items() if k not in {"source_text"}}),
                    now,
                )
            )
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO evidence_packs(
              cache_key, city, pdf_hash, config_hash, discovery_hash, pack_id,
              page, section, lane, source_text, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()

    def get_evidence_packs(
        self,
        *,
        city: str,
        pdf_hash: str,
        config_hash: str,
        discovery_hash: str,
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM evidence_packs
            WHERE city = ? AND pdf_hash = ? AND config_hash = ? AND discovery_hash = ?
            ORDER BY pack_id
            """,
            (city, pdf_hash, config_hash, discovery_hash),
        ).fetchall()
        return [_pack_from_row(row) for row in rows]

    def get_model_output(
        self,
        *,
        city: str,
        model_id: str,
        params_hash: str,
        prompt_hash: str,
        pack_id: str,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM model_outputs
            WHERE city = ? AND model_id = ? AND model_params_hash = ?
              AND prompt_hash = ? AND pack_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (city, model_id, params_hash, prompt_hash, pack_id),
        ).fetchone()
        return _model_output_from_row(row) if row else None

    def upsert_model_output(
        self,
        *,
        run_id: str,
        city: str,
        model_id: str,
        params_hash: str,
        prompt_hash: str,
        pack_id: str,
        raw: dict[str, Any],
        parsed_ok: bool,
        latency_ms: int,
        input_chars: int,
        output_chars: int,
        cost_estimate: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        key = cache_key(city, model_id, params_hash, prompt_hash, pack_id)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO model_outputs(
              cache_key, run_id, city, model_id, model_params_hash, prompt_hash,
              pack_id, raw_json, parsed_ok, latency_ms, input_chars,
              output_chars, cost_estimate, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                run_id,
                city,
                model_id,
                params_hash,
                prompt_hash,
                pack_id,
                stable_json(raw),
                1 if parsed_ok else 0,
                int(latency_ms),
                int(input_chars),
                int(output_chars),
                float(cost_estimate),
                stable_json(metadata or {}),
                utc_now(),
            ),
        )
        self.connection.commit()

    def record_artifact(self, *, run_id: str, artifact_name: str, path: Path, metadata: dict[str, Any] | None = None) -> None:
        content_hash = hash_file(path) if path.exists() else ""
        self.connection.execute(
            """
            INSERT OR REPLACE INTO artifacts(
              run_id, artifact_name, path, content_hash, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, artifact_name, str(path), content_hash, stable_json(metadata or {}), utc_now()),
        )
        self.connection.commit()

    def record_metrics(self, *, run_id: str, metrics: dict[str, Any]) -> None:
        rows = []
        now = utc_now()
        for name, value in metrics.items():
            metric_value = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            rows.append((run_id, name, metric_value, stable_json({"value": value}), now))
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO metrics(run_id, metric_name, metric_value, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()

    def insert_examiner_findings(self, *, run_id: str, findings: Iterable[dict[str, Any]]) -> None:
        now = utc_now()
        rows = []
        for index, finding in enumerate(findings, start=1):
            finding_id = str(finding.get("finding_id") or cache_key(run_id, index, finding.get("claim")))
            rows.append(
                (
                    finding_id,
                    run_id,
                    str(finding.get("severity") or "info"),
                    str(finding.get("category") or "unknown"),
                    finding.get("file_path"),
                    finding.get("line_start"),
                    finding.get("line_end"),
                    str(finding.get("claim") or ""),
                    str(finding.get("evidence") or ""),
                    str(finding.get("suggestion") or ""),
                    1 if finding.get("advisory_only", True) else 0,
                    stable_json({k: v for k, v in finding.items() if k not in {
                        "finding_id", "severity", "category", "file_path", "line_start",
                        "line_end", "claim", "evidence", "suggestion", "advisory_only",
                    }}),
                    now,
                )
            )
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO examiner_findings(
              finding_id, run_id, severity, category, file_path, line_start,
              line_end, claim, evidence, suggestion, advisory_only,
              metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()


def _json_field(row: sqlite3.Row, name: str) -> dict[str, Any]:
    try:
        value = json.loads(row[name] or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _source_chunk_from_row(row: sqlite3.Row) -> dict[str, Any]:
    metadata = _json_field(row, "metadata_json")
    evidence_type = metadata.get("evidence_type") or ("table_cell" if row["cell_value"] else "clause")
    return {
        "chunk_id": row["chunk_id"],
        "page": row["page"],
        "section": row["section"],
        "heading": row["heading"],
        "parent_text": row["parent_text"],
        "child_text": row["child_text"],
        "table_title": row["table_title"],
        "row_header": row["row_header"],
        "column_header": row["column_header"],
        "cell_value": row["cell_value"],
        "text": row["text"],
        "evidence_type": evidence_type,
        "metadata": metadata,
    }


def _pack_from_row(row: sqlite3.Row) -> dict[str, Any]:
    metadata = _json_field(row, "metadata_json")
    metadata.update(
        {
            "pack_id": row["pack_id"],
            "page": row["page"],
            "section": row["section"],
            "lane": row["lane"],
            "source_text": row["source_text"],
        }
    )
    return metadata


def _model_output_from_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        raw = json.loads(row["raw_json"])
    except json.JSONDecodeError:
        raw = {}
    return {
        "cache_key": row["cache_key"],
        "run_id": row["run_id"],
        "city": row["city"],
        "model_id": row["model_id"],
        "pack_id": row["pack_id"],
        "model_output": raw,
        "parsed_ok": bool(row["parsed_ok"]),
        "latency_ms": row["latency_ms"],
        "input_chars": row["input_chars"],
        "output_chars": row["output_chars"],
        "cost_estimate": row["cost_estimate"],
        "metadata": _json_field(row, "metadata_json"),
    }
