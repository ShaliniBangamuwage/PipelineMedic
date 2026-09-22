import { useEffect, useState } from "react";
import {
  Activity,
  GitBranch,
  ExternalLink,
  Github,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  ShieldCheck,
  Users,
  UserPlus,
} from "lucide-react";
import { accessToken, setAccessToken, ThemeToggle } from "./App";
import { PipelineMedicLogo } from "./components/Brand";
import { MemberList, type Member } from "./features/members/MemberList";
import {
  InvitationList,
  type Invitation,
} from "./features/invitations/InvitationList";
import { JobsPage } from "./features/jobs/JobsPage";
import { PRCommentSettings } from "./features/repositories/PRCommentSettings";
import { PRCommentDeliveryPanel } from "./features/jobs/PRCommentDeliveryPanel";
import { RepositoryManagement } from "./features/repositories/RepositoryManagement";
import { request as authenticatedRequest } from "./api/client";
const API = import.meta.env.VITE_API_BASE_URL || "/api";
type Org = { id: string; name: string };
type SuggestedAction = { description: string; priority: number };
type Analysis = {
  id: string;
  summary: string;
  rootCause: string;
  category: string;
  severity: string;
  confidence: number;
  repository: string | null;
  branch: string;
  workflowName: string;
  failedStep: string;
  evidence: string[];
  cleanedLog: string;
  suggestedActions?: SuggestedAction[];
  resolved: boolean;
  status?: string;
  occurrenceCount?: number;
  firstSeen?: string | null;
  lastSeen?: string | null;
  resolvedAt?: string | null;
  resolutionNote?: string | null;
  actualSolution?: string | null;
  createdAt: string;
  commitSha: string;
  failedCommand?: string | null;
  githubRunUrl?: string | null;
  runAttempt?: number | null;
  resolvedBy?: string | null;
};
type Patch = { id: string; status: string; explanation: string; unifiedDiff: string };
type DashboardSummary = {
  totalFailures: number;
  resolvedFailures: number;
  unresolvedFailures: number;
  resolutionRate: number;
  averageConfidence: number;
  repositoriesMonitored: number;
  failureRateByRepository: Array<{ repository: string; failures: number; failureRate: number; averageConfidence: number }>;
  mostCommonCategory?: string;
};
const call = authenticatedRequest;
export function AuthenticatedShell() {
  const [path, setPath] = useState(location.pathname);
  const [mobile, setMobile] = useState(false);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [selected, setSelected] = useState(
    localStorage.getItem("pipelinemedic.organization") || "",
  );
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("VIEWER");
  const [message, setMessage] = useState("");
  const [orgReady, setOrgReady] = useState(false);
  const [workspaceSummary, setWorkspaceSummary] = useState<DashboardSummary | null>(null);
  useEffect(() => {
    Promise.all([call("/auth/me"), call("/organizations")])
      .then(([user, result]) => {
        const available = (result.items || []) as Org[];
        const memberships = (user.organizations || []) as Array<{ id: string; role: string }>;
        const persisted = localStorage.getItem("pipelinemedic.organization") || "";
        const nextSelected = available.some((org) => org.id === persisted)
          ? persisted
          : available[0]?.id || "";
        setEmail(user.email);
        setOrgs(available);
        setSelected(nextSelected);
        setRole(memberships.find((item) => item.id === nextSelected)?.role || "VIEWER");
        if (nextSelected) localStorage.setItem("pipelinemedic.organization", nextSelected);
        else localStorage.removeItem("pipelinemedic.organization");
        setOrgReady(true);
      })
      .catch((cause) => {
        setMessage(cause instanceof Error ? cause.message : "Could not load organizations.");
        setOrgReady(true);
      });
  }, []);
  useEffect(() => {
    if (!selected) {
      setWorkspaceSummary(null);
      return;
    }
    call("/dashboard/summary")
      .then((result) => setWorkspaceSummary((result as DashboardSummary) || null))
      .catch(() => setWorkspaceSummary(null));
  }, [selected]);
  useEffect(() => {
    if (selected) localStorage.setItem("pipelinemedic.organization", selected);
    call("/auth/me")
      .then((result) => {
        setRole(
          result.organizations?.find(
            (item: { id: string; role: string }) => item.id === selected,
          )?.role || "VIEWER",
        );
      })
      .catch(() => setRole("VIEWER"));
    window.dispatchEvent(new Event("pipelinemedic:organization-changed"));
  }, [selected]);
  const go = (to: string) => {
    history.pushState({}, "", to);
    setPath(to);
    setMobile(false);
  };
  const normalizedPath = path === "/" ? "/overview" : path;
  const analysisId = normalizedPath.startsWith("/analyses/") ? normalizedPath.split("/")[2] : "";
  const jobId = normalizedPath.startsWith("/jobs/") ? normalizedPath.split("/")[2] : "";
  const pageTitle = normalizedPath === "/overview" ? "Overview" : normalizedPath === "/jobs" ? "Jobs" : normalizedPath === "/repositories" ? "Repositories" : normalizedPath === "/organizations" ? "Organizations" : normalizedPath === "/settings" ? "Settings" : analysisId ? "Analysis details" : jobId ? "Job details" : "PipelineMedic";
  const repositoryId = normalizedPath.startsWith("/repositories/")
    ? normalizedPath.split("/")[2]
    : "";
  const logout = async () => {
    await call("/auth/logout", { method: "POST" }).catch(() => {});
    setAccessToken("");
    localStorage.removeItem("pipelinemedic.organization");
    sessionStorage.clear();
    location.href = "/login";
  };
  const workspaceName = orgs.find((org) => org.id === selected)?.name || "Current workspace";
  const repoCount = workspaceSummary?.repositoriesMonitored ?? null;
  const currentFailures = workspaceSummary?.unresolvedFailures ?? null;
  const analyzedFailures = workspaceSummary?.totalFailures ?? null;
  return (
    <div className="shell">
      <aside className={mobile ? "open" : ""}>
        <PipelineMedicLogo />
        <nav>
          <button
            className={normalizedPath === "/overview" ? "selected" : ""}
            onClick={() => go("/overview")}
          >
            <LayoutDashboard size={16} />
            Overview
          </button>
          <button
            className={normalizedPath === "/organizations" ? "selected" : ""}
            onClick={() => go("/organizations")}
          >
            <Users size={16} />
            Organizations
          </button>
          <button
            className={normalizedPath === "/jobs" || Boolean(jobId) ? "selected" : ""}
            onClick={() => go("/jobs")}
          >
            <Activity size={16} />
            Jobs
          </button>
          <button
            className={normalizedPath === "/repositories" || Boolean(repositoryId) ? "selected" : ""}
            onClick={() => go("/repositories")}
          >
            <Github size={16} />
            Repositories
          </button>
          <button
            className={normalizedPath === "/settings" ? "selected" : ""}
            onClick={() => go("/settings")}
          >
            <Settings size={16} />
            Settings
          </button>
        </nav>
        <div className="sidebar-status">
          <div className="sidebar-section">
            <div className="sidebar-section-header">System Status</div>
            <div className="status-list">
              <div className="status-item">
                <span className={`status-dot ${email ? "good" : "neutral"}`} />
                <span>GitHub Connected</span>
                <strong>{email ? "Available" : "Pending"}</strong>
              </div>
              <div className="status-item">
                <span className={`status-dot ${workspaceSummary ? "good" : "neutral"}`} />
                <span>Webhook Active</span>
                <strong>{workspaceSummary ? "Available" : "Pending"}</strong>
              </div>
              <div className="status-item">
                <span className={`status-dot ${workspaceSummary ? "good" : "neutral"}`} />
                <span>Analysis Service</span>
                <strong>{workspaceSummary ? "Available" : "Pending"}</strong>
              </div>
            </div>
          </div>
          <div className="sidebar-section">
            <div className="sidebar-section-header">Current Workspace</div>
            <div className="workspace-card">
              <div className="workspace-name">{workspaceName}</div>
              <div className="workspace-metric">
                <span>Connected repos</span>
                <strong>{repoCount !== null ? repoCount : "—"}</strong>
              </div>
              <div className="workspace-metric">
                <span>Open failures</span>
                <strong>{currentFailures !== null ? currentFailures : "—"}</strong>
              </div>
              <div className="workspace-metric">
                <span>Analyzed failures</span>
                <strong>{analyzedFailures !== null ? analyzedFailures : "—"}</strong>
              </div>
            </div>
          </div>
        </div>
        <div className="sidebar-foot">
          <ShieldCheck size={16} />
          {orgs.find((org) => org.id === selected)?.name ||
            "Select organization"}
        </div>
      </aside>
      <main>
        <header>
          <button className="menu" aria-label="Open navigation" onClick={() => setMobile(!mobile)}>
            <Menu size={20} />
          </button>
          <div>
            <p className="eyebrow">GITHUB CI/CD FAILURE INTELLIGENCE</p>
            <h1>{pageTitle}</h1>
          </div>
          <div className="header-status">
            <label className="context-org">
              <GitBranch size={14} />
              <select aria-label="Current organization" value={selected} onChange={(event) => setSelected(event.target.value)}>
                <option value="">Select organization</option>
                {orgs.map((org) => <option value={org.id} key={org.id}>{org.name}</option>)}
              </select>
            </label>
            <div className="header-theme"><ThemeToggle compact /></div>
            {email}
            <button className="ghost" onClick={logout}>
              <LogOut size={15} /> Logout
            </button>
          </div>
        </header>
        {message && (
          <div className="content">
            <div className="notice" role="alert">
              {message}
            </div>
          </div>
        )}
        {!orgReady ? (
          <section className="content"><div className="panel empty">Loading organization context...</div></section>
        ) : !selected && ["/overview"].includes(normalizedPath) ? (
          <OrganizationWorkspace
            orgs={orgs}
            selected={selected}
            setSelected={setSelected}
            role={role}
            setRole={setRole}
            setMessage={setMessage}
          />
        ) : normalizedPath === "/organizations" ? (
          <OrganizationWorkspace
            orgs={orgs}
            selected={selected}
            setSelected={setSelected}
            role={role}
            setRole={setRole}
            setMessage={setMessage}
          />
        ) : jobId ? (
          <AuthenticatedJobDetail jobId={jobId} />
        ) : normalizedPath === "/jobs" ? (
          <JobsPage role={role} />
        ) : normalizedPath === "/repositories" ? (
          <RepositoryManagement go={go} />
        ) : normalizedPath === "/settings" ? (
          <AuthenticatedSettingsPage />
        ) : analysisId ? (
          <AuthenticatedAnalysisDetail analysisId={analysisId} />
        ) : repositoryId ? (
          <section className="content">
            <PRCommentSettings repositoryId={repositoryId} role={role} />
          </section>
        ) : (
          <AuthenticatedOverview go={go} />
        )}
      </main>
    </div>
  );
}

