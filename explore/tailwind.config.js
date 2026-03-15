/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: "class",
    content: ["./static/index.html", "./static/js/**/*.js"],
    theme: {
        extend: {
            colors: {
                "bg-deep": "var(--bg-deep)",
                "card-bg": "var(--card-bg)",
                "inner-bg": "var(--inner-bg)",
                "bg-hover": "var(--bg-hover)",
                "text-high": "var(--text-high)",
                "text-mid": "var(--text-mid)",
                "text-dim": "var(--text-dim)",
                "text-muted": "var(--text-muted)",
                "blue-accent": "var(--blue-accent)",
                "purple-accent": "var(--purple-accent)",
                "accent-green": "var(--accent-green)",
                "accent-yellow": "var(--accent-yellow)",
                "accent-red": "var(--accent-red)",
                "border-color": "var(--border-color)",
            },
        },
    },
    plugins: [require("@tailwindcss/forms")],
};
