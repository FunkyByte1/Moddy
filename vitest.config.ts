import { defineConfig } from 'vitest/config';

// Frontend unit tests. The Decky runtime provides @decky/ui + @decky/api (and React) at load
// time; tests mock the Decky externals in test/setup.ts so pure logic can be imported in isolation.
export default defineConfig({
  test: {
    environment: 'happy-dom',
    globals: false, // tests import describe/it/expect explicitly
    include: ['src/**/*.test.ts'],
    setupFiles: ['./test/setup.ts'],
  },
});
