import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  FileSearch,
  Github,
  Menu,
  Settings,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from "lucide-react";
import { request as authenticatedRequest, setToken } from "./api/client";
import { PRCommentSettings } from "./features/repositories/PRCommentSettings";
import { PRCommentDeliveryPanel } from "./features/jobs/PRCommentDeliveryPanel";
import { PatchSuggestionsPanel } from "./features/patches/PatchSuggestionsPanel";
const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";
const AUTH_ENABLED = import.meta.env.VITE_AUTH_ENABLED === "true";
export let accessToken = "";
export function setAccessToken(token: string) {
  accessToken = token;
  setToken(token);
}
type Analysis = {
  id: string;
  summary: string;
  rootCause: string;
  category: string;
  severity: string;
  confidence: number;
  source: string;
  repository: string | null;
  branch: string;
  workflowName: string;
  failedStep: string;
  evidence: string[];
  cleanedLog: string;
  resolved: boolean;
  createdAt: string;
};
type Repo = {
  id: string;
  owner: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  active: boolean;
  failureCount: number;
};
const api = authenticatedRequest;
function useData<T>(path: string, fallback: T) {
  const [data, setData] = useState(fallback);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    setLoading(true);
    api(path)
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [path, tick]);
  return { data, loading, error, reload: () => setTick((v) => v + 1) };
}
function Notice({ text }: { text: string }) {
  return (
    <div className="notice" role="alert">
      <AlertTriangle size={16} />
      {text}
    </div>
  );
}
function App() {
  const [path, setPath] = useState(location.pathname);
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const f = () => setPath(location.pathname);
    addEventListener("popstate", f);
    return () => removeEventListener("popstate", f);
  }, []);
  const go = (to: string) => {
    history.pushState({}, "", to);
    setPath(to);
    setMobile(false);
  };
  const id = path.startsWith("/analyses/") ? path.split("/")[2] : "";
  const repositorySettingsId = path.startsWith("/repositories/") ? path.split("/")[2] : "";
  const page =
    path === "/analyze"
      ? "analyze"
      : path.startsWith("/analyses")
        ? "history"
        : path === "/repositories"
          ? "repos"
            : path.startsWith("/repositories/")
              ? "repo-settings"
          : path === "/settings"
            ? "settings"
            : "home";
  const links = [
    ["/", "Overview"],
    ["/analyze", "Analyze log"],
    ["/analyses", "History"],
    ["/repositories", "Repositories"],
    ["/settings", "Settings"],
  ];
  return (
    <div className="shell">
      <aside className={mobile ? "open" : ""}>
        <div className="brand">
          <div className="mark">
            <Activity size={18} />
          </div>
          <span>
            Pipeline<span>Medic</span>
          </span>
        </div>
        <nav>
          {links.map(([url, label]) => (
            <button
              key={url}
              className={path === url ? "selected" : ""}
              onClick={() => go(url)}
            >
              <FileSearch size={16} />
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <ShieldCheck size={16} />
          Demo mode active
        </div>
      </aside>
      <main>
        <header>
          <button
            className="menu"
            aria-label="Open navigation"
            onClick={() => setMobile(!mobile)}
          >
            <Menu />
          </button>
          <div>
            <p className="eyebrow">OPERATIONS CONSOLE</p>
            <h1>
              {id
                ? "Analysis report"
                : page === "home"
                  ? "System overview"
                  : page === "analyze"
                    ? "Triage a failure"
                    : page === "history"
                      ? "Failure history"
                      : page === "repos" || page === "repo-settings"
                        ? "Repositories"
                        : "Integration settings"}
            </h1>
          </div>
          <Github size={16} />
        </header>
        {id ? (
          <Detail id={id} go={go} />
        ) : page === "home" ? (
          <Home go={go} />
        ) : page === "analyze" ? (
          <Analyze go={go} />
        ) : page === "history" ? (
          <History go={go} />
        ) : page === "repos" ? (
          <Repositories go={go} />
        ) : page === "repo-settings" ? (
          <section className="content"><PRCommentSettings repositoryId={repositorySettingsId} role="ADMIN" /></section>
        ) : (
          <SettingsPage />
        )}
      </main>
    </div>
  );
}
function Home({ go }: { go: (to: string) => void }) {
  const data = useData("/dashboard/summary", {
    totalFailures: 0,
    unresolvedFailures: 0,
    resolutionRate: 0,
    averageConfidence: 0,
  });
  const recent = useData<{ items: Analysis[] }>("/analyses", { items: [] });
  return (
    <section className="content">
      <div className="hero-row">
        <div>
          <p className="kicker">LAST 24 HOURS</p>
          <h2>Know why the pipeline broke.</h2>
          <p className="muted">Turn CI/CD failures into actionable fixes.</p>
        </div>
        <button className="primary" onClick={() => go("/analyze")}>
          Analyze a log <ChevronRight size={16} />
        </button>
      </div>
      {data.error && <Notice text="Backend unavailable." />}
      <div className="metrics">
        {[
          ["Total failures", data.data.totalFailures],
          ["Unresolved", data.data.unresolvedFailures],
          ["Resolution rate", `${data.data.resolutionRate}%`],
          ["Confidence", `${data.data.averageConfidence}%`],
        ].map(([label, value]) => (
          <div className="metric" key={label as string}>
            <Activity size={18} />
            <span>{label}</span>
            <strong>{data.loading ? "--" : value}</strong>
          </div>
        ))}
      </div>
      <div className="panel recent">
        <h3>Recent failures</h3>
        {recent.loading ? (
          <div className="empty">Loading failures...</div>
        ) : recent.data.items.length ? (
          recent.data.items.map((item) => (
            <Row key={item.id} item={item} go={go} />
          ))
        ) : (
          <div className="empty">No analyses yet.</div>
        )}
      </div>
    </section>
  );
}
function Row({ item, go }: { item: Analysis; go: (to: string) => void }) {
  return (
    <button className="failure-row" onClick={() => go("/analyses/" + item.id)}>
      <span className={`severity ${item.severity.toLowerCase()}`} />
      <span className="row-main">
        <strong>{item.summary}</strong>
        <small>
          {item.repository || "Manual run"} · {item.branch}
        </small>
      </span>
      <span className="tag">{item.category}</span>
      <span className="confidence">{Math.round(item.confidence * 100)}%</span>
    </button>
  );
}
function Analyze({ go }: { go: (to: string) => void }) {
  const [log, setLog] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const samples = [
    "TS2322: Type string is not assignable to type number.\nError: compilation failed",
    "FAIL auth.test.ts\nAssertionError: expected true, received false",
    "npm ERR! code ERESOLVE\nCould not resolve dependency tree",
  ];
  const run = async () => {
    if (!log.trim()) {
      setError("Paste a log or choose a sample first.");
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("log", log);
      const result = await api("/demo/analyze", { method: "POST", body: form });
      go("/analyses/" + result.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="content narrow">
      <div className="mode-banner">
        <Activity size={17} />
        <div>
          <strong>Rule-based triage</strong>
          <span>Deterministic evidence matching. Groq AI is optional.</span>
        </div>
        <span className="badge">DEMO MODE</span>
      </div>
      {error && <Notice text={error} />}
      <div className="panel form-panel">
        <h3>Paste a workflow log</h3>
        <textarea
          aria-label="Workflow log"
          value={log}
          onChange={(e) => setLog(e.target.value)}
          placeholder="Paste GitHub Actions output here..."
        />
        <div className="samples">
          {samples.map((sample, index) => (
            <button
              className="sample"
              key={index}
              onClick={() => setLog(sample)}
            >
              Sample {index + 1}
            </button>
          ))}
        </div>
        <label className="drop">
          Choose a .log or .txt file
          <input
            type="file"
            accept=".log,.txt"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file && !/\.(log|txt)$/i.test(file.name)) {
                setError("Only .log and .txt files are supported.");
                return;
              }
              file?.text().then(setLog);
            }}
          />
        </label>
        <button className="primary wide" disabled={busy} onClick={run}>
          {busy ? "Analyzing..." : "Run triage analysis"}
        </button>
      </div>
    </section>
  );
}
function Detail({ id, go }: { id: string; go: (to: string) => void }) {
  const item = useData<Analysis | null>("/analyses/" + id, null);
  const related = useData<{ items: Array<Analysis & { similarity: number }> }>(
    "/analyses/" + id + "/similar",
    { items: [] },
  );
  const [choice, setChoice] = useState("");
  const [category, setCategory] = useState("");
  const [solution, setSolution] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  if (item.loading)
    return (
      <section className="content">
        <div className="panel empty">Loading analysis...</div>
      </section>
    );
  if (item.error || !item.data)
    return (
      <section className="content">
        <Notice text="Analysis could not be loaded." />
      </section>
    );
  const report = item.data;
  const send = async () => {
    if (!choice) {
      setMessage("Choose accurate or inaccurate.");
      return;
    }
    setBusy(true);
    try {
      await api(`/analyses/${id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accurate: choice === "accurate",
          actual_category: category || null,
          actual_solution: solution || null,
        }),
      });
      setMessage("Feedback saved successfully.");
      item.reload();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not save feedback");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="content narrow">
      <button className="text-btn" onClick={() => go("/analyses")}>
        Back to history
      </button>
      <div className="detail-head">
        <div>
          <p className="kicker">
            {report.source} / {report.category}
          </p>
          <h2>{report.summary}</h2>
          <p className="muted">
            {report.repository || "Manual run"} · {report.branch} ·{" "}
            {report.workflowName}
          </p>
        </div>
        <span className="tag">{report.severity}</span>
      </div>
      <div className="panel prose">
        <p className="kicker">ROOT CAUSE</p>
        <h3>{report.rootCause}</h3>
        <p>
          Failed step: <b>{report.failedStep}</b>
        </p>
        <p className="kicker">EVIDENCE</p>
        <pre>{report.evidence.join("\n")}</pre>
        <p className="kicker">CLEANED LOG</p>
        <pre>{report.cleanedLog}</pre>
      </div>
      <div className="panel form-panel">
        <h3>Was this analysis accurate?</h3>
        {message && <Notice text={message} />}
        <button className="ghost" onClick={() => setChoice("accurate")}>
          <ThumbsUp size={15} /> Accurate
        </button>
        <button className="ghost" onClick={() => setChoice("inaccurate")}>
          <ThumbsDown size={15} /> Inaccurate
        </button>
        <label>
          Actual category
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
        </label>
        <label>
          Actual solution
          <input
            value={solution}
            onChange={(e) => setSolution(e.target.value)}
          />
        </label>
        <button className="primary" disabled={busy} onClick={send}>
          {busy ? "Saving..." : "Submit feedback"}
        </button>
      </div>
      <PRCommentDeliveryPanel analysisId={id} />
      <PatchSuggestionsPanel analysisId={id} />
      <div className="panel">
        <h3>Similar incidents</h3>
        {related.loading ? (
          <div className="empty">Finding related incidents...</div>
        ) : related.error ? (
          <Notice text="Similar incidents unavailable." />
        ) : related.data.items.length ? (
          related.data.items.map((match) => (
            <button
              className="failure-row"
              key={match.id}
              onClick={() => go("/analyses/" + match.id)}
            >
              <span className="row-main">
                <strong>{match.summary}</strong>
                <small>
                  {match.category} · {match.repository || "Manual run"} ·{" "}
                  {new Date(match.createdAt).toLocaleDateString()}
                </small>
              </span>
              <span className="confidence">
                {Math.round(match.similarity * 100)}%
              </span>
            </button>
          ))
        ) : (
          <div className="empty">No similar incidents found.</div>
        )}
      </div>
    </section>
  );
}
function History({ go }: { go: (to: string) => void }) {
  const list = useData<{ items: Analysis[] }>("/analyses", { items: [] });
  return (
    <section className="content">
      <div className="panel table">
        {list.loading ? (
          <div className="empty">Loading failures...</div>
        ) : list.data.items.length ? (
          list.data.items.map((item) => (
            <Row key={item.id} item={item} go={go} />
          ))
        ) : (
          <div className="empty">No analyses yet.</div>
        )}
      </div>
    </section>
  );
}
function Repositories({ go }: { go: (to: string) => void }) {
  const list = useData<{ items: Repo[] }>("/repositories", { items: [] });
  const [form, setForm] = useState({ owner: "", name: "", branch: "main" });
  const [edit, setEdit] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
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
    try {
      await api(edit ? `/repositories/${edit}` : "/repositories", {
        method: edit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          edit
            ? { default_branch: form.branch }
            : {
                owner: form.owner,
                name: form.name,
                default_branch: form.branch,
              },
        ),
      });
      list.reload();
      setMessage("Repository saved.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Repository save failed");
    } finally {
      setBusy(false);
    }
  };
  const toggle = async (repo: Repo) => {
    if (
      !window.confirm(
        `${repo.active ? "Deactivate" : "Activate"} ${repo.fullName}?`,
      )
    )
      return;
    setBusy(true);
    try {
      await api(`/repositories/${repo.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !repo.active }),
      });
      list.reload();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Repository update failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="content">
      <div className="panel form-panel">
        <h3>{edit ? "Edit repository" : "Add repository"}</h3>
        {message && <Notice text={message} />}
        <div className="form-grid">
          <label>
            Owner
            <input
              disabled={Boolean(edit)}
              value={form.owner}
              onChange={(e) => setForm({ ...form, owner: e.target.value })}
            />
          </label>
          <label>
            Repository
            <input
              disabled={Boolean(edit)}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label>
            Default branch
            <input
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
            />
          </label>
        </div>
        <button className="primary" disabled={busy} onClick={save}>
          {busy ? "Saving..." : "Save repository"}
        </button>
      </div>
      {list.error && <Notice text="Could not load repositories." />}
      <div className="panel table">
        {list.loading ? (
          <div className="empty">Loading repositories...</div>
        ) : list.data.items.length ? (
          list.data.items.map((repo) => (
            <div className="failure-row" key={repo.id}>
              <span className="row-main">
                <strong>{repo.fullName}</strong>
                <small>
                  {repo.defaultBranch} · {repo.failureCount} failures
                </small>
              </span>
              <button
                className="ghost"
                disabled={busy}
                onClick={() => {
                  setEdit(repo.id);
                  setForm({
                    owner: repo.owner,
                    name: repo.name,
                    branch: repo.defaultBranch,
                  });
                }}
              >
                Edit
              </button>
              <button className="ghost" onClick={() => go(`/repositories/${repo.id}/pr-comments`)}>
                PR comments
              </button>
              <button
                className="ghost"
                disabled={busy}
                onClick={() => toggle(repo)}
              >
                {repo.active ? "Deactivate" : "Activate"}
              </button>
              <button
                className="ghost"
                aria-label="Deactivate repository"
                disabled={busy}
                onClick={() => toggle(repo)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))
        ) : (
          <div className="empty">No repositories connected.</div>
        )}
      </div>
    </section>
  );
}
function SettingsPage() {
  return (
    <section className="content">
      <div className="panel prose">
        <h3>Integration settings</h3>
        <p>Demo mode is active without external credentials.</p>
        <p>
          Webhook: <code>{API}/webhooks/github</code>
        </p>
      </div>
    </section>
  );
}
export default App;
