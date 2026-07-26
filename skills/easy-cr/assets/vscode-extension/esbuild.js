const esbuild = require("esbuild");

esbuild
  .build({
    entryPoints: ["src/extension.ts"],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "node18",
    external: ["vscode"],
    outfile: "dist/extension.js",
    sourcemap: false,
    minify: false,
    logLevel: "info",
  })
  .catch(() => process.exit(1));
