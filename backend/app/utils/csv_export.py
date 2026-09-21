"""CSV export helper (UTF-8 BOM so Excel opens Chinese text correctly).

Exports stream row-by-row so large result sets never have to be buffered
in memory, and every response carries an ``X-Result-Count`` header with
the number of data rows written. The frontend compares it with the total
shown above the list to guarantee "导出条数 = 汇总条数".
"""
import csv
import io
from datetime import datetime

from flask import Response, stream_with_context

EXPORT_COUNT_HEADER = "X-Result-Count"


def _resolve(row, accessor):
    """Read a column from a model instance, a mapping or a callable."""
    value = accessor(row) if callable(accessor) else getattr(row, accessor, None)
    return "" if value is None else value


def iter_csv(rows, columns, batch_size=500):
    """Yield encoded CSV chunks. ``rows`` may be any iterable of ORM rows.

    Rows are consumed in batches; callers are expected to hand over a
    query (or ``yield_per`` iterator) rather than a materialised list.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for header, _ in columns])
    yield "﻿" + buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    for row in rows:
        writer.writerow([_resolve(row, accessor) for _, accessor in columns])
        if buffer.tell() >= 64 * 1024:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    yield buffer.getvalue()


def csv_response(rows, columns, filename_prefix, count=None):
    """Build a streaming CSV response.

    ``count`` is the exact number of data rows the caller is about to
    stream; it is echoed in ``X-Result-Count`` for client-side
    reconciliation. When omitted the header reports 0 (legacy callers).
    """
    filename = "%s_%s.csv" % (filename_prefix, datetime.now().strftime("%Y%m%d%H%M%S"))

    def generate():
        yield from iter_csv(rows, columns)

    response = Response(stream_with_context(generate()), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=%s" % filename
    response.headers[EXPORT_COUNT_HEADER] = str(int(count or 0))
    return response
