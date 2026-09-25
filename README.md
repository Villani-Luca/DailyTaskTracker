# DailyTaskTracker

Keep track of your tasks of the day in color-coded folders, plan them on a calendar, and
see how much time you actually spend on them.

## Features

- **Folders** with a color of your choice. The color follows the folder everywhere: task
  rows, project cards and every calendar block of its tasks and appointments.
- **Tasks** with status (To do, In progress, Blocked, Done), priority, planned date, due
  date, time estimate, description and **comments**.
- **Overview**: today's tasks and schedule, what is in progress, what is overdue, and the
  next six days.
- **Projects**: per folder, the share of tasks in each status, completion, time spent
  against the estimate, and overdue count.
- **Calendar** (month, week, day and list views):
  - *Planned* blocks (tinted): tasks you placed on the calendar, and appointments.
  - *Time spent* blocks (solid): from the timer, or logged by hand.
  - Tasks planned for a day show in the *Tasks* row; drag one into a time slot to schedule it.
  - Drag open tasks from the side panel onto the grid; drag and resize blocks to move them.
  - *Mark as spent* turns a planned block into tracked time.
  - The side panel totals time spent and planned per folder for the visible range.
- **Timer**: press ▶ on a task to start tracking; the running timer sits in the top bar.
- Light and dark theme.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run tasktracker --demo   # first run: adds sample data, then opens the browser
uv run tasktracker          # every run after that
```

Without uv: `pip install -e .`, then run `tasktracker`.

| Option | Meaning |
|---|---|
| `--port 8000` / `--host 127.0.0.1` | where to listen |
| `--no-browser` | don't open a browser tab |
| `--demo` | fill an **empty** database with sample folders, tasks and blocks |
| `--reload` | restart on code changes (development) |

Your data lives in a SQLite file at `~/.dailytasktracker/tasks.db`. Point
`TASKTRACKER_DATABASE_URL` elsewhere to use another database, for example
`sqlite:///C:/data/tasks.db`.

## How it works

```
src/tasktracker/
  models.py       SQLAlchemy models: Folder, Task, Comment, TimeBlock
  schemas.py      Pydantic models for everything in and out of the API
  services/       business rules (folders, tasks, calendar, reports)
  api/            thin FastAPI routers over the services, under /api
  main.py         app factory; __main__.py is the `tasktracker` command
  demo.py         sample data for --demo
  static/         the web UI: plain ES modules, no build step
tests/            API tests (pytest, in-memory SQLite)
```

Design decisions worth knowing:

- **One calendar table.** A `TimeBlock` is either `planned` or `tracked`, and is linked to
  a task or stands alone as an appointment with its own title and folder. A running
  timer is a tracked block with no end yet. Planned vs. spent time is a sum over blocks.
- **Business rules live in `services/`**, not in the routes:
  - Placing a task on the calendar plans it for that day, unless you picked a different
    date yourself. The planned date then follows the block when you drag it.
  - Starting a timer marks the task *In progress* and stops any other timer; only one
    runs at a time.
  - Completing a task stops its timer.
  - Deleting a folder keeps its tasks: they move to the *Inbox*.
- **Local time.** This is a single-user app on your machine, so datetimes are stored as
  naive local wall-clock time, the same way the calendar shows them.
- **Offline-friendly UI.** [FullCalendar 6](https://fullcalendar.io) (MIT) is vendored in
  `static/vendor/`, so nothing is fetched from the internet at runtime.

The REST API is documented at <http://127.0.0.1:8000/docs> while the app runs.

## Development

```bash
uv run pytest                  # tests
uv run ruff check src tests    # lint
uv run ruff format src tests   # format
uv run tasktracker --reload    # dev server
```

The database schema is created on startup with `create_all`. That creates missing
tables but does not alter existing ones, so once the schema changes after real data
exists, add [Alembic](https://alembic.sqlalchemy.org) migrations.

## Roadmap: AI

The service layer is deliberately shaped so an AI assistant can drive it. Each service
function takes plain arguments and returns data that already has a Pydantic schema,
which maps one-to-one to an LLM tool definition (for example with Claude's tool use).
Ideas:

- **Natural-language capture**: "call Marco tomorrow at 3pm about the demo" becomes a
  task plus a planned block in the right folder.
- **Plan my day**: fill today's free slots from open tasks by priority, due date and
  estimate.
- **Summaries**: a daily or weekly recap of time spent per folder, what got done, and the
  comments on blocked tasks.
- **Better estimates**: suggest estimates from how long similar tasks actually took.
