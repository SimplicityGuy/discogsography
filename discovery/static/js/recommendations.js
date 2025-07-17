// AI-Powered Music Recommendations Module

class RecommendationsModule {
    constructor() {
        this.currentRecommendations = [];
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupFormValidation();
    }

    setupEventListeners() {
        const getRecommendationsBtn = document.getElementById('getRecommendations');
        const recommendationType = document.getElementById('recommendationType');

        getRecommendationsBtn.addEventListener('click', () => {
            this.getRecommendations();
        });

        // Handle enter key in input fields
        document.getElementById('artistInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.getRecommendations();
            }
        });

        // Show/hide relevant fields based on recommendation type
        recommendationType.addEventListener('change', () => {
            this.updateFormFields();
        });

        this.updateFormFields();
    }

    setupFormValidation() {
        const form = document.querySelector('.discovery-controls');
        const inputs = form.querySelectorAll('input, select');

        inputs.forEach(input => {
            input.addEventListener('blur', () => {
                this.validateField(input);
            });
        });
    }

    validateField(field) {
        const value = field.value.trim();
        const type = document.getElementById('recommendationType').value;

        // Remove existing validation classes
        field.classList.remove('valid', 'invalid');

        // Validate based on recommendation type and field
        if (field.id === 'artistInput') {
            if ((type === 'similar' || type === 'discovery') && value === '') {
                field.classList.add('invalid');
                return false;
            } else if (value !== '') {
                field.classList.add('valid');
            }
        }

        return true;
    }

    updateFormFields() {
        const type = document.getElementById('recommendationType').value;
        const artistInput = document.getElementById('artistInput');
        const genreFilter = document.getElementById('genreFilter');

        // Update placeholders and requirements based on type
        switch (type) {
            case 'similar':
                artistInput.placeholder = 'Enter artist name (e.g., Miles Davis)';
                artistInput.required = true;
                genreFilter.style.display = 'block';
                break;
            case 'trending':
                artistInput.placeholder = 'Optional: Artist to filter trends';
                artistInput.required = false;
                genreFilter.style.display = 'block';
                break;
            case 'discovery':
                artistInput.placeholder = 'Enter search terms for discovery';
                artistInput.required = true;
                genreFilter.style.display = 'none';
                break;
        }
    }

    async getRecommendations() {
        const artistName = document.getElementById('artistInput').value.trim();
        const recommendationType = document.getElementById('recommendationType').value;
        const genreFilter = document.getElementById('genreFilter').value.trim();

        // Validate required fields
        if ((recommendationType === 'similar' || recommendationType === 'discovery') && !artistName) {
            window.discoveryApp.showToast('Please enter an artist name', 'error');
            return;
        }

        // Build request
        const request = {
            recommendation_type: recommendationType,
            limit: 10
        };

        if (artistName) {
            if (recommendationType === 'discovery') {
                request.release_title = artistName; // Use as search query
            } else {
                request.artist_name = artistName;
            }
        }

        if (genreFilter) {
            request.genres = genreFilter.split(',').map(g => g.trim());
        }

        try {
            const response = await window.discoveryApp.makeAPIRequest('recommendations', request, 'POST');
            this.currentRecommendations = response.recommendations;
            this.displayRecommendations(response);

            window.discoveryApp.showToast(
                `Found ${response.total} recommendations`,
                'success'
            );
        } catch (error) {
            console.error('Error getting recommendations:', error);
            this.displayError('Failed to get recommendations. Please try again.');
        }
    }

    displayRecommendations(response) {
        const container = document.getElementById('recommendationsResults');
        const recommendations = response.recommendations;

        if (!recommendations || recommendations.length === 0) {
            container.innerHTML = this.createEmptyState();
            return;
        }

        const html = `
            <div class="recommendations-header">
                <h3>🎵 ${response.total} Recommendations Found</h3>
                <p>Based on your ${response.request.recommendation_type} preferences</p>
            </div>
            <div class="recommendations-grid">
                ${recommendations.map(rec => this.createRecommendationCard(rec)).join('')}
            </div>
        `;

        container.innerHTML = html;
        this.setupRecommendationInteractions();
    }

    createRecommendationCard(recommendation) {
        const genres = recommendation.genres || [];
        const year = recommendation.year ? ` (${recommendation.year})` : '';
        const releaseTitle = recommendation.release_title ?
            `<div class="recommendation-details">
                <i class="fas fa-compact-disc"></i> ${this.sanitize(recommendation.release_title)}${year}
            </div>` : '';

        return `
            <div class="recommendation-card" data-id="${recommendation.neo4j_id}">
                <div class="recommendation-header">
                    <div class="recommendation-title">
                        <i class="fas fa-user-music"></i> ${this.sanitize(recommendation.artist_name)}
                    </div>
                    <div class="similarity-score">
                        ${(recommendation.similarity_score * 100).toFixed(1)}%
                    </div>
                </div>
                ${releaseTitle}
                <div class="recommendation-explanation">
                    <i class="fas fa-lightbulb"></i> ${this.sanitize(recommendation.explanation)}
                </div>
                ${genres.length > 0 ? `
                    <div class="genres">
                        ${genres.map(genre => `<span class="genre-tag">${this.sanitize(genre)}</span>`).join('')}
                    </div>
                ` : ''}
                <div class="recommendation-actions">
                    <button class="btn btn-secondary btn-sm explore-artist" data-id="${recommendation.neo4j_id}">
                        <i class="fas fa-search"></i> Explore in Graph
                    </button>
                </div>
            </div>
        `;
    }

    setupRecommendationInteractions() {
        // Add click handlers for exploring artists in graph
        document.querySelectorAll('.explore-artist').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const artistId = e.target.getAttribute('data-id');
                this.exploreArtistInGraph(artistId);
            });
        });

        // Add hover effects and additional interactions
        document.querySelectorAll('.recommendation-card').forEach(card => {
            card.addEventListener('click', (e) => {
                if (!e.target.classList.contains('explore-artist')) {
                    // Could add more detailed view or actions
                    card.classList.toggle('selected');
                }
            });
        });
    }

    exploreArtistInGraph(artistId) {
        if (!artistId) return;

        // Switch to graph section and trigger exploration
        window.discoveryApp.showSection('graph');

        // Wait for graph module to be initialized
        setTimeout(() => {
            if (window.graphModule) {
                window.graphModule.expandNode(artistId);
            }
        }, 100);
    }

    createEmptyState() {
        return `
            <div class="empty-state">
                <div class="empty-icon">
                    <i class="fas fa-music" style="font-size: 4rem; color: var(--text-muted);"></i>
                </div>
                <h3>No Recommendations Found</h3>
                <p>Try adjusting your search criteria or recommendation type.</p>
                <div class="empty-suggestions">
                    <h4>Suggestions:</h4>
                    <ul>
                        <li>Check the spelling of the artist name</li>
                        <li>Try a different recommendation type</li>
                        <li>Remove or change genre filters</li>
                        <li>Use broader search terms for discovery mode</li>
                    </ul>
                </div>
            </div>
        `;
    }

    displayError(message) {
        const container = document.getElementById('recommendationsResults');
        container.innerHTML = `
            <div class="error-state">
                <div class="error-icon">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--error-color);"></i>
                </div>
                <h3>Error Getting Recommendations</h3>
                <p>${this.sanitize(message)}</p>
                <button class="btn btn-primary" onclick="window.recommendationsModule.getRecommendations()">
                    <i class="fas fa-redo"></i> Try Again
                </button>
            </div>
        `;
    }

    sanitize(str) {
        if (!str) return '';
        const temp = document.createElement('div');
        temp.textContent = str;
        return temp.innerHTML;
    }

    // Export recommendations data
    exportRecommendations() {
        if (this.currentRecommendations.length === 0) {
            window.discoveryApp.showToast('No recommendations to export', 'warning');
            return;
        }

        const data = {
            timestamp: new Date().toISOString(),
            recommendations: this.currentRecommendations
        };

        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `music-recommendations-${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        URL.revokeObjectURL(url);
        window.discoveryApp.showToast('Recommendations exported successfully', 'success');
    }
}

// Initialize the module
window.recommendationsModule = new RecommendationsModule();

// Add some CSS for validation states
const style = document.createElement('style');
style.textContent = `
    .input-group input.valid {
        border-color: var(--success-color);
    }

    .input-group input.invalid {
        border-color: var(--error-color);
    }

    .recommendations-header {
        text-align: center;
        margin-bottom: 30px;
        padding-bottom: 20px;
        border-bottom: 1px solid var(--border-color);
    }

    .recommendations-header h3 {
        color: var(--primary-color);
        margin-bottom: 10px;
    }

    .recommendations-grid {
        display: grid;
        gap: 20px;
    }

    .recommendation-actions {
        margin-top: 15px;
        padding-top: 15px;
        border-top: 1px solid var(--border-color);
    }

    .btn-sm {
        padding: 8px 16px;
        font-size: 0.9rem;
    }

    .empty-state, .error-state {
        text-align: center;
        padding: 60px 20px;
        color: var(--text-muted);
    }

    .empty-state h3, .error-state h3 {
        margin: 20px 0;
        color: var(--text-light);
    }

    .empty-suggestions {
        margin-top: 30px;
        text-align: left;
        max-width: 400px;
        margin-left: auto;
        margin-right: auto;
    }

    .empty-suggestions ul {
        list-style-position: inside;
    }

    .empty-suggestions li {
        margin: 8px 0;
    }

    .recommendation-card.selected {
        border-color: var(--accent-color);
        background: linear-gradient(135deg, var(--dark-bg), var(--darker-bg));
    }
`;
document.head.appendChild(style);
