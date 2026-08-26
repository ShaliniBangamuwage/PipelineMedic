import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthPage, SessionGate } from './AuthPages';

beforeEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); localStorage.clear(); });

describe('authentication UI', () => {
  it('validates registration fields', () => {
    render(<AuthPage mode="register" />);
    expect(screen.getByRole('button', { name: 'Register' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'long-password-123' } });
    expect(screen.getByRole('button', { name: 'Register' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Organization'), { target: { value: 'Platform' } });
    expect(screen.getByRole('button', { name: 'Register' })).toBeEnabled();
  });

  it('shows failed login errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Invalid email or password' }), { status: 401 }));
    render(<AuthPage mode="login" />);
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'long-password-123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
  });

  it('keeps demo mode available without session restoration', () => {
    render(<SessionGate><div>Protected workspace</div></SessionGate>);
    expect(screen.getByText('Protected workspace')).toBeInTheDocument();
    expect(screen.getByText('Protected workspace')).toBeInTheDocument();
  });

  it('does not redirect in demo mode when refresh is unavailable', () => {
    render(<SessionGate><div>Protected workspace</div></SessionGate>);
    expect(screen.getByText('Protected workspace')).toBeInTheDocument();
  });
});