/**
 * Get Alpine.js reactive data for a DOM element.
 * Works with Alpine v3 ($data API) and falls back to v2 (__x) for test environments.
 */
function _alpineData(el) {
    if (typeof Alpine !== 'undefined' && Alpine.$data) return Alpine.$data(el);
    if (el.__x) return el.__x.$data;
    return {};
}

/**
 * Timeline scrubber controller for time-travel filtering.
 */
class TimelineScrubber {
    constructor() {
        this.container = document.getElementById('timelineScrubber');
        this.slider = document.getElementById('timelineSlider');
        this.yearLabel = document.getElementById('timelineYearLabel');
        this.playBtn = document.getElementById('timelinePlayBtn');
        this.playIcon = document.getElementById('timelinePlayIcon');
        this.speedToggle = document.getElementById('timelineSpeedToggle');
        this.speedLabel = document.getElementById('timelineSpeedLabel');
        this.resetBtn = document.getElementById('timelineResetBtn');

        this.playing = false;
        this.playInterval = null;
        this.speed = 'year'; // 'year' = 1yr/sec, 'decade' = 1decade/500ms
        this.minYear = 1900;
        this.maxYear = 2025;
        this.currentYear = null;

        // Debounce timer for manual slider drag
        this._debounceTimer = null;

        // Genre emergence state: cached responses and previous genre set
        this._emergenceCache = new Map();
        this._previousGenres = new Set();

        // Compare mode state
        this.comparing = false;
        this._savedBeforeYear = null;
        this.compareYearA = null;
        this.compareYearB = null;

        // Compare mode DOM references
        this.exploreControls = document.getElementById('timelineExploreControls');
        this.compareControls = document.getElementById('timelineCompareControls');
        this.compareBtn = document.getElementById('timelineCompareBtn');
        this.exitCompareBtn = document.getElementById('timelineExitCompareBtn');
        this.sliderA = document.getElementById('compareSliderA');
        this.sliderB = document.getElementById('compareSliderB');
        this.yearALabel = document.getElementById('compareYearALabel');
        this.yearBLabel = document.getElementById('compareYearBLabel');
        this.compareLegend = document.getElementById('compareLegend');
        this.legendCloseBtn = document.getElementById('compareLegendClose');
        this.sameYearHint = document.getElementById('compareSameYearHint');

        // Callback: called with (year) when year changes
        this.onYearChange = null;
        // Callback: called with (newGenres) for emergence highlighting
        this.onGenreEmergence = null;
        // Callback: called with (yearA, yearB) when comparison years change
        this.onCompareChange = null;
        // Callback: called with no args when comparison mode exits
        this.onCompareExit = null;

        // Debounce timer for compare slider drags
        this._compareDebounceTimer = null;

        this._bindEvents();
    }

    _bindEvents() {
        this.slider.addEventListener('input', () => {
            // Dragging during play pauses playback
            if (this.playing) this.pause();
            this._onSliderInput();
        });

        this.playBtn.addEventListener('click', () => {
            if (this.playing) this.pause();
            else this.play();
        });

        this.speedToggle.addEventListener('click', () => {
            this.speed = this.speed === 'year' ? 'decade' : 'year';
            this.speedLabel.textContent = this.speed === 'year' ? '1yr/s' : '10yr/s';
            // Restart playback with the new interval if currently playing
            if (this.playing) {
                this.pause();
                this.play();
            }
        });

        this.resetBtn.addEventListener('click', () => {
            this.pause();
            this.slider.value = this.maxYear;
            this.currentYear = null;
            this.yearLabel.textContent = 'All';
            this._previousGenres.clear();
            if (this.onYearChange) this.onYearChange(null);
        });

        this.compareBtn.addEventListener('click', () => this.enterCompare());
        this.exitCompareBtn.addEventListener('click', () => this.exitCompare());

        this.sliderA.addEventListener('input', () => this._onCompareSliderInput());
        this.sliderB.addEventListener('input', () => this._onCompareSliderInput());

        this.legendCloseBtn.addEventListener('click', () => {
            this.compareLegend.classList.add('hidden');
        });

        // Close button hides the timeline panel
        document.getElementById('timelineCloseBtn')?.addEventListener('click', () => this.toggle());
    }

    async init() {
        const range = await window.apiClient.getYearRange();
        if (!range || range.min_year === null) return;
        this.minYear = range.min_year;
        this.maxYear = range.max_year;
        this.slider.min = this.minYear;
        this.slider.max = this.maxYear;
        this.slider.value = this.maxYear;
        this.sliderA.min = this.minYear;
        this.sliderA.max = this.maxYear;
        this.sliderB.min = this.minYear;
        this.sliderB.max = this.maxYear;
        this.yearLabel.textContent = 'All';
        this.currentYear = null;
        this._previousGenres.clear();
        this._emergenceCache.clear();
        this._ready = true;
        // Show the toggle button but don't auto-show the timeline
        document.getElementById('timelineToggleBtn')?.classList.remove('hidden');
    }

    toggle() {
        if (!this._ready) return;
        if (this.container.classList.contains('hidden')) {
            this.container.classList.remove('hidden');
        } else {
            this.pause();
            this.container.classList.add('hidden');
        }
    }

    hide() {
        if (this.comparing) this.exitCompare();
        this.pause();
        this.container.classList.add('hidden');
    }

    _onSliderInput() {
        const year = parseInt(this.slider.value, 10);
        this.currentYear = year;
        this.yearLabel.textContent = String(year);

        // Debounced fetch
        clearTimeout(this._debounceTimer);
        this._debounceTimer = setTimeout(() => {
            this._emitYearChange(year);
        }, 300);
    }

    play() {
        if (this.currentYear === null) {
            this.currentYear = this.minYear;
            this.slider.value = this.minYear;
        }
        this.playing = true;
        this.playIcon.className = 'material-symbols-outlined'; this.playIcon.textContent = 'pause';

        const tick = () => {
            const step = this.speed === 'year' ? 1 : 10;
            let next = this.currentYear + step;
            if (next > this.maxYear) {
                next = this.maxYear;
                this.pause();
            }
            this.currentYear = next;
            this.slider.value = next;
            this.yearLabel.textContent = String(next);
            this._emitYearChange(next);
        };

        const interval = this.speed === 'year' ? 1000 : 500;
        this.playInterval = setInterval(tick, interval);
    }

    pause() {
        this.playing = false;
        this.playIcon.className = 'material-symbols-outlined'; this.playIcon.textContent = 'play_arrow';
        if (this.playInterval) {
            clearInterval(this.playInterval);
            this.playInterval = null;
        }
    }

    async _emitYearChange(year) {
        if (this.onYearChange) this.onYearChange(year);

        // Check genre emergence
        await this._checkEmergence(year);
    }

