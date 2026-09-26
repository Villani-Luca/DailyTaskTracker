"""Excel export of a time report: the same range and folder filter as the Reports page.

Four sheets: a summary with time per folder, time per task, time per day, and every
calendar block in the range (a timesheet). Hours are plain numbers, so they add up in
Excel; every table has a total row that follows Excel's filters.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from typing import Any

import xlsxwriter
from sqlalchemy.orm import Session
from xlsxwriter.format import Format
from xlsxwriter.worksheet import Worksheet

from tasktracker.models import BlockKind, TaskStatus, now
from tasktracker.services import reports
from tasktracker.services.folders import get_folder

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ALL_PROJECTS = "All projects"
STATUS_LABELS = {
    TaskStatus.TODO: "To do",
    TaskStatus.IN_PROGRESS: "In progress",
    TaskStatus.BLOCKED: "Blocked",
    TaskStatus.DONE: "Done",
}


def time_report_xlsx(
    session: Session,
    user_id: int,
    starts_at: datetime,
    ends_at: datetime,
    *,
    folder_id: int | None = None,
    inbox: bool = False,
) -> tuple[str, bytes]:
    """The time report as an Excel workbook, and a file name for it."""
    filters: dict[str, Any] = {"folder_id": folder_id, "inbox": inbox}
    report = reports.time_report(session, user_id, starts_at, ends_at, **filters)
    blocks = reports.report_blocks(session, user_id, starts_at, ends_at, **filters)
    if inbox:
        project = reports.INBOX_NAME
    elif folder_id is not None:
        project = get_folder(session, user_id, folder_id).name
    else:
        project = ALL_PROJECTS
    first_day, day_count = reports.report_days(starts_at, ends_at)
    last_day = first_day + timedelta(days=day_count - 1)
    folder_names = {f.folder_id: f.name for f in report.folders}

    output = io.BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True})
    fmt = {
        "title": book.add_format({"bold": True, "font_size": 14}),
        "label": book.add_format({"bold": True}),
        "hours": book.add_format({"num_format": "0.00"}),
        "date": book.add_format({"num_format": "yyyy-mm-dd", "align": "left"}),
        "datetime": book.add_format({"num_format": "yyyy-mm-dd hh:mm", "align": "left"}),
        "time": book.add_format({"num_format": "hh:mm", "align": "left"}),
        "text": None,
    }

    sheet = book.add_worksheet("Summary")
    sheet.write(0, 0, "Time report", fmt["title"])
    for row, (label, value, style) in enumerate(
        [
            ("Project", project, None),
            ("From", first_day, "date"),
            ("To", last_day, "date"),
            ("Exported", now(), "datetime"),
            (None, None, None),
            ("Time spent (h)", report.tracked_minutes / 60, "hours"),
            ("Planned (h)", report.planned_minutes / 60, "hours"),
            ("Tasks completed", report.completed_tasks, None),
        ],
        start=2,
    ):
        if label:
            sheet.write(row, 0, label, fmt["label"])
            sheet.write(row, 1, value, fmt[style] if style else None)
    _table(
        sheet,
        12,
        "ByFolder",
        fmt,
        [("Folder", 28, "text"), ("Spent (h)", 12, "hours"), ("Planned (h)", 12, "hours")],
        [[f.name, f.tracked_minutes / 60, f.planned_minutes / 60] for f in report.folders],
    )

    _table(
        book.add_worksheet("By task"),
        0,
        "ByTask",
        fmt,
        [
            ("Task or appointment", 44, "text"),
            ("Folder", 20, "text"),
            ("Status", 14, "text"),
            ("Spent (h)", 12, "hours"),
            ("Planned (h)", 12, "hours"),
        ],
        [
            [
                t.title,
                folder_names.get(t.folder_id, reports.INBOX_NAME),
                STATUS_LABELS[t.status] if t.status else "Appointment",
                t.tracked_minutes / 60,
                t.planned_minutes / 60,
            ]
            for t in report.tasks
        ],
    )

    _table(
        book.add_worksheet("By day"),
        0,
        "ByDay",
        fmt,
        [("Date", 14, "date"), ("Spent (h)", 12, "hours"), ("Planned (h)", 12, "hours")],
        [[d.day, d.tracked_minutes / 60, d.planned_minutes / 60] for d in report.days],
    )

    entries = []
    for block in blocks:
        start, end = reports.clip(block, starts_at, ends_at)
        if end <= start:
            continue
        hours = (end - start).total_seconds() / 3600
        tracked = block.kind is BlockKind.TRACKED
        folder = block.effective_folder
        entries.append(
            [
                start.date(),
                start.time(),
                end.time(),
                block.task.title if block.task else block.display_title,
                folder.name if folder else reports.INBOX_NAME,
                hours if tracked else None,
                None if tracked else hours,
                block.notes + (" (timer running)" if block.is_running else ""),
            ]
        )
    _table(
        book.add_worksheet("Time entries"),
        0,
        "TimeEntries",
        fmt,
        [
            ("Date", 12, "date"),
            ("Start", 8, "time"),
            ("End", 8, "time"),
            ("Task or appointment", 40, "text"),
            ("Folder", 20, "text"),
            ("Spent (h)", 11, "hours"),
            ("Planned (h)", 11, "hours"),
            ("Notes", 40, "text"),
        ],
        entries,
    )

    book.close()
    suffix = "" if project == ALL_PROJECTS else f"_{_slug(project)}"
    return f"time-report_{first_day}_{last_day}{suffix}.xlsx", output.getvalue()


def _table(
    sheet: Worksheet,
    first_row: int,
    name: str,
    fmt: dict[str, Format | None],
    columns: list[tuple[str, int, str]],
    rows: list[list[Any]],
) -> None:
    """An Excel table with a total row that sums the hours columns."""
    for i, (_, width, _) in enumerate(columns):
        sheet.set_column(i, i, width)
    options = []
    for i, (header, _, style) in enumerate(columns):
        column: dict[str, Any] = {"header": header, "format": fmt[style]}
        if i == 0:
            column["total_string"] = "Total"
        elif style == "hours":
            column["total_function"] = "sum"
            column["total_value"] = sum(row[i] or 0 for row in rows)
        options.append(column)
    last_row = first_row + max(len(rows), 1) + 1  # header, data (at least one row), total
    sheet.add_table(
        first_row,
        0,
        last_row,
        len(columns) - 1,
        {
            "name": name,
            "style": "Table Style Light 9",
            "total_row": True,
            "columns": options,
            "data": rows,
        },
    )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
