import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { request } from './api/client';
import { AuthenticatedAnalysisDetail, AuthenticatedOverview, AuthenticatedShell, InvitationAccept } from './AuthenticatedShell';

vi.mock('./api/client', () => ({ request: vi.fn() }));
const api = vi.mocked(request);

beforeEach(() => {
  api.mockReset();
  localStorage.clear();
});

test('renders organization-scoped failures and opens the analysis route', async () => {
  const go = vi.fn();
  api.mockResolvedValue({ items: [{ id: 'analysis-1', summary: 'Build failed', rootCause: 'Missing dependency', category: 'DEPENDENCY_ERROR', severity: 'HIGH', confidence: 0.9, repository: 'acme/app', branch: 'main', workflowName: 'CI', failedStep: 'Install', evidence: [], cleanedLog: 'npm install failed', resolved: false, createdAt: '2026-09-18T12:00:00Z', commitSha: 'abc' }] });
  render(<AuthenticatedOverview go={go} />);
  expect(await screen.findByText('Build failed')).toBeInTheDocument();
  expect(screen.getByText('acme/app · CI · main')).toBeInTheDocument();
});

test('replaces a stale organization with the first organization before loading overview data', async () => {
  localStorage.setItem('pipelinemedic.organization', 'stale-org');
  api.mockImplementation((path: string) => {
    if (path === '/auth/me') return Promise.resolve({ email: 'new@example.com', organizations: [{ id: 'org-b', role: 'OWNER' }] });
    if (path === '/organizations') return Promise.resolve({ items: [{ id: 'org-b', name: 'Org B' }] });
    if (path === '/dashboard/summary') return Promise.resolve({ totalFailures: 0, unresolvedFailures: 0, resolvedFailures: 0, resolutionRate: 0, averageConfidence: 0, repositoriesMonitored: 0, failureRateByRepository: [] });
    if (path === '/analyses') return Promise.resolve({ items: [], total: 0 });
    if (path === '/dashboard/trends') return Promise.resolve({ series: [], categories: [] });
    if (path === '/dashboard/insights') return Promise.resolve({ notifications: [] });
    return Promise.resolve({ items: [] });
  });

  window.history.pushState({}, '', '/overview');
  render(<AuthenticatedShell />);

  const organizationSelect = await screen.findByLabelText('Current organization');
  expect(organizationSelect).toHaveValue('org-b');
  expect(localStorage.getItem('pipelinemedic.organization')).toBe('org-b');
  await waitFor(() => expect(api.mock.calls.some(([path]) => path === '/dashboard/summary')).toBe(true));
});

test('renders a real settings page for the settings route', async () => {
  window.history.pushState({}, '', '/settings');
  api.mockImplementation((path: string) => {
    if (path === '/auth/me') {
      return Promise.resolve({ email: 'ops@example.com', organizations: [{ id: 'org-1', role: 'OWNER' }] });
    }
    if (path === '/organizations') {
      return Promise.resolve({ items: [{ id: 'org-1', name: 'Acme' }] });
    }
    if (path === '/dashboard/summary') {
      return Promise.resolve({ totalFailures: 3, resolvedFailures: 1, unresolvedFailures: 2, resolutionRate: 33.3, averageConfidence: 84.2, mostCommonCategory: 'DEPENDENCY_ERROR', repositoriesMonitored: 2, failureRateByRepository: [] });
    }
    if (path.startsWith('/analyses')) {
      return Promise.resolve({ items: [] });
    }
    return Promise.resolve({ items: [] });
  });

  render(<AuthenticatedShell />);

  expect(await screen.findByText('Theme preference')).toBeInTheDocument();
  expect(screen.getByLabelText('Theme preference')).toBeInTheDocument();
  expect(screen.queryByText('Detected failures')).not.toBeInTheDocument();
});

