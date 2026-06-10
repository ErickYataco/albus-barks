# Albus Barks

A Tamagotchi-style e-ink dog assistant for Raspberry Pi that barks for reminders and celebrates completed tasks.

Albus Barks has two lightweight parts:

- **Web CRUD app**: FastAPI + SQLAlchemy ORM + SQLite + Jinja UI for adding, editing, deleting, and completing tasks.
- **E-ink dashboard**: Python + Pillow renderer for a 2.13-inch Waveshare e-Paper display. It reads task state from the API and shows animated Albus mood frames.

## Project layout

```text
albus-barks/
├── background/                       # Background jobs run by systemd timers
│   └── calendar_sync.py              # One-shot / watch-mode Google Calendar sync
│
├── web/                              # FastAPI CRUD app, API, templates, static files
│   ├── main.py                       # FastAPI routes, HTML pages, API endpoints
│   ├── crud.py                       # Task database operations and dog-state logic
│   ├── database.py                   # SQLite engine/session setup
│   ├── models.py                     # SQLAlchemy Task model
│   ├── schemas.py                    # Optional API schemas / DTOs
│   ├── templates/                    # Jinja HTML templates
│   └── static/                       # CSS and web-only static assets
│
├── dashboard/                        # E-ink dashboard process
│   ├── main.py                       # Dashboard loop: fetch API, render frame, display it
│   ├── client.py                     # HTTP client for /api/dashboard-state
│   ├── display.py                    # Pillow render logic for 250x122 screen
│   ├── animator.py                   # Selects the next mood frame per state
│   ├── config.py                     # Paths, display size, API URL, refresh intervals
│   └── epd_driver.py                 # Waveshare driver wrapper + simulator fallback
│
├── resources/
│   └── images/
│       └── status/                   # Albus mood animation frames
│           ├── IDLE/                 # 1.png ... 5.png
│           ├── BARK/                 # 1.png ... 5.png
│           ├── HAPPY/                # 1.png ... 5.png
│           ├── SLEEPY/               # 1.png ... 5.png
│           └── SAD/                  # 1.png ... 5.png
│
├── data/                             # SQLite database: tasks.db
├── runtime/                          # Simulator output: last_render.png
├── requirements.txt                  # Python dependencies
├── install_albus_service.sh          # Raspberry Pi systemd installer
├── kill_port_5582.sh                 # Helper used by the web systemd service
├── systemd-web.service.example       # Example Linux service for the web app
└── systemd-dashboard.service.example # Example Linux service for the e-ink dashboard
```

## Hardware target

- Raspberry Pi Zero 2 WH
- Waveshare 2.13-inch e-Paper HAT
- Tested layout size: `250x122`
- Python 3.10+ recommended

The dashboard can also run in simulator mode on macOS/Linux. In simulator mode, it saves the latest render here:

```text
runtime/last_render.png
```

## What each main file does

### Web app

| File | Purpose |
|---|---|
| `web/main.py` | Main FastAPI app. Defines HTML routes, task actions, and API endpoints like `/api/dashboard-state`. |
| `web/crud.py` | Contains task database operations and logic that decides Albus mood: `IDLE`, `BARK`, `HAPPY`, `SLEEPY`, or `SAD`. |
| `web/database.py` | Creates the SQLite connection and SQLAlchemy session. |
| `web/models.py` | Defines the `Task` table using SQLAlchemy ORM. |
| `web/templates/index.html` | Main task dashboard UI. Shows tasks, counts, and Albus mood card. |
| `web/static/styles.css` | Styling for the web CRUD UI. |

### E-ink dashboard

| File | Purpose |
|---|---|
| `dashboard/main.py` | Main dashboard loop. Fetches state from the API, chooses the next animation frame, renders the screen, and sends it to the display. |
| `dashboard/client.py` | Calls the web API. If the API is offline, it returns a fallback state. |
| `dashboard/animator.py` | Cycles through image frames in `resources/images/status/<STATE>/`. |
| `dashboard/display.py` | Uses Pillow to create the final 250x122 black-and-white e-ink image. |
| `dashboard/epd_driver.py` | Uses the real Waveshare display when available, otherwise saves `runtime/last_render.png`. |
| `dashboard/config.py` | Central place for paths, API URL, refresh intervals, and display dimensions. |

### Systemd files

| File | Purpose |
|---|---|
| `systemd-web.service.example` | Runs the FastAPI web app automatically when the Raspberry Pi boots. |
| `systemd-dashboard.service.example` | Runs the e-ink dashboard automatically when the Raspberry Pi boots. |

These files are examples. You copy them into `/etc/systemd/system/`, adjust paths/user if needed, then enable them.