    async _checkEmergence(year) {
        // When scrubbing backward, reset genre tracking to avoid
        // re-highlighting known genres when scrubbing forward again
        if (this._lastEmergenceYear !== undefined && year < this._lastEmergenceYear) {
            this._previousGenres = new Set();
            this._lastEmergenceYear = year;
            return;
        }
        this._lastEmergenceYear = year;

        let data = this._emergenceCache.get(year);
        if (!data) {
            data = await window.apiClient.getGenreEmergence(year);
            if (!data) return;
            this._emergenceCache.set(year, data);
        }

        const currentGenres = new Set([
            ...data.genres.map(g => g.name),
            ...data.styles.map(s => s.name),
        ]);

        const newGenres = [];
        for (const name of currentGenres) {
            if (!this._previousGenres.has(name)) {
                newGenres.push(name);
            }
        }

        // Limit highlights on large jumps
        const highlighted = newGenres.slice(-5);

        if (highlighted.length > 0 && this.onGenreEmergence) {
            this.onGenreEmergence(highlighted);
        }

        this._previousGenres = currentGenres;
    }

    enterCompare() {
        if (this.comparing) return;
        this.pause();
        this.comparing = true;

        // Save current single-slider state
        this._savedBeforeYear = this.currentYear;

        // Initialize compare sliders to sensible defaults
        const midYear = Math.floor((this.minYear + this.maxYear) / 2);
        this.compareYearA = this.currentYear ? Math.max(this.minYear, this.currentYear - 10) : midYear - 10;
        this.compareYearB = this.currentYear || midYear + 10;

        // Clamp to bounds
        this.compareYearA = Math.max(this.minYear, Math.min(this.maxYear, this.compareYearA));
        this.compareYearB = Math.max(this.minYear, Math.min(this.maxYear, this.compareYearB));

        this.sliderA.min = this.minYear;
        this.sliderA.max = this.maxYear;
        this.sliderA.value = this.compareYearA;
        this.sliderB.min = this.minYear;
        this.sliderB.max = this.maxYear;
        this.sliderB.value = this.compareYearB;
        this.yearALabel.textContent = String(this.compareYearA);
        this.yearBLabel.textContent = String(this.compareYearB);

        // Disable explore-only controls
        this.playBtn.disabled = true;
        this.playBtn.style.opacity = '0.4';
        this.speedToggle.style.opacity = '0.4';
        this.speedToggle.style.pointerEvents = 'none';

        // Toggle UI
        this.exploreControls.classList.add('hidden');
        this.compareControls.classList.remove('hidden');
        this.compareBtn.classList.add('active');
        this.compareLegend.classList.remove('hidden');
        this.sameYearHint.classList.add('hidden');

        this._emitCompareChange();
    }

    exitCompare() {
        if (!this.comparing) return;
        this.comparing = false;

        // Re-enable explore controls
        this.playBtn.disabled = false;
        this.playBtn.style.opacity = '';
        this.speedToggle.style.opacity = '';
        this.speedToggle.style.pointerEvents = '';

        // Toggle UI back
        this.compareControls.classList.add('hidden');
        this.exploreControls.classList.remove('hidden');
        this.compareBtn.classList.remove('active');
        this.compareLegend.classList.add('hidden');
        this.sameYearHint.classList.add('hidden');

        clearTimeout(this._compareDebounceTimer);

        // Restore previous single-slider state
        if (this._savedBeforeYear !== null) {
            this.currentYear = this._savedBeforeYear;
            this.slider.value = this._savedBeforeYear;
            this.yearLabel.textContent = String(this._savedBeforeYear);
        } else {
            this.currentYear = null;
            this.slider.value = this.maxYear;
            this.yearLabel.textContent = 'All';
        }
        this._savedBeforeYear = null;

        if (this.onCompareExit) this.onCompareExit();
    }

    _onCompareSliderInput() {
        this.compareYearA = parseInt(this.sliderA.value, 10);
        this.compareYearB = parseInt(this.sliderB.value, 10);
        this.yearALabel.textContent = String(this.compareYearA);
        this.yearBLabel.textContent = String(this.compareYearB);

        clearTimeout(this._compareDebounceTimer);
        this._compareDebounceTimer = setTimeout(() => {
            this._emitCompareChange();
        }, 300);
    }

    _emitCompareChange() {
        // Normalize: yearA = min, yearB = max
        const a = Math.min(this.compareYearA, this.compareYearB);
        const b = Math.max(this.compareYearA, this.compareYearB);

        if (a === b) {
            this.sameYearHint.classList.remove('hidden');
            this.compareLegend.classList.add('hidden');
        } else {
            this.sameYearHint.classList.add('hidden');
            this.compareLegend.classList.remove('hidden');
        }

        if (this.onCompareChange) this.onCompareChange(a, b);
    }
}

/**
 * Main application controller.
 * Coordinates pane switching, search, graph, trends, auth, and user panes.
 */
class ExploreApp {
    constructor() {
        this.searchType = 'artist';
        this.currentQuery = '';
        this.activePane = 'explore';

        // Trends comparison state
        this.compareMode = false;
        this.primaryTrendsData = null;

        // Request counter for preventing stale node-click responses
        this._nodeClickRequestId = 0;

        // Initialize components
        this.autocomplete = new Autocomplete();
        this.graph = new GraphVisualization('graphContainer');
        this.trends = new TrendsChart('trendsChart');
        this.userPanes = new window.UserPanes();
        window.userPanes = this.userPanes;
        this.timeline = new TimelineScrubber();
        this.timeline.onYearChange = (year) => this._onTimelineYearChange(year);
        this.timeline.onGenreEmergence = (newGenres) => this._onGenreEmergence(newGenres);
        this.timeline.onCompareChange = (yearA, yearB) => this._onCompareChange(yearA, yearB);
        this.timeline.onCompareExit = () => this._onCompareExit();

        // Wire up callbacks
        this.autocomplete.onSelect = (name) => this._onSearch(name);
        this.graph.onNodeClick = (nodeId, type) => this._onNodeClick(nodeId, type);
        this.graph.onNodeExpand = (name, type) => this._onNodeExpand(name, type);

        // Auth state changes → update UI
        window.authManager.onChange(() => this._updateAuthUI());

        this._bindEvents();
        this._initAuth().then(() => this._restoreFromUrl());
    }

    // ------------------------------------------------------------------ //
    // Auth initialisation
    // ------------------------------------------------------------------ //

    async _initAuth() {
        const valid = await window.authManager.init();
        this._updateAuthUI();
        return valid;
    }

