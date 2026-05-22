-- Catalog of every series we track.
create table if not exists series (
    id            text primary key,
    source        text not null,
    native_code   text not null,
    title         text,
    units         text,
    frequency     text,
    last_updated  timestamptz default now()
);

-- Time-series observations, one row per (series, date).
create table if not exists observations (
    series_id  text not null references series(id) on delete cascade,
    ts         date not null,
    value      double precision,
    primary key (series_id, ts)
);

create index if not exists observations_series_ts_idx
    on observations (series_id, ts desc);

-- ETL run log.
create table if not exists runs (
    id              bigserial primary key,
    source          text not null,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    rows_upserted   integer,
    status          text,
    error_message   text
);
