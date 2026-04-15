/**
 * Bridges NlqActionApplier actions to existing explore subsystems.
 *
 * Each handler takes the sanitized action payload (without `type`) and
 * dispatches to the right app/graph/insights method. All handlers are sync —
 * async subsystem calls fire-and-forget here; the applier waits for none of them.
 */

export function buildHandlers({ app }) {
    return {
        switchPane: ({ pane }) => {
            app._switchPane?.(pane);
        },
        setTrendRange: ({ from, to }) => {
            app.trends?.setRange?.(from, to);
        },
        filterGraph: ({ by, value }) => {
            app.graph?.applyFilter?.(by, value);
        },
        seedGraph: ({ entities, replace }) => {
            if (replace) app.graph?.clearAll?.();
            for (const ent of entities || []) {
                app.graph?.addEntity?.(ent);
            }
        },
        findPath: ({ from, to, from_type, to_type }) => {
            app.graph?.findPath?.({ from, to, fromType: from_type, toType: to_type });
        },
        showCredits: ({ name, entity_type }) => {
            app.credits?.show?.(name, entity_type);
        },
        highlightPath: ({ nodes }) => {
            app.graph?.highlightPath?.(nodes);
        },
        focusNode: ({ name, entity_type }) => {
            app._loadExplore?.(name, entity_type);
        },
        openInsightTile: ({ tile_id }) => {
            app.insights?.openTile?.(tile_id);
        },
        suggestFollowups: ({ queries }) => {
            app.nlq?.setFollowups?.(queries);
        },
    };
}

export function buildSnapshotter({ app }) {
    return {
        capture: () => ({
            pane: app.activePane,
            graph: app.graph?.snapshot?.() ?? null,
            trendRange: app.trends?.getRange?.() ?? null,
        }),
        restore: (snap) => {
            if (!snap) return;
            if (snap.pane) app._switchPane?.(snap.pane);
            if (snap.graph) app.graph?.restore?.(snap.graph);
            if (snap.trendRange) app.trends?.setRange?.(snap.trendRange.from, snap.trendRange.to);
        },
    };
}
