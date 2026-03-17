# Kometa Configs

Custom [Kometa](https://github.com/Kometa-Team/Kometa) configuration for Plex — curated collections, overlays, metadata operations, seasonal pre-rolls, and an automated **Last Chance** media cleanup workflow.

---

## Overview

### Libraries

This config manages **7 Plex libraries**, all sharing a consistent structure:

| Library | Type | Config Style |
|---------|------|-------------|
| Movies | Movie | Full definition (`&MOVIES` anchor) |
| Retro: Movies | Movie | Inherits `*MOVIES` |
| Kids Movies | Movie | Inherits `*MOVIES` |
| Retro: Kids Movies | Movie | Inherits `*MOVIES` |
| TV Shows | Show | Full definition |
| Retro: TV Shows | Show | Explicit (reuses anchored settings/templates) |
| Retro: Kids Shows | Show | Explicit (reuses anchored settings/templates) |

### Collections

A mix of [Kometa Defaults](https://kometa.wiki/en/latest/defaults/guide/) and custom collection files:

**Built-in Defaults (via `config.yml`):**

| Default | Libraries | Description |
|---------|-----------|-------------|
| `seasonal` | Movies | Holiday collections (Christmas, Halloween, Easter, etc.) with custom date ranges and posters |
| `imdb` | Movies, TV Shows, Retro: TV Shows, Retro: Kids Shows | IMDB Top 250 |
| `oscars` | Movies | Best Picture winners |
| `streaming` | Movies, TV Shows, Retro: TV Shows, Retro: Kids Shows | Per-service collections (Netflix, Apple TV+, etc.) |
| `universe` | Movies | Franchise collections (MCU, Star Wars, LOTR, etc.) |
| `tautulli` | Movies, TV Shows, Retro: TV Shows | "Trending on NickflixTV" — most watched in last 30 days |
| `trakt` | TV Shows | Trending on Trakt |

**Custom Collection Files (in `metadata/`):**

| File | Libraries | Description |
|------|-----------|-------------|
| `movies.yml` | Movies | 8 franchise collections (Star Trek, Pirates of the Caribbean, Transformers, John Wick, Kingsman, LOTR, The Hobbit, The Godfather) with Radarr auto-add |
| `genres.yml` | Movies | ~30 genre-based collections (Action, Comedy, Horror, Sci-Fi, etc.) with custom posters |
| `studios.yml` | Movies | ~18 studio/brand collections (Disney Animation, Pixar, Marvel, etc.) |
| `networks.yml` | TV Shows, Retro: TV Shows, Retro: Kids Shows | ~43 network collections (HBO, Netflix, ABC, etc.) |
| `suggestions.yml` | Movies* | Trakt charts — Box Office Top 10, Trending, Most Watched Weekly/Yearly, Top Pirated |
| `preroll.yml` | Movies | Seasonal server pre-rolls (Christmas, Halloween, Spring, etc.) |
| `refresh.yml` | Movies, TV Shows, Retro: TV Shows, Retro: Kids Shows | Auto-refreshes metadata for recently released items |
| `lastchance.yml` | All 7 libraries | "Last Chance" — items tagged `leaving` collected monthly before deletion |

> \* Inherited by Retro: Movies, Kids Movies, and Retro: Kids Movies via the `&MOVIES` YAML anchor.

### Overlays

**Built-in Defaults (via `config.yml`):**

| Overlay | Libraries | Description |
|---------|-----------|-------------|
| `streaming` | Movies, TV Shows, Retro: TV Shows, Retro: Kids Shows | Streaming service badges |
| `studio` | Movies, TV Shows, Retro: TV Shows, Retro: Kids Shows | Studio logos |
| `video_format` | Movies | Flags poor-quality sources (Telesync, CAM) |
| `resolution` | Movies, TV Shows, Retro: TV Shows, Retro: Kids Shows | Resolution badges (4K, 1080p, etc.) |
| `ratings` | Movies, TV Shows | Rotten Tomatoes, IMDB, and TMDB rating badges |
| `runtimes` | TV Shows, Retro: TV Shows, Retro: Kids Shows | Episode runtime badges |
| `ribbon` | Movies, TV Shows, Retro: TV Shows, Retro: Kids Shows | Award ribbons (Oscars, Emmy, Golden Globe, etc.) |

**Custom Overlay Files (in `metadata/overlays/`):**

| File | Description |
|------|-------------|
| `movies/status.yml` | "In Theaters" badge from IMDB box office + Trakt |
| `shows/status.yml` | Show status badges — New Season, Airing, Returning, Ended, Cancelled |

Custom overlay images are stored in `assets/overlays/status/`.

### Metadata Operations

Configured per-library in `config.yml` under `operations:`:

- **Mass rating updates** — User (MDB/Rotten Tomatoes), Critic (IMDB), Audience (TMDB)
- **Mass genre/content rating updates** — Synced from TMDB, IMDB, TVDB, MDB
- **Asset management** — `assets_for_all: true`, auto-creates asset folders
- **Collection cleanup** — Deletes unmanaged and below-minimum collections
- **Duplicate splitting** — `split_duplicates: false`

### Integrations

All service connections are configured via `<<PLACEHOLDER>>` syntax in `config.yml`, resolved from environment variables:

| Service | Purpose |
|---------|---------|
| **Plex** | Library management, collections, overlays |
| **Radarr** | Movie monitoring, auto-add missing, file deletion |
| **Sonarr** | Show monitoring, auto-add missing, file deletion |
| **TMDB** | Metadata, ratings, collections |
| **OMDB** | Ratings, metadata |
| **MDBList** | Content ratings, Rotten Tomatoes scores |
| **Tautulli** | Watch history for "Trending" collections |
| **Trakt** | Charts, lists, trending data |
| **Gotify** | Push notifications (errors, run start/end, changes) |

---

## Setup Guide

### Prerequisites

- A running Plex server
- Radarr and Sonarr accessible from the Kometa host
- API keys for TMDB, OMDB, MDBList, and Trakt (see [Kometa docs](https://kometa.wiki/en/latest/config/overview/))
- A Kometa installation (see step 1)

### 1. Install Kometa

<details>
<summary><strong>Proxmox LXC (Community Script)</strong></summary>

Run the [Kometa community script](https://community-scripts.github.io/ProxmoxVE/) to create an LXC with Kometa installed at `/opt/kometa`. The script installs Python, dependencies (via `uv`), and creates a systemd service.

You can skip the interactive prompts for Plex URL/token/TMDB key — we'll configure those via `.env` in the next step.

After the script completes, stop Kometa before replacing the config:

```bash
systemctl stop kometa
```

**Kometa root:** `/opt/kometa`

</details>

<details>
<summary><strong>Docker</strong></summary>

Follow the [Kometa Docker walkthrough](https://kometa.wiki/en/latest/kometa/install/walkthroughs/docker/).

Example `docker-compose.yml`:

```yaml
services:
  kometa:
    image: kometateam/kometa
    container_name: kometa
    environment:
      - TZ=America/Toronto
    volumes:
      - /path/to/kometa-configs:/config
    restart: unless-stopped
```

Mount this repo directly as `/config` inside the container — no intermediate `config/` subdirectory needed.

> The Last Chance systemd timer does not apply in Docker. Schedule the cleanup script via cron on the host, or run it manually:
> ```bash
> docker exec kometa python3 /config/scripts/lastchance.py --env-file /config/.env --dry-run
> ```

</details>

<details>
<summary><strong>Manual (Local Python)</strong></summary>

Follow the [Kometa local walkthrough](https://kometa.wiki/en/latest/kometa/install/walkthroughs/local/) to clone Kometa and install requirements.

```bash
git clone https://github.com/Kometa-Team/Kometa.git ~/Kometa
cd ~/Kometa
pip install -r requirements.txt
```

**Kometa root:** `~/Kometa` (config lives at `~/Kometa/config/`)

</details>

### 2. Clone this repo into Kometa's config directory

Replace the default config with this repository:

```bash
# Set your Kometa root (adjust for your install method)
KOMETA_ROOT="/opt/kometa"   # Proxmox community script
# KOMETA_ROOT="$HOME/Kometa"  # Manual install

# Remove the template config created during install
rm -rf "$KOMETA_ROOT/config"

# Clone this repo as the config directory
git clone https://github.com/nickelsh1ts/kometa-configs.git "$KOMETA_ROOT/config"
```

For Docker, clone directly to wherever you mounted `/config`:

```bash
git clone https://github.com/nickelsh1ts/kometa-configs.git /path/to/kometa-configs
```

To update later:

```bash
cd "$KOMETA_ROOT/config" && git pull
```

### 3. Create your environment file

```bash
cd "$KOMETA_ROOT/config"
cp .env.example .env
```

Edit `.env` and fill in your values — Plex URL/token, Radarr/Sonarr URLs/tokens, API keys, etc. Every `<<PLACEHOLDER>>` in `config.yml` has a corresponding `KOMETA_` variable in `.env.example`.

> **How it works:** Kometa [automatically loads](https://kometa.wiki/en/latest/kometa/environmental/) a `.env` file from its config directory on startup. Variables use the `KOMETA_` prefix — for example, `KOMETA_PLEXURL` resolves the `<<PLEXURL>>` placeholder in `config.yml`. No `EnvironmentFile` directive in the systemd service is needed.

> **Security:** `.env` is excluded from git via `.gitignore` — your secrets stay local.

### 4. Install the Last Chance cleanup timer (optional)

> **Note:** This step requires systemd (Linux). Docker users should schedule the cleanup via cron instead. This step is optional — everything else works without it.

```bash
sudo bash "$KOMETA_ROOT/config/scripts/install-lastchance.sh" [TIME] [WORKDIR]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `TIME` | `03:00:00` | When the cleanup runs on the 1st of each month (HH:MM or HH:MM:SS) |
| `WORKDIR` | `/opt/kometa` | Kometa root directory (parent of `config/`) |

For non-default installs, pass your Kometa root as the second argument:

```bash
# Manual install example
sudo bash ~/Kometa/config/scripts/install-lastchance.sh 03:00 ~/Kometa
```

This script:
- Installs Python dependencies (`plexapi`, `requests`) via `uv` or `pip3`
- Generates and installs a systemd oneshot service + monthly timer
- Enables the timer

> **Scheduling:** The cleanup must run **before** Kometa on the 1st. With the defaults, cleanup runs at 03:00 and Kometa runs at 06:00 (`KOMETA_TIMES=06:00` in `.env`), giving a 3-hour window.

### 5. Start Kometa

**Proxmox / systemd:**

```bash
sudo systemctl restart kometa
```

**Docker:**

```bash
docker compose up -d
```

**Manual:**

```bash
cd ~/Kometa && python3 kometa.py
```

Kometa will load the config, read `.env`, resolve all `<<PLACEHOLDER>>` values, and process your libraries.

### Verify everything

```bash
# Check Kometa is running (systemd)
systemctl status kometa

# Check Last Chance timer is scheduled (if installed)
systemctl list-timers lastchance*

# Dry-run the cleanup script to test connectivity
python3 "$KOMETA_ROOT/config/scripts/lastchance.py" --env-file "$KOMETA_ROOT/config/.env" --dry-run
```

---

## Last Chance Workflow

The "Last Chance" collection gives users a month's notice before media is removed. It is applied to all 7 libraries.

### How it works

1. **Tag items** — In Plex, add the label `leaving` to any movie or show you want to remove
2. **Collection builds** — On the 1st of each month, Kometa builds the "Last Chance" collection from all items labeled `leaving`
3. **Users see it** — The collection appears on Home, in Shared views, and in each library for the full month
4. **Cleanup runs** — On the 1st of the *next* month (before Kometa), the cleanup script:
   - Deletes each item from Radarr/Sonarr (including files on disk)
   - Deletes each item from Plex
   - Sends a Gotify notification summarizing what was removed
5. **Cycle repeats** — Kometa rebuilds the collection from any *newly* tagged items

### Timeline example

| Date | What happens |
|------|-------------|
| Jan 15 | You label "Old Movie" as `leaving` in Plex |
| Feb 1 06:00 | Kometa builds "Last Chance" collection — "Old Movie" appears |
| Feb 1–28 | Users see "Old Movie" in the Last Chance collection |
| Feb 20 | You label "Another Show" as `leaving` |
| Mar 1 03:00 | Cleanup script deletes "Old Movie" from Plex + Radarr + disk |
| Mar 1 06:00 | Kometa rebuilds collection — "Another Show" now appears |

### Running the cleanup script

The script can be triggered via systemd or run directly:

```bash
# Via systemd (runs as configured)
sudo systemctl start lastchance.service

# Direct execution with options
python3 "$KOMETA_ROOT/config/scripts/lastchance.py" --env-file "$KOMETA_ROOT/config/.env" --dry-run
```

| Flag | Description |
|------|-------------|
| `--dry-run` | Preview deletions without executing |
| `--env-file PATH` | Load environment variables from a file |
| `--no-notify` | Skip Gotify notification |
| `--no-delete-files` | Remove from *arr but keep media files on disk |
| `--import-exclude` | Add import exclusion in *arr to prevent re-adding |

**Docker users** can run the script inside the container or on the host with the correct Python environment:

```bash
docker exec kometa python3 /config/scripts/lastchance.py --env-file /config/.env --dry-run
```

### Logs

The cleanup script writes to `logs/lastchance.log` using the same rotation pattern as Kometa (keeps 9 backups).

```bash
# View the latest cleanup log
cat "$KOMETA_ROOT/config/logs/lastchance.log"

# View systemd journal for the service
journalctl -u lastchance.service --no-pager -n 50
```

---

## File Structure

```
config.yml                          # Main Kometa config (uses <<PLACEHOLDER>> syntax)
.env.example                        # Environment variable template
.env                                # Your secrets (git-ignored, auto-loaded by Kometa)
metadata/
  genres.yml                        # ~30 genre collections for Movies
  lastchance.yml                    # Last Chance collection definition
  movies.yml                        # 8 franchise collections (LOTR, John Wick, etc.)
  networks.yml                      # ~43 network collections for TV Shows
  preroll.yml                       # Seasonal server pre-rolls
  refresh.yml                       # Auto metadata refresh for recent items
  studios.yml                       # ~18 studio/brand collections
  suggestions.yml                   # Trakt charts (Box Office, Trending, etc.)
  suggestions_shows.yml             # Smart filters — not currently referenced in config.yml
  overlays/
    movies/status.yml               # "In Theaters" overlay
    shows/status.yml                # Show status overlays (Airing, Ended, etc.)
scripts/
  lastchance.py                     # Monthly cleanup script
  lastchance.service                # systemd service template
  lastchance.timer                  # systemd timer template
  install-lastchance.sh             # Installer for systemd units
  requirements.txt                  # Python dependencies (plexapi, requests)
assets/
  posters/                          # Collection poster images
  overlays/status/                  # Custom overlay images
  movies/                           # Per-movie asset folders (git-ignored)
  shows/                            # Per-show asset folders (git-ignored)
logs/                               # Log output (git-ignored)
reports/                            # Kometa reports (git-ignored)
```
