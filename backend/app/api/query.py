"""数据查询 API: 条件检索 / 聚合统计 / 导出."""
from flask import Blueprint, current_app, request

from ..domain.constants import DATA_SOURCE_LABELS, PERIOD_LABELS, STATION_TYPE_LABELS
from ..domain.standards import POLLUTANTS
from ..services import query_service
from ..utils.pagination import keyset_params

bp = Blueprint("query", __name__)


@bp.get("/measurements")
def query_measurements():
    cursor, direction, page_size = keyset_params()
    page = query_service.measurement_page(
        request.args, cursor=cursor, direction=direction, page_size=page_size
    )
    items = [row.to_dict(include_station=True) for row in page["rows"]]
    return {
        "items": items,
        "total": page["total"],
        "page_size": page_size,
        "sort": page["sort"],
        "order": page["order"],
        "cursor_pagination": True,
        "next_cursor": page["next_cursor"],
        "prev_cursor": page["prev_cursor"],
        "has_next": page["has_next"],
        "has_prev": page["has_prev"],
        "summary": query_service.summary(page["filters"], total=page["total"]),
        "applied_filters": page["filters"],
    }


@bp.get("/statistics")
def query_statistics():
    return query_service.statistics(request.args)


@bp.get("/export")
def query_export():
    from ..utils.csv_export import csv_response

    query, _filters, sort, descending = query_service.measurement_query(
        request.args, sorted_query=True, with_station=True
    )
    total = query.order_by(None).count()
    # Full export: no row cap, streamed in the same order as the list.
    rows = query.yield_per(current_app.config["EXPORT_BATCH_SIZE"])
    columns = [
        ("站点编码", lambda row: row.station.code if row.station else ""),
        ("站点名称", lambda row: row.station.name if row.station else ""),
        ("所属区域", lambda row: row.station.area if row.station else ""),
        ("监测因子", lambda row: row.pollutant_label()),
        ("数据周期", lambda row: PERIOD_LABELS.get(row.period, row.period)),
        ("监测值", "value"),
        ("单位", "unit"),
        ("限值", "limit_value"),
        ("是否超标", lambda row: "是" if row.is_exceeded else "否"),
        ("超标倍数", "exceed_ratio"),
        ("监测时间", lambda row: row.measured_at.strftime("%Y-%m-%d %H:%M")),
        ("数据来源", lambda row: DATA_SOURCE_LABELS.get(row.data_source, row.data_source)),
        ("录入人", "recorder"),
    ]
    return csv_response(rows, columns, "monitoring_query", count=total)


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
