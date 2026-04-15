// explore/static/js/nlq.js
/**
 * NLQ orchestrator: pill + suggestions + action applier + summary strip.
 *
 * Kept as a thin coordinator — business logic lives in the individual
 * components imported below.
 */
import { NlqActionApplier } from './nlq-action-applier.js';
import { NlqPill } from './nlq-pill.js';
import { NlqSuggestions } from './nlq-suggestions.js';
import { NlqSummaryStrip } from './nlq-summary-strip.js';
import { buildHandlers, buildSnapshotter } from './nlq-handlers.js';

export function initNlq({ app, apiClient, mountId = 'nlqPillMount', stripMountId = 'nlqStripMount' }) {
    const handlers = buildHandlers({ app });
    const snapshotter = buildSnapshotter({ app });
    const applier = new NlqActionApplier({ handlers, snapshotter });

    const stripEl = document.getElementById(stripMountId) || document.body;
    const strip = new NlqSummaryStrip({
        container: stripEl,
        onUndo: () => applier.undo(),
        onEntityClick: (name, type) => app._loadExplore?.(name, type),
    });

    const pill = new NlqPill({
        mountId,
        fetchSuggestions: (ctx) => apiClient.fetchNlqSuggestions(ctx),
        getContext: () => ({
            pane: app.activePane || 'explore',
            focus: app.currentEntity?.name ?? null,
            focusType: app.currentEntity?.type ?? null,
        }),
        onSubmit: (query) => _submit({ query, app, apiClient, applier, strip, pill }),
    });

    apiClient.checkNlqStatus().then((status) => {
        if (status && status.enabled === true) pill.mount();
    });
}

function _submit({ query, app, apiClient, applier, strip, pill }) {
    pill.setLoading?.(true);
    strip.hide();

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
            strip.show({
                summary: result.summary || '',
                entities: result.entities || [],
                appliedActions: appliedActionTypes,
                skipped: counts.skipped,
            });
            pill.setLoading?.(false);
            pill.flash?.(`✓ ${counts.applied} actions applied`);
        },
        (err) => {
            console.error('❌ NLQ stream error', err);
            pill.setLoading?.(false);
            strip.show({ summary: 'Request failed — please try again.', entities: [], appliedActions: [], skipped: 0 });
        },
    );
}

if (typeof window !== 'undefined') {
    window.NlqInit = initNlq;
}
