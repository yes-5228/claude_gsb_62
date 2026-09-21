"""监测数据录入 API."""
from flask import Blueprint, request

from ..domain.constants import DATA_SOURCE_LABELS, PERIOD_LABELS
from ..services import measurement_service, query_service, snapshot_service, station_service
from ..utils.csv_export import csv_stream_response
from ..utils.validation import Validator
from .helpers import json_payload, list_payload

bp = Blueprint("measurements", __name__)


@bp.get("/", strict_slashes=False)
def list_measurements():
    payload, _ = snapshot_service.paginate(request.args)
    return payload


@bp.get("/summary")
def measurement_summary():
    return query_service.summary(query_service.parse_filters(request.args))


@bp.post("/preview")
def preview():
    """干跑校验: 录入表单实时预览超标情况, 不写库."""
    data = json_payload()
    validator = Validator(data)
    period = validator.choice("period", "数据周期", choices=tuple(PERIOD_LABELS.keys()),
                              required=True, default="hourly")
    validator.raise_if_invalid()
    entries = list_payload("entries", data)
    return measurement_service.preview_entries(period or "hourly", entries)


@bp.post("/entries")
def create_entries():
    """一次录入某个监测点在同一时刻的一组因子数据."""
    data = json_payload()
    validator = Validator(data)
    station_id = validator.number("station_id", "监测点", required=True, minimum=1)
    measured_at = validator.datetime_field("measured_at", "监测时间", required=True)
    period = validator.choice("period", "数据周期", choices=tuple(PERIOD_LABELS.keys()),
                              required=True, default="hourly")
    data_source = validator.choice("data_source", "数据来源",
                                   choices=tuple(DATA_SOURCE_LABELS.keys()),
                                   required=False, default="manual")
    recorder = validator.text("recorder", "录入人", required=False, max_length=64)
    remark = validator.text("remark", "备注", required=False, max_length=500)
    overwrite = validator.boolean("overwrite", False)
    validator.raise_if_invalid("录入信息不合法")

    entries = list_payload("entries", data)
    return measurement_service.record_entries(
        station_id=int(station_id),
        measured_at=measured_at,
        period=period,
        entries=entries,
        data_source=data_source or "manual",
        recorder=recorder,
        remark=remark,
        overwrite=bool(overwrite),
    ), 201


@bp.get("/export")
def export_measurements():
    snapshot, _ = snapshot_service.resolve_for_export(request.args)
    columns = [
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
        ("备注", lambda row: row.get("remark") or ""),
    ]
    payloads = snapshot_service.iter_snapshot_payloads(snapshot)
    return csv_stream_response(payloads, columns, "monitoring_data", total=snapshot.total)


@bp.get("/<int:measurement_id>")
def get_measurement(measurement_id):
    return measurement_service.get_measurement(measurement_id).to_dict(include_station=True)


@bp.delete("/<int:measurement_id>")
def delete_measurement(measurement_id):
    measurement = measurement_service.get_measurement(measurement_id)
    payload = measurement_service.delete_measurement(measurement)
    return {"id": payload["id"], "deleted": True}


@bp.get("/entry-context")
def entry_context():
    """Options needed by the entry form in a single round trip."""
    return {
        "stations": station_service.option_list(),
        "periods": [{"value": key, "label": label} for key, label in PERIOD_LABELS.items()],
        "data_sources": [
            {"value": key, "label": label} for key, label in DATA_SOURCE_LABELS.items()
        ],
    }
