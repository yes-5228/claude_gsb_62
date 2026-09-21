"""列表结果集快照服务.

同一筛选+排序条件下反复翻页时, 后端始终从同一份快照里按固定位置取数:

- 快照建立后他人新增的记录不会插入到已看过的页之间 (无重复、无遗漏、不位移);
- 他人删除的记录在快照中保留位置并以「记录已删除」占位, 总条数与页数不变;
- 汇总数字在建立快照时一次算好并固化;
- 导出遍历同一份快照, 因此导出行数恒等于页头总条数。
"""
import hashlib
import json
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy.orm import joinedload

from ..errors import ApiError, ValidationError
from ..extensions import db
from ..models import (
    Measurement,
    QuerySnapshot,
    QuerySnapshotItem,
    new_snapshot_token,
)
from ..models.base import iso
from ..utils.pagination import page_params
from . import query_service

INSERT_BATCH = 2000
EXPORT_BATCH = 500


class SnapshotExpiredError(ApiError):
    def __init__(self):
        super().__init__(
            "查询结果已过期, 正在按最新数据重新查询",
            status_code=410,
            code="SNAPSHOT_EXPIRED",
        )


def normalize_sort(sort, order):
    sort = sort if sort in query_service.SORT_CHOICES else "measured_at"
    order = "asc" if (order or "desc").lower() == "asc" else "desc"
    return sort, order


