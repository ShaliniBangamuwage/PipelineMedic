import { beforeEach, describe, expect, it, vi } from 'vitest';
import { request, setToken } from './client';

beforeEach(()=>{vi.restoreAllMocks();setToken('expired');localStorage.clear();sessionStorage.clear();});
describe('authenticated client',()=>{
  it('refreshes once and retries an expired request',async()=>{const fetchMock=vi.spyOn(globalThis,'fetch');fetchMock.mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response(JSON.stringify({access_token:'fresh'}),{status:200})).mockResolvedValueOnce(new Response(JSON.stringify({ok:true}),{status:200}));const result=await request('/analyses');expect(result).toEqual({ok:true});expect(fetchMock).toHaveBeenCalledTimes(3);expect(fetchMock.mock.calls[1][0]).toContain('/auth/refresh');});
  it('queues concurrent requests behind one refresh',async()=>{const fetchMock=vi.spyOn(globalThis,'fetch');fetchMock.mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response(JSON.stringify({access_token:'fresh'}),{status:200})).mockImplementation(async()=>new Response(JSON.stringify({ok:true}),{status:200}));await Promise.all([request('/analyses'),request('/dashboard/summary')]);expect(fetchMock.mock.calls.filter(call=>String(call[0]).includes('/auth/refresh'))).toHaveLength(1);});
  it('does not intercept auth endpoints',async()=>{const fetchMock=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}',{status:401}));await expect(request('/auth/me')).rejects.toThrow();expect(fetchMock).toHaveBeenCalledTimes(1);});
});
