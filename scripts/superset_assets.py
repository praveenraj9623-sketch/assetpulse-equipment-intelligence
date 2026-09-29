"""Superset 3.0 container worker. Invoked by setup_superset.py, not directly.

CRUD uses authenticated REST routes through Flask's local test client. This uses
the already-authorized container administrator, does not change passwords, and
keeps CSRF checks enabled. It is deliberately a local administrative workflow.
"""
import copy
import datetime as dt
import io
import json
import logging
import math
import os
from pathlib import Path
import secrets
import sys
import warnings
import zipfile

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
import yaml

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

RANGE = "2020-02-01 : 2020-09-02"
SLUG = "assetpulse-equipment-intelligence"
DATABASE = "AssetPulse Analytics (read only)"
ROLE = "assetpulse_analytics"
SECRET = Path("/app/superset_home/assetpulse_analytics.json")
OUT = Path("/tmp/assetpulse-export")


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def metric(name, expression, description, fmt=",.0f"):
    return {"metric_name": name, "verbose_name": name, "expression": expression,
            "description": description, "d3format": fmt}


def provision_database(payload):
    admin = psycopg2.connect(host="db", dbname="assetpulse", user="assetpulse",
                            password=payload.pop("admin_password"))
    with admin, admin.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(74193001)")
        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)", (ROLE,))
        exists = cursor.fetchone()[0]
        if SECRET.exists():
            credential = json.loads(SECRET.read_text())
        elif exists:
            raise RuntimeError("Analytics role exists without saved credentials; refusing to rotate it")
        else:
            credential = {"username": ROLE, "password": secrets.token_urlsafe(36)}
            # Persist before creating role so interrupted runs can reuse the same value.
            fd = os.open(SECRET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(credential, stream)
        if not exists:
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Identifier(ROLE)), (credential["password"],))
        cursor.execute(payload["analytics_sql"])
        cursor.execute(payload["eligibility_sql"])
        cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE assetpulse TO {}").format(sql.Identifier(ROLE)))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(ROLE)))
        cursor.execute(sql.SQL("GRANT SELECT ON mart_hourly, mart_daily, mart_candidate_hours, mart_hourly_investigation, mart_incidents, mart_report_review, failure_reports, dataset_state, analytics_operating_states, analytics_data_quality TO {}").format(sql.Identifier(ROLE)))
        cursor.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(ROLE)))
        cursor.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '60s'").format(sql.Identifier(ROLE)))
    weighted_checks = []
    with admin, admin.cursor() as cursor:
        for start, end in [("2020-02-01", "2020-09-02"), ("2020-04-01", "2020-05-01")]:
            cursor.execute("""SELECT COUNT(*), AVG(tp3), AVG(oil_temperature),
                COUNT(*) FILTER (WHERE motor_current >= 6),
                COUNT(*) FILTER (WHERE motor_current >= 6 AND tp3 < 7)
                FROM readings WHERE observed_at >= %s AND observed_at < %s""", (start, end))
            raw = cursor.fetchone()
            for table, time_col, panel, oil in [
                ("mart_hourly", "hour_ts", "panel_pressure_sum", "oil_temperature_sum"),
                ("mart_daily", "reading_date", "avg_panel_pressure_bar * readings", "avg_oil_temperature_c * readings")]:
                cursor.execute(f"SELECT SUM(readings), SUM({panel})/SUM(readings), SUM({oil})/SUM(readings), SUM(loaded_readings), SUM(low_pressure_loaded_readings) FROM {table} WHERE {time_col} >= %s AND {time_col} < %s", (start, end))
                rolled = cursor.fetchone()
                assert all(math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-8) for a, b in zip(raw, rolled))
                weighted_checks.append({"model": table, "start_inclusive": start, "end_exclusive": end, "raw_observation_count": raw[0], "panel_pressure_bar": raw[1], "oil_temperature_c": raw[2], "loaded_observations": raw[3], "low_pressure_loaded_observations": raw[4], "weighted_rollup_matches_raw": True})
    admin.close()
    conn = psycopg2.connect(host="db", dbname="assetpulse", user=ROLE, password=credential["password"])
    return credential, conn, weighted_checks


