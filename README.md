# Albus Barks

Albus Barks is a Raspberry Pi e-ink alert companion. Instead of being a task list app, the project is moving toward one focused job: watch configured sources and show useful alerts on the Waveshare display when something deserves attention.

The first alert sources are:

- Google Calendar meetings.
- LinkedIn job matches through Bright Data.

The web app becomes a small configuration and status surface. The Raspberry Pi dashboard becomes the main experience.

## Suggested version

Recommended branch/version for this rewrite:

```text
0.2.0-alpha.0
```

Why:

- `0.1.x` was the task-list prototype.
- `0.2.0-alpha.0` is the alert-first rewrite while the APIs, database shape, and dashboard behavior are still changing.
- `0.2.0` should be used once calendar alerts, Bright Data job alerts, and the dashboard queue are working end to end.

This is a product direction change, but the project is still pre-`1.0.0`, so a minor version bump is enough.

## New product direction

Albus should answer one question all day:

```text
What should Erick pay attention to now?
```

The app should not ask the user to maintain a manual task list. Instead, background jobs collect signals from configured sources, normalize them into alerts, and the dashboard decides what to show.

### Alert types

| Alert type | Source | What Albus shows |
|---|---|---|
| Meeting | Google Calendar | Meeting name, minutes remaining, "don't be late" reminder, talking/wagging Albus animation |
| Job match | Bright Data LinkedIn jobs feed | Role title, company, location/remote mode, match reason |

## Project layout

```text
albus-barks/
├── background/                       # Background sync jobs and alert collectors
│   ├── calendar_sync.py              # Google Calendar meeting sync
│   └── job_sync.py                   # Bright Data LinkedIn job sync
│
├── web/                              # FastAPI admin/status app
│   ├── main.py                       # Status pages and API endpoints
│   ├── crud.py                       # Alert persistence helpers
│   ├── database.py                   # SQLite engine/session setup
│   ├── models.py                     # Alert, source, and run models
│   ├── schemas.py                    # API schemas / DTOs
│   ├── templates/                    # Configuration/status UI
│   └── static/                       # CSS and web-only static assets
│
├── dashboard/                        # E-ink dashboard process
│   ├── main.py                       # Fetches alert state, renders frames, updates display
│   ├── client.py                     # HTTP client for dashboard state
│   ├── display.py                    # Pillow render logic for 250x122 screen
│   ├── animator.py                   # Selects Albus animation frames
│   ├── config.py                     # Paths, display size, API URL, refresh intervals
│   └── epd_driver.py                 # Waveshare driver wrapper + simulator fallback
│
├── config/
│   ├── alerts.example.json           # Example source/job configuration
│   ├── google_credentials.json       # Local-only Google OAuth client file
│   └── google_token.json             # Local-only Google OAuth token file
│
├── resources/
│   └── images/
│       └── status/                   # Albus animation frames
│
├── data/                             # SQLite database
├── runtime/                          # Simulator output
├── requirements.txt                  # Python dependencies
├── install_albus_service.sh          # Raspberry Pi systemd installer
├── uninstall_albus_service.sh        # Removes Albus systemd services/timers
└── systemd-*.example                 # Example Linux service/timer units
```

Some files above are the target shape for this branch. The first alert-first refactor is in place: `Alert` and `AlertRun` replace task storage, the dashboard API returns alerts, and the web UI is an alert/status console.

## Configuration-first jobs

All alert sources should run from configuration. The project should be useful without code edits when search terms, thresholds, or schedules change.

Example:

