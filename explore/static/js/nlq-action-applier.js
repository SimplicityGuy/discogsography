const ORDER = [
    'switch_pane',
    'set_trend_range',
    'filter_graph',
    'seed_graph',
    'find_path',
    'show_credits',
    'highlight_path',
    'focus_node',
    'open_insight_tile',
    'suggest_followups',
];

const MAX_LEN = 256;
const VALID_ENTITY_TYPES = new Set(['artist', 'label', 'genre', 'style', 'release']);
const VALID_PANES = new Set(['explore', 'trends', 'insights', 'genres', 'credits']);

function capStr(value) {
    return typeof value === 'string' ? value.slice(0, MAX_LEN) : value;
}

function sanitizeSeedGraph(action) {
    const entities = Array.isArray(action.entities) ? action.entities : [];
    const clean = entities
        .filter((e) => e && typeof e.name === 'string' && e.name.length > 0 && VALID_ENTITY_TYPES.has(e.entity_type))
        .map((e) => ({ name: capStr(e.name), entity_type: e.entity_type }));
    return { type: 'seed_graph', entities: clean, replace: !!action.replace };
}

function sanitizeSwitchPane(action) {
    if (!VALID_PANES.has(action.pane)) return null;
    return { type: 'switch_pane', pane: action.pane };
}

function sanitizeFocusNode(action) {
    if (typeof action.name !== 'string' || !VALID_ENTITY_TYPES.has(action.entity_type)) return null;
    return { type: 'focus_node', name: capStr(action.name), entity_type: action.entity_type };
}

const SANITIZERS = {
    seed_graph: sanitizeSeedGraph,
    switch_pane: sanitizeSwitchPane,
    focus_node: sanitizeFocusNode,
    highlight_path: (a) => ({ type: 'highlight_path', nodes: (a.nodes || []).map(capStr).filter(Boolean) }),
    filter_graph: (a) => ({ type: 'filter_graph', by: a.by, value: a.value }),
    find_path: (a) => ({ type: 'find_path', from: capStr(a.from), to: capStr(a.to), from_type: a.from_type, to_type: a.to_type }),
    show_credits: (a) => ({ type: 'show_credits', name: capStr(a.name), entity_type: a.entity_type }),
    open_insight_tile: (a) => ({ type: 'open_insight_tile', tile_id: capStr(a.tile_id) }),
    set_trend_range: (a) => ({ type: 'set_trend_range', from: capStr(a.from), to: capStr(a.to) }),
    suggest_followups: (a) => ({ type: 'suggest_followups', queries: (a.queries || []).map(capStr) }),
};

export class NlqActionApplier {
    constructor({ handlers, snapshotter }) {
        this.handlers = handlers;
        this.snapshotter = snapshotter;
        this._lastSnapshot = null;
    }

    apply(rawActions) {
        const sorted = [...(rawActions || [])].sort((a, b) => {
            const ai = ORDER.indexOf(a.type);
            const bi = ORDER.indexOf(b.type);
            return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
        });

        this._lastSnapshot = this.snapshotter.capture();
        let applied = 0;
        let skipped = 0;

        for (const raw of sorted) {
            const sanitizer = SANITIZERS[raw.type];
            if (!sanitizer) {
                console.warn('🤷 unknown NLQ action type', raw.type);
                skipped += 1;
                continue;
            }
            const clean = sanitizer(raw);
            if (!clean) {
                skipped += 1;
                continue;
            }
            const handler = this._handlerFor(clean.type);
            if (!handler) {
                skipped += 1;
                continue;
            }
            try {
                const { type: _type, ...payload } = clean;
                handler(payload);
                applied += 1;
            } catch (err) {
                console.error('❌ NLQ action handler failed', clean.type, err);
                skipped += 1;
            }
        }

        return { applied, skipped };
    }

    _handlerFor(type) {
        const map = {
            switch_pane: this.handlers.switchPane,
            set_trend_range: this.handlers.setTrendRange,
            filter_graph: this.handlers.filterGraph,
            seed_graph: this.handlers.seedGraph,
            find_path: this.handlers.findPath,
            show_credits: this.handlers.showCredits,
            highlight_path: this.handlers.highlightPath,
            focus_node: this.handlers.focusNode,
            open_insight_tile: this.handlers.openInsightTile,
            suggest_followups: this.handlers.suggestFollowups,
        };
        return map[type];
    }

    undo() {
        if (this._lastSnapshot != null) {
            this.snapshotter.restore(this._lastSnapshot);
            this._lastSnapshot = null;
        }
    }
}