class API:
    def __init__(self, app, user):
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True
        response = self.client.get("/api/v1/security/csrf_token/")
        assert response.status_code == 200
        self.headers = {"X-CSRFToken": response.get_json()["result"]}

    def call(self, method, path, body=None):
        response = self.client.open("/api/v1/" + path, method=method,
                                    json=body, headers=self.headers)
        if response.status_code not in (200, 201):
            # Never print response bodies for database connections.
            if not path.startswith("database"):
                print("API validation:", path, response.status_code, response.get_json())
            raise RuntimeError("API " + method + " " + path + " failed: " + str(response.status_code))
        return response.get_json()

    def items(self, kind):
        # Paginate: reruns must also work alongside unrelated assets.
        items, page = [], 0
        while True:
            result = self.call("GET", kind + "/?q=" + json.dumps({"page": page, "page_size": 100}))
            items.extend(result["result"])
            if len(items) >= result["count"]:
                return items
            page += 1

    def upsert(self, kind, body, key, value):
        matches = [item for item in self.items(kind) if item.get(key) == value]
        if len(matches) > 1:
            raise RuntimeError("Ambiguous duplicate " + kind + ": " + value)
        if matches:
            identity = matches[0]["id"]
            if kind == "chart":
                existing = self.call("GET", f"chart/{identity}")["result"]
                if json.loads(existing["params"])["datasource"] != f"{body['datasource_id']}__table":
                    raise RuntimeError("Chart title belongs to another dataset; refusing to overwrite")
            self.call("PUT", f"{kind}/{identity}", body)
            return identity
        return self.call("POST", kind + "/", body)["id"]


def common_metrics(daily=False):
    def weighted(sum_column, avg_column):
        return f"SUM({avg_column} * readings) / NULLIF(SUM(readings), 0)" if daily else f"SUM({sum_column}) / NULLIF(SUM(readings), 0)"
    return [
        metric("Observations", "COALESCE(SUM(readings), 0)", "Sensor observations; additive across disjoint time bins."),
        metric("Loaded observations", "COALESCE(SUM(loaded_readings), 0)", "Motor current >= 6 A; observation count, not duration."),
        metric("Low pressure among loaded (%)", "100.0 * SUM(low_pressure_loaded_readings) / NULLIF(SUM(loaded_readings), 0)", "TP3 < 7 bar and motor current >= 6 A, divided by loaded observations. NULL when none loaded.", ".2f"),
        metric("Panel pressure (bar)", weighted("panel_pressure_sum", "avg_panel_pressure_bar"), "Observation-weighted TP3 pressure. Denominator is observations.", ".3f"),
        metric("Oil temperature (C)", weighted("oil_temperature_sum", "avg_oil_temperature_c"), "Observation-weighted oil temperature, degrees Celsius.", ".2f"),
        metric("Pressure gap (bar)", weighted("pressure_gap_sum", "avg_pressure_gap_bar"), "Observation-weighted absolute TP3 minus reservoir pressure.", ".3f"),
    ]