    _updateAuthUI() {
        const loggedIn = window.authManager.isLoggedIn();
        const user = window.authManager.getUser();
        const discogsStatus = window.authManager.getDiscogsStatus();

        // Toggle auth buttons vs user dropdown
        document.getElementById('authButtons').classList.toggle('hidden', loggedIn);
        document.getElementById('userDropdown').classList.toggle('hidden', !loggedIn);

        // Toggle secondary nav bar (collection, wantlist, discover, gaps)
        document.getElementById('navSecondary')?.classList.toggle('hidden', !loggedIn);
        // Hide gaps nav when logged out (shown dynamically by gap analysis)
        if (!loggedIn) {
            document.getElementById('navGaps')?.classList.add('hidden');
        }

        if (loggedIn && user) {
            const emailEl = document.getElementById('userEmailDisplay');
            if (emailEl) emailEl.textContent = user.email || '';
        }

        // Discogs status display
        const statusDisplay = document.getElementById('discogsStatusDisplay');
        const connectBtn = document.getElementById('connectDiscogsBtn');
        const disconnectBtn = document.getElementById('disconnectDiscogsBtn');
        const syncBtn = document.getElementById('syncBtn');

        if (loggedIn && discogsStatus?.connected) {
            if (statusDisplay) {
                const badge = document.createElement('span');
                badge.className = 'badge bg-accent-green text-white discogs-badge';
                const icon = document.createElement('i');
                icon.className = 'material-symbols-outlined mr-1'; icon.textContent = 'check'; icon.style.fontSize = '18px';
                badge.append(icon, discogsStatus.discogs_username || 'Connected');
                statusDisplay.replaceChildren(badge);
            }
            connectBtn?.classList.add('hidden');
            disconnectBtn?.classList.remove('hidden');
            syncBtn?.classList.remove('hidden');
        } else if (loggedIn) {
            if (statusDisplay) {
                const badge = document.createElement('span');
                badge.className = 'badge bg-gray-600 text-text-mid discogs-badge';
                badge.textContent = 'Not connected';
                statusDisplay.replaceChildren(badge);
            }
            connectBtn?.classList.remove('hidden');
            disconnectBtn?.classList.add('hidden');
            syncBtn?.classList.add('hidden');
        } else {
            if (statusDisplay) {
                const badge = document.createElement('span');
                badge.className = 'badge bg-gray-600 text-text-mid discogs-badge';
                badge.textContent = 'Not connected';
                statusDisplay.replaceChildren(badge);
            }
            connectBtn?.classList.add('hidden');
            disconnectBtn?.classList.add('hidden');
            syncBtn?.classList.add('hidden');
        }

        // If we just logged out and were on a personal pane, switch to explore
        if (!loggedIn && ['collection', 'wantlist', 'recommendations'].includes(this.activePane)) {
            this._switchPane('explore');
        }
    }

    // ------------------------------------------------------------------ //
    // Event binding
    // ------------------------------------------------------------------ //

