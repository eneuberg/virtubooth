import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config.ts';

export default defineConfig((env) =>
  mergeConfig(
    viteConfig(env),
    defineConfig({
      test: {
        environment: 'happy-dom',
        include: ['src/**/*.test.{ts,tsx}', 'scripts/**/*.test.mjs'],
        setupFiles: ['src/test/setup.ts'],
        restoreMocks: true,
        unstubGlobals: true,
      },
    }),
  ),
);
