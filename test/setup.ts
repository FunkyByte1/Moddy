import { vi } from 'vitest';

// The Decky loader injects @decky/ui and @decky/api at runtime; they aren't usable in a plain test
// process. Blanket-mock them so any module under test imports cleanly without enumerating exports.
//
// vi.mock is hoisted above normal declarations, so the factory is built inside vi.hoisted (which is
// hoisted too) rather than referencing an outer const.
const { moduleStub } = vi.hoisted(() => {
  // A callable, infinitely-chainable stub for an individual export (callable(), a component, etc.).
  // Pure functions under test never invoke these — the stub just keeps the import graph alive.
  const leaf: any = () => new Proxy(() => null, { get: () => leaf() });
  // The module namespace itself MUST be an object (Vitest rejects a function as the factory return).
  const moduleStub = () =>
    new Proxy({}, {
      // `has` so Vitest's named-export existence check (`'callable' in mod`) passes for any name.
      has: () => true,
      get: (_target, prop) => {
        if (prop === 'then') return undefined; // never look like a thenable (dynamic-import safety)
        if (prop === '__esModule') return true; // esModuleInterop default-import interop
        if (typeof prop === 'symbol') return undefined;
        return leaf();
      },
    });
  return { moduleStub };
});

vi.mock('@decky/ui', moduleStub);
vi.mock('@decky/api', moduleStub);
