import os
import sqlite3
import subprocess
import sys

from api.app.config import ROOT, get_settings


def test_upgrade_populated_phase_zero_and_resume_partial_ddl(client, tmp_path):
    directory = tmp_path / "legacy"
    directory.mkdir()
    env = {**os.environ, "DATA_DIR": str(directory)}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "2dbee1114604"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    database = directory / "cuplik.sqlite3"
    with sqlite3.connect(database) as target:
        target.execute("PRAGMA foreign_keys=ON")
        target.execute(
            "INSERT INTO project (id,title,source_kind,source_ref,source_url,language,duration_s,ingest_status,transcript_status,error,job_id,created_at) VALUES ('p1','Data lama','demo','',NULL,'id',12,'done','done',NULL,NULL,'2026-11-18 00:00:00')"
        )
        target.execute(
            "INSERT INTO output (id,project_id,mode,settings,status,stage,progress,note,error,job_id,provider,actual_duration_s,created_at) VALUES ('o1','p1','clips','{}','done','done',1,'selesai',NULL,NULL,'mock',12,'2026-11-18 00:00:00')"
        )
        # Reproduce tables left by SQLite DDL before an interrupted/failed upgrade.
        with sqlite3.connect(get_settings().storage / "cuplik.sqlite3") as current:
            for table in ("task", "projectevent"):
                sql = current.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                target.execute(sql)
        target.execute("CREATE TABLE _alembic_tmp_project (id TEXT PRIMARY KEY)")
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as target:
        assert target.execute("SELECT title,updated_at FROM project WHERE id='p1'").fetchone() == (
            "Data lama",
            "2026-11-18 00:00:00",
        )
        assert target.execute("SELECT project_id FROM output WHERE id='o1'").fetchone() == ("p1",)
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []
        assert target.execute("SELECT stage,progress FROM project WHERE id='p1'").fetchone() == (
            "done",
            1.0,
        )
        assert (
            target.execute(
                "SELECT 1 FROM sqlite_master WHERE name='_alembic_tmp_project'"
            ).fetchone()
            is None
        )


def test_phase_two_upgrade_preserves_populated_clip(client, tmp_path):
    import json
    from datetime import datetime

    from api.app.models import Clip, Output, Project

    directory = tmp_path / "phase-one"
    directory.mkdir()
    env = {**os.environ, "DATA_DIR": str(directory)}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "7f3a10c2d8ab"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    path = directory / "cuplik.sqlite3"
    rows = [
        ("project", Project(id="old-project", title="Lama", source_kind="demo")),
        ("output", Output(id="old-output", project_id="old-project", mode="clips", status="done")),
        (
            "clip",
            Clip(
                id="old-clip",
                output_id="old-output",
                rank=1,
                start_s=0,
                end_s=12,
                topic="uji",
                titles=["A", "B"],
                hook_options=["C", "D"],
                score=8,
                rubric={"hook": 8},
                reason="Lama",
                file_path="outputs/old-output/old-clip.mp4",
            ),
        ),
    ]
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for table, row in rows:
            columns = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
            data = row.model_dump()
            values = [
                json.dumps(data[c])
                if isinstance(data[c], (dict, list))
                else str(data[c])
                if isinstance(data[c], datetime)
                else data[c]
                for c in columns
            ]
            db.execute(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                values,
            )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT score,file_path,selection FROM clip WHERE id='old-clip'"
        ).fetchone() == (8, "outputs/old-output/old-clip.mp4", "{}")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
