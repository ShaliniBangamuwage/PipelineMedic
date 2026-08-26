import { useEffect, useState } from 'react';
import { RefreshCw, RotateCcw } from 'lucide-react';
import { request } from '../../api/client';

type Job = { id: string; kind: string; status: string; attempts: number; errorCode: string | null; nextRetryAt: string | null; createdAt: string | null };
const terminal = new Set(['COMPLETED', 'FAILED']);

export function JobsPage({ role }: { role: string }) {
  const [items, setItems] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const load = async () => {
    try { setItems((await request('/jobs')).items || []); setMessage(''); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Could not load jobs.'); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    setItems([]); setLoading(true); load();
    const refresh = () => { setItems([]); setLoading(true); load(); };
    window.addEventListener('pipelinemedic:organization-changed', refresh);
    return () => window.removeEventListener('pipelinemedic:organization-changed', refresh);
  }, []);
  useEffect(() => {
    if (!items.some(item => !terminal.has(item.status))) return;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [items]);
  const retry = async (id: string) => {
    try { await request(`/jobs/${id}/retry`, { method: 'POST' }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Retry failed.'); }
  };
  return <section className="content"><div className="panel table"><div className="detail-head"><div><p className="kicker">BACKGROUND WORK</p><h2>Jobs</h2></div><button className="ghost" aria-label="Refresh jobs" onClick={load}><RefreshCw size={16}/></button></div>{message && <div className="notice" role="alert">{message}</div>}{loading ? <div className="empty">Loading jobs...</div> : items.length === 0 ? <div className="empty">No queued work.</div> : items.map(job => <div className="failure-row" key={job.id}><span className={`severity ${job.status.toLowerCase()}`}/><span className="row-main"><strong>{job.kind}</strong><small>{job.id}</small></span><span className="tag">{job.status}</span><span className="confidence">{job.attempts} attempts</span>{role !== 'VIEWER' && job.status === 'FAILED' && <button className="ghost" aria-label={`Retry ${job.kind}`} onClick={() => retry(job.id)}><RotateCcw size={15}/></button>}</div>)}</div></section>;
}