    _bindEvents() {
        // Pane switching
        document.querySelectorAll('[data-pane]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this._switchPane(link.dataset.pane);
            });
        });

        // Search type dropdown
        document.querySelectorAll('[data-type]').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                this._setSearchType(item.dataset.type);
            });
        });

        // Close info panel
        document.getElementById('closePanelBtn').addEventListener('click', () => {
            document.getElementById('infoPanel').classList.remove('open');
        });

        // Trends comparison controls
        document.getElementById('compareBtn').addEventListener('click', () => this._enableCompareMode());
        document.getElementById('clearCompareBtn').addEventListener('click', () => this._clearComparison());

        // Share button
        document.getElementById('shareBtn').addEventListener('click', () => this._shareSnapshot());

        // Timeline toggle
        document.getElementById('timelineToggleBtn')?.addEventListener('click', () => this.timeline.toggle());

        // Login form
        document.getElementById('loginSubmitBtn')?.addEventListener('click', () => this._handleLogin());
        document.getElementById('loginPassword')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this._handleLogin();
        });

        // Register form
        document.getElementById('registerSubmitBtn')?.addEventListener('click', () => this._handleRegister());
        document.getElementById('registerPassword')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this._handleRegister();
        });

        // Logout
        document.getElementById('logoutBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this._handleLogout();
        });

        // Discogs OAuth
        document.getElementById('connectDiscogsBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.userPanes.startDiscogsOAuth();
        });
        document.getElementById('disconnectDiscogsBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.userPanes.disconnectDiscogs();
        });
        document.getElementById('discogsVerifierSubmit')?.addEventListener('click', () => {
            this.userPanes.submitDiscogsVerifier();
        });
        document.getElementById('discogsVerifierInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.userPanes.submitDiscogsVerifier();
        });

        // Sync
        document.getElementById('syncBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.userPanes.triggerSync();
        });

        // Collection / wantlist / recommendations refresh (delegated — buttons are rendered dynamically)
        document.getElementById('collectionPane')?.addEventListener('click', (e) => {
            if (e.target.closest('#collectionRefreshBtn')) {
                this.userPanes.loadCollection(true);
                this.userPanes.loadCollectionStats();
            }
        });
        document.getElementById('wantlistPane')?.addEventListener('click', (e) => {
            if (e.target.closest('#wantlistRefreshBtn')) {
                this.userPanes.loadWantlist(true);
            }
        });
        document.getElementById('recommendationsRefreshBtn')?.addEventListener('click', () => {
            this.userPanes.loadRecommendations();
        });

        // Insights genre chip clicks
        document.getElementById('insightsGenreChips')?.addEventListener('click', (e) => {
            const chip = e.target.closest('.insights-genre-chip');
            if (chip && chip.dataset.genre) {
                window.insightsPanel._loadGenreTrends(chip.dataset.genre);
            }
        });

        // Login button opens modal and clears errors
        document.getElementById('navLoginBtn')?.addEventListener('click', () => {
            if (window.Alpine) Alpine.store('modals').authOpen = true;
            document.getElementById('loginError').textContent = '';
            document.getElementById('registerError').textContent = '';
            document.getElementById('registerSuccess')?.classList.add('hidden');
        });

        // Password reset flow
        document.getElementById('forgotPasswordLink')?.addEventListener('click', (e) => {
            e.preventDefault();
            const modal = document.getElementById('authModal');
            _alpineData(modal).tab = 'reset-request';
        });

        document.getElementById('backToLoginFromReset')?.addEventListener('click', (e) => {
            e.preventDefault();
            const modal = document.getElementById('authModal');
            _alpineData(modal).tab = 'login';
        });

        document.getElementById('resetRequestBtn')?.addEventListener('click', async () => {
            const email = document.getElementById('resetEmail').value.trim();
            const errorEl = document.getElementById('resetRequestError');
            const successEl = document.getElementById('resetRequestSuccess');
            errorEl.textContent = '';
            successEl.classList.add('hidden');
            if (!email) { errorEl.textContent = 'Please enter your email'; return; }
            const response = await window.apiClient.resetRequest(email);
            if (response.ok) {
                successEl.textContent = 'If an account exists for that email, a reset link has been sent.';
                successEl.classList.remove('hidden');
            } else {
                errorEl.textContent = 'Something went wrong. Please try again.';
            }
        });

        document.getElementById('resetConfirmBtn')?.addEventListener('click', async () => {
            const password = document.getElementById('newPassword').value;
            const confirm = document.getElementById('confirmNewPassword').value;
            const errorEl = document.getElementById('resetConfirmError');
            const successEl = document.getElementById('resetConfirmSuccess');
            errorEl.textContent = '';
            successEl.classList.add('hidden');
            if (password.length < 8) { errorEl.textContent = 'Password must be at least 8 characters'; return; }
            if (password !== confirm) { errorEl.textContent = 'Passwords do not match'; return; }
            const params = new URLSearchParams(window.location.search);
            const token = params.get('reset_token');
            if (!token) { errorEl.textContent = 'Invalid reset link'; return; }
            const response = await window.apiClient.resetConfirm(token, password);
            if (response.ok) {
                successEl.textContent = 'Password has been reset! You can now log in.';
                successEl.classList.remove('hidden');
                history.replaceState(null, '', window.location.pathname);
                setTimeout(() => {
                    const modal = document.getElementById('authModal');
                    _alpineData(modal).tab = 'login';
                }, 2000);
            } else {
                const data = await response.json().catch(() => ({}));
                errorEl.textContent = data.detail || 'Reset failed. The link may have expired.';
            }
        });

        // Check for reset_token in URL on page load
        (function checkResetToken() {
            const params = new URLSearchParams(window.location.search);
            if (params.has('reset_token')) {
                Alpine.store('modals').authOpen = true;
                // Wait for Alpine to process
                requestAnimationFrame(() => {
                    const modal = document.getElementById('authModal');
                    if (modal) _alpineData(modal).tab = 'reset-confirm';
                });
            }
        })();

        // 2FA verification flow
        document.getElementById('twoFactorVerifyBtn')?.addEventListener('click', async () => {
            const inputs = document.querySelectorAll('#totpInputGroup input');
            const code = Array.from(inputs).map(i => i.value).join('');
            const errorEl = document.getElementById('twoFactorVerifyError');
            errorEl.textContent = '';
            if (code.length !== 6 || !/^\d{6}$/.test(code)) { errorEl.textContent = 'Please enter a 6-digit code'; return; }
            const challengeToken = window.authManager.getChallengeToken();
            if (!challengeToken) { errorEl.textContent = 'Session expired, please log in again'; return; }
            const response = await window.apiClient.twoFactorVerify(challengeToken, code);
            if (response.ok) {
                const data = await response.json();
                window.authManager.setToken(data.access_token);
                window.authManager.clearChallenge();
                await window.authManager.init();
                window.authManager.notify();
                Alpine.store('modals').authOpen = false;
            } else {
                const data = await response.json().catch(() => ({}));
                errorEl.textContent = data.detail || 'Invalid code';
                inputs.forEach(i => { i.value = ''; });
                inputs[0]?.focus();
            }
        });

        // TOTP input auto-advance
        document.querySelectorAll('#totpInputGroup input').forEach((input, idx, arr) => {
            input.addEventListener('input', () => {
                if (input.value.length === 1 && idx < arr.length - 1) arr[idx + 1].focus();
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !input.value && idx > 0) arr[idx - 1].focus();
            });
        });

        document.getElementById('useRecoveryCodeLink')?.addEventListener('click', (e) => {
            e.preventDefault();
            const modal = document.getElementById('authModal');
            _alpineData(modal).tab = '2fa-recovery';
        });

        document.getElementById('backToTotpLink')?.addEventListener('click', (e) => {
            e.preventDefault();
            const modal = document.getElementById('authModal');
            _alpineData(modal).tab = '2fa-verify';
        });

        document.getElementById('twoFactorRecoveryBtn')?.addEventListener('click', async () => {
            const code = document.getElementById('recoveryCodeInput').value.trim();
            const errorEl = document.getElementById('twoFactorRecoveryError');
            errorEl.textContent = '';
            if (!code) { errorEl.textContent = 'Please enter a recovery code'; return; }
            const challengeToken = window.authManager.getChallengeToken();
            if (!challengeToken) { errorEl.textContent = 'Session expired, please log in again'; return; }
            const response = await window.apiClient.twoFactorRecovery(challengeToken, code);
            if (response.ok) {
                const data = await response.json();
                window.authManager.setToken(data.access_token);
                window.authManager.clearChallenge();
                await window.authManager.init();
                window.authManager.notify();
                Alpine.store('modals').authOpen = false;
            } else {
                const data = await response.json().catch(() => ({}));
                errorEl.textContent = data.detail || 'Invalid recovery code';
            }
        });
    }

    // ------------------------------------------------------------------ //
    // Auth handlers
    // ------------------------------------------------------------------ //

    async _handleLogin() {
        const email = document.getElementById('loginEmail')?.value.trim();
        const password = document.getElementById('loginPassword')?.value;
        const errorEl = document.getElementById('loginError');
        const submitBtn = document.getElementById('loginSubmitBtn');

        if (!email || !password) {
            if (errorEl) errorEl.textContent = 'Please enter your email and password.';
            return;
        }

        submitBtn.disabled = true;
        const loginSpinner = document.createElement('span');
        loginSpinner.className = 'material-symbols-outlined spin mr-1';
        loginSpinner.style.fontSize = '18px';
        loginSpinner.textContent = 'progress_activity';
        const loginText = document.createTextNode('Logging in...');
        submitBtn.replaceChildren(loginSpinner, loginText);
        if (errorEl) errorEl.textContent = '';

        try {
            const result = await window.apiClient.login(email, password);
            if (!result) {
                if (errorEl) errorEl.textContent = 'Invalid email or password.';
                return;
            }

            if (result.requires_2fa) {
                window.authManager.setChallengeToken(result.challenge_token);
                const modal = document.getElementById('authModal');
                _alpineData(modal).tab = '2fa-verify';
                document.querySelectorAll('#totpInputGroup input').forEach(i => { i.value = ''; });
                document.querySelector('#totpInputGroup input')?.focus();
                return;
            }

            if (!result.access_token) {
                if (errorEl) errorEl.textContent = 'Invalid email or password.';
                return;
            }

            window.authManager.setToken(result.access_token);
            const user = await window.apiClient.getMe(result.access_token);
            window.authManager.setUser(user);
            const discogsStatus = await window.apiClient.getDiscogsStatus(result.access_token);
            window.authManager.setDiscogsStatus(discogsStatus);
            window.authManager.notify();

            // Close modal
            Alpine.store('modals').authOpen = false;
            document.getElementById('loginEmail').value = '';
            document.getElementById('loginPassword').value = '';
        } finally {
            submitBtn.disabled = false;
            const loginIcon = document.createElement('span');
            loginIcon.className = 'material-symbols-outlined mr-1';
            loginIcon.style.fontSize = '18px';
            loginIcon.textContent = 'login';
            submitBtn.replaceChildren(loginIcon, document.createTextNode('Login'));
        }
    }

    async _handleRegister() {
        const email = document.getElementById('registerEmail')?.value.trim();
        const password = document.getElementById('registerPassword')?.value;
        const errorEl = document.getElementById('registerError');
        const successEl = document.getElementById('registerSuccess');
        const submitBtn = document.getElementById('registerSubmitBtn');

        if (!email || !password) {
            if (errorEl) errorEl.textContent = 'Please enter your email and password.';
            return;
        }
        if (password.length < 8) {
            if (errorEl) errorEl.textContent = 'Password must be at least 8 characters.';
            return;
        }

        submitBtn.disabled = true;
        const regSpinner = document.createElement('span');
        regSpinner.className = 'material-symbols-outlined spin mr-1';
        regSpinner.style.fontSize = '18px';
        regSpinner.textContent = 'progress_activity';
        const regText = document.createTextNode('Creating account...');
        submitBtn.replaceChildren(regSpinner, regText);
        if (errorEl) errorEl.textContent = '';
        if (successEl) successEl.classList.add('hidden');

        try {
            const ok = await window.apiClient.register(email, password);
            if (ok) {
                if (successEl) successEl.classList.remove('hidden');
                document.getElementById('registerEmail').value = '';
                document.getElementById('registerPassword').value = '';
                // Switch to login tab
                const modal = document.getElementById('authModal');
                _alpineData(modal).tab = 'login';
            } else {
                if (errorEl) errorEl.textContent = 'Registration failed. Please try again.';
            }
        } finally {
            submitBtn.disabled = false;
            const regIcon = document.createElement('span');
            regIcon.className = 'material-symbols-outlined mr-1';
            regIcon.style.fontSize = '18px';
            regIcon.textContent = 'person_add';
            submitBtn.replaceChildren(regIcon, document.createTextNode('Create Account'));
        }
    }

    async _handleLogout() {
        const token = window.authManager.getToken();
        await window.apiClient.logout(token);
        window.authManager.clear();
        window.authManager.notify();
    }

    // ------------------------------------------------------------------ //
    // Pane management
    // ------------------------------------------------------------------ //

    _switchPane(pane) {
        this.activePane = pane;

        // Update nav links — toggle active class
        document.querySelectorAll('.nav-link[data-pane]').forEach(link => {
            link.classList.toggle('active', link.dataset.pane === pane);
        });

        // Show/hide panes
        document.querySelectorAll('.pane').forEach(el => el.classList.remove('active'));
        const target = document.getElementById(pane + 'Pane');
        if (target) target.classList.add('active');

        // Focus search input when switching to search pane
        if (pane === 'search' && window.searchPane) {
            window.searchPane.focus();
        }

        // Stop insights polling when leaving that pane
        if (this._prevPane === 'insights' && pane !== 'insights' && window.insightsPanel) {
            window.insightsPanel.stopPolling();
        }

        // Pause timeline playback when leaving the explore pane
        if (this._prevPane === 'explore' && pane !== 'explore' && this.timeline) {
            this.timeline.pause();
        }

        this._prevPane = pane;

        // Lazy-load panes on first visit
        if (pane === 'insights') {
            window.insightsPanel.load();
            window.insightsPanel.startPolling();
        } else if (pane === 'trends' && this.currentQuery) {
            this._loadTrends(this.currentQuery, this.searchType);
        } else if (pane === 'collection' && window.authManager.isLoggedIn()) {
            this.userPanes.loadCollection(true);
            this.userPanes.loadCollectionStats();
            this.userPanes.loadTasteFingerprint();
        } else if (pane === 'wantlist' && window.authManager.isLoggedIn()) {
            this.userPanes.loadWantlist(true);
        } else if (pane === 'recommendations' && window.authManager.isLoggedIn()) {
            this.userPanes.loadRecommendations();
        } else if (pane === 'genres' && window.genreTreeView) {
            window.genreTreeView.load();
        } else if (pane === 'credits' && window.creditsPanel) {
            window.creditsPanel.load();
        }
    }

    _setSearchType(type) {
        this.searchType = type;
        const btn = document.getElementById('searchTypeBtn');
        if (btn) btn.textContent = type.charAt(0).toUpperCase() + type.slice(1);

        document.querySelectorAll('[data-type]').forEach(item => {
            item.classList.toggle('active', item.dataset.type === type);
        });

        const input = document.getElementById('searchInput');
        if (input?.value.trim().length >= 2) {
            this.autocomplete._search(input.value.trim());
        }
    }

    // ------------------------------------------------------------------ //
    // Search & graph
    // ------------------------------------------------------------------ //

    async _onSearch(name) {
        this.currentQuery = name;
        this._pushState(name, this.searchType);

        if (this.activePane === 'explore') {
            await this._loadExplore(name, this.searchType);
        } else {
            await this._loadTrends(name, this.searchType);
        }
    }

    async _loadExplore(name, type) {
        const loading = document.getElementById('graphLoading');
        loading.classList.add('active');
        let loaded = false;
        try {
            const data = await window.apiClient.explore(name, type);
            if (data) {
                await new Promise((resolve) => {
                    // Set callback BEFORE setExploreData to avoid race where
                    // all expansions complete before the callback is registered
                    this.graph.onExpandsComplete = () => {
                        this.graph.onExpandsComplete = null;
                        resolve();
                    };
                    this.graph.setExploreData(data);
                    // Fallback: if no expansions were needed, resolve immediately
                    if (this.graph._pendingExpands <= 0) {
                        this.graph.onExpandsComplete = null;
                        resolve();
                    }
                });
                // Decorate release nodes with ownership badges if logged in
                await this._decorateOwnership();
                loaded = true;
            }
        } finally {
            loading.classList.remove('active');
        }
        // Initialize timeline scrubber after spinner is dismissed (don't auto-show)
        if (loaded) {
            await this.timeline.init();
        }
    }

    async _decorateOwnership() {
        if (!window.authManager.isLoggedIn()) return;
        const token = window.authManager.getToken();
        const releaseNodes = (this.graph.nodes || []).filter(n => n.type === 'release' && !n.isCategory);
        if (releaseNodes.length === 0) return;

        const ids = releaseNodes.map(n => n.nodeId || n.name).slice(0, 100);
        const result = await window.apiClient.getUserStatus(ids, token);
        if (!result || !result.status) return;

        // Update info panel if it's showing a release node that has status
        const title = document.getElementById('infoPanelTitle')?.textContent;
        if (title) {
            const matchId = ids.find(id => id === title);
            if (matchId && result.status[matchId]) {
                this._addOwnershipBadges(matchId, result.status[matchId]);
            }
        }
    }

    _onTimelineYearChange(year) {
        this.graph.setBeforeYear(year);
    }

    _onGenreEmergence(newGenres) {
        // Highlight genre/style nodes that just appeared
        const genreSet = new Set(newGenres.map(n => n.toLowerCase()));
        this.graph.g.selectAll('g').each(function(d) {
            if ((d.type === 'genre' || d.type === 'style') && genreSet.has(d.name.toLowerCase())) {
                d3.select(this).classed('node-emergence', true);
                setTimeout(() => d3.select(this).classed('node-emergence', false), 2000);
            }
        });
    }

    _onCompareChange(yearA, yearB) {
        if (yearA === yearB) {
            // Same year — clear comparison styling, show as single year
            this.graph.clearComparison();
            this.graph.setBeforeYear(yearA);
            return;
        }
        this.graph.setCompareYears(yearA, yearB);
    }

    _onCompareExit() {
        this.graph.clearComparison();
        // Re-fetch with the restored single-year filter
        this.graph.setBeforeYear(this.timeline.currentYear);
    }

    _addOwnershipBadges(releaseId, statusObj) {
        const body = document.getElementById('infoPanelBody');
        if (!body) return;

        // Remove existing badges
        body.querySelectorAll('.ownership-badge').forEach(b => b.remove());

        const container = document.createElement('div');
        container.className = 'mb-2';

        if (statusObj.in_collection) {
            const badge = document.createElement('span');
            badge.className = 'ownership-badge in-collection';
            const icon = document.createElement('span');
            icon.className = 'material-symbols-outlined mr-1';
            icon.style.fontSize = '18px';
            icon.textContent = 'check';
            badge.appendChild(icon);
            badge.appendChild(document.createTextNode('In Collection'));
            container.appendChild(badge);
        }
        if (statusObj.in_wantlist) {
            const badge = document.createElement('span');
            badge.className = 'ownership-badge in-wantlist';
            const icon = document.createElement('span');
            icon.className = 'material-symbols-outlined mr-1';
            icon.style.fontSize = '18px';
            icon.textContent = 'favorite';
            badge.appendChild(icon);
            badge.appendChild(document.createTextNode('In Wantlist'));
            container.appendChild(badge);
        }

        if (container.children.length > 0) {
            body.insertBefore(container, body.firstChild);
        }
    }

    async _loadTrends(name, type) {
        const loading = document.getElementById('trendsLoading');
        loading.classList.add('active');
        try {
            const data = await window.apiClient.getTrends(name, type);
            if (data) {
                if (this.compareMode && this.primaryTrendsData) {
                    this.trends.addComparison(data);
                    document.getElementById('compareBadge').textContent = `vs ${data.name}`;
                    document.getElementById('compareInfo').classList.remove('hidden');
                    document.getElementById('compareHint').classList.add('hidden');
                    this.compareMode = false;
                } else {
                    this.primaryTrendsData = data;
                    this.trends.render(data);
                    document.getElementById('compareBtn').classList.remove('hidden');
                    document.getElementById('compareHint').classList.add('hidden');
                    document.getElementById('compareInfo').classList.add('hidden');
                    this.compareMode = false;
                }
            }
        } finally {
            loading.classList.remove('active');
        }
    }

    _enableCompareMode() {
        if (!this.primaryTrendsData) return;
        this.compareMode = true;
        document.getElementById('compareBtn').classList.add('hidden');
        document.getElementById('compareHint').classList.remove('hidden');
    }

    _clearComparison() {
        this.compareMode = false;
        this.trends.clearComparison();
        document.getElementById('compareBtn').classList.remove('hidden');
        document.getElementById('compareHint').classList.add('hidden');
        document.getElementById('compareInfo').classList.add('hidden');
    }

    _pushState(name, type) {
        const params = new URLSearchParams({ name, type });
        history.pushState({ name, type }, '', `?${params}`);
    }

    async _restoreFromUrl() {
        const params = new URLSearchParams(window.location.search);
        const snapshotToken = params.get('snapshot');
        if (snapshotToken) {
            await this._loadSnapshot(snapshotToken);
            return;
        }
        const name = params.get('name');
        const type = params.get('type');
        if (name && type) {
            this._setSearchType(type);
            document.getElementById('searchInput').value = name;
            this._onSearch(name);
        }
    }

    async _loadSnapshot(token) {
        const loading = document.getElementById('graphLoading');
        loading.classList.add('active');
        try {
            const data = await window.apiClient.restoreSnapshot(token);
            if (data) this.graph.restoreSnapshot(data.nodes, data.center);
        } finally {
            loading.classList.remove('active');
        }
    }

    async _shareSnapshot() {
        const token = window.authManager.getToken();
        if (!token) return;

        const nodes = this.graph.nodes
            .filter(n => !n.isCategory)
            .map(n => ({ id: n.nodeId || n.name, type: n.type }));
        const centerName = this.graph.centerName;
        const centerType = this.graph.centerType;
        if (!centerName || nodes.length === 0) return;

        const result = await window.apiClient.saveSnapshot(nodes, { id: centerName, type: centerType }, token);
        if (!result) return;

        const url = `${window.location.origin}/?snapshot=${result.token}`;
        try {
            await navigator.clipboard.writeText(url);
        } catch {
            prompt('Copy this link:', url);
            return;
        }
        this._showToast('Link copied!');
    }

    _showToast(message) {
        const toast = document.getElementById('shareToast');
        const toastMsg = document.getElementById('shareToastMsg');
        if (toastMsg) toastMsg.textContent = message;
        toast?.classList.add('show');
        setTimeout(() => toast?.classList.remove('show'), 2500);
    }

    async _onNodeClick(nodeId, type) {
        const panel = document.getElementById('infoPanel');
        const body = document.getElementById('infoPanelBody');
        const title = document.getElementById('infoPanelTitle');

        // Track request to prevent stale responses from overwriting newer ones
        const requestId = ++this._nodeClickRequestId;

        const loadingP = document.createElement('p');
        loadingP.className = 'text-text-mid';
        loadingP.textContent = 'Loading...';
        body.replaceChildren(loadingP);
        panel.classList.add('open');

        const details = await window.apiClient.getNodeDetails(nodeId, type);
        // Discard stale response if a newer click has occurred
        if (requestId !== this._nodeClickRequestId) return;
        if (!details) {
            const noDataP = document.createElement('p');
            noDataP.className = 'text-text-mid';
            noDataP.textContent = 'No details available';
            body.replaceChildren(noDataP);
            return;
        }

        title.textContent = details.name || nodeId;
        body.replaceChildren(...this._renderDetails(details, type, nodeId));

        // Add ownership badges for release nodes
        if (type === 'release' && window.authManager.isLoggedIn()) {
            const token = window.authManager.getToken();
            const result = await window.apiClient.getUserStatus([nodeId], token);
            if (requestId !== this._nodeClickRequestId) return;
            if (result?.status?.[nodeId]) {
                this._addOwnershipBadges(nodeId, result.status[nodeId]);
            }
        }

        const exploreBtn = body.querySelector('.explore-node-btn');
        if (exploreBtn) {
            exploreBtn.addEventListener('click', () => {
                this._onNodeExpand(exploreBtn.dataset.name, exploreBtn.dataset.type);
                panel.classList.remove('open');
            });
        }
    }

    async _onNodeExpand(name, type) {
        const explorableTypes = ['artist', 'genre', 'label', 'style'];
        if (!explorableTypes.includes(type)) return;

        this._setSearchType(type);
        this.currentQuery = name;
        document.getElementById('searchInput').value = name;
        await this._loadExplore(name, type);
    }

    _renderDetails(details, type, nodeId) {
        const nodes = [];

        const explorableTypes = ['artist', 'genre', 'label', 'style'];
        if (explorableTypes.includes(type)) {
            const btn = document.createElement('button');
            btn.className = 'btn-outline-primary btn-sm w-full mb-3 explore-node-btn';
            btn.dataset.name = details.name;
            btn.dataset.type = type;
            const icon = document.createElement('i');
            icon.className = 'material-symbols-outlined mr-1'; icon.textContent = 'hub'; icon.style.fontSize = '18px';
            btn.append(icon, `Explore ${details.name}`);
            nodes.push(btn);
        }

        if (type === 'artist') {
            nodes.push(this._detailStat('Releases', details.release_count || 0));
            if (details.genres?.length) nodes.push(this._detailTags('Genres', details.genres));
            if (details.styles?.length) nodes.push(this._detailTags('Styles', details.styles));
            if (details.groups?.length) nodes.push(this._detailTags('Groups', details.groups));
            if (window.authManager.isLoggedIn() && details.id) {
                nodes.push(this._gapAnalysisButton('artist', details.id, details.name));
            }
            // Collaborators section
            const collabSection = document.createElement('div');
            collabSection.className = 'detail-section mt-3';
            const collabHeading = document.createElement('h6');
            collabHeading.textContent = 'Collaborators';
            const collabContainer = document.createElement('div');
            collabContainer.id = 'collaboratorsContainer';
            const collabLoading = document.createElement('p');
            collabLoading.className = 'text-text-mid text-sm';
            collabLoading.textContent = 'Loading...';
            collabContainer.appendChild(collabLoading);
            collabSection.append(collabHeading, collabContainer);
            nodes.push(collabSection);
            // Trigger async load
            if (window.collaboratorsPanel && details.id) {
                window.collaboratorsPanel.load(details.id);
            }
        } else if (type === 'release') {
            if (details.year) nodes.push(this._detailStat('Year', details.year));
            if (details.artists?.length) nodes.push(this._detailTags('Artists', details.artists));
            if (details.labels?.length) nodes.push(this._detailTags('Labels', details.labels));
            if (details.genres?.length) nodes.push(this._detailTags('Genres', details.genres));
            if (details.styles?.length) nodes.push(this._detailTags('Styles', details.styles));
        } else if (type === 'label') {
            nodes.push(this._detailStat('Releases', details.release_count || 0));
            if (window.authManager.isLoggedIn() && details.id) {
                nodes.push(this._gapAnalysisButton('label', details.id, details.name));
            }
        } else if (type === 'genre' || type === 'style') {
            nodes.push(this._detailStat('Artists', details.artist_count || 0));
        }

        if (nodes.length === 0) {
            const p = document.createElement('p');
            p.className = 'text-text-mid';
            p.textContent = 'No additional details';
            nodes.push(p);
        }

        return nodes;
    }

    _detailStat(label, value) {
        const div = document.createElement('div');
        div.className = 'detail-stat';
        const labelEl = document.createElement('span');
        labelEl.className = 'label';
        labelEl.textContent = label;
        const valueEl = document.createElement('span');
        valueEl.className = 'value';
        valueEl.textContent = label === 'Year' ? value : (typeof value === 'number' ? value.toLocaleString() : value);
        div.append(labelEl, valueEl);
        return div;
    }

    _gapAnalysisButton(entityType, entityId, entityName) {
        const btn = document.createElement('button');
        btn.className = 'btn-outline-warning btn-sm w-full mt-3 gap-analysis-btn';
        const icon = document.createElement('i');
        icon.className = 'material-symbols-outlined mr-1'; icon.textContent = 'search_off'; icon.style.fontSize = '18px';
        btn.append(icon, 'What am I missing?');
        btn.addEventListener('click', () => {
            const panel = document.getElementById('infoPanel');
            if (panel) panel.classList.remove('open');
            window.userPanes.loadGapAnalysis(entityType, entityId, true);
        });
        return btn;
    }

    _detailTags(label, tags) {
        const section = document.createElement('div');
        section.className = 'detail-section';
        const heading = document.createElement('h6');
        heading.textContent = label;
        const tagsDiv = document.createElement('div');
        tagsDiv.className = 'detail-tags';
        tags.forEach(t => {
            const span = document.createElement('span');
            span.className = 'detail-tag';
            span.textContent = t;
            tagsDiv.appendChild(span);
        });
        section.append(heading, tagsDiv);
        return section;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.exploreApp = new ExploreApp();
});