## Quick start on laptop/macOS

```bash
cd albus-barks
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Terminal 1 — run the web app:

```bash
uvicorn web.main:app --host 0.0.0.0 --port 5582 --reload
```

Open:

```text
http://localhost:5582
```

Terminal 2 — render the e-ink simulator once:

```bash
source .venv/bin/activate
python -m dashboard.main --once --simulate
open runtime/last_render.png
```

Continuous simulator mode:

```bash
python -m dashboard.main --simulate
```

## Quick start on Raspberry Pi

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip libopenjp2-7 libtiff5

cd albus-barks
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Terminal 1 — run the web app:

```bash
uvicorn web.main:app --host 0.0.0.0 --port 5582
```

Terminal 2 — run the dashboard:

```bash
source .venv/bin/activate
python -m dashboard.main
```

Then open the CRUD UI from your laptop or phone:

```text
http://raspberrypi.local:5582
```

or:

```text
http://<raspberry-pi-ip>:5582
```

## API used by dashboard

```text
GET /api/dashboard-state
```

Example response:

```json
{
  "dog_state": "BARK",
  "message": "You have overdue tasks",
  "counts": {
    "all": 2,
    "pending": 1,
    "done": 1,
    "overdue": 1,
    "due_soon": 0
  },
  "tasks": [
    {
      "id": 1,
      "title": "Clean kitchen",
      "due_time": "2026-05-17T20:03:00",
      "status": "overdue",
      "done": false
    }
  ]
}
```

The dashboard uses this response to decide:

```text
API state -> animator frame -> Pillow render -> e-ink display
```

## Calendar meeting reminder

Albus can treat Google Calendar meetings as calendar-backed tasks. When a meeting is within 15 minutes, the dashboard API returns a `MEETING` reminder directive. The dashboard briefly switches to a reminder screen with Albus talking and wagging his tail, a "DON'T BE LATE" message, the minutes remaining, and the meeting name. It then returns to the normal task dashboard and repeats periodically until the meeting start time. Once the meeting starts, Albus marks that calendar task as done.

The active meeting reminder frames live in:

```text
resources/images/status/MEETING/
```

### Local meeting test

With the web app running, create a calendar-style test task due within the next 15 minutes:

```bash
curl -X POST http://127.0.0.1:5582/api/calendar-test-task \
  -F "title=Standup meeting" \
  -F "due_time=2026-06-09T18:45"
```

Then run the simulator continuously:

```bash
python -m dashboard.main --simulate
```

Albus should briefly switch to the meeting reminder screen, then return to the regular task dashboard.

### Google Calendar setup

Google Calendar sync is handled by a background job, not by the web app or dashboard API.

Install dependencies after pulling this feature:

```bash
pip install -r requirements.txt
```

Create Google OAuth credentials for a desktop app, then place the downloaded client secret at:

```text
config/google_credentials.json
```

Create or copy the OAuth token to:

```text
config/google_token.json
```

Both Google credential files are ignored by git.

The Raspberry Pi installer requires both files before it installs/enables services:

```text
config/google_credentials.json
config/google_token.json
```

If you keep them somewhere else, set these paths in `/etc/default/albus-barks` before rerunning the installer:

```text
ALBUS_GOOGLE_CALENDAR_ID=primary
ALBUS_GOOGLE_CREDENTIALS_FILE=/home/albus/albus-barks/config/google_credentials.json
ALBUS_GOOGLE_TOKEN_FILE=/home/albus/albus-barks/config/google_token.json
```

Calendar sync runs as its own systemd timer. It does not run inside the dashboard API. The timer invokes:

```bash
python -m background.calendar_sync
```

That command syncs once and exits. The installer creates `albus-barks-calendar-sync.timer`, which runs it every 5 minutes.

For local Mac testing, keep the sync job running in the foreground:

```bash
python -m background.calendar_sync --watch --interval 300
```

For a one-time local sync:

```bash
python -m background.calendar_sync
```

The installer creates an optional environment file here:

```text
/etc/default/albus-barks
```

If you use a non-primary calendar, replace `primary` with that calendar ID.

If you need to install temporarily without Google Calendar files, pass:

```bash
sudo REQUIRE_GOOGLE_CALENDAR=false ./install_albus_service.sh
```

Then add the files later and start the timer:

```bash
sudo systemctl start albus-barks-calendar-sync.timer
```

## Image frames and animation

Mood frames live in:

```text
resources/images/status/<STATE>/
```

Expected states:

```text
IDLE
BARK
HAPPY
SLEEPY
SAD
MEETING
```

Each folder can contain multiple frames:

```text
resources/images/status/IDLE/1.png
resources/images/status/IDLE/2.png
resources/images/status/IDLE/3.png
resources/images/status/IDLE/4.png
resources/images/status/IDLE/5.png
```

The dashboard uses `dashboard/animator.py` to cycle through available frames. If a state has no frames, it falls back to `IDLE`.

## Running with systemd on Raspberry Pi

The easiest install path is the repo installer:

```bash
curl -fsSL https://raw.githubusercontent.com/ErickYataco/albus-barks/main/install_albus_service.sh -o /tmp/install_albus_service.sh
chmod +x /tmp/install_albus_service.sh
sudo /tmp/install_albus_service.sh
sudo systemctl start albus-barks-web.service
sudo systemctl start albus-barks-dashboard.service
```

The installer:

- Creates and enables `albus-barks-web.service`.
- Creates and enables `albus-barks-dashboard.service`.
- Creates and enables `albus-barks-calendar-sync.timer` for Google Calendar sync every 5 minutes.
- Clones or updates `https://github.com/ErickYataco/albus-barks.git` when needed.
- Installs Raspberry Pi system packages for Python, Pillow, GPIOZero/LGPIO, GPIO, and SPI.
- Enables SPI and I2C with `raspi-config nonint`.
- Creates or reuses the dedicated `albus` user and adds it to `spi`, `gpio`, and `i2c`.
- Creates `kill_port_5582.sh` as a manual helper for freeing port `5582`.
- Writes install logs under `/var/log/albus_install`.
- Runs the services as `albus`, not `root`.