export function AuthenticatedOverview({ go }: { go: (to: string) => void }) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [items, setItems] = useState<Analysis[]>([]);
  const [trend, setTrend] = useState<{ series: Array<{ date: string; count: number }>; categories: Array<{ category: string; count: number }> }>({ series: [], categories: [] });
  const [insights, setInsights] = useState<Array<{ level: string; title: string; message: string }>>([]);
  const [search, setSearch] = useState(() => new URLSearchParams(location.search).get("search") || "");
  const [category, setCategory] = useState(() => new URLSearchParams(location.search).get("category") || "");
  const [status, setStatus] = useState(() => new URLSearchParams(location.search).get("status") || "");
  const [dateRange, setDateRange] = useState(() => new URLSearchParams(location.search).get("range") || "30");
  const [page, setPage] = useState(() => Number(new URLSearchParams(location.search).get("page") || 1));
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams();
    if (search.trim()) params.set("search", search.trim());
    if (category) params.set("category", category);
    if (status) params.set("resolved", status === "resolved" ? "true" : "false");
    if (dateRange !== "all") {
      const start = new Date(Date.now() - Number(dateRange) * 86400000).toISOString();
      params.set("start_date", start);
    }
    params.set("page", String(page));
    params.set("pageSize", "8");
    const query = params.toString();
    const trendsQuery = dateRange === "all" ? "" : `?start_date=${encodeURIComponent(new Date(Date.now() - Number(dateRange) * 86400000).toISOString())}`;
    const nextUrl = query ? `/overview?${query}&range=${dateRange}` : `/overview?range=${dateRange}`;
    history.replaceState({}, "", nextUrl);
    setLoading(true);
    Promise.all([call("/dashboard/summary"), call(`/analyses?${query}`), call(`/dashboard/trends${trendsQuery}`), call("/dashboard/insights")])
      .then(([summaryResult, analysesResult, trendResult, insightResult]) => {
        setSummary(summaryResult as DashboardSummary);
        setItems((analysesResult.items || []) as Analysis[]);
        setTotal(analysesResult.total || 0);
        setTrend({ series: trendResult?.series || [], categories: trendResult?.categories || [] });
        setInsights(insightResult?.notifications || []);
        setError("");
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load dashboard."))
      .finally(() => setLoading(false));
  }, [search, category, status, dateRange, page]);

  const recurringFailures = items.filter((item) => (item.occurrenceCount ?? 1) > 1).length;
  const totalFailures = summary?.totalFailures ?? items.length;
  const openCount = summary?.unresolvedFailures ?? items.filter((item) => !item.resolved).length;
  const resolvedCount = summary?.resolvedFailures ?? items.filter((item) => item.resolved).length;

  return (
    <section className="content">
      <div className="detail-head">
        <div>
          <p className="kicker">WORKSPACE OVERVIEW</p>
          <h2>Overview</h2>
          <p className="muted">Your GitHub CI/CD failure insights at a glance.</p>
        </div>
        <span className="tag">Failure Intelligence</span>
      </div>
      {error && <div className="notice" role="alert">{error}</div>}

      {!loading && !error && totalFailures === 0 && items.length === 0 ? (
        <div className="panel empty">
          <strong>No failure data yet</strong>
          <span>Workflow runs and analysis results will appear here once your organization starts producing CI failures.</span>
        </div>
      ) : (
        <>
          <div className="metrics">
            <div className="metric">
              <div className="metric-icon cyan"><Activity size={18} /></div>
              <span>Total failures</span>
              <strong>{loading ? "--" : totalFailures}</strong>
            </div>
            <div className="metric">
              <div className="metric-icon red"><Activity size={18} /></div>
              <span>Open</span>
              <strong>{loading ? "--" : openCount}</strong>
            </div>
            <div className="metric">
              <div className="metric-icon green"><Activity size={18} /></div>
              <span>Resolved</span>
              <strong>{loading ? "--" : resolvedCount}</strong>
            </div>
            <div className="metric">
              <div className="metric-icon amber"><Activity size={18} /></div>
              <span>Recurring failures</span>
              <strong>{loading ? "--" : recurringFailures}</strong>
            </div>
            <div className="metric">
              <div className="metric-icon cyan"><Github size={18} /></div>
              <span>Repositories</span>
              <strong>{loading ? "--" : summary?.repositoriesMonitored ?? 0}</strong>
            </div>
          </div>

          <div className="grid-two">
            <div className="panel">
              <div className="panel-head">
                <div>
                  <p className="kicker">REPOSITORY ACTIVITY</p>
                  <h3>Failure distribution</h3>
                </div>
              </div>
              {(summary?.failureRateByRepository?.length ?? 0) ? (
                <div className="category-list">
                  {summary!.failureRateByRepository.map((repo) => (
                    <div className="category" key={repo.repository}>
                      <div>
                        <span className="legend" />
                        <span>{repo.repository}</span>
                      </div>
                      <strong>{repo.failures}</strong>
                      <div className="track">
                        <i style={{ width: `${Math.min(repo.failureRate, 100)}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty">No repository activity data is available yet.</div>
              )}
            </div>

            <div className="panel">
              <div className="panel-head">
                <div>
                  <p className="kicker">SUMMARY</p>
                  <h3>Operational status</h3>
                </div>
              </div>
              <div className="setting">
                <span>Resolution rate</span>
                <strong>{summary ? `${summary.resolutionRate}%` : "--"}</strong>
              </div>
              <div className="setting">
                <span>Average confidence</span>
                <strong>{summary ? `${summary.averageConfidence}%` : "--"}</strong>
              </div>
              <div className="setting">
                <span>Repositories monitored</span>
                <strong>{summary?.repositoriesMonitored ?? 0}</strong>
              </div>
              <div className="setting">
                <span>Most common category</span>
                <strong>{summary?.mostCommonCategory || "NONE"}</strong>
              </div>
            </div>
          </div>

          <div className="grid-two">
            <div className="panel"><div className="panel-head"><div><p className="kicker">FAILURE TREND</p><h3>Failures by day</h3></div></div>{trend.series.length ? <div className="trend-list">{trend.series.slice(-14).map((point) => <div className="trend-row" key={point.date}><small>{point.date}</small><i style={{ width: `${Math.max(4, Math.min(100, point.count * 12))}%` }} /><strong>{point.count}</strong></div>)}</div> : <div className="empty">No trend data is available for this range.</div>}</div>
            <div className="panel"><div className="panel-head"><div><p className="kicker">FAILURE CATEGORIES</p><h3>Categories</h3></div></div>{trend.categories.length ? <div className="category-list">{trend.categories.map((item) => <div className="category" key={item.category}><div><span className="legend" /><span>{item.category}</span></div><strong>{item.count}</strong><div className="track"><i style={{ width: `${Math.min(100, (item.count / Math.max(trend.categories[0].count, 1)) * 100)}%` }} /></div></div>)}</div> : <div className="empty">No category data is available for this range.</div>}</div>
          </div>

          {insights.length > 0 && <div className="panel insights-panel"><div className="panel-head"><div><p className="kicker">INSIGHTS</p><h3>Operational signals</h3></div></div>{insights.map((item) => <div className="insight" key={`${item.level}-${item.title}`}><span className={`tag ${item.level}`}>{item.level}</span><div><strong>{item.title}</strong><p>{item.message}</p></div></div>)}</div>}

          <div className="panel table">
            <div className="panel-head">
              <div>
                <p className="kicker">RECENT FAILURES</p>
                <h3>Latest workflow failures</h3>
              </div>
              <div className="toolbar overview-filters"><input aria-label="Search failures" placeholder="Search failures..." value={search} onChange={(event) => { setPage(1); setSearch(event.target.value); }} /><select aria-label="Failure category" value={category} onChange={(event) => { setPage(1); setCategory(event.target.value); }}><option value="">All categories</option>{trend.categories.map((item) => <option key={item.category}>{item.category}</option>)}</select><select aria-label="Failure status" value={status} onChange={(event) => { setPage(1); setStatus(event.target.value); }}><option value="">All statuses</option><option value="open">Open failures</option><option value="resolved">Resolved failures</option></select><select aria-label="Failure date range" value={dateRange} onChange={(event) => { setPage(1); setDateRange(event.target.value); }}><option value="1">Last 24 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="all">All time</option></select><button className="ghost" onClick={() => { setSearch(""); setCategory(""); setStatus(""); setDateRange("30"); setPage(1); }}>Clear filters</button></div>
            </div>
            {loading ? (
              <div className="empty">Loading failure intelligence...</div>
            ) : items.length ? (
              items.map((item) => (
                <button className="failure-row" key={item.id} onClick={() => go(`/analyses/${item.id}`)}>
                  <span className={`severity ${item.severity.toLowerCase()}`} />
                  <span className="row-main">
                    <strong>{item.summary}</strong>
                    <small>{item.repository || "Unassigned"} · {item.workflowName} · {item.branch}</small>
                  </span>
                  <span className="tag">{item.category}</span>
                  <span className="confidence">{Math.round(item.confidence * 100)}%</span>
                </button>
              ))
            ) : (
              <div className="empty">No workflow failures have been analyzed for this organization.</div>
            )}
            {total > 8 && <div className="pagination"><button className="ghost" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page {page} of {Math.ceil(total / 8)}</span><button className="ghost" disabled={page >= Math.ceil(total / 8)} onClick={() => setPage((value) => value + 1)}>Next</button></div>}
          </div>
        </>
      )}
    </section>
  );
}

export function AuthenticatedSettingsPage() {
  return (
    <section className="content">
      <div className="panel prose">
        <h3>Settings</h3>
        <p>Manage the workspace experience for your current account and organization.</p>
      </div>
      <div className="panel prose settings-panel">
        <h3>Appearance</h3>
        <ThemeToggle />
      </div>
    </section>
  );
}

export function AuthenticatedAnalysisDetail({ analysisId }: { analysisId: string }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [similar, setSimilar] = useState<Analysis[]>([]);
  const [patches, setPatches] = useState<Patch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [resolutionNote, setResolutionNote] = useState("");
  const [actualSolution, setActualSolution] = useState("");
  const [resolving, setResolving] = useState(false);
  useEffect(() => {
    Promise.all([call(`/analyses/${analysisId}`), call(`/analyses/${analysisId}/patches`), call(`/analyses/${analysisId}/similar`)]).then(([result, patchResult, similarResult]) => {
      setAnalysis(result);
      setPatches(patchResult.items || []);
      setSimilar(similarResult?.items || []);
    }).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load analysis.")).finally(() => setLoading(false));
  }, [analysisId]);
  if (loading) return <section className="content"><div className="panel empty">Loading analysis...</div></section>;
  if (error || !analysis) return <section className="content"><div className="notice" role="alert">{error || "Analysis not found."}</div></section>;
  const statusLabel = analysis.status || (analysis.resolved ? "RESOLVED" : "OPEN");
  const repositoryUrl = analysis.repository ? `https://github.com/${analysis.repository}` : "";
  const commitUrl = repositoryUrl && analysis.commitSha ? `${repositoryUrl}/commit/${encodeURIComponent(analysis.commitSha)}` : "";
  const resolveFailure = async () => {
    setResolving(true);
    try {
      const result = await call(`/analyses/${analysisId}/resolve`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resolution_note: resolutionNote || null, actual_solution: actualSolution || null }) });
      setAnalysis(result);
      setResolutionNote("");
      setActualSolution("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not resolve failure.");
    } finally {
      setResolving(false);
    }
  };
  return <section className="content narrow">
    <div className="detail-head"><div><p className="kicker">{analysis.category} / {analysis.workflowName}</p><h2>{analysis.summary}</h2><p className="muted">{analysis.repository || "Unassigned"} · {analysis.branch} · {analysis.commitSha || "No commit SHA"}{analysis.runAttempt ? ` · Attempt ${analysis.runAttempt}` : ""}</p><div className="detail-links">{repositoryUrl && <a href={repositoryUrl} target="_blank" rel="noreferrer">View repository <ExternalLink size={13} /></a>}{analysis.githubRunUrl && <a href={analysis.githubRunUrl} target="_blank" rel="noreferrer">View run <ExternalLink size={13} /></a>}{commitUrl && <a href={commitUrl} target="_blank" rel="noreferrer">View commit <ExternalLink size={13} /></a>}</div></div><span className="tag">{analysis.severity}</span></div>
    <div className="panel prose">
      <p className="kicker">STATUS</p>
      <h3>{statusLabel}</h3>
      <div className="setting"><span>Recurring failures</span><strong>{analysis.occurrenceCount ?? 1}</strong></div>
      <div className="setting"><span>First seen</span><span>{analysis.firstSeen ? new Date(analysis.firstSeen).toLocaleString() : "Not recorded"}</span></div>
      <div className="setting"><span>Last seen</span><span>{analysis.lastSeen ? new Date(analysis.lastSeen).toLocaleString() : "Not recorded"}</span></div>
      <div className="setting"><span>Resolved at</span><span>{analysis.resolvedAt ? new Date(analysis.resolvedAt).toLocaleString() : "Still open"}</span></div>
    </div>
    <div className="panel prose"><p className="kicker">ROOT CAUSE</p><h3>{analysis.rootCause || "No root cause was stored."}</h3><p>Failed step: <b>{analysis.failedStep}</b></p><p>Detected {new Date(analysis.createdAt).toLocaleString()} · {analysis.resolved ? "Resolved" : "Unresolved"}</p></div>
    <div className="panel prose"><p className="kicker">FAILED COMMAND</p>{analysis.failedCommand ? <code className="command-block">{analysis.failedCommand}</code> : <p>No failed command was recorded for this analysis.</p>}</div>
    {!analysis.resolved && <div className="panel form-panel"><p className="kicker">RESOLUTION</p><h3>Resolve failure</h3><label>Resolution note<textarea value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} placeholder="What fixed or acknowledged this failure?" /></label><label>Actual solution <input value={actualSolution} onChange={(event) => setActualSolution(event.target.value)} /></label><button className="primary" disabled={resolving} onClick={resolveFailure}>{resolving ? "Saving..." : "Mark as resolved"}</button></div>}
    {(analysis.resolutionNote || analysis.actualSolution) && <div className="panel prose"><p className="kicker">PREVIOUS RESOLUTION</p>{analysis.resolutionNote && <p>{analysis.resolutionNote}</p>}{analysis.actualSolution && <p><b>Actual solution:</b> {analysis.actualSolution}</p>}</div>}
    <div className="panel prose"><p className="kicker">RECOMMENDED ACTIONS</p>{(analysis.suggestedActions ?? []).length ? <ol>{analysis.suggestedActions!.map((action, index) => <li key={`${action.description}-${index}`}>Priority {action.priority}: {action.description}</li>)}</ol> : <p>No recommended actions were captured for this failure.</p>}</div>
    <div className="panel prose"><p className="kicker">LOG EVIDENCE</p><pre>{analysis.cleanedLog || "No cleaned log was stored."}</pre>{analysis.evidence.length > 0 && <><p className="kicker">EVIDENCE EXCERPTS</p><pre>{analysis.evidence.join("\n")}</pre></>}</div>
    <div className="panel prose"><p className="kicker">RECOMMENDATIONS</p>{patches.length ? patches.map((patch) => <div key={patch.id}><h3>{patch.status}</h3><p>{patch.explanation}</p>{patch.unifiedDiff && <pre>{patch.unifiedDiff}</pre>}</div>) : <p>No patch recommendation has been generated for this analysis.</p>}</div>
    <div className="panel"><div className="panel-head"><div><p className="kicker">RELATED HISTORY</p><h3>Similar incidents</h3></div></div>{similar.length ? similar.map((item) => <button className="failure-row" key={item.id} onClick={() => (location.href = `/analyses/${item.id}`)}><span className="row-main"><strong>{item.summary}</strong><small>{item.category} · {item.repository || "Unassigned"} · {item.status || (item.resolved ? "RESOLVED" : "OPEN")} · {new Date(item.createdAt).toLocaleDateString()}</small></span><span className="confidence">{item.resolved ? "RESOLVED" : "OPEN"}</span></button>) : <div className="empty">No similar incidents found.</div>}</div>
  </section>;
}

export function AuthenticatedJobDetail({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<{ id: string; kind: string; status: string; attempts: number; errorMessage?: string | null; createdAt?: string | null; updatedAt?: string | null; workflowRunId?: string | null; runAttempt?: number | null } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    call(`/jobs/${jobId}`).then(setJob).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load job."));
  }, [jobId]);
  if (error) return <section className="content"><div className="notice" role="alert">{error}</div></section>;
  if (!job) return <section className="content"><div className="panel empty">Loading job...</div></section>;
  return <section className="content narrow"><button className="text-btn" onClick={() => (location.href = "/jobs")}>Back to jobs</button><div className="detail-head"><div><p className="kicker">BACKGROUND PROCESSING</p><h2>{job.kind}</h2><p className="muted">{job.id}</p></div><span className="tag">{job.status}</span></div><div className="panel prose"><div className="setting"><span>Workflow run</span><strong>{job.workflowRunId || "Not linked"}</strong></div><div className="setting"><span>Run attempt</span><strong>{job.runAttempt ?? "Not recorded"}</strong></div><div className="setting"><span>Attempts</span><strong>{job.attempts}</strong></div><div className="setting"><span>Created</span><span>{job.createdAt ? new Date(job.createdAt).toLocaleString() : "Not recorded"}</span></div><div className="setting"><span>Updated</span><span>{job.updatedAt ? new Date(job.updatedAt).toLocaleString() : "Not recorded"}</span></div>{job.errorMessage && <div className="notice" role="alert">Analysis processing failed<br />Reason: {job.errorMessage}</div>}</div></section>;
}
function OrganizationWorkspace({
  orgs,
  selected,
  setSelected,
  role,
  setRole,
  setMessage,
}: {
  orgs: Org[];
  selected: string;
  setSelected: (id: string) => void;
  role: string;
  setRole: (role: string) => void;
  setMessage: (message: string) => void;
}) {
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invitation[]>([]);
  const [email, setEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("DEVELOPER");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => {
    if (!selected) return;
    const requests = [
      call(`/organizations/${selected}/members`, {
        headers: { "X-Organization-ID": selected },
      }),
    ];
    if (role === "ADMIN" || role === "OWNER") {
      requests.push(
        call(`/organizations/${selected}/invitations`, {
          headers: { "X-Organization-ID": selected },
        }),
      );
    }
    Promise.all(requests)
      .then(([memberResult, inviteResult]) => {
        setMembers(memberResult.items || []);
        setInvites(inviteResult?.items || []);
      })
      .catch(() => setMessage("Could not load workspace details."));
  };
  useEffect(load, [selected, role]);
  const create = async () => {
    setBusy(true);
    try {
      const result = await call("/organizations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setName("");
      setSelected(result.id);
      setMessage("Organization created.");
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Could not create organization.",
      );
    } finally {
      setBusy(false);
    }
  };
  const invite = async () => {
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setMessage("Enter a valid email address.");
      return;
    }
    setBusy(true);
    try {
      const result = await call(`/organizations/${selected}/invitations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Organization-ID": selected,
        },
        body: JSON.stringify({ email, role: inviteRole }),
      });
      setInvites([...invites, result]);
      setEmail("");
      setMessage("Invitation created.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not create invitation.",
      );
    } finally {
      setBusy(false);
    }
  };
  const updateRole = async (member: Member, next: string) => {
    setBusy(true);
    try {
      await call(`/organizations/${selected}/members/${member.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-Organization-ID": selected,
        },
        body: JSON.stringify({ role: next }),
      });
      load();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Could not update member role.",
      );
    } finally {
      setBusy(false);
    }
  };
  const remove = async (member: Member) => {
    if (!window.confirm(`Remove ${member.email}?`)) return;
    setBusy(true);
    try {
      await call(`/organizations/${selected}/members/${member.id}`, {
        method: "DELETE",
        headers: { "X-Organization-ID": selected },
      });
      load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not remove member.",
      );
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (inviteItem: Invitation) => {
    if (!window.confirm(`Revoke invitation for ${inviteItem.email}?`)) return;
    setBusy(true);
    try {
      await call(`/organizations/${selected}/invitations/${inviteItem.id}`, {
        method: "DELETE",
        headers: { "X-Organization-ID": selected },
      });
      load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not revoke invitation.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="content">
      <div className="panel form-panel">
        <h2>Organizations</h2>
        <label>
          Active organization
          <select
            aria-label="Active organization"
            value={selected}
            onChange={(event) => {
              setSelected(event.target.value);
              setMembers([]);
              setInvites([]);
            }}
          >
            <option value="">Select organization</option>
            {orgs.map((org) => (
              <option value={org.id} key={org.id}>
                {org.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          New organization
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button
          className="primary"
          disabled={busy || !name.trim()}
          onClick={create}
        >
          Create organization
        </button>
      </div>
      {selected && (role === "ADMIN" || role === "OWNER") && (
        <>
          <div className="panel form-panel">
            <h3>Invite member</h3>
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label>
              Role
              <select
                value={inviteRole}
                onChange={(event) => setInviteRole(event.target.value)}
              >
                {role === "OWNER" && <option>OWNER</option>}
                <option>ADMIN</option>
                <option>DEVELOPER</option>
                <option>VIEWER</option>
              </select>
            </label>
            <button className="primary" disabled={busy} onClick={invite}>
              <UserPlus size={15} /> Send invitation
            </button>
          </div>
          <MemberList
            members={members}
            role={role}
            busy={busy}
            onRole={updateRole}
            onRemove={remove}
          />
          <InvitationList items={invites} busy={busy} onRevoke={revoke} />
        </>
      )}
    </section>
  );
}
export function InvitationAccept({ token }: { token: string }) {
  const [message, setMessage] = useState(
    "You have been invited to join this organization.",
  );
  const [busy, setBusy] = useState(false);
  const accept = async () => {
    setBusy(true);
    setMessage("Accepting invitation...");
    try {
      const result = await call(`/invitations/${token}/accept`, {
        method: "POST",
      });
      localStorage.setItem("pipelinemedic.organization", result.organizationId);
      window.dispatchEvent(new Event("pipelinemedic:organization-changed"));
      setMessage("Invitation accepted.");
      setTimeout(() => (location.href = "/organizations"), 500);
    } catch (error) {
      setBusy(false);
      if (error instanceof Error && error.message === "Invitation email does not match current user") {
        setMessage("This invitation belongs to a different email address. Sign out and sign in with the invited email.");
        return;
      }
      setMessage(
        error instanceof Error
          ? error.message
          : "Invitation is invalid or expired.",
      );
      return;
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="auth-page">
      <div className="panel empty">
        <h2>Invitation</h2>
        <p>{message}</p>
        {!busy && message !== "Invitation accepted." && (
          <button className="primary" onClick={accept}>
            Accept invitation
          </button>
        )}
      </div>
    </main>
  );
}
