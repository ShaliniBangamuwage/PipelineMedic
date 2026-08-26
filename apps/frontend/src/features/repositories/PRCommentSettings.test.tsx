import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { request } from '../../api/client';
import { PRCommentSettings } from './PRCommentSettings';
vi.mock('../../api/client', () => ({ request: vi.fn() }));
const api = vi.mocked(request);
beforeEach(() => api.mockReset());
test('loads and saves editable settings', async () => {
  api.mockResolvedValueOnce({ pr_comments_enabled: false, pr_comment_min_confidence: .8, pr_comment_allowed_branches: 'main', pr_comment_include_similar_incident: true, pr_comment_include_patch: false });
  api.mockResolvedValueOnce({});
  render(<PRCommentSettings repositoryId="repo-1" role="ADMIN" />);
  expect(await screen.findByText('Pull-request comments')).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('Enable PR comments'));
  fireEvent.click(screen.getByRole('button', { name: 'Save PR comment settings' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/repositories/repo-1/pr-comment-settings', expect.objectContaining({ method: 'PATCH' })));
});
test('keeps patch disabled and viewers read only', async () => {
  api.mockResolvedValue({ pr_comments_enabled: true, pr_comment_min_confidence: .9, pr_comment_allowed_branches: 'main', pr_comment_include_similar_incident: true, pr_comment_include_patch: false });
  render(<PRCommentSettings repositoryId="repo-2" role="VIEWER" />);
  await screen.findByText('Read only');
  expect(screen.getByLabelText(/Include suggested patch/)).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Save PR comment settings' })).not.toBeInTheDocument();
});
