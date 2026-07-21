document.addEventListener('DOMContentLoaded', () => {
    const inputUrl = document.getElementById('music-url');
    const btnSearch = document.getElementById('btn-search');
    const searchError = document.getElementById('search-error');
    const loader = document.getElementById('loader');
    
    const previewSection = document.getElementById('preview-section');
    const badgeType = document.getElementById('badge-type');
    const trackArt = document.getElementById('track-art');
    const trackTitle = document.getElementById('track-title');
    const trackArtist = document.getElementById('track-artist');
    const metaAlbum = document.getElementById('meta-album');
    const metaYear = document.getElementById('meta-year');
    const metaGenre = document.getElementById('meta-genre');
    const metaTracks = document.getElementById('meta-tracks');
    
    const selectFormat = document.getElementById('download-format');
    const selectCookiesSource = document.getElementById('cookies-source');
    const checkboxCleanAudio = document.getElementById('clean-audio');
    const btnDownload = document.getElementById('btn-download');
    
    const albumTracksContainer = document.getElementById('album-tracks-container');
    const albumTracksList = document.getElementById('album-tracks-list');
    
    const consoleSection = document.getElementById('console-section');
    const downloadStatus = document.getElementById('download-status');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressText = document.getElementById('progress-text');
    const progressPercent = document.getElementById('progress-percent');
    const logTerminal = document.getElementById('log-terminal');

    let currentUrl = '';
    let previewData = null;
    let eventSource = null;

    // Trigger search on click
    btnSearch.addEventListener('click', loadMetadata);
    
    // Trigger search on enter key
    inputUrl.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            loadMetadata();
        }
    });

    async function loadMetadata() {
        const url = inputUrl.value.trim();
        if (!url) {
            showError("Please enter a valid Apple Music link.");
            return;
        }

        // Reset state
        hideError();
        previewSection.classList.add('hide');
        consoleSection.classList.add('hide');
        if (eventSource) {
            eventSource.close();
        }
        
        loader.classList.remove('hide');
        btnSearch.disabled = true;

        try {
            const response = await fetch('/api/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });

            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || "Failed to retrieve metadata.");
            }

            currentUrl = url;
            previewData = data;
            renderPreview(data);
        } catch (err) {
            showError(err.message);
        } finally {
            loader.classList.add('hide');
            btnSearch.disabled = false;
        }
    }

    function renderPreview(data) {
        // Set basic metadata fields
        trackArt.src = data.artwork || 'https://via.placeholder.com/600';
        trackTitle.textContent = data.title || 'Unknown Title';
        trackArtist.textContent = data.artist || 'Unknown Artist';
        metaAlbum.textContent = data.album || 'Unknown Album';
        metaYear.textContent = data.releaseDate || 'N/A';
        metaGenre.textContent = data.genre || 'N/A';
        metaTracks.textContent = data.trackCount || '1';

        // Badge styling
        badgeType.textContent = data.type;
        badgeType.className = `badge ${data.type}`;

        // Populate tracklist if album
        if (data.type === 'album' && data.tracks && data.tracks.length > 0) {
            albumTracksList.innerHTML = '';
            data.tracks.forEach((track, index) => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <span class="track-num">${index + 1}</span>
                    <span class="track-name">${track}</span>
                `;
                albumTracksList.appendChild(li);
            });
            albumTracksContainer.classList.remove('hide');
        } else {
            albumTracksContainer.classList.add('hide');
        }

        previewSection.classList.remove('hide');
        previewSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // Start download process using SSE (Server-Sent Events)
    btnDownload.addEventListener('click', () => {
        if (!currentUrl || !previewData) return;

        const format = selectFormat.value;
        const cookiesSource = selectCookiesSource ? selectCookiesSource.value : 'none';
        const cleanAudio = checkboxCleanAudio ? checkboxCleanAudio.checked : true;
        
        // Hide preview card, reveal console card
        previewSection.classList.add('hide');
        consoleSection.classList.remove('hide');
        consoleSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        // Reset console state
        downloadStatus.textContent = 'Processing';
        downloadStatus.className = 'status-indicator processing';
        progressBarFill.style.width = '0%';
        progressPercent.textContent = '0%';
        progressText.textContent = 'Connecting to server...';
        logTerminal.innerHTML = '';

        appendLog('info', 'Establishing connection to download server...');

        const sseUrl = `/api/download?url=${encodeURIComponent(currentUrl)}&format=${format}&cookies_from=${cookiesSource}&clean_audio=${cleanAudio}`;
        eventSource = new EventSource(sseUrl);

        let totalTracks = previewData.trackCount || 1;
        let currentTrackIdx = 0;

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const status = data.status;
            const message = data.message;

            // Log messages to terminal
            if (message) {
                appendLog(status, message);
                if (message.includes("Could not copy") && message.includes("cookie database")) {
                    appendLog('warning', "💡 TIP: Your selected browser is currently running, which locks its cookie database file on Windows. Please CLOSE your browser completely and click 'Start Downloader' again, or select a different browser.");
                }
            }

            // Update Progress Bar
            if (previewData.type === 'song') {
                // Single Song Progress Interpolation
                let pct = 0;
                if (status === 'searching') pct = 15;
                else if (status === 'downloading') pct = 45;
                else if (status === 'converting') pct = 75;
                else if (status === 'tagging') pct = 90;
                else if (status === 'completed') pct = 100;
                
                updateProgressBar(pct, message || "Processing song...");
            } else {
                // Album Progress Interpolation
                if (status === 'start') {
                    totalTracks = data.total_tracks || totalTracks;
                    updateProgressBar(0, `Starting download of ${totalTracks} tracks...`);
                } else if (status === 'track_start') {
                    currentTrackIdx = data.index;
                    const basePct = Math.round(((currentTrackIdx - 1) / totalTracks) * 100);
                    updateProgressBar(basePct, `Processing Track ${currentTrackIdx} of ${totalTracks}: "${data.title}"`);
                } else if (status === 'searching') {
                    const pct = Math.round(((currentTrackIdx - 1 + 0.15) / totalTracks) * 100);
                    updateProgressBar(pct, `Searching YouTube for Track ${currentTrackIdx}...`);
                } else if (status === 'downloading') {
                    const pct = Math.round(((currentTrackIdx - 1 + 0.45) / totalTracks) * 100);
                    updateProgressBar(pct, `Downloading audio for Track ${currentTrackIdx}...`);
                } else if (status === 'converting') {
                    const pct = Math.round(((currentTrackIdx - 1 + 0.75) / totalTracks) * 100);
                    updateProgressBar(pct, `Encoding formats for Track ${currentTrackIdx}...`);
                } else if (status === 'tagging') {
                    const pct = Math.round(((currentTrackIdx - 1 + 0.90) / totalTracks) * 100);
                    updateProgressBar(pct, `Embedding tags & artwork for Track ${currentTrackIdx}...`);
                } else if (status === 'track_completed') {
                    const basePct = Math.round((currentTrackIdx / totalTracks) * 100);
                    updateProgressBar(basePct, `Track ${currentTrackIdx} of ${totalTracks} completed.`);
                }
            }

            // Finish States
            if (status === 'completed') {
                updateProgressBar(100, "Download completed successfully!");
                downloadStatus.textContent = 'Completed';
                downloadStatus.className = 'status-indicator completed';
                appendLog('completed', "SUCCESS: All files downloaded and tags embedded! You can find them in the project's 'downloads' folder.");
                eventSource.close();
            } else if (status === 'failed') {
                downloadStatus.textContent = 'Failed';
                downloadStatus.className = 'status-indicator failed';
                appendLog('failed', `FATAL ERROR: ${message}`);
                eventSource.close();
            }
        };

        eventSource.onerror = (err) => {
            console.error("SSE connection error:", err);
            downloadStatus.textContent = 'Failed';
            downloadStatus.className = 'status-indicator failed';
            appendLog('failed', "Connection to server was lost or timed out.");
            eventSource.close();
        };
    });

    function updateProgressBar(percentage, text) {
        progressBarFill.style.width = `${percentage}%`;
        progressPercent.textContent = `${percentage}%`;
        progressText.textContent = text;
    }

    function appendLog(type, text) {
        const line = document.createElement('div');
        line.className = `log-line ${type}`;
        
        // Add timestamp prefix
        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0];
        
        line.innerHTML = `<span style="color: var(--text-muted)">[${timeStr}]</span> ${text}`;
        logTerminal.appendChild(line);
        logTerminal.scrollTop = logTerminal.scrollHeight;
    }

    function showError(msg) {
        searchError.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${msg}`;
        searchError.classList.remove('hide');
    }

    function hideError() {
        searchError.classList.add('hide');
        searchError.textContent = '';
    }
});
