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
- **Accounts**: log in with a username and password; everyone sees only their own
  folders, tasks and calendar. Accounts are created by hand (there is no sign-up).
- Light and dark theme.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run tasktracker-users create luca   # first run: create your account (asks for a password)
uv run tasktracker --demo luca         # first run: adds sample data to it, opens the browser
uv run tasktracker                     # every run after that
```

Without uv: `pip install -e .`, then run `tasktracker-users` and `tasktracker`.

| Option | Meaning |
|---|---|
| `--port 8000` / `--host 127.0.0.1` | where to listen |
| `--no-browser` | don't open a browser tab |
| `--demo USERNAME` | fill that user's **empty** account with sample folders, tasks and blocks |
| `--reload` | restart on code changes (development) |

Your data lives in a SQLite file at `~/.dailytasktracker/tasks.db`. Point
`TASKTRACKER_DATABASE_URL` elsewhere to use another database, for example
`sqlite:///C:/data/tasks.db`.

## Users

There is no sign-up page: accounts are created by hand with `tasktracker-users`.

```bash
tasktracker-users create luca          # asks for the password twice
tasktracker-users set-password luca    # new password; also logs luca out everywhere
tasktracker-users list
```

Usernames are case-insensitive. Passwords need at least 8 characters and are stored as
argon2id hashes. Every folder, task, comment and calendar block belongs to one user,
and nobody else can see or change it.

**In production**, run the script with the same environment as the server, so it
writes to the same database, for example inside the app's container:

```bash
TASKTRACKER_DATABASE_URL=... tasktracker-users create luca
printf '%s\n' "$PASSWORD" | tasktracker-users create luca --password-stdin   # no prompt
```

Also set `TASKTRACKER_SECURE_COOKIES=true` when the app is served over HTTPS (on
Vercel it's automatic), so the login cookie is never sent over plain HTTP. Logins last
30 days.

## Deploy to Vercel

The project is ready for [Vercel](https://vercel.com/docs/frameworks/backend/fastapi):
`app.py` is the entrypoint Vercel looks for, dependencies come from `pyproject.toml` and
`uv.lock`, and `.python-version` picks Python 3.12.

1. **Create the project.** Push the repository to GitHub and import it at
   <https://vercel.com/new> (Vercel detects FastAPI), or run `vercel deploy` here.
2. **Add a Postgres database.** Files written on Vercel don't last, so SQLite won't do.
   In the project, open *Storage*, create a **Neon** database and connect it to the
   project. That adds `DATABASE_URL`, which the app uses. Any other Postgres works too:
   set `DATABASE_URL` (or `TASKTRACKER_DATABASE_URL`) to its connection string.
3. **Set your timezone.** Add the environment variable `TASKTRACKER_TIMEZONE`, for
   example `Europe/Rome`. Vercel runs on UTC and doesn't let you set `TZ`; without this,
   timers and "today" are off by your UTC offset.
4. **Redeploy** so the variables apply. The app creates its tables when it starts.
5. **Create your user** from your own machine, pointed at the same database (copy the
   connection string from the Neon dashboard):

   ```bash
   TASKTRACKER_DATABASE_URL='postgresql://...' uv run tasktracker-users create luca
   ```

   In PowerShell:

   ```powershell
   $env:TASKTRACKER_DATABASE_URL = 'postgresql://...'; uv run tasktracker-users create luca
   ```

| Environment variable | Meaning |
|---|---|
| `DATABASE_URL` or `TASKTRACKER_DATABASE_URL` | the database; `postgres://` URLs use psycopg 3 |
| `TASKTRACKER_TIMEZONE` | your timezone, e.g. `Europe/Rome` (default: the server's) |
| `TASKTRACKER_SECURE_COOKIES` | HTTPS-only login cookie (default: on for Vercel, off elsewhere) |

## How it works

```
src/tasktracker/
  models.py       SQLAlchemy models: User, LoginSession, Folder, Task, Comment, TimeBlock
  schemas.py      Pydantic models for everything in and out of the API
  services/       business rules (auth, folders, tasks, calendar, reports)
  api/            thin FastAPI routers over the services, under /api
  main.py         app factory; __main__.py is the `tasktracker` command
  users_cli.py    the `tasktracker-users` command
  demo.py         sample data for --demo
  static/         the web UI: plain ES modules, no build step; login.html is the login page
tests/            API tests (pytest, in-memory SQLite)
app.py            the entrypoint Vercel runs
```

Design decisions worth knowing:

- **Every record has an owner.** Folders, tasks and calendar blocks carry a `user_id`
  (comments belong to their task). Every service function takes the `user_id` and
  filters by it, so another user's record looks exactly like one that doesn't exist
  (404). Logins are server-side sessions: the cookie holds a random token and the
  database stores only its hash, so logging out or changing a password ends the session.
- **One calendar table.** A `TimeBlock` is either `planned` or `tracked`, and is linked to
  a task or stands alone as an appointment with its own title and folder. A running
  timer is a tracked block with no end yet. Planned vs. spent time is a sum over blocks.
- **Business rules live in `services/`**, not in the routes:
  - Placing a task on the calendar plans it for that day, unless you picked a different
    date yourself. The planned date then follows the block when you drag it.
  - Starting a timer marks the task *In progress* and stops any other timer; each user
    has at most one running.
  - Completing a task stops its timer.
  - Deleting a folder keeps its tasks: they move to the *Inbox*.
- **Local time.** Datetimes are stored as naive local wall-clock time, the same way the
  calendar shows them. "Local" is `TASKTRACKER_TIMEZONE`, or the server's timezone when
  it isn't set.
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
exists, add [Alembic](https://alembic.sqlalchemy.org) migrations. A database created
before user accounts existed has no `user_id` columns: delete it and start again.

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
