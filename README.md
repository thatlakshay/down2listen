# down2listen

A premium, easy-to-use application featuring both a modern **Web Interface** and a **Command Line Interface (CLI)** to search, download, convert, and tag audio tracks and albums from Apple Music.

It extracts metadata from Apple Music, searches for the best matching audio stream on YouTube Music, converts it to high-quality audio, embeds metadata (including official high-resolution album art), and stores them cleanly.

---

## 🌟 Key Features

- **One-Click Run**: Batch startup scripts manage environment setup, dependencies, and automatically open the application in your browser.
- **High-Res Artwork**: Automatically scales and embeds official iTunes artwork up to 1000x1000 pixels into the downloaded audio files.
- **Full Tagging**: Writes comprehensive metadata tags (Title, Artist, Album, Year, Genre, Track Number, Disc Number) in ID3v2.3 (for MP3) and Vorbis Comments (for FLAC).
- **Flexible Formats**: Download as high-bitrate **MP3 (320kbps)**, **FLAC (Lossless container)**, or **both** at the same time.
- **Album Batch Downloading**: Paste any Apple Music album link to download and tag every track automatically in sequence.
- **Glassmorphism Web UI**: A beautiful, fluid interface featuring a live progress console so you can see the downloader's activities in real-time.
- **Command Line Tool**: Includes a fully-featured CLI for scripting or headless environment usage.

---

## ⚡ One-Click Startup (Recommended)

### 🪟 Windows
1. **Double-click `run.bat`** in the project directory.
2. The script will automatically:
   - Verify Python is installed.
   - Create a Python virtual environment (`.venv`) if it doesn't exist.
   - Install/update all required dependencies from `requirements.txt`.
   - Start the local Flask web server.
   - Open the web interface in your default browser at [http://127.0.0.1:5000](http://127.0.0.1:5000).
3. To stop the server, simply close the command window or press `Ctrl+C` in it.

### 🍎 macOS & 🐧 Linux
1. Open a terminal in the project directory.
2. Run the script using:
   ```bash
   chmod +x run.sh
   ./run.sh
   ```
3. The script will perform the same automated environment setup and launch the web interface in your browser.

---

## 🍪 Bypassing YouTube "Please sign in" blocks

YouTube frequently restricts anonymous downloads, resulting in a `Please sign in` error. To bypass this easily:

1. **In the Web UI**:
   - In the settings section under **Use Browser Cookies**, select your active browser (e.g., `Google Chrome`, `Microsoft Edge`, `Brave Browser`, etc.).
   - Make sure you are logged into YouTube in that browser.
   - Click **Start Downloader**. The app will extract your YouTube session cookies securely and use them to complete the download.
2. **Close Browser (if needed)**:
   - If you encounter a database lock error, close your browser window temporarily while downloading.

---

## 🖥️ CLI Usage

If you prefer using a terminal interface instead of the web browser, you can run the command-line utility directly using the virtual environment:

### Windows CLI Setup
```cmd
.venv\Scripts\activate
python cli.py --url "<Apple-Music-URL>" --format both --output-dir "downloads"
```

### macOS/Linux CLI Setup
```bash
source .venv/bin/activate
python cli.py --url "<Apple-Music-URL>" --format both --output-dir "downloads"
```

### Options
- `--url`: (Required) The Apple Music track or album link.
- `--format`: (Optional) Choose from `mp3`, `flac`, or `both` (default is `both`).
- `--output-dir`: (Optional) Base directory for saving downloads (default is `downloads`).
- `--cookies-from`: (Optional) Browser name to extract YouTube cookies from (e.g., `chrome`, `edge`, `brave`, `firefox`, `safari`, `opera`, `vivaldi`).

---

## 🛠️ Tech Stack & Dependencies

The project is built on standard, lightweight Python and frontend libraries:
- **Flask**: Serves the local web application.
- **yt-dlp**: Extracts matching streams from YouTube Music.
- **static-ffmpeg**: Dynamically manages and binds standalone FFmpeg binaries so you don't have to manually install or configure FFmpeg on your computer.
- **mutagen**: Tagging library utilized to write audio metadata and artwork.
- **requests**: Interfaces with iTunes Search/Lookup API to get high-fidelity metadata.
- **Modern Web UI**: Built using Vanilla HTML/CSS with premium Google Fonts (Outfit) and FontAwesome icon resources.

---

## 📂 Downloads Directory

Downloads are placed in the `downloads/` directory inside the project root:
- **Tracks**: Saved as `<Title> - <Artist>.<format>` inside the root downloads directory.
- **Albums**: Automatically grouped into a subfolder named `<Artist> - <Album>` and files are indexed as `<TrackNumber> - <Title>.<format>`.

---

## ⚠️ Disclaimer
This utility is for educational, personal backup, and archival purposes only. Please support artists by streaming their music on official platforms.
