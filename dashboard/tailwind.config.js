/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: "class",
    content: ["./static/index.html", "./static/dashboard.js"],
    plugins: [require("@tailwindcss/forms")],
};