```json
{
  "calendar": {
    "enabled": true,
    "calendar_id": "primary",
    "reminder_minutes": 15,
    "repeat_minutes": 5
  },
  "linkedin_jobs": {
    "enabled": true,
    "provider": "bright_data",
    "openai_relevance": {
      "enabled": true,
      "api_key_env": "OPENAI_API_KEY",
      "model": "gpt-4.1-mini",
      "min_score": 70,
      "max_jobs_to_score": 5,
      "batch_size": 10,
      "system_prompt": "You score LinkedIn jobs for a candidate. Use candidate_profile and objective as the primary relevance criteria. Return structured results. Each result must include index, score from 0 to 100, include boolean, severity as info or high, and reason. Set include=true only when score is at least minimum_alert_score.",
      "objective": "Find remote full-time DevOps, SRE, platform engineering, Kubernetes, cloud infrastructure, and automation roles that are realistic for a candidate in Peru or Latin America.",
      "profile": "Senior DevOps / platform engineer interested in remote roles, Kubernetes, CI/CD, Linux, cloud infrastructure, automation, observability, and reliability engineering."
    },
    "exclude_companies": [],
    "searches": [
      {
        "keyword": "platform engineer",
        "location": "United States",
        "country": "US",
        "remote": "Remote",
        "job_type": "Full-time",
        "experience_level": "Mid-Senior level",
        "time_range": "Past week"
      }
    ],
    "bright_data": {
      "api_token_env": "BRIGHT_DATA_API_TOKEN",
      "api_url": "https://api.brightdata.com/datasets/v3/trigger",
      "snapshot_url": "https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}?format=json",
      "limit_per_input": 10,
      "dataset_id": "gd_lpfll7v5hcqtkxl6l",
      "collector_id": "",
      "request_mode": "discover_by_keyword",
      "timeout_seconds": 180,
      "snapshot_timeout_seconds": 900,
      "snapshot_poll_interval_seconds": 15
    }
  },
  "notifications": {
    "job_reminder_repeat_minutes": 5
  }
}
```

Secrets must stay outside git. Use environment variables or local files ignored by `.gitignore`.

## Google Calendar alerts

Calendar sync should run as a background job, not inside the web request path.

Expected behavior:

- Sync upcoming meetings from Google Calendar.
- Create or update meeting alerts.
- When a meeting is within `reminder_minutes`, show a full-screen reminder.
- Repeat the reminder every `repeat_minutes` until the meeting starts.
- After the meeting starts, expire or complete the alert automatically.

The dashboard reminder should prioritize clarity:

- Albus animation on the left half of the display.
- Meeting message on the right half of the display.
- Meeting title and minutes remaining.
- Return to the normal dashboard after the reminder animation.

## Bright Data LinkedIn jobs

The project should not scrape LinkedIn directly. LinkedIn job discovery should use Bright Data as the data provider.

Target behavior:

- Run on a configured interval.
- Discover jobs from the Bright Data LinkedIn Jobs discover-by-keyword API.
- Use configured `searches` as keyword/location inputs.
- Filter Bright Data error rows and score usable jobs with OpenAI relevance.
- Deduplicate by stable external ID or job URL.
- Create an alert only when a job crosses `openai_relevance.min_score`.
- Notify once per job unless the job changes meaningfully.

The current config uses Bright Data dataset `gd_lpfll7v5hcqtkxl6l` with `type=discover_new` and `discover_by=keyword`, so it searches for new jobs from keyword/location inputs.

Real-time Bright Data requests can take longer than a normal API call because the scraper is collecting the page before returning the response. The example config uses `timeout_seconds: 180`, which is better for small 1 to 10 URL runs. Larger batches should use Bright Data's async batch collection or push delivery flow instead of keeping one HTTP request open.

Suggested scoring signals:

- Role title and description match `openai_relevance.objective`.
- Required skills fit `openai_relevance.profile`.
- Location or remote mode is realistic for the candidate profile.
- Company is not excluded.
- Posted date is recent.
- Seniority matches the target profile.

`openai_relevance.max_jobs_to_score` limits the total jobs sent to OpenAI in one sync. `openai_relevance.batch_size` only controls how many jobs are sent per OpenAI request.

## Dashboard behavior

The dashboard should render the highest priority active alert.

Suggested priority:

1. Meeting starting soon.
2. New high-score job match.
3. Idle status.

Alert screens should be short and readable on the 2.13-inch e-ink display. The display is not a video screen, so use slow, purposeful animation frames.

## Web app role

The web app should become an admin/status console:

- Show active alerts.
- Show last sync time for each source.
- Show last sync error.
- Show current configuration summary.
- Allow manual "sync now" commands.
- Allow dismissing or acknowledging an alert.

It should no longer be a manual task CRUD app.

## Local development

