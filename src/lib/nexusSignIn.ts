import { Navigation } from '@decky/ui';
import { nexusLoginStart, nexusLoginWait } from './api';

// The full Nexus OAuth sign-in flow (loopback PKCE): start the backend's one-shot listener, hand
// off to the in-app browser, await the redirect + token exchange. Shared by Settings and the
// Browse empty-state sign-in button so both offer the identical flow.

export function loginErrorMessage(reason?: string): string {
  switch (reason) {
    case 'port_in_use': return "Couldn't start sign-in — the local port is busy. Close any other sign-in attempt and try again.";
    case 'timeout': return 'Sign-in timed out or was cancelled.';
    case 'exchange_failed': return 'Nexus rejected the sign-in. Please try again.';
    case 'not_configured': return "Nexus sign-in isn't available in this build.";
    case 'access_denied': return 'Sign-in was declined.';
    default: return "Sign-in didn't complete. Please try again.";
  }
}

/** Run the sign-in end to end. Resolves to null on success, else a user-facing error message.
 *  Never rejects. */
export async function signInToNexus(): Promise<string | null> {
  try {
    const start = await nexusLoginStart();
    if (!start.ok || !start.authorize_url) return loginErrorMessage(start.reason);
    // Hand off to the browser; the backend's loopback listener catches the redirect.
    Navigation.NavigateToExternalWeb(start.authorize_url);
    const result = await nexusLoginWait();
    return result.ok ? null : loginErrorMessage(result.reason);
  } catch {
    return loginErrorMessage();
  }
}
