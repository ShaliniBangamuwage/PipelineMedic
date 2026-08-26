import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemberList } from './MemberList';

const members=[{id:'owner',email:'owner@example.com',role:'OWNER'},{id:'dev',email:'dev@example.com',role:'DEVELOPER'}];
describe('MemberList',()=>{
  it('shows member details and owner controls',()=>{render(<MemberList members={members} role="OWNER" busy={false} onRole={vi.fn()} onRemove={vi.fn()}/>);expect(screen.getAllByText(/owner@example.com/).length).toBeGreaterThan(0);expect(screen.getByLabelText('Role for dev@example.com')).toBeEnabled();});
  it('keeps viewer membership read-only',()=>{render(<MemberList members={members} role="VIEWER" busy={false} onRole={vi.fn()} onRemove={vi.fn()}/>);expect(screen.queryByLabelText('Role for dev@example.com')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:/Remove/})).not.toBeInTheDocument();});
  it('disables final owner role changes',()=>{render(<MemberList members={[members[0]]} role="OWNER" busy={false} onRole={vi.fn()} onRemove={vi.fn()}/>);expect(screen.getByLabelText('Role for owner@example.com')).toBeDisabled();});
  it('emits role updates',()=>{const onRole=vi.fn();render(<MemberList members={members} role="OWNER" busy={false} onRole={onRole} onRemove={vi.fn()}/>);fireEvent.change(screen.getByLabelText('Role for dev@example.com'),{target:{value:'ADMIN'}});expect(onRole).toHaveBeenCalledWith(members[1],'ADMIN');});
});