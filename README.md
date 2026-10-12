# GitHub Build Monitor for Home Assistant

A standalone **read-only GitHub Actions monitor** for Home Assistant with native HA sensors, estimated build progress and iPhone Live Activities / Android Live Updates. No runner registration or Docker socket permissions.

> **Preview version 0.1.1**. The original v0.1.0 archive created earlier in ChatGPT is not available in the current workspace. This repository version was reconstructed and should be tested against the already-working local app before changing its installation source. **Do not replace your working HA app yet.**

## Capabilities

- Multiple repositories, including Touchy28/DSO-Optimizer and Touchy28/more-tents
- GitHub Actions workflows, job and step states, success/failure/cancelled results
- Native entity for each repository with progress, completed/total steps, current job, runner name, URL and optional ETA
- Weighted progress using previous successful step execution durations; percentages within a running step are **estimates**, not GitHub-reported metrics
- One Live Activity per concurrently active run (up to six active runs per repository), status updates and automatic removal after completion
- Persistent learning history and notification state across app restarts
- Works regardless of whether runs execute on Windows, Synology, HA or GitHub-hosted runners

## Security

- GitHub fine-grained personal access token: select repositories, **Actions: Read-only**; Metadata read is implicit. No Secrets, Contents write, Webhooks or Admin permission.
- Home Assistant app uses only **homeassistant_api: true** for its entities and mobile notifications. It does not request host Docker APIs or privileged access.
- Token is stored in **Home Assistant app options only** and never committed here. All runtime history is kept in the app's private data volume.
- If your repository is public, unauthenticated API reads may work, but authenticated requests have higher rate limits and are necessary for private repositories.

## Important: installation and migration

You currently have a local app installed and working. This new repository has the same logical app slug; installing both in parallel is **not recommended**. First test this version on a separate HA instance or review the differences, then switch to the repository source once the monitor version is verified. There is **no automatic migration** of learning history from the local installation.

For a new installation on Home Assistant OS / Supervisor:

1. In **Settings → Apps → App Store → ⋮ → Repositories**, add:
   https://github.com/Touchy28/ha-github-build-monitor
2. Refresh the store, select **GitHub Build Monitor**, then install it.
3. In app configuration, enter a GitHub Actions **read-only** token, select repositories, and leave mobile notifications off for the initial sensor check.
4. Start the app; inspect **Log** and look for sensors with the prefix sensor.github_build_ under Developer Tools → States.
5. Once the sensor check succeeds, enable Live Activities and set **live_activity_notify_service** to e.g. notify.mobile_app_iphone (use your actual mobile service).

### Options

| Setting | Example | Meaning |
| --- | --- | --- |
| repositories | Touchy28/DSO-Optimizer, Touchy28/more-tents | GitHub repositories to monitor |
| github_api_token | (secret) | GitHub fine-grained token: Actions Read |
| live_activity_enabled | false | Enable mobile push Live Activities |
| live_activity_notify_service | notify.mobile_app_iphone | Actual Home Assistant phone notifier |
| poll_interval_seconds | 60 | 30–300 seconds; higher interval saves API calls |

### Entities

Each repository has a stable ID with prefix **sensor.github_build_** and a repository-specific suffix. The sensor's state is queued/in_progress/completed/idle/unavailable. Attributes include progress_percent, progress_is_estimate, workflow, run_id, run_url, current_job, current_step, completed_steps, total_steps, estimated_remaining_seconds, active_run_count, and runner_name.

Home Assistant REST-created sensor entities are **not persistent** across an HA restart until the monitor posts them again. They are not Config Entries.

### iPhone Live Activities

When enabled, notifications use the Companion App live_update setting with a unique tag per run. Updates modify the same activity; after a completed run, the monitor publishes the final result and removes the notification on a subsequent poll. Requires HA Core 2026.7+, iOS 17.2+ and working Companion App push notifications.

### Known limits

- At most six active runs per repository and first 20 runs / first 100 jobs per request.
- Percentage and ETA are **approximations**. Progress is clamped to avoid decreases when steps/jobs appear.
- GitHub API authentication errors and rate limits show up in the HA app log; monitor retries on the next cycle.
- Service calls update live notifications only while Home Assistant/Companion App push transport is available.
- This repository build is not guaranteed identical to previously installed prototype 0.1.0.

## Development and tests

Unit tests use the Python standard library; no third-party runtime dependencies.

    python -m unittest discover -s tests -v

GitHub Actions runs the tests and syntax checks on each push and pull request.

## Attribution

Inspired by the experience of using separate GitHub Actions runners on Home Assistant. Existing runner projects such as [dchote/github-runner-addon](https://github.com/dchote/github-runner-addon) remain independent; this monitor can observe jobs they run.
