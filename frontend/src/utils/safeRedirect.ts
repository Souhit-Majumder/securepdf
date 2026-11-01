/**
 * Validates and extracts a safe internal application redirect path.
 * Strictly prevents open-redirect vulnerabilities:
 * - Rejects protocol-relative URLs (e.g. "//evil.com").
 * - Rejects backslash escapes (e.g. "/\\evil.com").
 * - Rejects arbitrary protocols (e.g. "javascript:", "http://", "https://").
 * - Only permits valid relative paths starting with a single "/".
 */
export function getSafeRedirect(redirectParam: string | null | undefined): string {
  if (!redirectParam) return "/";
  const trimmed = redirectParam.trim();
  if (
    trimmed.startsWith("/") &&
    !trimmed.startsWith("//") &&
    !trimmed.startsWith("/\\") &&
    !trimmed.includes("://") &&
    !trimmed.includes(":") &&
    !trimmed.includes("\n") &&
    !trimmed.includes("\r")
  ) {
    return trimmed;
  }
  return "/";
}
