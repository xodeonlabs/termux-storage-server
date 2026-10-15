# Termux Storage Server

A lightweight, private file storage server that runs directly on an Android phone with [Termux](https://termux.dev/). It uses only Python's standard library: no pip packages, database, Docker, or cloud account is required.

## Features

- Responsive web UI for phones and desktop browsers
- Upload multiple files by selecting or drag-and-drop
- Download and delete files
- Access token authentication
- Safe path handling to prevent directory traversal
- Collision-safe filenames (existing files are not overwritten)
- Stores files locally in `storage/`
- Configurable port and storage directory

> **Security note:** this server is intended for a trusted local Wi-Fi network. It uses HTTP, not HTTPS. Do not port-forward it to the public internet. Keep your access token private.

## Install from GitHub on Termux

### 1. Install Termux

Install Termux from [F-Droid](https://f-droid.org/packages/com.termux/) or the official Termux GitHub releases. Avoid mixing Termux and its add-ons from different sources.

Open Termux and run:

```bash
pkg update -y
pkg upgrade -y
pkg install -y git python
```

Optional, if you want the phone to keep the server alive while the screen is off:

```bash
termux-wake-lock
```

### 2. Clone this GitHub repository

Replace `YOUR_GITHUB_USERNAME/YOUR_REPOSITORY` with the repository URL provided after publishing:

```bash
cd ~
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY.git storage-server
cd storage-server
```

### 3. Start the server

```bash
python server.py
```

The terminal prints a token similar to:

```text
Listening on: http://0.0.0.0:8080
Access token: YOUR_SECRET_TOKEN
```

Keep this terminal open. Press `Ctrl+C` to stop the server.

### 4. Open the web UI

- On the phone itself: open `http://127.0.0.1:8080` in a browser.
- From another device on the same Wi-Fi: find the phone's local IP and open `http://PHONE_IP:8080`.

In Termux, you can usually find the Wi-Fi IP with:

```bash
ip addr show wlan0
```

Look for an address such as `192.168.1.42`. Then open `http://192.168.1.42:8080` on the other device and enter the access token.

## Useful commands

Use a different port:

```bash
python server.py --port 9090
```

Use a different storage folder:

```bash
python server.py --storage ~/storage/shared/MyStorage
```

Set a permanent token for your own private setup:

```bash
export STORAGE_TOKEN='replace-with-a-long-random-secret'
python server.py
```

Generate a strong token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

To let Termux access shared Android storage first:

```bash
termux-setup-storage
```

## Updating from GitHub

Stop the server with `Ctrl+C`, then:

```bash
cd ~/storage-server
git pull
python server.py
```

Your files remain in the `storage/` folder and are not removed by `git pull`.

## Uploading this project to your own GitHub

The project owner can publish it with GitHub CLI:

```bash
cd ~/termux-storage-server
git init
git add server.py web/index.html README.md .gitignore
git commit -m "Initial Termux storage server"
gh repo create termux-storage-server --private --source=. --remote=origin --push
```

The command creates a **private** repository by default. To intentionally make it public, replace `--private` with `--public`.

If Git asks for your identity, configure it once:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## Troubleshooting

- **Port already in use:** start with another port, for example `python server.py --port 8081`.
- **Cannot connect from another device:** make sure both devices are on the same Wi-Fi, use the phone's Wi-Fi IP (not `127.0.0.1`), and keep Termux open.
- **Android stops the server:** disable battery optimization for Termux and run `termux-wake-lock`.
- **Token lost:** stop and restart the server; a new token is printed unless `STORAGE_TOKEN` was set.

## License

MIT
