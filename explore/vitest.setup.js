// Node 25+ ships an experimental Web Storage API that creates a stub
// `localStorage` / `sessionStorage` (with no Storage prototype methods)
// when `--localstorage-file` is not set. That stub shadows the working
// Storage instances jsdom installs on `window`. Restore jsdom's real
// Storage objects (which it stashes on `_localStorage` / `_sessionStorage`)
// so tests can call `localStorage.clear()`, `setItem()`, etc.
if (typeof globalThis._localStorage !== 'undefined' && globalThis._localStorage instanceof Storage) {
    Object.defineProperty(globalThis, 'localStorage', {
        configurable: true,
        get() {
            return globalThis._localStorage;
        },
    });
}
if (typeof globalThis._sessionStorage !== 'undefined' && globalThis._sessionStorage instanceof Storage) {
    Object.defineProperty(globalThis, 'sessionStorage', {
        configurable: true,
        get() {
            return globalThis._sessionStorage;
        },
    });
}
