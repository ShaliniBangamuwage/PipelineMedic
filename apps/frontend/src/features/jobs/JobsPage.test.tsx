import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { JobsPage } from './JobsPage';
import { request } from '../../api/client';

vi.mock('../../api/client', () => ({ request: vi.fn() }));
const api = vi.mocked(request);

beforeEach(() => { api.mockReset(); });

test('renders jobs and permits retry for developers', async () => {
  api.mockResolvedValueOnce({ items: [{ id: 'job-1', kind: 'workflow_run', status: 'FAILED', attempts: 3, errorCode: null, nextRetryAt: null, createdAt: null }] });
  api.mockResolvedValueOnce({});
  render(<JobsPage role="DEVELOPER" />);
  expect(await screen.findByText('workflow_run')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry workflow_run' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/jobs/job-1/retry', { method: 'POST' }));
});

test('does not show retry controls to viewers', async () => {
  api.mockResolvedValue({ items: [{ id: 'job-2', kind: 'workflow_run', status: 'FAILED', attempts: 1, errorCode: null, nextRetryAt: null, createdAt: null }] });
  render(<JobsPage role="VIEWER" />);
  await screen.findByText('workflow_run');
  expect(screen.queryByRole('button', { name: 'Retry workflow_run' })).not.toBeInTheDocument();
});
