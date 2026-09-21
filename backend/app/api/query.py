"""数据查询 API: 条件检索 / 聚合统计 / 导出.

列表与导出均基于查询快照 (见 services/snapshot_service.py): 翻页过程中他人
继续录入或删除记录时, 已看过的页不位移, 页头汇总与最终导出条数保持一致。
"""
from flask import Blueprint, request

from ..domain.constants import DATA_SOURCE_LABELS, PERIOD_LABELS, STATION_TYPE_LABELS
from ..domain.standards import POLLUTANTS
from ..services import query_service, snapshot_service
from ..utils.csv_export import csv_stream_response

bp = Blueprint("query", __name__)


def _export_columns():
    return [
        ("站点编码", lambda row: (row.get("station") or {}).get("code", "")),
        ("站点名称", lambda row: (row.get("station") or {}).get("name", "")),
        ("所属区域", lambda row: (row.get("station") or {}).get("area", "")),
        ("监测因子", "pollutant_label"),
        ("数据周期", lambda row: PERIOD_LABELS.get(row.get("period"), row.get("period") or "")),
        ("监测值", lambda row: row.get("value") if row.get("value") is not None else ""),
        ("单位", "unit"),
        ("限值", lambda row: row.get("limit_value") if row.get("limit_value") is not None else ""),
        ("是否超标", lambda row: "是" if row.get("is_exceeded") else "否"),
        ("超标倍数", lambda row: row.get("exceed_ratio") if row.get("exceed_ratio") is not None else ""),
        ("监测时间", lambda row: row.get("measured_at", "").replace("T", " ")[:16] if row.get("measured_at") else ""),
        ("数据来源", lambda row: DATA_SOURCE_LABELS.get(row.get("data_source"), row.get("data_source") or "")),
        ("录入人", lambda row: row.get("recorder") or ""),
    ]


@bp.get("/measurements")
def query_measurements():
    payload, _ = snapshot_service.paginate(request.args)
    return payload


@bp.get("/statistics")
def query_statistics():
    return query_service.statistics(request.args)


@bp.get("/export")
def query_export():
    snapshot, _ = snapshot_service.resolve_for_export(request.args)
    payloads = snapshot_service.iter_snapshot_payloads(snapshot)
    return csv_stream_response(payloads, _export_columns(), "monitoring_query", total=snapshot.total)


@bp.get("/options")
def query_options():
    payload = query_service.option_payload()
    payload["pollutants"] = [
        {"value": item["code"], "label": item["label"], "unit": item["unit"],
         "limits": item["limits"]}
        for item in POLLUTANTS.values()
    ]
    payload["periods"] = [{"value": key, "label": label} for key, label in PERIOD_LABELS.items()]
    payload["station_types"] = [
        {"value": key, "label": label} for key, label in STATION_TYPE_LABELS.items()
    ]
    payload["data_sources"] = [
        {"value": key, "label": label} for key, label in DATA_SOURCE_LABELS.items()
    ]
    return payload