def datasets(api, database):
    definitions = {
        "mart_hourly": ("hour_ts", common_metrics(), "One row per observed hour; sums support observation-weighted rollups."),
        "mart_daily": ("reading_date", common_metrics(True), "One row per observed date. Reweight daily means by readings for multi-day summaries."),
        "mart_hourly_investigation": ("hour_ts", common_metrics() + [
            metric("Candidate hours", "COUNT(*) FILTER (WHERE candidate_status = 'REVIEW_PRESSURE')", "Observed hours meeting unchanged pressure-v1 rule."),
            metric("Eligible hours", "COUNT(*) FILTER (WHERE rule_eligible)", "Current loaded count >=30 and preceding seven-day loaded count >=300, with both rates available."),
            metric("Eligibility (%)", "100.0 * COUNT(*) FILTER (WHERE rule_eligible) / NULLIF(COUNT(*), 0)", "Eligible observed hours / all observed hours in the selected period. Not elapsed calendar hours; NULL for an empty period.", ".2f"),
            metric("Not evaluated hours", "COUNT(*) FILTER (WHERE evaluation_status = 'Not evaluated')", "Excluded hours are not evaluated no-breach results."),
            metric("Current samples only", "COUNT(*) FILTER (WHERE current_samples_insufficient AND NOT baseline_samples_insufficient)", "Current loaded samples <30; baseline samples >=300."),
            metric("Baseline samples only", "COUNT(*) FILTER (WHERE baseline_samples_insufficient AND NOT current_samples_insufficient)", "Prior loaded samples <300; current samples >=30."),
            metric("Both sample requirements", "COUNT(*) FILTER (WHERE current_samples_insufficient AND baseline_samples_insufficient)", "Both sample minima fail; mutually exclusive with the single-reason counts."),
            metric("Missing rates", "COUNT(*) FILTER (WHERE NOT current_samples_insufficient AND NOT baseline_samples_insufficient AND NOT rule_eligible)", "Defensive exclusion: no valid rate despite sufficient counts; not coerced to no breach."),
            metric("Observed hours", "COUNT(*)", "Observed hourly windows, not elapsed operating hours."),
            metric("Prior 7-day loaded share (%)", "CASE WHEN COUNT(*) = 1 THEN 100.0 * MAX(prior_low_fraction) END", "Hourly point only. Ratio of prior low/loaded counts; excludes current hour. NULL when grouping multiple hours to prevent overlapping-window averaging.", ".2f"),
            metric("Rule floor (%)", "15.0", "pressure-v1 fixed floor; eligibility also required.", ".1f"),
            metric("2x prior baseline (%)", "CASE WHEN COUNT(*) = 1 THEN 200.0 * MAX(prior_low_fraction) END", "Hourly point only; current share must meet BOTH this threshold and 15% floor.", ".2f"),
        ], "One row per observed hour with prior seven-day context. Maintenance overlap is an external overlay, never rule input."),
        "mart_incidents": ("starts_at", [metric("Candidate incidents", "COUNT(*)", "Consecutive candidate-hour islands. Not confirmed failures or downtime.")], "One row per contiguous candidate incident. Zero rows is a valid result. Time filter applies to incident start."),
        "mart_report_review": ("starts_at", [metric("Maintenance reports", "COUNT(*)", "Externally reported intervals; not exhaustive fault labels.")], "Four external maintenance intervals with candidate counts. Prior-24-hour count uses hour-ending boundaries. Full-source dashboard context."),
        "analytics_operating_states": ("hour_ts", [metric("State observations", "COALESCE(SUM(observations), 0)", "Mutually exclusive current-based states; counts reconcile to all observations.")], "Three operating-state observation counts per observed hour; state thresholds are current proxies."),
        "analytics_data_quality": (None, [metric("Source rows", "MAX(raw_observations)", "Whole-source context, excluded from time filter.")], "Single full-source quality row. loaded_at is pipeline load time, not a live telemetry timestamp."),
    }
    output = {}
    for name, (time_col, metrics, description) in definitions.items():
        matches = [d for d in api.items("dataset") if d["table_name"] == name and d.get("schema") == "public" and d["database"]["id"] == database]
        assert len(matches) <= 1
        identity = matches[0]["id"] if matches else api.call("POST", "dataset/", {"database": database, "schema": "public", "table_name": name})["id"]
        api.call("PUT", f"dataset/{identity}/refresh")
        detail = api.call("GET", f"dataset/{identity}")["result"]
        existing_metrics = {m["metric_name"]: m for m in detail["metrics"]}
        for m in metrics:
            if m["metric_name"] in existing_metrics:
                m["id"] = existing_metrics[m["metric_name"]]["id"]
        columns = [{"id": c["id"], "column_name": c["column_name"], "is_dttm": c["column_name"] in ["hour_ts", "reading_date", "starts_at", "ends_at", "first_observation", "last_observation", "pipeline_loaded_at"],
                    "verbose_name": "Pipeline loaded at (UTC)" if c["column_name"] == "pipeline_loaded_at" else c["column_name"].replace("_", " ").capitalize()} for c in detail["columns"]]
        api.call("PUT", f"dataset/{identity}", {"description": description, "main_dttm_col": time_col,
                  "metrics": metrics, "columns": columns, "cache_timeout": 0})
        output[name] = {"id": identity, "time": time_col, "metrics": metrics, "columns": [c["column_name"] for c in columns]}
    return output