// ============================================================
// Find Path
// ============================================================

(function initPathFinder() {
    'use strict';

    // DOM refs
    const fromInput    = document.getElementById('pathFromInput');
    const toInput      = document.getElementById('pathToInput');
    const fromTypeBtn  = document.getElementById('pathFromTypeBtn');
    const toTypeBtn    = document.getElementById('pathToTypeBtn');
    const fromDropdown = document.getElementById('pathFromDropdown');
    const toDropdown   = document.getElementById('pathToDropdown');
    const connectBtn   = document.getElementById('pathConnectBtn');
    const loadingEl    = document.getElementById('pathLoading');
    const placeholder  = document.getElementById('pathPlaceholder');
    const resultEl     = document.getElementById('pathResult');
    const summaryEl    = document.getElementById('pathResultSummary');
    const chainEl      = document.getElementById('pathChain');
    const errorEl      = document.getElementById('pathError');

    if (!fromInput) return;  // pane not in DOM

    let fromType = 'artist';
    let toType   = 'artist';

    // Type selectors
    document.querySelectorAll('[data-path-from-type]').forEach(link => {
        link.addEventListener('click', e => {
            e.preventDefault();
            fromType = e.currentTarget.dataset.pathFromType;
            fromTypeBtn.textContent = fromType.charAt(0).toUpperCase() + fromType.slice(1);
        });
    });
    document.querySelectorAll('[data-path-to-type]').forEach(link => {
        link.addEventListener('click', e => {
            e.preventDefault();
            toType = e.currentTarget.dataset.pathToType;
            toTypeBtn.textContent = toType.charAt(0).toUpperCase() + toType.slice(1);
        });
    });

    // ----------------------------------------------------------------
    // Autocomplete wiring
    // ----------------------------------------------------------------

    function wireAutocomplete(input, dropdown, getType) {
        let debounceTimer;
        input.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            dropdown.textContent = '';
            dropdown.classList.remove('show');
            if (q.length < 3) return;
            debounceTimer = setTimeout(async () => {
                const results = await window.apiClient.autocomplete(q, getType(), 8);
                if (!results.length) return;
                dropdown.textContent = '';
                results.forEach(r => {
                    const item = document.createElement('div');
                    item.className = 'autocomplete-item';
                    item.textContent = r.name;       // textContent — safe
                    item.addEventListener('mousedown', e => {
                        e.preventDefault();
                        input.value = r.name;
                        dropdown.textContent = '';
                        dropdown.classList.remove('show');
                    });
                    dropdown.appendChild(item);
                });
                dropdown.classList.add('show');
            }, 220);
        });
        input.addEventListener('blur', () => {
            setTimeout(() => { dropdown.classList.remove('show'); }, 150);
        });
    }

    wireAutocomplete(fromInput, fromDropdown, () => fromType);
    wireAutocomplete(toInput,   toDropdown,   () => toType);

    // ----------------------------------------------------------------
    // Render helpers
    // ----------------------------------------------------------------

    function setVisible(el, visible) {
        // The loading overlay uses .active for display; all others use .hidden
        if (el === loadingEl) {
            el.classList.toggle('active', visible);
        } else {
            el.classList.toggle('hidden', !visible);
        }
    }

    function showError(msg) {
        setVisible(loadingEl, false);
        setVisible(placeholder, false);
        setVisible(resultEl, false);
        errorEl.textContent = msg;          // textContent — safe
        setVisible(errorEl, true);
    }

    function buildNodeCard(node) {
        const card = document.createElement('div');
        card.className = 'path-node';

        const typeSpan = document.createElement('span');
        typeSpan.className = 'path-node-type';
        typeSpan.textContent = node.type;   // textContent — safe

        const nameSpan = document.createElement('span');
        nameSpan.className = 'path-node-name';
        nameSpan.title = node.name;
        nameSpan.textContent = node.name;   // textContent — safe

        card.appendChild(typeSpan);
        card.appendChild(nameSpan);
        return card;
    }

    function buildEdge(relType) {
        const edge = document.createElement('div');
        edge.className = 'path-edge';

        const arrowWrap = document.createElement('span');
        arrowWrap.className = 'path-edge-arrow';
        const arrowIcon = document.createElement('i');
        arrowIcon.className = 'material-symbols-outlined'; arrowIcon.textContent = 'arrow_forward';
        arrowWrap.appendChild(arrowIcon);

        const label = document.createElement('span');
        label.className = 'path-edge-label';
        label.textContent = relType || '';  // textContent — safe

        edge.appendChild(arrowWrap);
        edge.appendChild(label);
        return edge;
    }

    function renderPath(data) {
        chainEl.textContent = '';
        summaryEl.textContent = `Path length: ${data.length} hop${data.length === 1 ? '' : 's'}`;

        data.path.forEach((node, i) => {
            if (i > 0) {
                chainEl.appendChild(buildEdge(node.rel));
            }
            chainEl.appendChild(buildNodeCard(node));
        });

        setVisible(loadingEl, false);
        setVisible(placeholder, false);
        setVisible(errorEl, false);
        setVisible(resultEl, true);
    }

    // ----------------------------------------------------------------
    // Connect button
    // ----------------------------------------------------------------

    async function handleConnect() {
        const fromName = fromInput.value.trim();
        const toName   = toInput.value.trim();

        if (!fromName || !toName) {
            showError('Please enter both a "From" and "To" entity.');
            return;
        }

        setVisible(placeholder, false);
        setVisible(resultEl, false);
        setVisible(errorEl, false);
        setVisible(loadingEl, true);
        connectBtn.disabled = true;

        try {
            const data = await window.apiClient.findPath(fromName, fromType, toName, toType);

            if (!data) {
                showError('An error occurred. Please try again.');
                return;
            }
            if (data.notFound) {
                showError(data.error || 'One or both entities not found.');
                return;
            }
            if (!data.found) {
                summaryEl.textContent =
                    `No path found between "${fromName}" and "${toName}" within the search depth.`;
                chainEl.textContent = '';
                setVisible(loadingEl, false);
                setVisible(placeholder, false);
                setVisible(errorEl, false);
                setVisible(resultEl, true);
                return;
            }

            renderPath(data);
        } finally {
            connectBtn.disabled = false;
        }
    }

    connectBtn.addEventListener('click', handleConnect);
    [fromInput, toInput].forEach(el => {
        el.addEventListener('keydown', e => {
            if (e.key === 'Enter') handleConnect();
        });
    });
})();

