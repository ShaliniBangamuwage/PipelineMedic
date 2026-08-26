import { useEffect, useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { request } from '../../api/client';

type Delivery = { status: string; pullRequestNumber: number | null; githubCommentUrl: string | null; attemptCount: number; errorCode: string | null; errorMessage: string | null; createdAt: string | null; deliveredAt?: string | null } | null;
const active = new Set(['QUEUED', 'SENDING', 'RETRYING']);
export function PRCommentDeliveryPanel({ analysisId, role = 'DEVELOPER' }: { analysisId: string; role?: string }) {
  const [delivery, setDelivery] = useState<Delivery>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = () => request(`/analyses/${analysisId}/pr-comment`).then(setDelivery).catch(error => setError(error instanceof Error ? error.message : 'Could not load delivery status.')).finally(() => setLoading(false));
  useEffect(() => { load(); }, [analysisId]);
  useEffect(() => { if (!delivery || !active.has(delivery.status)) return; const timer = window.setInterval(load, 2000); return () => window.clearInterval(timer); }, [delivery?.status, analysisId]);
  const retry = async () => { try { await request(`/analyses/${analysisId}/pr-comment/retry`, { method: 'POST' }); setLoading(true); await load(); } catch (error) { setError(error instanceof Error ? error.message : 'Retry failed.'); } };
  if (loading) return <div className="panel empty">Loading PR comment delivery...</div>;
  return <div className="panel prose"><div className="detail-head"><div><p className="kicker">GITHUB DELIVERY</p><h3>Pull-request comment</h3></div>{delivery && <span className="tag">{delivery.status}</span>}</div>{error && <div className="notice" role="alert">{error}</div>}{!delivery ? <p className="muted">No PR comment delivery was created.</p> : <><p>Pull request: <b>{delivery.pullRequestNumber ?? 'Not found'}</b></p><p>Attempts: <b>{delivery.attemptCount}</b></p>{delivery.githubCommentUrl && <p><a href={delivery.githubCommentUrl} target="_blank" rel="noreferrer">Open GitHub comment</a></p>}{delivery.errorMessage && <p className="muted">{delivery.errorMessage}</p>}{delivery.status !== 'DELIVERED' && delivery.status !== 'SKIPPED' && role !== 'VIEWER' && <button className="ghost" onClick={retry}><RotateCcw size={15}/> Retry delivery</button>}</>}</div>;
}
