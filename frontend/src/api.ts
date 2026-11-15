/**
 * fetch wrapper for your own API.
 *
 * Adds the X-Requested-With header the backend requires on state-changing requests
 * (its CSRF defence). Cookies are sent automatically because requests are same-origin.
 * Use this for every non-GET call you add.
 */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-Requested-With", "fetch");
  }
  return fetch(path, { ...init, headers });
}