```bash
cd albus-barks
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the web app:

```bash
uvicorn web.main:app --host 0.0.0.0 --port 5582 --reload
```

Run the dashboard simulator once:

```bash
python -m dashboard.main --once --simulate
open runtime/last_render.png
```

Run the dashboard simulator continuously:

```bash
python -m dashboard.main --simulate
```

Run calendar sync once:

```bash
python -m background.calendar_sync
```

Source-specific commands:

```bash
python -m background.job_sync
```

The job sync command runs once and exits. In production, `albus-barks-job-sync.timer` decides when to run it again. Job reminders keep repeating until the alert is acknowledged, using `notifications.job_reminder_repeat_minutes` as the cooldown.

`notifications.job_reminder_repeat_minutes` only affects already-created job alerts. For example, `5` means Albus can show the job reminder again every 5 minutes until the alert is acknowledged. The interval for fetching new LinkedIn jobs is controlled by the systemd job sync timer configured during install.

## Raspberry Pi deployment

The installer creates or updates:

- `albus-barks-web.service`
- `albus-barks-dashboard.service`
- `albus-barks-calendar-sync.timer`
- `albus-barks-job-sync.timer`

Before running the installer, put these files in `config/`:

```text
config/google_credentials.json
config/google_token.json
config/alerts.json
```

What the Google files mean:

- `google_credentials.json` is the OAuth client file downloaded from Google Cloud. Use a Desktop app OAuth client.
- `google_token.json` is the authorized user token created after you approve Calendar read-only access. Albus uses it to refresh access without opening a browser on the Pi.

Official Google docs:

- [Create Google Workspace access credentials](https://developers.google.com/workspace/guides/create-credentials)
- [Google Calendar API Python quickstart](https://developers.google.com/calendar/api/quickstart/python)

Create the alert config from the example:

```bash
cp config/alerts.example.json config/alerts.json
nano config/alerts.json
```

Then confirm the required files exist:

```bash
ls config/google_credentials.json config/google_token.json config/alerts.json
```

The installer will stop with a clear error if any of those files are missing.

Install or update services after those files are in place:

```bash
sudo ./install_albus_service.sh
```

During install, the script asks for:

```text
BRIGHT_DATA_API_TOKEN
OPENAI_API_KEY
Google Calendar sync interval, default 5min
LinkedIn job sync interval, default 2d
```

Press Enter to keep the default intervals. Press Enter to skip either API key and fill it later. The installer saves API keys in the systemd environment file:

```text
/etc/default/albus-barks
```

That file is intentionally outside the repo. It is the normal Debian/Raspberry Pi convention for service environment variables and keeps tokens out of git. To edit it later:

```bash
sudo nano /etc/default/albus-barks
```

Example values:

```text
BRIGHT_DATA_API_TOKEN=your_bright_data_token
OPENAI_API_KEY=your_openai_api_key
```

For a non-interactive install, pass the keys as environment variables:

```bash
sudo BRIGHT_DATA_API_TOKEN=your_bright_data_token \
  OPENAI_API_KEY=your_openai_api_key \
  CALENDAR_SYNC_INTERVAL=5min \
  JOB_SYNC_INTERVAL=2d \
  ./install_albus_service.sh
```

Do not use `export` in this file. systemd reads it as `KEY=value` lines.

OpenAI docs:

- [OpenAI API quickstart](https://platform.openai.com/docs/quickstart)

After changing `/etc/default/albus-barks`, restart long-running services:

```bash
sudo systemctl restart albus-barks-web.service albus-barks-dashboard.service
```

The calendar and job timers run one-shot commands, so they pick up env/config changes on their next run. To force them now:

```bash
sudo systemctl start albus-barks-calendar-sync.service
sudo systemctl start albus-barks-job-sync.service
```

Only one process should own the Waveshare EPD/SPI/GPIO stack at a time. Stop Bjorn before starting Albus dashboard:

```bash
sudo systemctl stop bjorn.service
sudo systemctl start albus-barks-web.service
sudo systemctl start albus-barks-dashboard.service
```

To switch back:

```bash
sudo systemctl stop albus-barks-dashboard.service
sudo systemctl stop albus-barks-web.service
sudo systemctl start bjorn.service
```

Uninstall systemd units:

```bash
sudo ./uninstall_albus_service.sh
```

By default, uninstall keeps the repo, `albus` user, and `/etc/default/albus-barks`. Remove those only when you really mean it:

```bash
sudo REMOVE_ENV_FILE=true ./uninstall_albus_service.sh
sudo REMOVE_APP_DIR=true ./uninstall_albus_service.sh
sudo REMOVE_USER=true ./uninstall_albus_service.sh
```

## Secrets and local files

These files should never be committed:

```text
config/alerts.json
config/google_credentials.json
config/google_token.json
.env
```

Usually needed in `/etc/default/albus-barks`:

```text
BRIGHT_DATA_API_TOKEN
OPENAI_API_KEY
```

## Hardware target

- Raspberry Pi Zero 2 WH
- Waveshare 2.13-inch e-Paper HAT
- Display layout: `250x122`
- Python 3.10+ recommended

In simulator mode, the latest render is saved here:

```text
runtime/last_render.png
```
