import { describe, expect, it } from 'vitest';

describe('PipelineMedic frontend', () => {
  it('exposes the expected API fallback', () => {
    expect(import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').toContain('/api');
  });
});
