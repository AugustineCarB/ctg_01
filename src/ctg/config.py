"""Environment loading and Postgres connection helper."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing env var: {key}")
    return val


def connect():
    return psycopg2.connect(
        host=env("SUPABASE_DB_HOST"),
        port=int(env("SUPABASE_DB_PORT")),
        dbname=env("SUPABASE_DB_NAME"),
        user=env("SUPABASE_DB_USER"),
        password=env("SUPABASE_DB_PASSWORD"),
        sslmode="require",
    )
