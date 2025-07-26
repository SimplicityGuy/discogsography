# Discovery Playground Examples

This document provides practical examples of using the Discovery Playground to explore music data.

## Getting Started

1. **Start the Services**

   ```bash
   docker-compose up -d
   ```

1. **Wait for Data Processing**

   - Check dashboard at http://localhost:8003 for processing status
   - Wait for some data to be processed before exploring

1. **Open the Playground**

   - Navigate to http://localhost:8005
   - The interface loads with the Graph Explorer view

## Example Workflows

### 1. Exploring Artist Connections

**Objective**: Discover how artists are connected through collaborations, labels, and releases.

**Steps**:

1. Search for "Miles Davis" in the search bar
1. Click "Explore" to load the graph visualization
1. Adjust the depth slider to 3 for deeper connections
1. Hover over nodes to see connection highlights
1. Click on connected artists to explore further

**What You'll See**:

- Blue nodes: Artists (Miles Davis at the center)
- Red nodes: Releases/Albums
- Gray nodes: Record labels
- Yellow nodes: Genres

**Insights Gained**:

- Direct collaborators and band members
- Record labels throughout career
- Genre evolution over time
- Influence network and connections

### 2. Finding Musical Journeys

**Objective**: Find the shortest path between two seemingly unconnected artists.

**Steps**:

1. Switch to "Music Journey" view
1. Search for "The Beatles" and select as start artist
1. Search for "Kendrick Lamar" and select as end artist
1. Click "Find Journey"
1. Explore the timeline view to see chronological progression

**Expected Results**:

- Path might go through: The Beatles → Producer → Hip-hop producer → Kendrick Lamar
- Or: The Beatles → Sample usage → Hip-hop artist → Kendrick Lamar
- Timeline shows the decades spanned in the connection

**Use Cases**:

- Music education and discovery
- Understanding genre evolution
- Finding surprising connections
- Creating themed playlists

### 3. Analyzing Music Trends

**Objective**: Visualize how musical genres evolved over decades.

**Steps**:

1. Go to "Trend Analysis" view
1. Select "Genre" as the trend type
1. Set start year to 1960 and end year to 2020
1. Click "Explore" to generate the visualization
1. Hover over different areas to see specific data points

**What to Look For**:

- Rise and fall of different genres
- Peak periods for specific styles
- Emergence of new genres
- Correlation between genres

**Insights**:

- Rock's dominance in the 70s-80s
- Hip-hop's emergence in the 80s-90s
- Electronic music growth in the 90s-2000s
- Genre fragmentation in modern times

### 4. Artist Similarity Analysis

**Objective**: Discover which artists share the most musical similarities.

**Steps**:

1. Navigate to "Similarity Heatmap" view
1. Select "Genre" similarity type
1. Adjust the "Top Artists" slider to 20
1. Click "Explore" to generate the heatmap
1. Click on high-intensity cells to explore connections

**Reading the Heatmap**:

- Darker colors = higher similarity
- Light/white areas = little to no similarity
- Diagonal shows perfect self-similarity
- Off-diagonal cells show cross-artist similarity

**Advanced Usage**:

- Try "Collaboration" mode to see who worked together
- Use results to discover new artists with similar styles
- Export interesting findings for further research

## API Examples

### Using the REST API Directly

```bash
# Search for artists
curl "http://localhost:8005/api/search?q=metallica&type=artist"

# Get graph data for an artist
curl "http://localhost:8005/api/graph?node_id=72872&depth=2&limit=50"

# Find journey between artists
curl -X POST "http://localhost:8005/api/journey" \
  -H "Content-Type: application/json" \
  -d '{"start_artist_id": "72872", "end_artist_id": "194", "max_depth": 5}'

# Get trend data
curl "http://localhost:8005/api/trends?type=genre&start_year=1970&end_year=2000"

# Get similarity heatmap
curl "http://localhost:8005/api/heatmap?type=genre&top_n=15"
```

### WebSocket Connection

```javascript
// Connect to real-time updates
const ws = new WebSocket('ws://localhost:8005/ws');

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('Real-time update:', data);
};

// Send a message
ws.send(JSON.stringify({
    type: 'subscribe',
    view: 'graph'
}));
```

## Performance Tips

### Optimizing Graph Exploration

- Start with depth 2, increase gradually
- Use node limits (50-100) for large graphs
- Clear cache if data seems stale
- Use specific searches rather than broad terms

### Trend Analysis Best Practices

- Limit year ranges for detailed analysis
- Use "Top N" slider to focus on major players
- Compare different trend types side by side
- Export data for deeper analysis

### Heatmap Usage

- Start with 15-20 artists for readability
- Use genre similarity for musical discovery
- Try collaboration mode for network analysis
- Click on cells to explore specific connections

## Troubleshooting

### Common Issues

**Empty Results**:

- Ensure data has been processed (check dashboard)
- Try broader search terms
- Reduce complexity (depth, limits)
- Check spelling of artist names

**Slow Performance**:

- Reduce node limits in graph explorer
- Use smaller year ranges in trends
- Lower the number of artists in heatmaps
- Check Redis cache connection

**Connection Errors**:

- Verify all services are running
- Check Docker container health
- Restart discovery service if needed
- Clear browser cache and cookies

### Performance Monitoring

Check the dashboard at http://localhost:8003 for:

- Service health status
- Cache hit rates
- Database connection status
- Processing queue lengths

## Advanced Features

### Custom Queries

The playground uses Neo4j Cypher queries. Advanced users can:

- Examine the source code for query patterns
- Use Neo4j Browser (http://localhost:7474) for custom queries
- Extend the API with additional endpoints

### Data Export

- Journey data can be exported as JSON
- Graph visualizations can be saved as images
- Trend data suitable for further analysis
- Heatmap data exportable for research

### Integration

- Use API endpoints in other applications
- Build custom dashboards with the data
- Create automated music discovery workflows
- Integrate with recommendation systems

## Educational Use Cases

### Music History Classes

- Trace genre evolution through decades
- Explore artist influence networks
- Analyze regional music movements
- Study technological impact on music

### Data Science Projects

- Network analysis of music industry
- Machine learning on music similarity
- Time series analysis of trends
- Graph theory applications

### Music Discovery

- Find new artists similar to favorites
- Explore musical connections
- Discover collaboration networks
- Understand genre relationships

## Contributing

To add new examples or improve existing ones:

1. Fork the repository
1. Add your examples to this file
1. Test with real data
1. Submit a pull request

For questions or suggestions, please open an issue on GitHub.
