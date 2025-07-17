// Main Discovery App JavaScript

class DiscoveryApp {
    constructor() {
        this.currentSection = 'recommendations';
        this.websocket = null;
        this.init();
    }

    init() {
        this.setupNavigation();
        this.setupWebSocket();
        this.setupEventListeners();
        this.showSection('recommendations');
    }

    setupNavigation() {
        const hamburger = document.getElementById('hamburger');
        const navMenu = document.getElementById('navMenu');
        const navItems = document.querySelectorAll('.nav-item[data-section]');

        // Hamburger menu toggle
        hamburger.addEventListener('click', () => {
            hamburger.classList.toggle('active');
            navMenu.classList.toggle('active');
        });

        // Navigation item clicks
        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const section = item.getAttribute('data-section');
                this.showSection(section);

                // Close mobile menu
                hamburger.classList.remove('active');
                navMenu.classList.remove('active');
            });
        });

        // Close mobile menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!hamburger.contains(e.target) && !navMenu.contains(e.target)) {
                hamburger.classList.remove('active');
                navMenu.classList.remove('active');
            }
        });
    }

    showSection(sectionName) {
        // Hide all sections
        document.querySelectorAll('.content-section').forEach(section => {
            section.classList.remove('active');
        });

        // Show target section
        const targetSection = document.getElementById(sectionName);
        if (targetSection) {
            targetSection.classList.add('active');
            this.currentSection = sectionName;
        }

        // Update navigation active state
        document.querySelectorAll('.nav-item[data-section]').forEach(item => {
            item.classList.remove('active');
        });

        const activeNavItem = document.querySelector(`[data-section="${sectionName}"]`);
        if (activeNavItem) {
            activeNavItem.classList.add('active');
        }

        // Initialize section-specific functionality
        this.initializeSection(sectionName);
    }

    initializeSection(sectionName) {
        switch (sectionName) {
            case 'recommendations':
                if (window.recommendationsModule) {
                    window.recommendationsModule.init();
                }
                break;
            case 'analytics':
                if (window.analyticsModule) {
                    window.analyticsModule.init();
                }
                break;
            case 'graph':
                if (window.graphModule) {
                    window.graphModule.init();
                }
                break;
        }
    }

    setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        try {
            this.websocket = new WebSocket(wsUrl);

            this.websocket.onopen = () => {
                console.log('🔌 WebSocket connected');
                this.showToast('Connected to Discovery service', 'success');
            };

            this.websocket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleWebSocketMessage(data);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            this.websocket.onclose = () => {
                console.log('🔌 WebSocket disconnected');
                this.showToast('Disconnected from Discovery service', 'error');

                // Attempt to reconnect after 5 seconds
                setTimeout(() => {
                    this.setupWebSocket();
                }, 5000);
            };

            this.websocket.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.showToast('Connection error', 'error');
            };
        } catch (error) {
            console.error('Failed to setup WebSocket:', error);
        }
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'update':
                // Handle real-time updates
                this.showToast(data.message, 'success');
                break;
            case 'error':
                this.showToast(data.message, 'error');
                break;
            case 'echo':
                console.log('Echo received:', data.message);
                break;
        }
    }

    setupEventListeners() {
        // Toast close button
        document.getElementById('toastClose').addEventListener('click', () => {
            this.hideToast();
        });

        // Auto-hide toast after 5 seconds
        this.toastTimeout = null;
    }

    // API Helper Methods
    async makeAPIRequest(endpoint, data = null, method = 'GET') {
        this.showLoading();

        try {
            const options = {
                method: method,
                headers: {
                    'Content-Type': 'application/json',
                }
            };

            if (data && method !== 'GET') {
                options.body = JSON.stringify(data);
            }

            const response = await fetch(`/api/${endpoint}`, options);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            this.hideLoading();
            return result;
        } catch (error) {
            this.hideLoading();
            this.showToast(`Error: ${error.message}`, 'error');
            throw error;
        }
    }

    // UI Helper Methods
    showLoading() {
        document.getElementById('loadingSpinner').style.display = 'flex';
    }

    hideLoading() {
        document.getElementById('loadingSpinner').style.display = 'none';
    }

    showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        const toastMessage = document.getElementById('toastMessage');

        toastMessage.textContent = message;
        toast.className = `toast ${type}`;
        toast.style.display = 'block';

        // Clear existing timeout
        if (this.toastTimeout) {
            clearTimeout(this.toastTimeout);
        }

        // Auto-hide after 5 seconds
        this.toastTimeout = setTimeout(() => {
            this.hideToast();
        }, 5000);
    }

    hideToast() {
        document.getElementById('toast').style.display = 'none';
        if (this.toastTimeout) {
            clearTimeout(this.toastTimeout);
            this.toastTimeout = null;
        }
    }

    // Utility Methods
    formatDate(dateString) {
        return new Date(dateString).toLocaleDateString();
    }

    formatNumber(number) {
        return new Intl.NumberFormat().format(number);
    }

    sanitizeHtml(str) {
        const temp = document.createElement('div');
        temp.textContent = str;
        return temp.innerHTML;
    }

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.discoveryApp = new DiscoveryApp();
});

// Export for use in other modules
window.DiscoveryApp = DiscoveryApp;
