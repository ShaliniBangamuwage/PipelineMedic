import { useEffect, useState } from "react";
import { CheckCircle2, Copy, GitBranch, Github, ExternalLink, LockKeyhole, Plus, RotateCcw, Trash2, Webhook } from "lucide-react";
import { request } from "../../api/client";

type Repository = {
  id: string;
  owner: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  active: boolean;
  failureCount: number;
  githubTokenConfigured?: boolean;
  webhookSecretConfigured?: boolean;
  verified?: boolean;
};

type RepositoryManagementProps = {
  go: (to: string) => void;
};

type GitHubRepository = {
  id: string;
  name: string;
  fullName: string;
  owner: string;
  private: boolean;
  defaultBranch: string;
  htmlUrl: string;
  installationId: string;
  alreadyConnected: boolean;
};

export function RepositoryManagement({ go }: RepositoryManagementProps) {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({
    owner: "",
    name: "",
    branch: "main",
    githubToken: "",
    webhookSecret: "",
  });
  const [edit, setEdit] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [verification, setVerification] = useState("");
  const [oneTimeSecret, setOneTimeSecret] = useState("");
  const [githubRepositories, setGithubRepositories] = useState<GitHubRepository[]>([]);
  const [githubLoading, setGithubLoading] = useState(true);
  const [githubError, setGithubError] = useState("");
  const [githubSearch, setGithubSearch] = useState("");
  const [githubBusy, setGithubBusy] = useState<string | null>(null);
  const [githubLoadVersion, setGithubLoadVersion] = useState(0);

  const load = async () => {
    setLoading(true);
    try {
      const result = await request("/repositories");
      setRepositories(result?.items || []);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load repositories.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    let cancelled = false;
    const loadGitHubRepositories = async () => {
      setGithubLoading(true);
      try {
        const result = await request("/github/app/repositories");
        if (cancelled) return;
        setGithubRepositories(result.items || []);
        setGithubError("");
      } catch (cause) {
        if (cancelled) return;
        setGithubRepositories([]);
        setGithubError(cause instanceof Error ? cause.message : "Could not load GitHub App repositories.");
      } finally {
        if (!cancelled) setGithubLoading(false);
      }
    };
    loadGitHubRepositories();
    return () => {
      cancelled = true;
    };
  }, [githubLoadVersion]);

  useEffect(() => {
    const refreshForOrganization = () => setGithubLoadVersion((version) => version + 1);
    window.addEventListener("pipelinemedic:organization-changed", refreshForOrganization);
    return () => window.removeEventListener("pipelinemedic:organization-changed", refreshForOrganization);
  }, []);

  const connectGitHub = async () => {
    const result = await request("/github/app/install", { method: "POST" });
    if (!result?.url) throw new Error("GitHub App installation URL was not returned.");
    window.location.assign(result.url);
  };

  const connectGitHubRepository = async (repository: GitHubRepository) => {
    setGithubBusy(repository.id);
    try {
      await request("/github/app/repositories/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ installation_id: repository.installationId, repository_id: repository.id }) });
      setGithubRepositories((items) => items.map((item) => item.id === repository.id ? { ...item, alreadyConnected: true } : item));
      await load();
    } catch (cause) {
      setGithubError(cause instanceof Error ? cause.message : "Could not connect repository.");
    } finally {
      setGithubBusy(null);
    }
  };

  const normalizedGitHubSearch = githubSearch.trim().toLowerCase();
  const filteredGitHubRepositories = normalizedGitHubSearch
    ? githubRepositories.filter((repository) => repository.fullName.toLowerCase().includes(normalizedGitHubSearch))
    : githubRepositories;

  const resetForm = () => {
    setEdit(null);
    setForm({ owner: "", name: "", branch: "main", githubToken: "", webhookSecret: "" });
  };

  const save = async () => {
    if (
      !/^[A-Za-z0-9_.-]+$/.test(form.owner) ||
      !/^[A-Za-z0-9_.-]+$/.test(form.name) ||
      !form.branch.trim()
    ) {
      setMessage("Use valid owner, repository, and branch values.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await request(edit ? `/repositories/${edit}` : "/repositories", {
        method: edit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          edit
            ? {
                default_branch: form.branch,
                github_token: form.githubToken || undefined,
                webhook_secret: form.webhookSecret || undefined,
              }
            : {
                owner: form.owner,
                name: form.name,
                default_branch: form.branch,
                github_token: form.githubToken || undefined,
                webhook_secret: form.webhookSecret || undefined,
              },
        ),
      });
      await load();
      setMessage("Repository saved. Credentials are stored securely and are not displayed.");
      setOneTimeSecret(result.webhookSecret || "");
      resetForm();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Repository save failed");
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    if (!form.owner || !form.name || !form.githubToken) {
      setVerification("Owner, repository, and PAT are required to verify the connection.");
      return;
    }
    setVerification("Checking connection...");
    try {
      const result = await request("/repositories/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ owner: form.owner, name: form.name, github_token: form.githubToken }) });
      setVerification(`Connected successfully: ${result.fullName} · default branch ${result.defaultBranch} · ${result.visibility}.`);
    } catch (cause) {
      setVerification(cause instanceof Error ? cause.message : "Unable to verify repository connection.");
    }
  };

  const rotate = async (repository: Repository) => {
    if (!window.confirm(`Rotate the webhook secret for ${repository.fullName}? GitHub webhook settings must be updated immediately.`)) return;
    setBusy(true);
    try {
      const result = await request(`/repositories/${repository.id}/rotate-webhook-secret`, { method: "POST" });
      setOneTimeSecret(result.webhookSecret);
      setMessage(result.message);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Could not rotate webhook secret.");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (repository: Repository) => {
    if (!window.confirm(`${repository.active ? "Deactivate" : "Activate"} ${repository.fullName}?`)) return;
    setBusy(true);
    try {
      await request(`/repositories/${repository.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !repository.active }),
      });
      await load();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Repository update failed");
    } finally {
      setBusy(false);
    }
  };

  const webhookUrl = `${import.meta.env.VITE_API_BASE_URL || `${location.origin}/api`}/webhooks/github`;

  return (
    <section className="content repository-page">
      <div className="page-heading-row">
        <div><p className="kicker">GITHUB INTEGRATIONS</p><h2>Repositories</h2><p className="muted">Connect and manage your GitHub repositories for CI/CD failure analysis.</p></div>
        <button type="button" className="primary" onClick={() => { resetForm(); setShowForm(true); }}><Plus size={15} /> Add repository</button>
      </div>
      <div className="panel github-app-panel">
        <div className="page-heading-row">
          <div><p className="kicker">GITHUB APP</p><h3>Connect GitHub</h3><p className="muted">Choose repository access in GitHub, then connect selected repositories here.</p></div>
          <button type="button" className="primary" onClick={() => connectGitHub().catch((cause) => setGithubError(cause instanceof Error ? cause.message : "Could not start GitHub App installation."))}><Github size={15} /> Manage GitHub Access</button>
        </div>
        {githubError && <div className="notice" role="alert">{githubError}</div>}
        <label htmlFor="github-repository-search">Search GitHub repositories</label>
        <input id="github-repository-search" name="github-repository-search" type="search" autoComplete="off" value={githubSearch} onChange={(event) => setGithubSearch(event.target.value)} placeholder="Search repositories..." />
        {githubLoading ? <div className="empty">Loading authorized repositories...</div> : filteredGitHubRepositories.length ? (
          <div className="github-repository-list">
            {filteredGitHubRepositories.map((repository) => <div className="repository-row" key={`${repository.installationId}:${repository.id}`}>
              <div className="repo-identity"><Github size={25}/><span><strong>{repository.fullName}</strong><small>{repository.private ? "Private" : "Public"} · {repository.defaultBranch}</small></span></div>
              <div className="repo-detail"><small>Access</small><span>{repository.private ? "Private" : "Public"}</span></div>
              <div className="repo-detail"><small>Default branch</small><span><GitBranch size={14}/> {repository.defaultBranch}</span></div>
              <div className="repo-actions"><a className="ghost" href={repository.htmlUrl} target="_blank" rel="noreferrer">View <ExternalLink size={13} /></a><button type="button" className={repository.alreadyConnected ? "ghost" : "primary"} disabled={repository.alreadyConnected || githubBusy === repository.id} onClick={() => connectGitHubRepository(repository)}>{repository.alreadyConnected ? "Connected" : githubBusy === repository.id ? "Connecting..." : "Connect"}</button></div>
            </div>)}
          </div>
        ) : <div className="empty">No authorized GitHub App repositories found.</div>}
      </div>
      <div className="repo-stats">
        <div className="repo-stat"><Github size={24}/><strong>{repositories.length}</strong><span>Total repositories</span></div>
        <div className="repo-stat"><CheckCircle2 size={20}/><strong>{repositories.filter((item) => item.active).length}</strong><span>Active repositories</span></div>
        <div className="repo-stat inactive"><span className="stat-dot"/><strong>{repositories.filter((item) => !item.active).length}</strong><span>Inactive repositories</span></div>
        <div className="repo-stat"><GitBranch size={21}/><strong>{repositories.reduce((total, item) => total + item.failureCount, 0)}</strong><span>Analyzed failures</span></div>
      </div>
      <div className={`panel form-panel repository-form ${showForm || edit ? "" : "is-collapsed"}`}>
        <h3>{edit ? "Edit repository" : "Add repository"}</h3>
        <p className="muted">Connect a GitHub repository to monitor its workflow failures. Each organization keeps its own repositories and tokens separate.</p>
        {message && <div className="notice" role="alert">{message}</div>}
        {verification && <div className="notice" role="status">{verification}</div>}
        {oneTimeSecret && <div className="notice" role="alert"><span><b>Webhook secret shown once:</b> <code>{oneTimeSecret}</code><br />Save it in GitHub webhook settings before closing this form.</span><button className="ghost" onClick={() => navigator.clipboard.writeText(oneTimeSecret)}><Copy size={14} /> Copy secret</button></div>}
        <div className="form-grid">
          <label>
            Owner
            <input disabled={Boolean(edit)} value={form.owner} onChange={(event) => setForm({ ...form, owner: event.target.value })} />
          </label>
          <label>
            Repository
            <input disabled={Boolean(edit)} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>
          <label>
            Default branch
            <input value={form.branch} onChange={(event) => setForm({ ...form, branch: event.target.value })} />
          </label>
          <label>
            GitHub personal access token
            <input type="password" value={form.githubToken} onChange={(event) => setForm({ ...form, githubToken: event.target.value })} placeholder="Token for this repo only" />
          </label>
          <label>
            Webhook secret (optional)
            <input type="password" value={form.webhookSecret} onChange={(event) => setForm({ ...form, webhookSecret: event.target.value })} placeholder="Generated if omitted" />
          </label>
        </div>
        <p className="muted">GitHub credentials are configured per repository. They are never returned or displayed after saving.</p>
        <div className="panel webhook-box">
          <p className="kicker">WEBHOOK SETUP</p>
          <p className="muted">Payload URL: {webhookUrl} <button className="ghost" onClick={() => navigator.clipboard.writeText(webhookUrl)}><Copy size={13} /> Copy</button></p>
          <p className="muted">Content type: application/json</p>
          <p className="muted">Event: workflow_run</p>
          <p className="muted">Secret: use the repository-specific secret you store here, or generate one in GitHub and enter it in the field above.</p>
          <p className="muted">Required GitHub permission: repository access for workflow logs and metadata.</p>
        </div>
        <button className="ghost" disabled={busy} onClick={verify}>Verify connection</button>
        <button className="primary" disabled={busy} onClick={save}>{busy ? "Saving..." : "Save repository"}</button>
        {edit && <button className="text-btn" disabled={busy} onClick={() => { resetForm(); setShowForm(false); }}>Cancel edit</button>}
      </div>
      {error && <div className="notice" role="alert">{error}</div>}
      <div className="panel table">
        {loading ? (
          <div className="empty">Loading repositories...</div>
        ) : repositories.length ? (
          repositories.map((repository) => (
            <div className="repository-row" key={repository.id}>
              <div className="repo-identity"><Github size={25}/><span><strong>{repository.fullName}</strong><small>{repository.defaultBranch} · {repository.failureCount} analyzed failures</small></span></div>
              <div className="repo-detail"><small>Default branch</small><span><GitBranch size={14}/> {repository.defaultBranch}</span></div>
              <div className="repo-detail"><small>Status</small><span className={repository.active ? "status-good" : "status-bad"}><i/> {repository.active ? "Active" : "Inactive"}</span></div>
              <div className="repo-detail"><small>GitHub PAT</small><span className={repository.githubTokenConfigured ? "status-good" : "status-bad"}><LockKeyhole size={13}/> {repository.githubTokenConfigured ? "Configured" : "Not configured"}</span></div>
              <div className="repo-detail"><small>Webhook</small><span className={repository.webhookSecretConfigured ? "status-good" : "status-bad"}><Webhook size={13}/> {repository.webhookSecretConfigured ? "Configured" : "Not configured"}</span></div>
              <div className="repo-actions">
              <span className="row-main">
                <span className="sr-only">Repository actions</span>
              </span>
              <button className="ghost" disabled={busy} onClick={() => {
                setEdit(repository.id);
                setShowForm(true);
                setForm({ owner: repository.owner, name: repository.name, branch: repository.defaultBranch, githubToken: "", webhookSecret: "" });
              }}>Edit</button>
              <button className="ghost" onClick={() => go(`/repositories/${repository.id}/pr-comments`)}>PR comments</button>
              <button className="ghost" disabled={busy} onClick={() => rotate(repository)}><RotateCcw size={14} /> Rotate secret</button>
              <a className="ghost" href={`https://github.com/${repository.owner}/${repository.name}`} target="_blank" rel="noreferrer">View on GitHub <ExternalLink size={13} /></a>
              <button className="ghost" disabled={busy} onClick={() => toggle(repository)}>{repository.active ? "Deactivate" : "Activate"}</button>
              <button className="ghost" aria-label={`${repository.active ? "Deactivate" : "Activate"} ${repository.fullName}`} disabled={busy} onClick={() => toggle(repository)}><Trash2 size={15} /></button>
              </div>
            </div>
          ))
        ) : (
          <div className="empty">No repositories connected.</div>
        )}
      </div>
    </section>
  );
}
