import { defineConfig } from 'orval'

// Generates typed React Query hooks from the FastAPI OpenAPI schema.
// Regenerate with `npm run codegen` after backend schema changes
// (re-export first: `uv run python -c "..."` -> ../openapi.json).
export default defineConfig({
  parkmap: {
    input: '../openapi.json',
    output: {
      target: './src/api/endpoints.ts',
      schemas: './src/api/model',
      client: 'react-query',
      httpClient: 'fetch',
      baseUrl: '/api',
      clean: true,
      prettier: false,
      override: {
        query: { useQuery: true },
      },
    },
  },
})
