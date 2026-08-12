export const PAGE_SIZE = 25;

export function paginate(items, requestedPage, pageSize = PAGE_SIZE) {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const page = Math.min(Math.max(1, requestedPage), totalPages);
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page,
    pageSize,
    totalItems: items.length,
    totalPages,
  };
}

export function decisionTiming(startedAt, completedAt = performance.now()) {
  const elapsedSeconds = Math.max(0, (completedAt - startedAt) / 1000);
  return {
    elapsedSeconds,
    insideTarget: elapsedSeconds <= 20,
  };
}

export function title(value) {
  return String(value ?? "—")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/(^| )\w/g, (character) => character.toUpperCase());
}
