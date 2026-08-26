import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { InvitationList } from './InvitationList';

describe('InvitationList',()=>{
  it('renders statuses and only revokes pending invitations',()=>{const onRevoke=vi.fn();render(<InvitationList busy={false} onRevoke={onRevoke} items={[{id:'pending',email:'p@example.com',role:'DEVELOPER',expiresAt:new Date(Date.now()+86400000).toISOString(),accepted:false,revoked:false},{id:'accepted',email:'a@example.com',role:'VIEWER',expiresAt:new Date(Date.now()+86400000).toISOString(),accepted:true,revoked:false}]}/>);expect(screen.getByText(/Pending/)).toBeInTheDocument();expect(screen.getByText(/Accepted/)).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'Revoke'}));expect(onRevoke).toHaveBeenCalledTimes(1);});
  it('does not expose token hashes',()=>{render(<InvitationList busy={false} onRevoke={vi.fn()} items={[{id:'one',email:'p@example.com',role:'DEVELOPER',expiresAt:new Date(Date.now()+86400000).toISOString(),accepted:false,revoked:false}]}/>);expect(screen.queryByText(/token_hash|sha256|secret/i)).not.toBeInTheDocument();});
});