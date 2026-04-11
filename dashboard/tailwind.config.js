/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: "class",
    content: ["./static/index.html", "./static/dashboard.js", "./static/admin.html", "./static/admin.js"],
    plugins: [require("@tailwindcss/forms")],
};
