# Music Discovery Playground

The Music Discovery Playground is an interactive web interface for exploring music data from the Discogs database. It provides multiple visualization modes and analysis tools to discover musical connections and trends.

## Features

### 1. Graph Explorer

- Interactive network visualization of artists, releases, and labels
- Explore connections between music entities
- Adjustable exploration depth and node limits
- Real-time graph manipulation with zoom and drag capabilities

### 2. Music Journey

- Find musical paths between any two artists
- Visualize the connections through collaborations, labels, and releases
- Timeline view showing the chronological progression
- Export journey data for further analysis

### 3. Trend Analysis

- Analyze music trends over time
- Genre evolution tracking
- Artist productivity metrics
- Label activity patterns
- Interactive time-series visualizations

### 4. Similarity Heatmap

- Visual representation of artist similarities
- Genre overlap analysis
- Collaboration network mapping
- Style-based connections

## Getting Started

1. **Access the Playground**

   - Navigate to http://localhost:8005 after starting the discovery service
   - The interface loads automatically with the Graph Explorer view

1. **Search for Music**

   - Use the search bar to find artists, releases, or labels
   - Results appear in real-time as you type
   - Click on any result to explore further

1. **Navigate Views**

   - Use the navigation menu to switch between different visualizations
   - Each view has its own controls in the sidebar
   - The info panel shows details about selected items

## API Endpoints

The playground extends the Discovery Service with these endpoints:

- `GET /api/search` - Search for music entities
- `GET /api/graph` - Get graph data for visualization
- `POST /api/journey` - Find paths between artists
- `GET /api/trends` - Get trend analysis data
- `GET /api/heatmap` - Get similarity heatmap data
- `GET /api/artists/{id}` - Get detailed artist information

## WebSocket Support

Real-time updates are supported through WebSocket connections at `/ws`. This enables:

- Live data updates across all connected clients
- Collaborative exploration sessions
- Performance monitoring

## Technical Stack

- **Frontend**: HTML5, Bootstrap 5, D3.js for visualizations
- **Backend**: FastAPI with async support
- **Database**: Neo4j for graph data, PostgreSQL for structured data
- **Real-time**: WebSocket for live updates

## Development

To extend the playground:

1. **Add New Visualizations**

   - Create a new JavaScript module in `/static/js/`
   - Implement the visualization class with standard methods
   - Register it in `playground.js`

1. **Add API Endpoints**

   - Extend `playground_api.py` with new methods
   - Add route handlers in `discovery.py`
   - Update the API client in `api-client.js`

1. **Customize Styling**

   - Modify `/static/css/playground.css`
   - Follow the existing theme and color scheme

## Performance Tips

- Limit graph exploration depth for large datasets
- Use the node limit slider to control visualization complexity
- Enable caching for frequently accessed data (coming soon)
- Close unused browser tabs to free resources

## Examples and Tutorials

See **[examples.md](examples.md)** for detailed usage examples, workflows, and tutorials including:

- Exploring artist connections and influence networks
- Finding musical journeys between artists
- Analyzing music trends over decades
- Creating similarity heatmaps and collaboration networks
- API usage examples and WebSocket integration
- Performance optimization tips and troubleshooting

## Future Enhancements

- Export visualizations as images or PDFs
- Collaborative playlists based on discoveries
- Machine learning-powered recommendations
- Advanced filtering and search options
- Custom query builder interface
