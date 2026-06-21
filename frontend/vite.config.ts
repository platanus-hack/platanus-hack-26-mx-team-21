import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@db-types": fileURLToPath(
        new URL("../packages/db-types/database.ts", import.meta.url),
      ),
    },
  },
  server: {
    port: 5173,
    // allow importing the shared db-types package from outside the app root
    fs: { allow: [".", "..", "../packages"] },
  },
});
