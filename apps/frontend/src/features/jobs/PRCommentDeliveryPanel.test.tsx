import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { request } from '../../api/client';
import { PRCommentDeliveryPanel } from './PRCommentDeliveryPanel';
vi.mock('../../api/client', () => ({ request: vi.fn() }));
const api = vi.mocked(request);
beforeEach(() => api.mockReset());
test('renders delivered status and safe GitHub link', async () => {
  api.mockResolvedValue({ status: 'DELIVERED', pullRequestNumber: 7, githubCommentUrl: 'https://github.com/acme/app/issues/7#issuecomment-1', attemptCount: 1, errorCode: null, errorMessage: null, createdAt: null, deliveredAt: '2026-08-26T00:00:00Z' });
  render(<PRCommentDeliveryPanel analysisId="a1" role="VIEWER" />);
  expect(await screen.findByText('DELIVERED')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Open GitHub comment' })).toHaveAttribute('target', '_blank');
});
test('shows retry for failed delivery and refreshes', async () => {
  api.mockResolvedValueOnce({ status: 'FAILED', pullRequestNumber: null, githubCommentUrl: null, attemptCount: 3, errorCode: 'PERMISSION', errorMessage: 'Permission denied', createdAt: null });
  api.mockResolvedValueOnce({ status: 'QUEUED', pullRequestNumber: null, githubCommentUrl: null, attemptCount: 3, errorCode: null, errorMessage: null, createdAt: null });
  render(<PRCommentDeliveryPanel analysisId="a2" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry delivery' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/analyses/a2/pr-comment/retry', { method: 'POST' }));
});
