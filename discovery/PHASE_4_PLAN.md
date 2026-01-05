# Phase 4: Integration & API Enhancement

**Goal**: Integrate all Phase 3 components into the main Discovery service with production-ready APIs, tests, and documentation.

## 4.1: API Integration (5 tasks)

### 4.1.1: ML & Recommendations API
**Files**: `discovery/discovery.py`, `discovery/api_ml.py` (new)
**Endpoints**:
- `POST /api/ml/recommend/collaborative` - Collaborative filtering recommendations
- `POST /api/ml/recommend/hybrid` - Hybrid multi-signal recommendations
- `POST /api/ml/recommend/explain` - Get recommendation explanations
- `GET /api/ml/metrics` - Recommender performance metrics
- `POST /api/ml/ab-test/assign` - A/B test variant assignment
- `GET /api/ml/ab-test/results` - A/B test performance results

**Integration Points**:
- Initialize collaborative_filtering.CollaborativeFilterEngine
- Initialize hybrid_recommender.HybridRecommender
- Initialize explainability.RecommendationExplainer
- Initialize ab_testing.ABTestManager
- Initialize recommender_metrics.RecommenderMetrics

### 4.1.2: Advanced Search API
**Files**: `discovery/discovery.py`, `discovery/api_search.py` (new)
**Endpoints**:
- `POST /api/search/fulltext` - PostgreSQL full-text search
- `POST /api/search/semantic` - ONNX semantic similarity search
- `POST /api/search/faceted` - Faceted search with dynamic filters
- `POST /api/search/autocomplete` - Search suggestions
- `GET /api/search/stats` - Search statistics

**Integration Points**:
- Initialize fulltext_search.FullTextSearch with PostgreSQL connection
- Initialize semantic_search.SemanticSearch with ONNX model
- Initialize faceted_search.FacetedSearch
- Initialize search_ranking.SearchRanker

### 4.1.3: Graph Analytics API
**Files**: `discovery/discovery.py`, `discovery/api_graph.py` (new)
**Endpoints**:
- `POST /api/graph/centrality` - Calculate centrality metrics
- `POST /api/graph/communities` - Detect communities
- `POST /api/graph/genre-evolution` - Genre evolution analysis
- `POST /api/graph/similarity-network` - Build similarity networks
- `GET /api/graph/analytics/stats` - Graph statistics

**Integration Points**:
- Initialize centrality_metrics.CentralityCalculator
- Initialize community_detection.CommunityDetector
- Initialize genre_evolution.GenreEvolutionTracker
- Initialize similarity_network.SimilarityNetworkBuilder

### 4.1.4: Real-Time Features API
**Files**: `discovery/discovery.py`, `discovery/api_realtime.py` (new)
**Endpoints**:
- `WebSocket /ws` - WebSocket connection for live updates
- `POST /api/realtime/trending` - Get current trending items
- `POST /api/realtime/subscribe` - Subscribe to channels
- `GET /api/realtime/stats` - WebSocket statistics
- `POST /api/cache/invalidate` - Manual cache invalidation

**Integration Points**:
- Initialize websocket_manager.WebSocketManager
- Initialize trend_tracking.TrendTracker
- Initialize cache_invalidation.CacheInvalidationManager
- Set up WebSocket routes and lifecycle

### 4.1.5: API Documentation Updates
**Files**: `discovery/discovery.py`, `discovery/openapi.py` (new)
**Tasks**:
- Add comprehensive OpenAPI schemas for all new endpoints
- Create Pydantic request/response models
- Add example requests and responses
- Update `/docs` endpoint with categories
- Add authentication/authorization docs (if applicable)

## 4.2: Testing & Validation (3 tasks)

### 4.2.1: E2E Tests for ML Features
**Files**: `tests/discovery/test_ml_integration.py` (new)
**Test Cases**:
- Test collaborative filtering with real graph data
- Test hybrid recommender with multiple signals
- Test explanation generation
- Test A/B test assignment and tracking
- Test metrics calculation and reporting
- Test error handling and edge cases

### 4.2.2: E2E Tests for Search Features
**Files**: `tests/discovery/test_search_integration.py` (new)
**Test Cases**:
- Test full-text search with various queries
- Test semantic search with embeddings
- Test faceted search with multiple filters
- Test autocomplete suggestions
- Test search ranking and relevance
- Test search statistics

### 4.2.3: E2E Tests for Graph Analytics
**Files**: `tests/discovery/test_graph_analytics_integration.py` (new)
**Test Cases**:
- Test centrality calculations on sample graphs
- Test community detection algorithms
- Test genre evolution tracking
- Test similarity network building
- Test graph statistics and metrics

## 4.3: UI Enhancement (2 tasks)

### 4.3.1: Dashboard Visualizations
**Files**: `discovery/static/js/ml-dashboard.js` (new), `discovery/static/index.html`
**Features**:
- ML recommendations panel with explanations
- Advanced search interface with facets
- Graph analytics visualizations (centrality, communities)
- A/B test results dashboard
- Real-time trending display

### 4.3.2: Real-Time Updates UI
**Files**: `discovery/static/js/websocket-client.js` (new)
**Features**:
- WebSocket connection management
- Live trending updates
- Real-time notifications
- Channel subscription interface
- Connection status indicator

## Implementation Order

1. **Phase 4.1.1** - ML & Recommendations API (highest value)
2. **Phase 4.1.2** - Advanced Search API (user-facing)
3. **Phase 4.1.4** - Real-Time Features API (enables live updates)
4. **Phase 4.1.3** - Graph Analytics API (analytical features)
5. **Phase 4.1.5** - API Documentation (developer experience)
6. **Phase 4.2.1-4.2.3** - E2E Testing (quality assurance)
7. **Phase 4.3.1-4.3.2** - UI Enhancement (user experience)

## Success Criteria

- ✅ All new endpoints integrated into discovery.py
- ✅ Full API documentation with examples
- ✅ ≥80% test coverage for new endpoints
- ✅ All E2E tests passing
- ✅ Performance benchmarks documented
- ✅ UI components functional and responsive
- ✅ No regressions in existing functionality

## Dependencies

- PostgreSQL connection for full-text search
- Neo4j connection for graph analytics
- ONNX models for semantic search
- WebSocket support in deployment environment

## Out of Scope (Phase 5)

- Blue/green deployments
- Feature flags
- Advanced monitoring dashboards
- Chaos engineering
- Disaster recovery
