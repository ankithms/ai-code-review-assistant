export function isDemoMode() {
  return window.location.pathname === "/demo" || window.location.pathname.startsWith("/demo/");
}
