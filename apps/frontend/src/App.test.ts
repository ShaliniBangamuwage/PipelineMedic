import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ThemeToggle } from './App';

describe('PipelineMedic frontend', () => {
  it('exposes the expected API fallback', () => {
    expect(import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').toContain('/api');
  });

  it('persists and applies a selected theme', () => {
    localStorage.setItem('pipelinemedic.theme', 'dark');
    render(React.createElement(ThemeToggle));
    const select = screen.getByLabelText('Theme preference');
    expect(select).toHaveValue('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('uses the system theme when selected and follows prefers-color-scheme changes', () => {
    const listeners: Record<string, () => void> = {};
    const mediaQuery = {
      matches: true,
      media: '(prefers-color-scheme: light)',
      addEventListener: vi.fn((event: string, callback: () => void) => {
        listeners[event] = callback;
      }),
      removeEventListener: vi.fn((event: string) => {
        delete listeners[event];
      }),
    };
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn(() => mediaQuery),
    });
    localStorage.setItem('pipelinemedic.theme', 'system');

    render(React.createElement(ThemeToggle));

    expect(screen.getByLabelText('Theme preference')).toHaveValue('system');
    expect(document.documentElement.dataset.theme).toBe('light');

    mediaQuery.matches = false;
    listeners.change?.();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});
