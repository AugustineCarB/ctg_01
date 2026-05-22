"""Apply every .sql file in supabase/migrations in lexical order."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ctg.config import REPO_ROOT, connect  # noqa: E402


def main() -> None:
    migrations = sorted((REPO_ROOT / "supabase" / "migrations").glob("*.sql"))
    with connect() as conn, conn.cursor() as cur:
        for path in migrations:
            print(f"applying {path.name}")
            cur.execute(path.read_text())
    print("done")


if __name__ == "__main__":
    main()