def build_charts(api, ds, dashboard):
    charts = []

    def add(key, title, dataset, viz, metrics=None, columns=None, grain="P1D", full=False, filters=None, description="", width=6, height=45, groups=None, number_format=",.0f"):
        source = ds[dataset]
        form = {"datasource": f"{source['id']}__table", "viz_type": viz,
                "time_range": "No filter" if full else RANGE, "granularity_sqla": source["time"],
                "time_grain_sqla": grain, "adhoc_filters": filters or [], "row_limit": 10000,
                "metrics": metrics or [], "groupby": [], "color_scheme": "supersetColors",
                "show_legend": True, "legendType": "scroll", "legendOrientation": "top",
                "rich_tooltip": True, "tooltipTimeFormat": "%Y-%m-%d %H:%M",
                "y_axis_format": ".2f", "x_axis_time_format": "%b %d", "truncateYAxis": False}
        query = {"time_range": form["time_range"], "granularity": source["time"],
                 "filters": [], "metrics": metrics or [], "columns": [], "row_limit": 10000,
                 "orderby": [], "is_timeseries": False,
                 "extras": {"time_grain_sqla": grain, "having": "", "where": ""}}
        if viz == "big_number_total":
            form.update(metric=metrics[0], subheader="", y_axis_format=number_format, header_font_size=0.35)
        elif viz == "echarts_timeseries_line":
            form.update(x_axis=source["time"], seriesType="line", showValue=False,
                        markerEnabled=False, zoomable=True, connect_nulls=False,
                        resample_rule="h" if grain == "PT1H" else "D", resample_method="asfreq")
            query["is_timeseries"] = True
            query["post_processing"] = [
                {"operation": "pivot", "options": {"index": ["__timestamp"], "columns": [], "aggregates": {m: {"operator": "mean"} for m in metrics}, "drop_missing_columns": False}},
                {"operation": "resample", "options": {"rule": form["resample_rule"], "method": "asfreq", "fill_value": None}},
                {"operation": "flatten"}]
        elif viz == "echarts_timeseries_bar":
            form.update(x_axis=columns[0], groupby=[], orientation="horizontal", showValue=True, y_axis_format=",.0f")
            query["columns"] = columns
        elif viz == "table":
            form.update(query_mode="raw" if columns else "aggregate", all_columns=columns or [],
                        groupby=[] if columns else (groups if groups is not None else ["candidate_status"]), page_length=10,
                        include_search=dataset == "mart_incidents", order_desc=False, table_timestamp_format="%Y-%m-%d %H:%M", allow_render_html=False)
            query["columns"] = columns or (groups if groups is not None else ["candidate_status"])
            if columns and "starts_at" in columns:
                form["order_by_cols"] = [json.dumps(["starts_at", True])]
                query["orderby"] = [["starts_at", True]]
        context = {"datasource": {"id": source["id"], "type": "table"}, "force": True,
                   "queries": [query], "form_data": form, "result_format": "json", "result_type": "full"}
        body = {"slice_name": title, "viz_type": viz, "datasource_id": source["id"],
                "datasource_type": "table", "params": json.dumps(form), "query_context": json.dumps(context),
                "description": description, "dashboards": [dashboard], "cache_timeout": 0}
        identity = api.upsert("chart", body, "slice_name", title)
        form["slice_id"] = identity
        context["form_data"] = form
        api.call("PUT", f"chart/{identity}", {"params": json.dumps(form), "query_context": json.dumps(context)})
        charts.append({"id": identity, "key": key, "title": title, "dataset": dataset, "context": context,
                       "width": width, "height": height, "full_source": full})

    add("observations", "Observations", "mart_hourly", "big_number_total", ["Observations"], width=3, height=18)
    add("candidates", "Candidate investigation hours", "mart_hourly_investigation", "big_number_total", ["Candidate hours"], width=3, height=18)
    add("incidents", "Candidate incidents", "mart_incidents", "big_number_total", ["Candidate incidents"], width=3, height=18)
    add("eligible", "Rule-eligible hours", "mart_hourly_investigation", "big_number_total", ["Eligible hours"], width=3, height=18)
    add("eligibility_percent", "Eligible observed hours (%)", "mart_hourly_investigation", "big_number_total", ["Eligibility (%)"], width=6, height=18, number_format=".2f", description="Eligible / all observed hours in the selected period; excluded hours are not no-breach results.")
    add("not_evaluated", "Not evaluated hours", "mart_hourly_investigation", "big_number_total", ["Not evaluated hours"], width=6, height=18)
    add("pressure", "Daily panel pressure (bar)", "mart_daily", "echarts_timeseries_line", ["Panel pressure (bar)"], description="Weighted by observations. Gaps mean unobserved periods; timestamps have no published timezone.")
    add("temperature", "Daily oil temperature (C)", "mart_daily", "echarts_timeseries_line", ["Oil temperature (C)"], description="Degrees Celsius; weighted by observation count.")
    add("states", "Operating-state observations", "analytics_operating_states", "echarts_timeseries_bar", ["State observations"], ["operating_state"], description="Current-based proxies, including possible startup transients; UCI supports typical states, not exact threshold validation. Counts are not time-in-state or downtime.", width=6, height=34)
    add("eligibility", "Rule evaluation coverage (hours)", "mart_hourly_investigation", "table", ["Observed hours"], groups=["evaluation_status"], width=6, height=34)
    add("exclusions", "Why hours were not evaluated (exclusive counts)", "mart_hourly_investigation", "table", ["Current samples only", "Baseline samples only", "Both sample requirements", "Missing rates"], groups=[], width=12, height=22, description="Mutually exclusive reasons sum to Not evaluated hours. Current-only and both must not be added again to marginal baseline counts.")
    add("baseline", "Hourly low-pressure share, historical baseline and rule (%)", "mart_hourly_investigation", "echarts_timeseries_line", ["Low pressure among loaded (%)", "Prior 7-day loaded share (%)", "Rule floor (%)", "2x prior baseline (%)"], grain="PT1H", width=12, height=48, description="Low pressure <7 bar among loaded observations >=6 A. Prior seven-day baseline excludes the current hour. Both thresholds and minimum counts (30 current, 300 prior) are required. No averaging of overlapping baselines.")
    add("incident_table", "Incident investigation queue (start-date filter)", "mart_incidents", "table", columns=["incident_id", "starts_at", "ends_at", "candidate_hours", "readings", "loaded_readings", "low_pressure_share", "peak_hour_share", "overlaps_reported_failure", "rule_version"], width=12, height=30, description="An empty table is valid. Candidate hour windows do not establish equipment downtime.")
    add("maintenance", "Maintenance-report context (full source)", "mart_report_review", "table", columns=ds["mart_report_review"]["columns"], full=True, width=12, height=34)
    add("quality", "Data quality and reconciliation (full source)", "analytics_data_quality", "table", columns=["raw_observations", "hourly_observations", "observed_hours", "observed_dates", "unobserved_hour_windows", "duplicate_timestamps", "missing_core_sensor_rows", "reconciliation_difference", "state_reconciliation_difference", "is_complete_source"], full=True, width=12, height=24)
    add("provenance", "Source period and pipeline provenance (full source)", "analytics_data_quality", "table", columns=["source_name", "first_observation", "last_observation", "pipeline_loaded_at", "source_sha256", "timestamp_context"], full=True, width=12, height=24)
    return charts


