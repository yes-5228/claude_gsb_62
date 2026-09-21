"""稳定翻页 (键集游标) 测试.

覆盖需求: 同一排序反复前后翻页不重不漏; 翻页期间并发新增/删除,
已看过的页不发生整页位移; 切换排序回到第一页并给出新总数;
汇总总数与导出条数一致。
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Measurement


def _bulk_rows(station, amount, start=None, value_step=1, pollutant="PM25", period="hourly"):
    """直接写入若干 measured_at 唯一的监测数据, 返回按 id 排序的记录."""
    start = start or datetime(2026, 9, 1, 0, 0)
    for index in range(amount):
        db.session.add(
            Measurement(
                station_id=station.id,
                pollutant=pollutant,
                period=period,
                value=float(index * value_step),
                unit="x",
                is_exceeded=False,
                measured_at=start + timedelta(hours=index),
            )
        )
    db.session.commit()
    return Measurement.query.order_by(Measurement.id.asc()).all()


def _get(client, **params):
    from urllib.parse import urlencode

    return client.get("/api/query/measurements?" + urlencode(params))


def _walk_forward(client, size, **extra):
    """顺着 next_cursor 走完整个结果集, 返回 (全部 id, 每页快照)."""
    pages, seen = [], []
    response = _get(client, page_size=size, **extra).get_json()
    pages.append(response)
    seen.extend(item["id"] for item in response["items"])
    while response["next_cursor"]:
        response = _get(
            client, page_size=size, cursor=response["next_cursor"], dir="next", **extra
        ).get_json()
        pages.append(response)
        seen.extend(item["id"] for item in response["items"])
    return seen, pages


def test_cursor_walk_is_gap_and_duplicate_free(client, station):
    rows = _bulk_rows(station, 45)
    seen, pages = _walk_forward(client, 10)

    assert seen == [row.id for row in reversed(rows)]  # 默认 measured_at 倒序
    assert len(seen) == len(set(seen)) == 45
    assert pages[0]["total"] == 45
    assert pages[0]["has_prev"] is False and pages[0]["has_next"] is True
    assert pages[-1]["has_next"] is False
    assert all(page["cursor_pagination"] for page in pages)


def test_concurrent_newest_insert_does_not_shift_visited_pages(client, station):
    rows = _bulk_rows(station, 25)
    first = _get(client, page_size=10).get_json()
    second = _get(client, page_size=10, cursor=first["next_cursor"], dir="next").get_json()

    # 别人在翻页间隙录入了一条“最新”数据
    db.session.add(
        Measurement(
            station_id=station.id, pollutant="PM25", period="hourly", value=999, unit="x",
            is_exceeded=False, measured_at=datetime(2026, 12, 1, 0, 0),
        )
    )
    db.session.commit()

    # 用前进时拿到的游标继续/回退: 已看过的两页内容完全不变
    second_again = _get(
        client, page_size=10, cursor=first["next_cursor"], dir="next"
    ).get_json()
    assert [item["id"] for item in second_again["items"]] == [
        item["id"] for item in second["items"]
    ]
    third = _get(client, page_size=10, cursor=second["next_cursor"], dir="next").get_json()
    seen = [item["id"] for item in first["items"] + second["items"] + third["items"]]
    assert len(seen) == len(set(seen)) == 25
    assert set(seen) == {row.id for row in rows}

    # 显式回到第一页才看到新记录与新总数
    refreshed = _get(client, page_size=10).get_json()
    assert refreshed["total"] == 26
    assert refreshed["items"][0]["value"] == 999


def test_concurrent_delete_ahead_is_skipped_without_duplicates(client, station):
    _bulk_rows(station, 35)
    first = _get(client, page_size=10).get_json()
    second = _get(client, page_size=10, cursor=first["next_cursor"], dir="next").get_json()

    # 删除“还没翻到”的一行
    victim_id = second["items"][-1]["id"] - 1
    victim = db.session.get(Measurement, victim_id)
    assert victim is not None
    db.session.delete(victim)
    db.session.commit()

    seen = [item["id"] for item in first["items"] + second["items"]]
    cursor = second["next_cursor"]
    while cursor:
        response = _get(client, page_size=10, cursor=cursor, dir="next").get_json()
        seen.extend(item["id"] for item in response["items"])
        cursor = response["next_cursor"]

    live_ids = {row.id for row in Measurement.query.all()}
    assert len(seen) == len(set(seen))
    assert set(seen) == live_ids  # 每个存活行恰好出现一次, 被删行消失


def test_prev_walk_from_last_page_covers_every_row_once(client, station):
    _bulk_rows(station, 26)
    last = _get(client, page_size=10, dir="last").get_json()
    assert len(last["items"]) == 6
    assert last["has_prev"] is True and last["has_next"] is False

    gathered = [item["id"] for item in last["items"]]
    cursor = last["prev_cursor"]
    while cursor:
        response = _get(client, page_size=10, cursor=cursor, dir="prev").get_json()
        gathered.extend(item["id"] for item in response["items"])
        cursor = response["prev_cursor"]
    assert len(gathered) == len(set(gathered)) == 26


def test_changing_sort_resets_order_and_reports_total(client, station):
    _bulk_rows(station, 20)
    desc = _get(client, page_size=10, sort="value", order="desc").get_json()
    assert desc["sort"] == "value" and desc["order"] == "desc"
    assert desc["total"] == 20
    values = [item["value"] for item in desc["items"]]
    assert values == sorted(values, reverse=True)

    asc = _get(client, page_size=10, sort="value", order="asc").get_json()
    assert asc["order"] == "asc"
    assert [item["value"] for item in asc["items"]] == sorted(
        item["value"] for item in asc["items"]
    )

    # 非法排序维度回退默认值, 不报错
    fallback = _get(client, page_size=10, sort="nope").get_json()
    assert fallback["sort"] == "measured_at"


def test_value_ties_break_deterministically_on_id(client, station):
    _bulk_rows(station, 12, value_step=0)  # 所有 value 相同
    seen, _ = _walk_forward(client, 5, sort="value", order="asc")
    expected = [
        row.id
        for row in Measurement.query.order_by(
            Measurement.value.asc(), Measurement.id.asc()
        ).all()
    ]
    assert seen == expected


def test_invalid_cursor_rejected(client, station):
    _bulk_rows(station, 5)
    response = client.get("/api/query/measurements?cursor=garbage")
    assert response.status_code == 422
    assert response.get_json()["error"]["fields"] == {"cursor": "invalid"}


def test_summary_total_matches_page_total(client, station):
    _bulk_rows(station, 12)
    page = _get(client, page_size=5).get_json()
    assert page["summary"]["total"] == page["total"] == 12


def test_export_row_count_header_matches_total(client, station):
    _bulk_rows(station, 12)
    response = client.get("/api/query/export")
    assert response.status_code == 200
    assert response.headers["X-Result-Count"] == "12"
    # BOM + 表头一行 + 12 条数据
    assert len(response.get_data(as_text=True).strip().splitlines()) == 13


def test_measurements_endpoint_uses_cursor_pagination(client, station):
    _bulk_rows(station, 23)
    first = client.get("/api/measurements?page_size=10").get_json()
    assert first["cursor_pagination"] is True
    assert first["total"] == 23 and first["summary"]["total"] == 23
    second = client.get(
        "/api/measurements?page_size=10&cursor=%s&dir=next" % first["next_cursor"]
    ).get_json()
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(ids) == len(set(ids))


def test_measurements_export_count_header(client, station):
    _bulk_rows(station, 7)
    response = client.get("/api/measurements/export")
    assert response.headers["X-Result-Count"] == "7"
