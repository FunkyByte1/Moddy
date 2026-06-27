// Feature flags for work-in-progress functionality.
//
// SHOW_VERSION_OPTIONS gates the version-selection UI (choose/change a specific
// version of a mod or modloader, and the per-version delete picker). It's hidden
// for now because many distributors don't expose multiple versions; the backend
// and the modal components are all left intact, so flipping this to `true`
// restores the full feature. Revisit when versioning is properly designed.
export const SHOW_VERSION_OPTIONS: boolean = false;