// ---------------------------------------------------------------------------
// NLQ panel setup
// ---------------------------------------------------------------------------
(function initNlqPanel() {
    const nlqPanel = new NLQPanel();
    nlqPanel.onExploreEntity = (name, type) => {
        document.getElementById('askModeBtn')?.classList.remove('bg-purple-accent', 'text-white');
        document.getElementById('askModeBtn')?.classList.add('bg-inner-bg', 'text-text-mid', 'border', 'border-border-color');
        document.getElementById('searchModeBtn')?.classList.add('bg-purple-accent', 'text-white');
        document.getElementById('searchModeBtn')?.classList.remove('bg-inner-bg', 'text-text-mid', 'border', 'border-border-color');
        nlqPanel.hide();
        // Trigger explore
        if (window.exploreApp) {
            window.exploreApp._switchPane('explore');
            window.exploreApp._loadExplore(name, type);
        }
    };

    nlqPanel.checkEnabled().then(enabled => {
        if (enabled) {
            const toggle = document.getElementById('searchAskToggle');
            if (toggle) toggle.style.display = '';
        }
    });

    document.getElementById('searchModeBtn')?.addEventListener('click', () => {
        document.getElementById('searchModeBtn')?.classList.add('bg-purple-accent', 'text-white');
        document.getElementById('searchModeBtn')?.classList.remove('bg-inner-bg', 'text-text-mid', 'border', 'border-border-color');
        document.getElementById('askModeBtn')?.classList.remove('bg-purple-accent', 'text-white');
        document.getElementById('askModeBtn')?.classList.add('bg-inner-bg', 'text-text-mid', 'border', 'border-border-color');
        nlqPanel.hide();
    });

    document.getElementById('askModeBtn')?.addEventListener('click', () => {
        document.getElementById('askModeBtn')?.classList.add('bg-purple-accent', 'text-white');
        document.getElementById('askModeBtn')?.classList.remove('bg-inner-bg', 'text-text-mid', 'border', 'border-border-color');
        document.getElementById('searchModeBtn')?.classList.remove('bg-purple-accent', 'text-white');
        document.getElementById('searchModeBtn')?.classList.add('bg-inner-bg', 'text-text-mid', 'border', 'border-border-color');
        nlqPanel.show();
        nlqPanel.input?.focus();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === '?' && !e.target.matches('input, textarea, [contenteditable]')) {
            e.preventDefault();
            document.getElementById('askModeBtn')?.click();
        }
    });
})();
