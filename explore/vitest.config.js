import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        environment: 'jsdom',
        include: ['__tests__/**/*.test.js'],
        coverage: {
            provider: 'v8',
            include: ['static/js/**/*.js'],
            reporter: ['text', 'json', 'lcov'],
            reportsDirectory: 'coverage',
        },
    },
});
