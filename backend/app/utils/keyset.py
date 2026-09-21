"""Keyset (cursor) pagination.

OFFSET/LIMIT pagination shifts the whole result set whenever a row is
inserted or deleted between two page requests: rows already seen can be
skipped twice or surface again on the next page. Keyset pagination anchors
each page to the sort value of the last row the client has seen, so pages
are stable under concurrent writes as long as the sort order is
deterministic. Every order here ends on the unique primary key, which
guarantees a total order with no ties.

A cursor is an opaque, base64-encoded JSON payload describing one
boundary row, e.g. ``{"v": 60.0, "k": "n", "id": 12}``.
"""
import base64
import json
from datetime import datetime

from sqlalchemy import and_, or_

# Sentinels used to normalise NULL sort values so that NULLs occupy one
# fixed spot regardless of sort direction (treated as "smallest").
NEG_INF_FLOAT = -1e300
NEG_INF_STR = "\x00"

KIND_DATETIME = "dt"
KIND_TEXT = "s"
KIND_NUMBER = "n"
KIND_ID = "id"


class SortSpec:
    """One sortable dimension.

    ``expr`` is a SQLAlchemy expression (already COALESCEd when nullable),
    ``attr`` reads the raw value back from an ORM row, ``kind`` tells the
    cursor codec how to serialise the value and ``null_value`` replaces
    NULL both in SQL and when reading a row.
    """

    def __init__(self, expr, attr, kind=KIND_NUMBER, null_value=None):
        self.expr = expr
        self.attr = attr
        self.kind = kind
        self.null_value = null_value

    def row_value(self, row):
        value = self.attr(row)
        return self.null_value if value is None else value


def encode_cursor(payload):
    raw = json.dumps(payload, separators=(",", ":"), default=_json_default).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token):
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or "id" not in payload or "v" not in payload:
        return None
    return payload


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    raise TypeError("无法序列化游标值: %r" % type(value))


def _bound_value(cursor, spec):
    """Convert the decoded JSON value into a bound literal for the SQLAlchemy expression."""
    value = cursor["v"]
    if value is None:
        return spec.null_value
    if spec.kind == KIND_DATETIME and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def order_columns(dim_spec, id_column, descending, reverse=False):
    """Deterministic ORDER BY: the chosen dimension then the unique id.

    ``reverse`` scans backwards (used to fetch a previous page); the
    caller reverses the rows back to canonical order afterwards.
    """
    first_descending = (not descending) if reverse else descending
    return [
        dim_spec.expr.desc() if first_descending else dim_spec.expr.asc(),
        id_column.desc() if first_descending else id_column.asc(),
    ]


def seek_filter(dim_spec, id_column, cursor, descending, forward):
    """Tuple comparison ``(value, id) <op> (:v, :id)`` for one boundary.

    Expanded into an OR of prefix-equality clauses so it works on SQLite
    and PostgreSQL alike. ``forward`` strictly continues along the
    canonical order; ``backward`` scans in reverse.
    """
    value = _bound_value(cursor, dim_spec)
    row_id = cursor["id"]
    # Canonical desc + forward -> strictly smaller; asc + forward -> larger.
    # Backward (prev) inverts whichever direction is canonical.
    moving_to_smaller = descending == forward
    compare = dim_spec.expr.__lt__ if moving_to_smaller else dim_spec.expr.__gt__
    id_compare = id_column.__lt__ if moving_to_smaller else id_column.__gt__
    return or_(
        compare(value),
        and_(dim_spec.expr == value, id_compare(row_id)),
    )


def boundary_cursor(row, dim_spec):
    """Opaque cursor describing ``row`` (anchor for a sibling page)."""
    return encode_cursor({"v": dim_spec.row_value(row), "k": dim_spec.kind, "id": row.id})


def keyset_page(query, dim_spec, id_column, page_size, cursor=None,
                direction="first", descending=True, total=None):
    """Return one stable page plus cursors for sibling pages.

    ``direction`` is ``first`` / ``next`` / ``prev`` / ``last``. One row
    is over-fetched to detect whether another page exists in the scan
    direction, avoiding an extra COUNT-style query.

    Only the explicit "last page" jump uses an OFFSET computed from the
    current ``total``; all in-session paging (next/prev) is anchored and
    therefore immune to rows being inserted or deleted concurrently.
    """
    forward = direction in ("first", "next")
    is_last = direction == "last"

    if cursor and direction in ("next", "prev"):
        query = query.filter(seek_filter(dim_spec, id_column, cursor, descending, forward))

    # "last" is positioned by a total-based OFFSET in canonical order;
    # "prev" scans backwards from the anchor and is flipped afterwards.
    reverse_scan = direction == "prev"
    query = query.order_by(None).order_by(
        *order_columns(dim_spec, id_column, descending, reverse=reverse_scan)
    )

    last_offset = None
    if is_last:
        if total is None:
            total = query.order_by(None).count()
        remainder = total % page_size
        last_offset = max(total - (remainder or page_size), 0)
        query = query.offset(last_offset)

    rows = query.limit(page_size + 1).all()

    scan_has_more = len(rows) > page_size
    if scan_has_more:
        rows = rows[:page_size]
    if reverse_scan:
        # Scanned backwards to land on the target page; present rows in
        # canonical order so rendering never flips around.
        rows.reverse()

    if not rows:
        return {
            "rows": rows, "next_cursor": None, "prev_cursor": None,
            "has_next": False, "has_prev": False,
        }

    if is_last:
        # Rows grew between COUNT and SELECT: the fetched window is no
        # longer truly last, surface a forward cursor instead of lying.
        has_next = scan_has_more
        has_prev = (last_offset or 0) > 0 or scan_has_more
    elif direction in ("first", "next"):
        has_next = scan_has_more
        # A first page starts the list; a next page always has a preceding
        # one (the page its cursor was anchored to).
        has_prev = direction == "next"
    else:  # prev
        has_prev = scan_has_more
        has_next = True

    return {
        "rows": rows,
        # Anchor on the END edge of this page for the page continuing forward.
        "next_cursor": boundary_cursor(rows[-1], dim_spec) if has_next else None,
        # Anchor on the START edge of this page for the preceding page.
        "prev_cursor": boundary_cursor(rows[0], dim_spec) if has_prev else None,
        "has_next": has_next,
        "has_prev": has_prev,
    }