The installer uses a virtual environment at `/home/albus/albus-barks/.venv`. This is different from Bjorn's installer, which installs into the system Python with `--break-system-packages`. Albus uses a venv so FastAPI/Uvicorn dependencies stay isolated from Raspberry Pi OS packages, while `--system-site-packages` still lets the venv see apt-installed hardware packages such as `python3-spidev` and `python3-gpiozero`.

Albus does not stop Bjorn automatically. Only one process should own the Waveshare EPD/SPI/GPIO stack at a time, so stop Bjorn manually before starting Albus:

```bash
sudo systemctl stop bjorn.service
sudo systemctl start albus-barks-web.service
sudo systemctl start albus-barks-dashboard.service
```

To switch back to Bjorn:

```bash
sudo systemctl stop albus-barks-dashboard.service
sudo systemctl stop albus-barks-web.service
sudo systemctl start bjorn.service
```

If you want systemd to make the services mutually exclusive without pre-start stop commands, install Albus with an explicit conflict:

```bash
sudo CONFLICTS_SERVICE=bjorn.service ./install_albus_service.sh
```

You can also install the example units manually.

The repo includes two service examples:

```text
systemd-web.service.example
systemd-dashboard.service.example
systemd-calendar-sync.service.example
systemd-calendar-sync.timer.example
```

They are not active by default. To install them:

```bash
sudo cp systemd-web.service.example /etc/systemd/system/albus-barks-web.service
sudo cp systemd-dashboard.service.example /etc/systemd/system/albus-barks-dashboard.service
sudo cp systemd-calendar-sync.service.example /etc/systemd/system/albus-barks-calendar-sync.service
sudo cp systemd-calendar-sync.timer.example /etc/systemd/system/albus-barks-calendar-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable albus-barks-web.service
sudo systemctl enable albus-barks-dashboard.service
sudo systemctl enable albus-barks-calendar-sync.timer
sudo systemctl start albus-barks-web.service
sudo systemctl start albus-barks-dashboard.service
sudo systemctl start albus-barks-calendar-sync.timer
```

Check status:

```bash
sudo systemctl status albus-barks-web.service
sudo systemctl status albus-barks-dashboard.service
sudo systemctl status albus-barks-calendar-sync.timer
```

View logs:

```bash
journalctl -u albus-barks-web.service -f
journalctl -u albus-barks-dashboard.service -f
journalctl -u albus-barks-calendar-sync.service -f
```

If your project is not in `/home/albus/albus-barks`, update `WorkingDirectory` and `ExecStart` inside both service files, or run the installer with `ALBUS_PATH=/your/path`.

## Notes about e-ink animation

E-ink is not made for smooth video. It is better for slow state-based animation.

Recommended behavior:

- `IDLE`: normal waiting
- `BARK`: task due soon or overdue
- `HAPPY`: recently completed task
- `SLEEPY`: no pending tasks
- `SAD`: too many overdue tasks or API fallback

The dashboard refreshes more often for alert states:

```text
BARK / HAPPY / SAD -> ALERT_REFRESH_SECONDS
IDLE / SLEEPY      -> REFRESH_SECONDS
```

Those values are configured in:

```text
dashboard/config.py
```
