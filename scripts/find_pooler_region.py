"""Probe Supabase pooler regions to find the project's actual region."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-central-1", "eu-west-1", "eu-west-2",
    "ap-southeast-1", "ap-southeast-2", "ap-northeast-1", "ap-south-1",
    "sa-east-1", "ca-central-1",
]

ref = os.environ["SUPABASE_URL"].split("//")[1].split(".")[0]
password = os.environ["SUPABASE_DB_PASSWORD"]

for region in REGIONS:
    host = f"aws-0-{region}.pooler.supabase.com"
    try:
        conn = psycopg2.connect(
            host=host, port=5432, dbname="postgres",
            user=f"postgres.{ref}", password=password,
            sslmode="require", connect_timeout=5,
        )
        conn.close()
        print(f"MATCH: {region}")
        sys.exit(0)
    except Exception as e:
        msg = str(e).splitlines()[0][:80]
        print(f"  {region}: {msg}")

print("no region matched")
sys.exit(1)
