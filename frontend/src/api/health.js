// Kept apart from the endpoints so the app shell, which loads on every page,
// does not pull in the response schemas.
export async function checkHealth() {
  try {
    const base = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
    const response = await fetch(`${base}/health`, { signal: AbortSignal.timeout(8000) });
    return response.ok;
  } catch {
    return false;
  }
}
