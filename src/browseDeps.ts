import { ThunderstorePackage } from './types';
import { stripVersion } from './modGraph';

/**
 * Every dependency id reachable from `rootRefs` through the catalog — the roots themselves plus
 * their FULL transitive dependency tree — with Thunderstore version suffixes stripped and ids
 * lowercased. Cycle-guarded by the result set; a Map keeps the recursive lookups O(1).
 *
 * BrowseTab feeds this the in-flight installs (active queue jobs + just-clicked refs) to know which
 * dependency ids are already being installed, so it doesn't re-prompt for them. The walk must be
 * transitive because the backend install cascade is: a dependency an in-flight mod pulls in
 * *transitively* (but a second mod declares directly) is still covered.
 */
export function transitiveCatalogDeps(
  catalog: ThunderstorePackage[],
  rootRefs: Iterable<string>,
): Set<string> {
  const byId = new Map(catalog.map(c => [c.full_name.toLowerCase(), c]));
  const ids = new Set<string>();
  const visit = (id: string) => {
    if (ids.has(id)) return;
    ids.add(id);
    for (const dep of byId.get(id)?.latest.dependencies ?? []) {
      visit(stripVersion(dep).toLowerCase());
    }
  };
  for (const ref of rootRefs) visit(ref.toLowerCase());
  return ids;
}
