/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ["./static/index.html", "./static/js/**/*.js"],
    theme: {
        extend: {
            colors: {
                "bg-primary": "#0a0e27",
                "bg-secondary": "#151934",
                "bg-card": "#1e2139",
                "text-primary": "#e4e6eb",
                "text-secondary": "#b0b3b8",
                "accent-blue": "#1877f2",
                "accent-green": "#42b883",
                "accent-yellow": "#f0db4f",
                "accent-red": "#e74c3c",
                "border-color": "#2d3051",
            },
        },
    },
    plugins: [require("@tailwindcss/forms")],
};
