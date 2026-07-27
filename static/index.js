document.addEventListener('DOMContentLoaded', () => {
    // 1. Theme Switcher (Dark / Light Mode)
    const btnThemeToggle = document.getElementById('btn-theme-toggle');
    const themeToggleIcon = document.getElementById('theme-toggle-icon');
    let currentTheme = localStorage.getItem('d2l_theme') || 'dark';

    applyTheme(currentTheme);

    if (btnThemeToggle) {
        btnThemeToggle.addEventListener('click', () => {
            currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
            localStorage.setItem('d2l_theme', currentTheme);
            applyTheme(currentTheme);
        });
    }

    function applyTheme(theme) {
        document.documentElement.className = theme;
        if (themeToggleIcon) {
            themeToggleIcon.setAttribute('data-lucide', theme === 'dark' ? 'sun' : 'moon');
        }
        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    // Initialize Lucide Icons
    if (window.lucide) {
        window.lucide.createIcons();
    }

    // DOM References
    const inputUrl = document.getElementById('music-url');
    const btnSearch = document.getElementById('btn-search');
    const searchError = document.getElementById('search-error');
    const searchErrorText = document.getElementById('search-error-text');
    const loader = document.getElementById('loader');

    // Column 1: Album Artwork & Metadata
    const trackArt = document.getElementById('track-art');
    const trackTitle = document.getElementById('track-title');
    const trackArtist = document.getElementById('track-artist');
    const metaAlbum = document.getElementById('meta-album');
    const metaYear = document.getElementById('meta-year');
    const metaGenre = document.getElementById('meta-genre');
    const metaTracks = document.getElementById('meta-tracks');
    const badgeSource = document.getElementById('badge-source');
    const albumTracksContainer = document.getElementById('album-tracks-container');
    const albumTracksCount = document.getElementById('album-tracks-count');
    const albumTracksList = document.getElementById('album-tracks-list');

    // Column 2: Settings Form
    const selectFormat = document.getElementById('download-format');
    const selectCookiesSource = document.getElementById('cookies-source');
    const checkboxCleanAudio = document.getElementById('clean-audio');
    const btnDownload = document.getElementById('btn-download');

    // Column 3: Queue & Step Pipeline
    const queueStatusIndicator = document.getElementById('queue-status-indicator');
    const stepPipeline = document.getElementById('step-pipeline');
    const queueThumb = document.getElementById('queue-thumb');
    const queueSongTitle = document.getElementById('queue-song-title');
    const queueSongArtist = document.getElementById('queue-song-artist');
    const queueProgressFill = document.getElementById('queue-progress-fill');
    const queueItemStatus = document.getElementById('queue-item-status');
    const queueItemTime = document.getElementById('queue-item-time');
    const queueItemCount = document.getElementById('queue-item-count');

    // Activity Terminal
    const terminalContainer = document.getElementById('terminal-container');
    const terminalHeader = document.getElementById('terminal-header');
    const btnToggleTerminal = document.getElementById('btn-toggle-terminal');
    const btnClearTerminal = document.getElementById('btn-clear-terminal');
    const btnCopyTerminal = document.getElementById('btn-copy-terminal');
    const logTerminal = document.getElementById('log-terminal');

    // Nav Modals & Tabs
    const navBtnHistory = document.getElementById('nav-btn-history');
    const navBtnSettings = document.getElementById('nav-btn-settings');
    const historyModal = document.getElementById('history-modal');
    const settingsModal = document.getElementById('settings-modal');
    const btnCloseHistory = document.getElementById('btn-close-history');
    const btnCloseSettings = document.getElementById('btn-close-settings');
    const btnClearHistory = document.getElementById('btn-clear-history');
    const historyList = document.getElementById('history-list');
    const historyCountPill = document.getElementById('history-count');

    // State Variables
    let currentUrl = '';
    let previewData = null;
    let eventSource = null;
    let downloadHistory = JSON.parse(localStorage.getItem('d2l_history') || '[]');

    updateHistoryUI();

    // Search Event Listeners
    btnSearch.addEventListener('click', loadMetadata);
    inputUrl.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            loadMetadata();
        }
    });

    // 2. Fetch Catalog Metadata
    async function loadMetadata() {
        const url = inputUrl.value.trim();
        if (!url) {
            showError("Please enter a valid Spotify, Apple Music, or YouTube link.");
            return;
        }

        hideError();
        loader.classList.remove('hide');
        btnSearch.disabled = true;

        if (eventSource) {
            eventSource.close();
        }

        appendLog('info', `Resolving catalog URL: ${url}`);
        updatePipelineStep('resolve', 'active');

        try {
            const response = await fetch('/api/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || "Failed to retrieve catalog metadata.");
            }

            currentUrl = url;
            previewData = data;
            
            updatePipelineStep('resolve', 'done');
            updatePipelineStep('metadata', 'done');
            renderPreview(data);
            appendLog('start', `Successfully loaded: "${data.title}" by ${data.artist}`);
        } catch (err) {
            showError(err.message);
            updatePipelineStep('resolve', 'idle');
            appendLog('failed', `Error: ${err.message}`);
        } finally {
            loader.classList.add('hide');
            btnSearch.disabled = false;
            if (window.lucide) window.lucide.createIcons();
        }
    }

    // 3. Render Metadata
    function renderPreview(data) {
        trackArt.src = data.artwork || 'https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=600&auto=format&fit=crop&q=80';
        queueThumb.src = data.artwork || trackArt.src;
        
        trackTitle.textContent = data.title || 'Unknown Title';
        trackArtist.textContent = data.artist || 'Unknown Artist';
        queueSongTitle.textContent = data.title || 'Unknown Title';
        queueSongArtist.textContent = data.artist || 'Unknown Artist';

        metaAlbum.textContent = data.album || 'Single Track';
        metaYear.textContent = data.releaseDate || '2026';
        metaGenre.textContent = data.genre || 'Music';
        metaTracks.textContent = `${data.trackCount || 1} ${data.trackCount === 1 ? 'Track' : 'Tracks'}`;

        if (badgeSource) {
            if (currentUrl.includes('spotify.com')) {
                badgeSource.textContent = 'SPOTIFY';
            } else if (currentUrl.includes('youtube.com') || currentUrl.includes('youtu.be')) {
                badgeSource.textContent = 'YOUTUBE';
            } else {
                badgeSource.textContent = 'APPLE MUSIC';
            }
        }

        if (data.type === 'album' && data.tracks && data.tracks.length > 0) {
            albumTracksList.innerHTML = '';
            albumTracksCount.textContent = `${data.tracks.length} tracks`;
            data.tracks.forEach((trackName, idx) => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <span style="font-size:11px; opacity:0.6; width:18px;">${idx + 1}</span>
                    <span>${trackName}</span>
                `;
                albumTracksList.appendChild(li);
            });
            albumTracksContainer.classList.remove('hide');
            queueItemCount.textContent = `${data.tracks.length} Tracks`;
        } else {
            albumTracksContainer.classList.add('hide');
            queueItemCount.textContent = '1 Track';
        }

        queueStatusIndicator.textContent = 'Ready';
        queueStatusIndicator.className = 'status-pill status-ready';
        queueItemStatus.textContent = 'Ready';
        queueItemStatus.className = 'queue-status-tag tag-pending';
    }

    // 4. Download Execution
    btnDownload.addEventListener('click', () => {
        if (!currentUrl || !previewData) {
            if (inputUrl.value.trim()) {
                loadMetadata().then(() => startDownloadProcess());
            } else {
                showError("Please enter a track or album URL first.");
            }
            return;
        }

        startDownloadProcess();
    });

    function startDownloadProcess() {
        const format = selectFormat.value;
        const cookiesSource = selectCookiesSource.value;
        const cleanAudio = checkboxCleanAudio.checked;

        queueStatusIndicator.textContent = 'Downloading';
        queueStatusIndicator.className = 'status-pill status-active';
        queueItemStatus.textContent = 'Downloading';
        queueItemStatus.className = 'queue-status-tag tag-downloading';
        queueProgressFill.style.width = '5%';

        resetPipeline();
        updatePipelineStep('resolve', 'done');
        updatePipelineStep('metadata', 'done');
        updatePipelineStep('audio', 'active');

        appendLog('start', `Starting downloader engine [${format.toUpperCase()}]...`);

        const sseUrl = `/api/download?url=${encodeURIComponent(currentUrl)}&format=${format}&cookies_from=${cookiesSource}&clean_audio=${cleanAudio}`;
        eventSource = new EventSource(sseUrl);

        const startTime = Date.now();
        const timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
            const secs = String(elapsed % 60).padStart(2, '0');
            queueItemTime.textContent = `${mins}:${secs}`;
        }, 1000);

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const status = data.status;
            const message = data.message;

            if (message) {
                appendLog(status, message);
            }

            if (status === 'searching') {
                updatePipelineStep('audio', 'active');
                queueProgressFill.style.width = '20%';
            } else if (status === 'downloading') {
                updatePipelineStep('audio', 'done');
                updatePipelineStep('download', 'active');
                queueProgressFill.style.width = '50%';
            } else if (status === 'converting') {
                updatePipelineStep('download', 'done');
                updatePipelineStep('convert', 'active');
                queueProgressFill.style.width = '75%';
            } else if (status === 'tagging') {
                updatePipelineStep('convert', 'done');
                updatePipelineStep('tagging', 'active');
                queueProgressFill.style.width = '90%';
            } else if (status === 'completed' || status === 'track_completed') {
                updatePipelineStep('tagging', 'done');
                updatePipelineStep('verify', 'done');
                updatePipelineStep('complete', 'done');
                queueProgressFill.style.width = '100%';
            }

            if (status === 'completed') {
                clearInterval(timerInterval);
                queueStatusIndicator.textContent = 'Completed';
                queueStatusIndicator.className = 'status-pill status-done';
                queueItemStatus.textContent = 'Completed';
                queueItemStatus.className = 'queue-status-tag tag-completed';

                appendLog('completed', "Download finished! Output file saved in downloads folder.");
                saveToHistory({
                    title: previewData.title,
                    artist: previewData.artist,
                    artwork: previewData.artwork,
                    format: format.toUpperCase(),
                    date: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                });

                eventSource.close();
            } else if (status === 'failed') {
                clearInterval(timerInterval);
                queueStatusIndicator.textContent = 'Failed';
                queueStatusIndicator.className = 'status-pill status-ready';
                queueItemStatus.textContent = 'Failed';
                queueItemStatus.className = 'queue-status-tag tag-failed';
                appendLog('failed', `Download process error: ${message}`);
                eventSource.close();
            }
        };

        eventSource.onerror = () => {
            clearInterval(timerInterval);
            appendLog('failed', "Connection to local download engine lost.");
            eventSource.close();
        };
    }

    function resetPipeline() {
        const steps = stepPipeline.querySelectorAll('.pipeline-step');
        steps.forEach(step => {
            step.className = 'pipeline-step step-idle';
            const icon = step.querySelector('.step-icon-node i');
            if (icon) {
                const stepKey = step.dataset.step;
                if (stepKey === 'resolve' || stepKey === 'metadata') icon.setAttribute('data-lucide', 'check');
                else if (stepKey === 'audio') icon.setAttribute('data-lucide', 'disc');
                else if (stepKey === 'download') icon.setAttribute('data-lucide', 'arrow-down-circle');
                else if (stepKey === 'convert') icon.setAttribute('data-lucide', 'refresh-cw');
                else if (stepKey === 'tagging') icon.setAttribute('data-lucide', 'tag');
                else if (stepKey === 'verify') icon.setAttribute('data-lucide', 'shield-check');
                else if (stepKey === 'complete') icon.setAttribute('data-lucide', 'check-circle-2');
            }
        });
    }

    function updatePipelineStep(stepKey, state) {
        const step = stepPipeline.querySelector(`[data-step="${stepKey}"]`);
        if (!step) return;

        if (state === 'done') {
            step.className = 'pipeline-step step-done';
            const icon = step.querySelector('.step-icon-node');
            if (icon) icon.innerHTML = '<i data-lucide="check"></i>';
        } else if (state === 'active') {
            step.className = 'pipeline-step step-active';
            const icon = step.querySelector('.step-icon-node');
            if (icon) icon.innerHTML = '<i data-lucide="loader"></i>';
        } else {
            step.className = 'pipeline-step step-idle';
        }

        if (window.lucide) window.lucide.createIcons();
    }

    // Terminal Controls
    terminalHeader.addEventListener('click', (e) => {
        if (e.target.closest('.term-btn') && !e.target.closest('#btn-toggle-terminal')) return;
        terminalContainer.classList.toggle('collapsed');
    });

    btnToggleTerminal.addEventListener('click', (e) => {
        e.stopPropagation();
        terminalContainer.classList.toggle('collapsed');
    });

    btnClearTerminal.addEventListener('click', (e) => {
        e.stopPropagation();
        logTerminal.innerHTML = '<div class="log-line info"><span class="log-time">[SYSTEM]</span> Terminal logs cleared.</div>';
    });

    btnCopyTerminal.addEventListener('click', (e) => {
        e.stopPropagation();
        const text = logTerminal.innerText;
        navigator.clipboard.writeText(text).then(() => {
            appendLog('info', 'Log buffer copied to clipboard.');
        });
    });

    function appendLog(type, text) {
        const line = document.createElement('div');
        line.className = `log-line ${type}`;

        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0];

        line.innerHTML = `<span class="log-time">[${timeStr}]</span> ${text}`;
        logTerminal.appendChild(line);
        logTerminal.scrollTop = logTerminal.scrollHeight;
    }

    // Modals & History
    navBtnHistory.addEventListener('click', () => historyModal.classList.remove('hide'));
    navBtnSettings.addEventListener('click', () => settingsModal.classList.remove('hide'));
    btnCloseHistory.addEventListener('click', () => historyModal.classList.add('hide'));
    btnCloseSettings.addEventListener('click', () => settingsModal.classList.add('hide'));

    btnClearHistory.addEventListener('click', () => {
        downloadHistory = [];
        localStorage.removeItem('d2l_history');
        updateHistoryUI();
    });

    function saveToHistory(item) {
        downloadHistory.unshift(item);
        if (downloadHistory.length > 50) downloadHistory.pop();
        localStorage.setItem('d2l_history', JSON.stringify(downloadHistory));
        updateHistoryUI();
    }

    function updateHistoryUI() {
        if (downloadHistory.length === 0) {
            historyList.innerHTML = '<li class="empty-history">No past downloads recorded yet.</li>';
            historyCountPill.classList.add('hide');
        } else {
            historyCountPill.textContent = downloadHistory.length;
            historyCountPill.classList.remove('hide');
            historyList.innerHTML = '';
            downloadHistory.forEach(item => {
                const li = document.createElement('li');
                li.className = 'history-item';
                li.innerHTML = `
                    <div>
                        <strong>${item.title}</strong>
                        <p style="font-size:12px; color:var(--text-muted);">${item.artist} &bull; ${item.format}</p>
                    </div>
                    <span style="font-size:12px; color:var(--text-secondary);">${item.date}</span>
                `;
                historyList.appendChild(li);
            });
        }
    }

    function showError(msg) {
        searchErrorText.textContent = msg;
        searchError.classList.remove('hide');
    }

    function hideError() {
        searchError.classList.add('hide');
        searchErrorText.textContent = '';
    }
});