test('renders the overview dashboard with real metrics instead of a failure list', async () => {
  api.mockImplementation((path: string) => {
    if (path === '/auth/me') {
      return Promise.resolve({ email: 'ops@example.com', organizations: [{ id: 'org-1', role: 'OWNER' }] });
    }
    if (path === '/organizations') {
      return Promise.resolve({ items: [{ id: 'org-1', name: 'Acme' }] });
    }
    if (path === '/dashboard/summary') {
      return Promise.resolve({ totalFailures: 5, resolvedFailures: 2, unresolvedFailures: 3, resolutionRate: 40, averageConfidence: 88.5, repositoriesMonitored: 4, mostCommonCategory: 'DEPENDENCY_ERROR', failureRateByRepository: [{ repository: 'acme/app', failures: 2, failureRate: 40, averageConfidence: 91 }] });
    }
    if (path.startsWith('/analyses')) {
      return Promise.resolve({ items: [{ id: 'analysis-1', summary: 'Build failed', rootCause: 'Missing dependency', category: 'DEPENDENCY_ERROR', severity: 'HIGH', confidence: 0.9, repository: 'acme/app', branch: 'main', workflowName: 'CI', failedStep: 'Install', evidence: [], cleanedLog: 'npm install failed', resolved: false, createdAt: '2026-09-18T12:00:00Z', commitSha: 'abc' }] });
    }
    return Promise.resolve({ items: [] });
  });

  localStorage.setItem('pipelinemedic.organization', 'org-1');
  window.history.pushState({}, '', '/overview');
  render(<AuthenticatedShell />);

  expect(await screen.findByText('Failure Intelligence')).toBeInTheDocument();
  expect(screen.getByText('Open')).toBeInTheDocument();
  expect(screen.getByText('Resolved')).toBeInTheDocument();
  expect(await screen.findByText('5')).toBeInTheDocument();
});

test('renders stored analysis details without inventing recommendations', async () => {
  api.mockResolvedValueOnce({ id: 'analysis-1', summary: 'Build failed', rootCause: 'Missing dependency', category: 'DEPENDENCY_ERROR', severity: 'HIGH', confidence: 0.9, repository: 'acme/app', branch: 'main', workflowName: 'CI', failedStep: 'Install', evidence: ['npm ERR'], cleanedLog: 'npm install failed', resolved: false, createdAt: '2026-09-18T12:00:00Z', commitSha: 'abc', suggestedActions: [{ description: 'Install the missing package lock and retry CI.', priority: 1 }] });
  api.mockResolvedValueOnce({ items: [] });
  render(<AuthenticatedAnalysisDetail analysisId="analysis-1" />);
  expect(await screen.findByText('Missing dependency')).toBeInTheDocument();
  expect(screen.getAllByText((_, element) => Boolean(element?.textContent?.includes('Priority') && element?.textContent?.includes('Install the missing package lock and retry CI.'))).length).toBeGreaterThan(0);
  expect(screen.getByText('No patch recommendation has been generated for this analysis.')).toBeInTheDocument();
});

test('renders recurring metadata and resolution status for recurring failures', async () => {
  api.mockResolvedValueOnce({
    id: 'analysis-1',
    summary: 'Build failed',
    rootCause: 'Missing dependency',
    category: 'DEPENDENCY_ERROR',
    severity: 'HIGH',
    confidence: 0.9,
    repository: 'acme/app',
    branch: 'main',
    workflowName: 'CI',
    failedStep: 'Install',
    evidence: ['npm ERR'],
    cleanedLog: 'npm install failed',
    resolved: true,
    status: 'RESOLVED',
    createdAt: '2026-09-18T12:00:00Z',
    firstSeen: '2026-09-01T00:00:00Z',
    lastSeen: '2026-09-18T12:00:00Z',
    occurrenceCount: 4,
    resolvedAt: '2026-09-19T00:00:00Z',
    resolutionNote: 'Dependencies were pinned to a compatible version.',
    actualSolution: 'Pin the package version',
    commitSha: 'abc',
    suggestedActions: [{ description: 'Pin the package version before rerunning CI.', priority: 1 }],
  });
  api.mockResolvedValueOnce({ items: [] });

  render(<AuthenticatedAnalysisDetail analysisId="analysis-1" />);

  expect(await screen.findByText('RESOLVED')).toBeInTheDocument();
  expect(screen.getByText('Recurring failures')).toBeInTheDocument();
  expect(screen.getByText('4')).toBeInTheDocument();
  expect(screen.getByText('Pin the package version')).toBeInTheDocument();
  expect(screen.getByText('Dependencies were pinned to a compatible version.')).toBeInTheDocument();
});

test('waits for an explicit accept action before accepting an invitation', async () => {
  api.mockResolvedValue({ organizationId: 'org-123', accepted: true });

  render(<InvitationAccept token="invite-token-123" />);

  expect(screen.getByRole('button', { name: 'Accept invitation' })).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Accept invitation' }));

  await waitFor(() => expect(api).toHaveBeenCalledWith('/invitations/invite-token-123/accept', { method: 'POST' }));
  expect(screen.getByText('Invitation accepted.')).toBeInTheDocument();
});

test('explains when the signed-in email cannot accept an invitation', async () => {
  api.mockRejectedValue(new Error('Invitation email does not match current user'));

  render(<InvitationAccept token="invite-token-123" />);
  fireEvent.click(screen.getByRole('button', { name: 'Accept invitation' }));

  expect(await screen.findByRole('paragraph')).toHaveTextContent(
    'This invitation belongs to a different email address. Sign out and sign in with the invited email.',
  );
});
