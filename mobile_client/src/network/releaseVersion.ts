export const MOBILE_CLIENT_BUILD_ID = process.env.EXPO_PUBLIC_PLAYAURAL_BUILD_ID || "";

export function applicationUpdateRequired(
  info: { version?: string; build_id?: string } | undefined,
  currentVersion: string,
  currentBuild = MOBILE_CLIENT_BUILD_ID,
  development = typeof __DEV__ !== "undefined" && __DEV__,
): boolean {
  const version = info?.version?.trim();
  if (!version) return false;
  if (version !== currentVersion) return true;
  if (development && !currentBuild) return false;
  const expected = info?.build_id;
  return typeof expected === "string" && /^[0-9a-f]{40}$/.test(expected) && expected !== currentBuild;
}
