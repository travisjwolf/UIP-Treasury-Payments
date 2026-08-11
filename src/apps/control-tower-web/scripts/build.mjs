import { cp, mkdir } from "node:fs/promises";

await mkdir("dist", { recursive: true });
await cp("app/index.html", "dist/index.html");
console.log("Built control-tower-web/dist/index.html");