def layout(charts):
    pos = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": "AssetPulse Equipment Intelligence"}}}
    def markdown(key, text, height):
        row = "ROW-" + key
        identity = "MARKDOWN-" + key
        pos["GRID_ID"]["children"].append(row)
        pos[row] = {"type": "ROW", "id": row, "children": [identity], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        pos[identity] = {"type": "MARKDOWN", "id": identity, "children": [], "parents": ["ROOT_ID", "GRID_ID", row], "meta": {"code": text, "width": 12, "height": height}}
    markdown("context", "**Historical railway compressor telemetry · MetroPT-3 · 2020**  \nUse the time filter to explore recorded observations. Timestamps have no published timezone; trend gaps are unobserved periods. Counts describe observations and candidate windows, never confirmed failures or downtime. Zero candidates is a valid rule result.", 15)
    used, row = 12, None
    for chart in charts:
        if chart["key"] == "baseline":
            markdown("rule", "**pressure-v1, unchanged:** TP3 < 7 bar while current ≥ 6 A; hourly share ≥ 15% **and** ≥ 2× prior share. Evaluation requires ≥ 30 current and ≥ 300 prior loaded observations. **Not evaluated is not no breach.** Prior means [hour − 7 days, hour), excluding the current hour; a fully populated week is not required. Current is a proxy (typical loaded ≈ 7 A; startup ≈ 9 A), not a validated state label. Missing hours are not downtime.", 22)
            used = 12
        if chart["key"] == "maintenance":
            markdown("reports", "**Historical context and source quality**  \nThe sections below always show the full source and are excluded from the time filter. Four published maintenance intervals are context only; absence of a report does not establish healthy operation. Local TEST ONLY SMTP delivery is verified through Mailpit. Both alert schedules are disabled. External email and live equipment monitoring are not configured.", 15)
            used = 12
        if used + chart["width"] > 12:
            row = "ROW-" + chart["key"]
            pos["GRID_ID"]["children"].append(row)
            pos[row] = {"type": "ROW", "id": row, "children": [], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
            used = 0
        identity = "CHART-" + chart["key"]
        pos[row]["children"].append(identity)
        pos[identity] = {"type": "CHART", "id": identity, "children": [], "parents": ["ROOT_ID", "GRID_ID", row], "meta": {"chartId": chart["id"], "width": chart["width"], "height": chart["height"], "sliceName": chart["title"]}}
        used += chart["width"]
    return pos


def validate(api, conn, charts, ds, dashboard):
    results = []
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM analytics_data_quality")
        quality = dict(cursor.fetchone())
        assert quality["raw_observations"] == quality["hourly_observations"] == quality["state_observations"] == quality["original_rows"]
        assert quality["reconciliation_difference"] == quality["state_reconciliation_difference"] == 0
        cursor.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        assert not any(cursor.fetchone().values())
        cursor.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','v','m') AND (has_table_privilege(current_user,c.oid,'INSERT') OR has_table_privilege(current_user,c.oid,'UPDATE') OR has_table_privilege(current_user,c.oid,'DELETE') OR has_table_privilege(current_user,c.oid,'TRUNCATE'))")
        assert cursor.fetchall() == [], "Analytics role has write privileges"
        cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS can_create")
        assert not cursor.fetchone()["can_create"]
        cursor.execute("SHOW default_transaction_read_only")
        assert next(iter(cursor.fetchone().values())) == "on"
    for chart in charts:
        for period in (RANGE, "2020-04-01 : 2020-05-01", "2021-01-01 : 2021-01-02") if not chart["full_source"] else ("No filter",):
            context = copy.deepcopy(chart["context"])
            context["queries"][0]["time_range"] = period
            response = api.call("POST", "chart/data", context)
            query = response["result"][0]
            assert query.get("status") == "success", chart["title"]
            with conn.cursor() as cursor:
                cursor.execute(query["query"])
                records = cursor.fetchall()
                names = [c.name for c in cursor.description]
            returned_rows = query["data"]
            if context["queries"][0].get("post_processing") and records:
                # Resampling inserts only NULL points for absent time windows.
                stamps = {row[0].replace(tzinfo=dt.timezone.utc).timestamp() * 1000 for row in records}
                for row in returned_rows:
                    if row["__timestamp"] not in stamps:
                        assert all(v is None for k, v in row.items() if k != "__timestamp")
                returned_rows = [row for row in returned_rows if row["__timestamp"] in stamps]
                records = sorted(records, key=lambda row: row[0])
            assert len(records) == len(returned_rows), chart["title"]
            # Match all SQL scalar values, including time-series values, against API data.
            def norm(value):
                if isinstance(value, dt.datetime):
                    return value.replace(tzinfo=dt.timezone.utc).timestamp() * 1000
                if isinstance(value, dt.date):
                    return dt.datetime.combine(value, dt.time()).replace(tzinfo=dt.timezone.utc).timestamp() * 1000
                return value
            for row, returned in zip(records, returned_rows):
                for name, expected in zip(names, row):
                    actual = returned[name]
                    expected = norm(expected)
                    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and expected is not None:
                        assert math.isclose(float(expected), actual, rel_tol=1e-10, abs_tol=1e-8), (chart["key"], name)
                    else:
                        assert expected == actual, (chart["key"], name)
            results.append({"chart": chart["title"], "time_range": period, "rows": len(records), "null_gap_points": len(query["data"]) - len(records), "postgresql_values_match": True, "sql": query["query"]})
    # Saved dashboard and saved chart-data routes, not only construction payloads.
    assert api.client.get(f"/superset/dashboard/{SLUG}/").status_code == 200
    assert len(api.call("GET", f"dashboard/{dashboard}/charts")["result"]) == len(charts)
    return {"verified_at": dt.datetime.now(dt.timezone.utc).isoformat(), "dashboard_url": "http://localhost:8089/superset/dashboard/" + SLUG + "/",
            "read_only_privileges_verified": True, "quality": quality, "chart_checks": results,
            "datasets": {name: data["id"] for name, data in ds.items()}, "chart_count": len(charts),
            "dashboard_id": dashboard, "dashboard_html_http_status": 200,
            "browser_rendering": "See docs/SUPERSET.md for separate rendered verification."}


def export(api, dashboard, ds, credential):
    # Native export contains every chart and its dependent datasets. Export daily
    # and hourly explicitly as well, so all registered models are retained.
    exported = []
    for kind, identities in [("dashboard", [dashboard]), ("dataset", [d["id"] for d in ds.values()])]:
        response = api.client.get(f"/api/v1/{kind}/export/?q=" + json.dumps(identities))
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            for name in archive.namelist():
                parts = Path(name).parts[1:]
                if not parts or ".." in parts:
                    continue
                value = yaml.safe_load(archive.read(name))
                if parts[0] == "databases":
                    value["sqlalchemy_uri"] = "postgresql+psycopg2://assetpulse_analytics@db:5432/assetpulse"
                    for key in ("password", "encrypted_extra", "masked_encrypted_extra", "server_cert", "ssh_tunnel"):
                        value.pop(key, None)
                text = yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
                assert credential["password"] not in text
                target = OUT / "definitions" / Path(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
                exported.append(str(Path(*parts)))
    dump(OUT / "export_manifest.json", {"format": "Superset native YAML v1.0.0", "files": sorted(set(exported)), "credentials_removed": True, "restore": "Use scripts/setup_superset.py on the existing instance. Native import requires supplying analytics credentials privately."})


def main():
    payload = json.load(sys.stdin)
    credential, conn, weighted_checks = provision_database(payload)
    from superset.app import create_app
    from superset import security_manager
    app = create_app()
    with app.app_context():
        admin = security_manager.find_user(username="admin")
        assert admin and admin.is_active and any(role.name == "Admin" for role in admin.roles)
        api = API(app, admin)
        database = api.upsert("database", {"database_name": DATABASE,
            "sqlalchemy_uri": "postgresql+psycopg2://" + ROLE + ":" + credential["password"] + "@db:5432/assetpulse",
            "expose_in_sqllab": True, "allow_dml": False, "allow_ctas": False, "allow_cvas": False,
            "allow_run_async": False, "allow_file_upload": False}, "database_name", DATABASE)
        ds = datasets(api, database)
        dashboard = api.upsert("dashboard", {"dashboard_title": "AssetPulse Equipment Intelligence", "slug": SLUG, "published": True}, "slug", SLUG)
        charts = build_charts(api, ds, dashboard)
        metadata = {"refresh_frequency": 0, "timed_refresh_immune_slices": [], "color_scheme": "supersetColors",
                    "native_filter_configuration": [{"id": "NATIVE_FILTER-assetpulse-time", "name": "Recorded observation period", "filterType": "filter_time", "targets": [{}],
                    "defaultDataMask": {"extraFormData": {"time_range": RANGE}, "filterState": {"value": RANGE}},
                    "cascadeParentIds": [], "scope": {"rootPath": ["ROOT_ID"], "excluded": [c["id"] for c in charts if c["full_source"]]},
                    "controlValues": {}, "type": "NATIVE_FILTER", "description": "Historical 2020 source. Report and quality sections always use full-source context."}]}
        api.call("PUT", f"dashboard/{dashboard}", {"position_json": json.dumps(layout(charts)), "json_metadata": json.dumps(metadata), "published": True})
        evidence = validate(api, conn, charts, ds, dashboard)
        evidence["independent_raw_weighting_checks"] = weighted_checks
        from superset import db
        from superset.models.core import Log
        assert db.session.query(Log).filter(Log.json.contains(credential["password"])).count() == 0
        evidence["analytics_password_absent_from_superset_event_logs"] = True
        export(api, dashboard, ds, credential)
        dump(OUT / "verification.json", evidence)
        dump(OUT / "asset_ids.json", {"database_id": database, "dashboard_id": dashboard, "datasets": {k: v["id"] for k, v in ds.items()}, "charts": {c["key"]: c["id"] for c in charts}})
        print(json.dumps({"dashboard_url": evidence["dashboard_url"], "datasets": len(ds), "charts": len(charts), "query_checks": len(evidence["chart_checks"]), "read_only_verified": True}))
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not print exceptions from credential-bearing calls or stack locals.
        import traceback
        frames = traceback.extract_tb(error.__traceback__)
        print("Provisioning stopped:", type(error).__name__, "at worker line", frames[-1].lineno, file=sys.stderr)
        sys.exit(1)
