import type * as THREE from "three";

/**
 * Make a three.js loader send the session cookie.
 *
 * The API calls use `fetch(..., { credentials: "include" })` and carry the
 * httpOnly `allure_session` cookie. Texture and mesh loads did not: three.js
 * requests images with `crossOrigin = "anonymous"` (a CORS request, needed
 * before the pixels may be used in WebGL) and files with `withCredentials =
 * false`, and a CORS request from localhost:3001 to localhost:8000 - a
 * different ORIGIN, whatever the site - omits cookies unless asked. So every
 * `/files/materials/**` and `/files/assets-web/**` load answered 401 for a
 * signed-in owner once P0-SEC-005 closed `/files/*`, and the 3D viewer showed
 * a runtime error instead of a room (found in the browser, 2026-09-23).
 *
 * The backend already allows credentials for the studio origin (CORS
 * `allow_credentials=True`), which is what the API relies on. A share-link
 * visitor has no cookie; their `?k=` token still rides in the URL and the
 * credentials flag is harmless.
 */
export function withSessionCredentials<L extends THREE.Loader>(loader: L): L {
  loader.setCrossOrigin("use-credentials");
  loader.setWithCredentials(true);
  return loader;
}
