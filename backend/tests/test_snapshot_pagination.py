"""结果集快照: 并发增删下的翻页稳定性与导出一致性测试."""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import Measurement, QuerySnapshot
from app.services import snapshot_service


BASE_DAY = date(2026, 9, 1)


def _seed(client, station, n, start_index=0):
    for i in range(n):
        day = BASE_DAY + timedelta(days=start_index + i)
        client.post(
            "/api/measurements/entries",
            json={
                "station_id": station.id,
                "measured_at": "%s 10:00" % day.isoformat(),
                "period": "hourly",
                "entries": [{"pollutant": "PM25", "value": 20.0}],
            },
        )


def test_first_page_returns_snapshot_token_and_fixed_summary(client, station):
    _seed(client, station, 25)
    body = client.get("/api/query/measurements?page_size=20").get_json()
    assert body["total"] == 25
    assert body["pages"] == 2
    assert len(body["items"]) == 20
    token = body["snapshot_token"]
    assert token
    assert body["summary"]["total"] == 25
    assert body["sort"] == "measured_at"
    assert body["order"] == "desc"

    second = client.get(
        "/api/query/measurements?page=2&page_size=20&snapshot_token=%s" % token
    ).get_json()
    assert len(second["items"]) == 5
    # 第二页与第一页没有重复 ID
    first_ids = {item["id"] for item in body["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids & second_ids == set()
    assert second["snapshot_token"] == token
    assert second["summary"]["total"] == 25


def test_inserts_during_paging_do_not_shift_seen_pages(client, station):
    """翻到第二页前他人大量新增: 快照内第一页内容与总数保持不变。"""
    _seed(client, station, 25)
    first = client.get("/api/query/measurements?page_size=20").get_json()
    token = first["snapshot_token"]
    first_ids = [item["id"] for item in first["items"]]

    # 他人新录入 25 条更新的监测时间数据, 在普通 OFFSET 分页下会把第一页整体顶走
    _seed(client, station, 25, start_index=60)

    first_repeated = client.get(
        "/api/query/measurements?page=1&page_size=20&snapshot_token=%s" % token
    ).get_json()
    assert [item["id"] for item in first_repeated["items"]] == first_ids
    assert first_repeated["total"] == 25
    assert first_repeated["summary"]["total"] == 25

    second = client.get(
        "/api/query/measurements?page=2&page_size=20&snapshot_token=%s" % token
    ).get_json()
    assert len(second["items"]) == 5
    seen = first_ids + [item["id"] for item in second["items"]]
    assert len(seen) == len(set(seen)) == 25  # 无重复、无遗漏


def test_deletes_during_paging_keep_positions_with_placeholder(client, station):
    _seed(client, station, 25)
    first = client.get("/api/query/measurements?page_size=20").get_json()
    token = first["snapshot_token"]

    # 他人删除第一页的 3 条
    for item in first["items"][:3]:
        client.delete("/api/measurements/%s" % item["id"])

    first_again = client.get(
        "/api/query/measurements?page=1&page_size=20&snapshot_token=%s" % token
    ).get_json()
    assert len(first_again["items"]) == 20  # 页数与每页条数不变
    deleted_rows = [row for row in first_again["items"] if row["snapshot_deleted"]]
    assert len(deleted_rows) == 3
    assert all(row["id"] is None for row in deleted_rows)
    assert first_again["total"] == 25  # 快照总数不缩水

    second = client.get(
        "/api/query/measurements?page=2&page_size=20&snapshot_token=%s" % token
    ).get_json()
    assert len(second["items"]) == 5


def test_export_uses_snapshot_and_matches_summary_count(client, station):
    _seed(client, station, 25)
    first = client.get("/api/query/measurements?page_size=20").get_json()
    token = first["snapshot_token"]

    # 翻页期间新增数据, 导出仍只含快照内的 25 条
    _seed(client, station, 10, start_index=90)

    response = client.get("/api/query/export?snapshot_token=%s" % token)
    assert response.status_code == 200
    assert response.headers["X-Export-Total"] == "25"
    lines = response.get_data(as_text=True).strip().splitlines()
    assert len(lines) == 1 + 25  # 表头 + 25 行, 与页头 total 一致


def test_export_without_token_builds_snapshot_and_is_consistent(client, station):
    _seed(client, station, 3)
    response = client.get("/api/query/export")
    lines = response.get_data(as_text=True).strip().splitlines()
    assert len(lines) == 4
    # 导出后快照库应留有 1 份快照
    with client.application.app_context():
        assert db.session.query(QuerySnapshot).count() == 1


def test_changed_filters_ignores_stale_token(client, station, second_station):
    _seed(client, station, 10)
    client.post(
        "/api/measurements/entries",
        json={
            "station_id": second_station.id,
            "measured_at": "2026-09-15 10:00",
            "period": "hourly",
            "entries": [{"pollutant": "PM25", "value": 20.0}],
        },
    )
    first = client.get("/api/query/measurements").get_json()
    token = first["snapshot_token"]
    assert first["total"] == 11

    # 携带旧 token 但切换了筛选条件: 必须按新条件重建快照
    switched = client.get(
        "/api/query/measurements?station_id=%s&snapshot_token=%s"
        % (second_station.id, token)
    ).get_json()
    assert switched["total"] == 1
    assert switched["snapshot_token"] != token
    assert switched["items"][0]["station_id"] == second_station.id


def test_changing_sort_resets_and_rebuilds(client, station):
    _seed(client, station, 5)
    by_time = client.get(
        "/api/query/measurements?sort=measured_at&order=desc"
    ).get_json()
    times = [item["measured_at"] for item in by_time["items"]]
    assert times == sorted(times, reverse=True)

    by_value = client.get("/api/query/measurements?sort=value&order=asc")
    assert by_value.status_code == 200


def test_snapshot_token_reuse_requires_matching_sort(client, station):
    _seed(client, station, 5)
    desc = client.get("/api/query/measurements?sort=measured_at&order=desc").get_json()
    token = desc["snapshot_token"]
    # token 属于 desc 快照, 却带着 asc 请求: 必须重建, 不能返回旧顺序
    asc = client.get(
        "/api/query/measurements?sort=measured_at&order=asc&snapshot_token=%s" % token
    ).get_json()
    assert asc["snapshot_token"] != token
    desc_times = [item["measured_at"] for item in desc["items"]]
    asc_times = [item["measured_at"] for item in asc["items"]]
    assert asc_times == list(reversed(desc_times))


def test_expired_snapshot_returns_410(client, station):
    _seed(client, station, 3)
    first = client.get("/api/query/measurements").get_json()
    token = first["snapshot_token"]

    with client.application.app_context():
        snapshot = QuerySnapshot.query.filter_by(token=token).first()
        snapshot.expires_at = datetime.now() - timedelta(seconds=1)
        db.session.commit()

    response = client.get(
        "/api/query/measurements?snapshot_token=%s" % token
    )
    assert response.status_code == 410
    assert response.get_json()["error"]["code"] == "SNAPSHOT_EXPIRED"


def test_tie_breaker_makes_ordering_stable_when_sort_values_equal(client, station):
    """排序值相同时以 id 兜底, 同一快照反复取页顺序完全一致。"""
    _seed(client, station, 25)
    first = client.get("/api/query/measurements?sort=value&page_size=20").get_json()
    token = first["snapshot_token"]
    again = client.get(
        "/api/query/measurements?sort=value&page=1&page_size=20&snapshot_token=%s" % token
    ).get_json()
    assert [item["id"] for item in again["items"]] == [item["id"] for item in first["items"]]


def test_paging_forward_and_back_never_duplicates(client, station):
    _seed(client, station, 45)
    page1 = client.get("/api/query/measurements?page_size=20").get_json()
    token = page1["snapshot_token"]

    def page(n):
        return client.get(
            "/api/query/measurements?page=%s&page_size=20&snapshot_token=%s" % (n, token)
        ).get_json()

    p1, p2, p3 = page(1), page(2), page(3)
    p1b, p2b = page(1), page(2)  # 来回翻页
    collected = [item["id"] for item in p1["items"] + p2["items"] + p3["items"]]
    assert len(collected) == len(set(collected)) == 45
    assert [i["id"] for i in p1b["items"]] == [i["id"] for i in p1["items"]]
    assert [i["id"] for i in p2b["items"]] == [i["id"] for i in p2["items"]]


def test_snapshot_creation_prunes_expired_rows(client, station):
    _seed(client, station, 3)
    client.get("/api/query/measurements")
    with client.application.app_context():
        assert QuerySnapshot.query.count() == 1
        old = QuerySnapshot.query.first()
        old.expires_at = datetime.now() - timedelta(hours=1)
        db.session.commit()

    client.get("/api/query/measurements")  # 新建时顺手清理过期快照
    with client.application.app_context():
        assert QuerySnapshot.query.count() == 1
