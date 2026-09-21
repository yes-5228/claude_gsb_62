"""CSV export helpers (UTF-8 BOM so Excel opens Chinese text correctly)."""
import csv
import io
from datetime import datetime

from flask import Response, stream_with_context


def _resolve(row, accessor):
    """Read a column from a model instance, a mapping or a callable."""
    value = accessor(row) if callable(accessor) else getattr(row, accessor, None)
    return "" if value is None else value


def csv_response(rows, columns, filename_prefix):
    """Eagerly build a CSV file from in-memory rows."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([_resolve(row, accessor) for _, accessor in columns])

    filename = "%s_%s.csv" % (filename_prefix, datetime.now().strftime("%Y%m%d%H%M%S"))
    payload = "\ufeff" + buffer.getvalue()
    return Response(
        payload,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=%s" % filename},
    )


def _dict_value(row, accessor):
    value = accessor(row) if callable(accessor) else row.get(accessor)
    return "" if value is None else value


def csv_stream_response(payloads, columns, filename_prefix, total=None):
    """Stream a (possibly large) iterable of dict payloads row by row."""

    def generate():
        yield "\ufeff"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([header for header, _ in columns])
        yield buffer.getvalue()
        for row in payloads:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([_dict_value(row, accessor) for _, accessor in columns])
            yield buffer.getvalue()

    filename = "%s_%s.csv" % (filename_prefix, datetime.now().strftime("%Y%m%d%H%M%S"))
    headers = {"Content-Disposition": "attachment; filename=%s" % filename}
    if total is not None:
        headers["X-Export-Total"] = str(total)
    # 生成器在视图返回后才由 WSGI 迭代, 需用 stream_with_context 保留应用上下文
    return Response(
        stream_with_context(generate()),
        mimetype="text/csv; charset=utf-8",
        headers=headers,
    )
