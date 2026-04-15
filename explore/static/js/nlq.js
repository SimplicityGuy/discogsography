// explore/static/js/nlq.js
/**
 * NLQ orchestrator: pill + suggestions + action applier.
 *
 * Kept as a thin coordinator — business logic lives in the individual
 * components imported below. The pill now owns the full conversation
 * surface (collapsed → expanded → loading → answered), so there is no
 * separate summary strip.
 */
import { NlqActionApplier } from './nlq-action-applier.js';
import { NlqPill } from './nlq-pill.js';
import { buildHandlers, buildSnapshotter } from './nlq-handlers.js';

export function initNlq({ app, apiClient, mountId = 'nlqPillMount' }) {
    const handlers = buildHandlers({ app });
    const snapshotter = buildSnapshotter({ app });
    const applier = new NlqActionApplier({ handlers, snapshotter });

    const pill = new NlqPill({
        mountId,
        fetchSuggestions: (ctx) => apiClient.fetchNlqSuggestions(ctx),
        getContext: () => ({
            pane: app.activePane || 'explore',
            focus: app.currentEntity?.name ?? null,
            focusType: app.currentEntity?.type ?? null,
        }),
        onSubmit: (query) => _submit({ query, app, apiClient, applier, pill }),
        onUndo: () => applier.undo(),
        onEntityClick: (name, type) => app._loadExplore?.(name, type),
    });

    apiClient.checkNlqStatus().then((status) => {
        if (status && status.enabled === true) pill.mount();
    });
}

function _submit({ query, app, apiClient, applier, pill }) {
    pill.setLoading();

    const appliedActionTypes = [];

    apiClient.askNlqStream(
        query,
        {
            entity_id: app.currentEntity?.name ?? null,
            entity_type: app.currentEntity?.type ?? null,
        },
        () => {},
        (result) => {
            const actions = result.actions || [];
            appliedActionTypes.push(...actions.map((a) => a.type));
            const counts = applier.apply(actions);
            pill.setAnswer({
                summary: result.summary || '',
                entities: result.entities || [],
                appliedActions: appliedActionTypes,
                skipped: counts.skipped,
            });
        },
        (err) => {
            console.error('❌ NLQ stream error', err);
            pill.setAnswer({
                summary: 'Request failed — please try again.',
                entities: [],
                appliedActions: [],
                skipped: 0,
                isError: true,
            });
        },
    );
}

if (typeof window !== 'undefined') {
    window.NlqInit = initNlq;
}
