import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { request } from '../../api/client';
import { RepositoryManagement } from './RepositoryManagement';

vi.mock('../../api/client', () => ({ request: vi.fn() }));
const api = vi.mocked(request);

beforeEach(() => api.mockReset());

test('edits an existing repository through its PATCH endpoint', async () => {
  api.mockResolvedValueOnce({
    items: [{ id: 'repo-1', owner: 'ShaliniBangamuwage', name: 'my-portfolio', fullName: 'ShaliniBangamuwage/my-portfolio', defaultBranch: 'main', active: true, failureCount: 0 }],
  });
  api.mockResolvedValueOnce({});
  api.mockResolvedValueOnce({ items: [] });

  render(<RepositoryManagement go={vi.fn()} />);
  await screen.findByText('ShaliniBangamuwage/my-portfolio');
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  fireEvent.change(screen.getByPlaceholderText('Generated if omitted'), { target: { value: 'new-webhook-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save repository' }));

  await waitFor(() => expect(api).toHaveBeenCalledWith('/repositories/repo-1', expect.objectContaining({
    method: 'PATCH',
    body: expect.stringContaining('new-webhook-secret'),
  })));
  expect(api.mock.calls.some(([path, options]) => path === '/repositories' && options?.method === 'POST')).toBe(false);
});

test('viewing an authorized repository keeps the list rendered', async () => {
  api.mockResolvedValueOnce({ items: [] });
  api.mockResolvedValueOnce({ items: [{ id: 'gh-1', name: 'my-portfolio', fullName: 'ShaliniBangamuwage/my-portfolio', owner: 'ShaliniBangamuwage', private: true, defaultBranch: 'main', htmlUrl: 'https://github.com/ShaliniBangamuwage/my-portfolio', installationId: 'install-1', alreadyConnected: false }] });

  render(<RepositoryManagement go={vi.fn()} />);
  await screen.findByText('ShaliniBangamuwage/my-portfolio');
  fireEvent.click(screen.getByRole('link', { name: /View/ }));

  expect(screen.getByText('ShaliniBangamuwage/my-portfolio')).toBeInTheDocument();
  expect(api.mock.calls.filter(([path]) => path === '/github/app/repositories')).toHaveLength(1);
});

test('connecting my-portfolio keeps authorized repositories and marks it connected', async () => {
  api.mockResolvedValueOnce({ items: [] });
  api.mockResolvedValueOnce({ items: [{ id: 'gh-1', name: 'my-portfolio', fullName: 'ShaliniBangamuwage/my-portfolio', owner: 'ShaliniBangamuwage', private: true, defaultBranch: 'main', htmlUrl: 'https://github.com/ShaliniBangamuwage/my-portfolio', installationId: 'install-1', alreadyConnected: false }] });
  api.mockResolvedValueOnce({ id: 'repo-1' });
  api.mockResolvedValueOnce({ items: [{ id: 'repo-1', owner: 'ShaliniBangamuwage', name: 'my-portfolio', fullName: 'ShaliniBangamuwage/my-portfolio', defaultBranch: 'main', active: true, failureCount: 0 }] });

  render(<RepositoryManagement go={vi.fn()} />);
  await screen.findByText('ShaliniBangamuwage/my-portfolio');
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

  await waitFor(() => expect(api).toHaveBeenCalledWith('/github/app/repositories/connect', expect.objectContaining({ method: 'POST', body: JSON.stringify({ installation_id: 'install-1', repository_id: 'gh-1' }) })));
  expect(await screen.findByRole('button', { name: 'Connected' })).toBeInTheDocument();
  expect(screen.getAllByText('ShaliniBangamuwage/my-portfolio')).toHaveLength(2);
});