def filters_signature(filters):
    """归一化筛选条件的稳定签名, 区分不同查询。"""
    payload = {key: filters[key] for key in sorted(filters)}
    canonical = json.dumps(payload, default=iso, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_snapshot(args):
    """返回与请求匹配的快照。

    - 携带 token 且快照已过期: 抛 410, 由调用方/前端重建;
    - token 不存在 (旧库已清理) 或筛选/排序不一致: 返回 None 静默重建;
    - 其余情况返回匹配的快照。
    """
    token = (args.get("snapshot_token") or "").strip()
    sort, order = normalize_sort(args.get("sort"), args.get("order"))
    signature = filters_signature(query_service.parse_filters(args))
    if token:
        snapshot = QuerySnapshot.query.filter_by(token=token).first()
        if snapshot is not None and snapshot.is_expired():
            raise SnapshotExpiredError()
        if (
            snapshot is not None
            and snapshot.signature == signature
            and snapshot.sort == sort
            and snapshot.order == order
        ):
            return snapshot
    return None


def prune_expired(now=None):
    """删除已过期快照 (级联清理明细), 每次新建快照时顺手执行一次。"""
    QuerySnapshot.query.filter(QuerySnapshot.expires_at < (now or datetime.now())).delete(
        synchronize_session=False
    )


def _summary_from_rows(rows):
    """与 query_service.summary 同构, 但直接对快照行求聚合, 保证与快照同源。"""
    total = len(rows)
    exceeded = sum(1 for row in rows if row.is_exceeded)
    station_ids = {row.station_id for row in rows}
    values = [row.value for row in rows if row.value is not None]
    measured_times = [row.measured_at for row in rows if row.measured_at is not None]
    return {
        "total": total,
        "exceeded_count": exceeded,
        "exceed_rate": round(exceeded / total, 4) if total else 0.0,
        "station_count": len(station_ids),
        "first_measured_at": iso(min(measured_times)) if measured_times else None,
        "last_measured_at": iso(max(measured_times)) if measured_times else None,
        "avg_value": round(sum(values) / len(values), 2) if values else None,
    }


def create_snapshot(args):
    """按当前筛选+排序物化结果集, 返回新建的快照。"""
    filters = query_service.parse_filters(args)
    sort, order = normalize_sort(args.get("sort"), args.get("order"))
    max_rows = current_app.config["QUERY_SNAPSHOT_MAX_ROWS"]
    ttl = current_app.config["QUERY_SNAPSHOT_TTL"]

    prune_expired()

    query = query_service.apply_filters(db.session.query(Measurement), filters)
    query = query_service.apply_sort(query, sort, order)

    # 只取计算汇总所需的轻量列; 多取一条用于判断是否超过快照上限
    probe = (
        query.with_entities(
            Measurement.id,
            Measurement.value,
            Measurement.is_exceeded,
            Measurement.station_id,
            Measurement.measured_at,
        )
        .limit(max_rows + 1)
        .all()
    )
    if len(probe) > max_rows:
        raise ValidationError(
            "符合条件的记录超过 %s 条, 结果集过大无法稳定翻页, 请收紧筛选条件或缩小时间范围"
            % max_rows,
            fields={"result_set": "too_large"},
        )

    now = datetime.now()
    snapshot = QuerySnapshot(
        token=new_snapshot_token(),
        signature=filters_signature(filters),
        sort=sort,
        order=order,
        total=len(probe),
        filters_json=json.dumps(filters, default=iso, ensure_ascii=False),
        summary_json=json.dumps(_summary_from_rows(probe), ensure_ascii=False),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    db.session.add(snapshot)
    db.session.flush()

    pending = []
    for position, row in enumerate(probe):
        pending.append(
            QuerySnapshotItem(
                snapshot_id=snapshot.id, measurement_id=row.id, position=position
            )
        )
        if len(pending) >= INSERT_BATCH:
            db.session.bulk_save_objects(pending)
            pending.clear()
    if pending:
        db.session.bulk_save_objects(pending)
    db.session.commit()
    return snapshot


def deleted_placeholder():
    """源记录已被他人删除时的占位行, 保留其在快照中的位置。"""
    return {
        "id": None,
        "station_id": None,
        "pollutant": None,
        "pollutant_label": "记录已删除",
        "period": None,
        "period_label": "-",
        "value": None,
        "unit": "",
        "limit_value": None,
        "exceed_ratio": None,
        "is_exceeded": False,
        "measured_at": None,
        "data_source": None,
        "data_source_label": "已删除",
        "recorder": None,
        "remark": None,
        "created_at": None,
        "updated_at": None,
        "exceedance_id": None,
        "exceedance_status": None,
        "station": None,
        "snapshot_deleted": True,
    }


def _load_measurements(ids):
    if not ids:
        return {}
    rows = (
        db.session.query(Measurement)
        .options(joinedload(Measurement.station))
        .filter(Measurement.id.in_(ids))
        .all()
    )
    return {row.id: row for row in rows}


def _payloads_in_order(ids, rows_by_id):
    payloads = []
    for measurement_id in ids:
        row = rows_by_id.get(measurement_id)
        if row is None:
            payloads.append(deleted_placeholder())
        else:
            payload = row.to_dict(include_station=True)
            payload["snapshot_deleted"] = False
            payloads.append(payload)
    return payloads


def _load_page_items(snapshot, page, page_size):
    offset = (page - 1) * page_size
    ids = [
        item.measurement_id
        for item in QuerySnapshotItem.query.filter_by(snapshot_id=snapshot.id)
        .order_by(QuerySnapshotItem.position)
        .limit(page_size)
        .offset(offset)
        .all()
    ]
    return _payloads_in_order(ids, _load_measurements(ids))


def snapshot_page(snapshot, page, page_size):
    """从快照固定位置取一页数据, 与线上表的并发写入互不影响。"""
    items = _load_page_items(snapshot, page, page_size)
    return {
        "items": items,
        "total": snapshot.total,
        "page": page,
        "page_size": page_size,
        "pages": (snapshot.total + page_size - 1) // page_size if page_size else 0,
        "summary": json.loads(snapshot.summary_json),
        "applied_filters": json.loads(snapshot.filters_json),
        **snapshot.to_meta(),
    }


def iter_snapshot_payloads(snapshot, batch_size=EXPORT_BATCH):
    """按快照顺序遍历全部记录供导出, 行数恒等于 snapshot.total。

    每批独立查询 (而非流式游标), 避免同一连接上嵌套执行查询在不同
    数据库驱动下的兼容性问题。
    """
    position = 0
    item_query = (
        QuerySnapshotItem.query.filter_by(snapshot_id=snapshot.id)
        .order_by(QuerySnapshotItem.position)
    )
    while True:
        items = item_query.limit(batch_size).offset(position).all()
        if not items:
            break
        ids = [item.measurement_id for item in items]
        yield from _payloads_in_order(ids, _load_measurements(ids))
        position += len(items)


def paginate(args):
    """列表端点统一入口: 第一页建快照, 后续页从快照固定位置取数。

    返回 (payload, snapshot)。翻页期间他人增删记录不影响已看过的页。
    任何触发新建快照的请求 (新筛选 / 改排序 / 无令牌) 一律回到第一页。
    """
    page, page_size = page_params()
    snapshot = resolve_snapshot(args)
    if snapshot is None:
        snapshot = create_snapshot(args)
        page = 1  # 任何新建快照的请求一律从第一页开始
    return snapshot_page(snapshot, page, page_size), snapshot


def resolve_for_export(args):
    """导出端点入口: 复用列表快照, 保证导出行数 = 页头总条数。

    返回 (snapshot, created_now): 没有可复用快照时按当前条件新建一份。
    """
    snapshot = resolve_snapshot(args)
    created_now = False
    if snapshot is None:
        snapshot = create_snapshot(args)
        created_now = True
    return snapshot, created_now
