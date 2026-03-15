import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { loadScriptDirect } from './helpers.js';

/**
 * Set up the DOM elements required by trends.js.
 */
function setupTrendsDOM() {
    document.body.textContent = '';

    const chart = document.createElement('div');
    chart.id = 'trendsChart';
    document.body.appendChild(chart);

    const placeholder = document.createElement('div');
    placeholder.id = 'trendsPlaceholder';
    document.body.appendChild(placeholder);
}

describe('TrendsChart', () => {
    let chart;
    let PlotlyMock;

    beforeAll(() => {
        delete globalThis.window;
        globalThis.window = globalThis;
        // Load the class into global scope once
        loadScriptDirect('trends.js');
    });

    beforeEach(() => {
        setupTrendsDOM();

        // Stub Plotly
        PlotlyMock = {
            newPlot: vi.fn(),
            addTraces: vi.fn(),
            deleteTraces: vi.fn(),
            purge: vi.fn(),
        };
        globalThis.Plotly = PlotlyMock;

        chart = new TrendsChart('trendsChart');
    });

    describe('constructor', () => {
        it('should initialize with hasData false', () => {
            expect(chart.hasData).toBe(false);
        });

        it('should initialize with hasComparison false', () => {
            expect(chart.hasComparison).toBe(false);
        });

        it('should reference the container element', () => {
            expect(chart.container).toBe(document.getElementById('trendsChart'));
        });

        it('should reference the placeholder element', () => {
            expect(chart.placeholder).toBe(document.getElementById('trendsPlaceholder'));
        });
    });

    describe('render', () => {
        const validData = {
            name: 'Radiohead',
            type: 'artist',
            data: [
                { year: 1993, count: 1 },
                { year: 1995, count: 2 },
                { year: 2000, count: 3 },
            ],
        };

        it('should call Plotly.newPlot with correct trace', () => {
            chart.render(validData);

            expect(PlotlyMock.newPlot).toHaveBeenCalledOnce();
            const [container, traces] = PlotlyMock.newPlot.mock.calls[0];
            expect(container).toBe(document.getElementById('trendsChart'));
            expect(traces[0].x).toEqual([1993, 1995, 2000]);
            expect(traces[0].y).toEqual([1, 2, 3]);
            expect(traces[0].name).toBe('Radiohead releases');
        });

        it('should set hasData to true after render', () => {
            chart.render(validData);
            expect(chart.hasData).toBe(true);
        });

        it('should hide placeholder after render', () => {
            const placeholder = document.getElementById('trendsPlaceholder');
            placeholder.classList.remove('hidden');

            chart.render(validData);

            expect(placeholder.classList.contains('hidden')).toBe(true);
        });

        it('should call clear (Plotly.purge) when data is null', () => {
            chart.render(null);
            expect(PlotlyMock.purge).toHaveBeenCalled();
        });

        it('should call clear when data.data is empty', () => {
            chart.render({ name: 'Test', data: [] });
            expect(PlotlyMock.purge).toHaveBeenCalled();
        });

        it('should call clear when data.data is missing', () => {
            chart.render({ name: 'Test' });
            expect(PlotlyMock.purge).toHaveBeenCalled();
        });

        it('should pad x-axis range by 3 years on each side', () => {
            chart.render(validData);

            const layout = PlotlyMock.newPlot.mock.calls[0][2];
            // min year is 1993 - 3 = 1990, max year is 2000 + 3 = 2003
            expect(layout.xaxis.range[0]).toBe(1990);
            expect(layout.xaxis.range[1]).toBe(2003);
        });

        it('should use the title with entity name', () => {
            chart.render(validData);

            const layout = PlotlyMock.newPlot.mock.calls[0][2];
            expect(layout.title.text).toBe('Release Timeline: Radiohead');
        });

        it('should pass responsive config', () => {
            chart.render(validData);

            const config = PlotlyMock.newPlot.mock.calls[0][3];
            expect(config.responsive).toBe(true);
        });
    });

    describe('addComparison', () => {
        const primaryData = {
            name: 'Radiohead',
            type: 'artist',
            data: [{ year: 1993, count: 5 }],
        };

        const comparisonData = {
            name: 'Blur',
            type: 'artist',
            data: [{ year: 1993, count: 3 }, { year: 1995, count: 7 }],
        };

        it('should call Plotly.addTraces when hasData is true', () => {
            chart.render(primaryData);
            chart.addComparison(comparisonData);

            expect(PlotlyMock.addTraces).toHaveBeenCalledOnce();
        });

        it('should pass correct trace data to addTraces', () => {
            chart.render(primaryData);
            chart.addComparison(comparisonData);

            const trace = PlotlyMock.addTraces.mock.calls[0][1];
            expect(trace.x).toEqual([1993, 1995]);
            expect(trace.y).toEqual([3, 7]);
            expect(trace.name).toBe('Blur releases');
        });

        it('should set hasComparison to true', () => {
            chart.render(primaryData);
            chart.addComparison(comparisonData);

            expect(chart.hasComparison).toBe(true);
        });

        it('should NOT add comparison when hasData is false', () => {
            chart.addComparison(comparisonData);

            expect(PlotlyMock.addTraces).not.toHaveBeenCalled();
            expect(chart.hasComparison).toBe(false);
        });

        it('should NOT add comparison when comparison data is null', () => {
            chart.render(primaryData);
            chart.addComparison(null);

            expect(PlotlyMock.addTraces).not.toHaveBeenCalled();
        });

        it('should NOT add comparison when comparison data.data is empty', () => {
            chart.render(primaryData);
            chart.addComparison({ name: 'Empty', data: [] });

            expect(PlotlyMock.addTraces).not.toHaveBeenCalled();
        });
    });

    describe('clearComparison', () => {
        it('should call Plotly.deleteTraces when hasComparison is true', () => {
            const primaryData = {
                name: 'Radiohead',
                data: [{ year: 1993, count: 5 }],
            };
            const compData = {
                name: 'Blur',
                data: [{ year: 1993, count: 3 }],
            };
            chart.render(primaryData);
            chart.addComparison(compData);

            chart.clearComparison();

            expect(PlotlyMock.deleteTraces).toHaveBeenCalledWith(
                document.getElementById('trendsChart'),
                -1
            );
            expect(chart.hasComparison).toBe(false);
        });

        it('should NOT call deleteTraces when hasComparison is false', () => {
            chart.clearComparison();

            expect(PlotlyMock.deleteTraces).not.toHaveBeenCalled();
        });
    });

    describe('clear', () => {
        it('should call Plotly.purge', () => {
            chart.clear();
            expect(PlotlyMock.purge).toHaveBeenCalledWith(document.getElementById('trendsChart'));
        });

        it('should show placeholder', () => {
            const placeholder = document.getElementById('trendsPlaceholder');
            placeholder.classList.add('hidden');

            chart.clear();

            expect(placeholder.classList.contains('hidden')).toBe(false);
        });

        it('should reset hasData and hasComparison', () => {
            const data = { name: 'Radiohead', data: [{ year: 1993, count: 5 }] };
            const compData = { name: 'Blur', data: [{ year: 1993, count: 3 }] };
            chart.render(data);
            chart.addComparison(compData);

            chart.clear();

            expect(chart.hasData).toBe(false);
            expect(chart.hasComparison).toBe(false);
        });
    });
});
