/**
 * The capability token for the page currently being viewed, if any.
 *
 * P0-SEC-005 closed `/files/*`. A signed-in owner is fine without this: the
 * session cookie rides along on `fetch(..., { credentials: "include" })` and
 * on a plain `<img src>`. It does NOT ride along on a three.js texture or
 * mesh load by default - those are CORS requests, and localhost:3001 and
 * localhost:8000 are different origins - so the loaders are told to send it
 * (walkthrough3d/api/loader-credentials.ts). Found the hard way: every
 * `/files/materials/**` load answered 401 in the signed-in 3D viewer.
 *
 * A share-link visitor has no cookie at all. Their only credential is the `k`
 * in the page URL, and an `<img>` or a WebGL texture load cannot carry a
 * header. So the token has to go into the query string of every asset URL, and
 * something has to know it where those URLs are built — deep inside a panorama
 * renderer that has no business taking a token as a prop.
 *
 * Hence one module-scoped value, set once by the share page. Deliberately NOT
 * in localStorage or a cookie: it lives exactly as long as the page does, so
 * closing the tab is the end of it and it can never leak into another tab.
 */

let current: string | null = null;

export function setShareToken(token: string | null | undefined): void {
  current = token || null;
}

export function getShareToken(): string | null {
  return current;
}

/**
 * Append the share token to a URL, if there is one.
 *
 * A signed-in owner has no token and gets the URL untouched — their cookie
 * already authorises the request, and adding an empty `k` would only make the
 * server look up a token that does not exist.
 */
export function withShareToken(url: string): string {
  if (!current) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}k=${encodeURIComponent(current)}`;
}
