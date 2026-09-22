import { useEffect, useState } from "react";
import { ArrowRight, Check, Eye, EyeOff, GitBranch, Github, ShieldCheck, Terminal } from "lucide-react";
import { accessToken, setAccessToken } from "./App";
import { PipelineMedicLogo } from "./components/Brand";

const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

async function submit(path: string, payload: Record<string, string>) {
  if (path === "/auth/register") {
    if (!/^\S+@\S+\.\S+$/.test(payload.email)) throw new Error("Enter a valid email address.");
    if (payload.password.length < 12) throw new Error("Password must be at least 12 characters.");
    if (payload.organization.trim().length < 2) throw new Error("Organization must be at least 2 characters.");
  }
  const response = await fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(payload) });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map((item: { msg?: string }) => item.msg || "Invalid value").join(" ") : body.detail;
    throw new Error(detail || "Request failed");
  }
  return response.json();
}

export function SessionGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(!import.meta.env.VITE_AUTH_ENABLED || import.meta.env.VITE_AUTH_ENABLED !== "true");
  const [authenticated, setAuthenticated] = useState(ready);
  useEffect(() => {
    if (ready) return;
    fetch(API + "/auth/refresh", { method: "POST", credentials: "include" }).then((response) => response.ok ? response.json() : Promise.reject()).then((result) => { setAccessToken(result.access_token); setAuthenticated(true); }).catch(() => setAuthenticated(false)).finally(() => setReady(true));
  }, [ready]);
  if (!ready) return <main className="auth-page auth-page--silent" aria-live="polite" aria-busy="true"><div className="session-loading"><span className="session-spinner" aria-hidden="true" /><span>Checking session…</span></div></main>;
  return authenticated ? <>{children}</> : <LandingPage />;
}

export function LandingPage() {
  return <main className="landing-page"><header className="landing-nav"><PipelineMedicLogo /><nav><a href="#features">Features</a><a href="#how-it-works">How it works</a><a href="#security">Security</a></nav><div className="landing-actions"><a className="text-btn" href="/login">Sign in</a><a className="button-primary" href="/register">Get started <ArrowRight size={15} /></a></div></header><section className="landing-hero"><div className="landing-copy"><span className="eyebrow"><GitBranch size={13} /> BUILT FOR GITHUB ACTIONS</span><h1>Understand your GitHub CI/CD <em>failures in seconds.</em></h1><p>PipelineMedic analyzes failed workflows, surfaces the evidence behind the break, and gives developers a clear next step.</p><div className="landing-cta"><a className="button-primary" href="/register">Get started <ArrowRight size={15} /></a><a className="button-secondary" href="#how-it-works">See how it works</a></div><div className="trust-line"><ShieldCheck size={15} /> Organization-scoped analysis and repository-specific credentials</div></div><WorkflowPreview /></section><section className="feature-strip" id="features"><Feature icon={<Terminal size={18} />} title="Automatic failure analysis" text="Analyze failed workflow logs automatically." /><Feature icon={<ShieldCheck size={18} />} title="Clear root causes" text="Surface the evidence that explains the break." /><Feature icon={<ArrowRight size={18} />} title="Actionable recommendations" text="Get practical next steps from real failure evidence." /><Feature icon={<GitBranch size={18} />} title="Failure history" text="Track recurring CI/CD failures across runs." /></section><section className="how-section" id="how-it-works"><span className="eyebrow">THE WORKFLOW</span><h2>From failed run to useful diagnosis.</h2><div className="flow"><span>Push code</span><i>→</i><span>GitHub Actions</span><i>→</i><span className="flow-fail">Workflow fails</span><i>→</i><span>PipelineMedic</span><i>→</i><strong>Root cause + evidence</strong></div></section><section className="trust-section" id="security"><ShieldCheck size={19} /><div><h3>Built with boundaries in mind</h3><p>Workspaces stay organization-scoped. Repository credentials are configured per repository and hidden after saving.</p></div></section></main>;
}

function Feature({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) { return <article className="feature-item"><span className="feature-icon">{icon}</span><div><h3>{title}</h3><p>{text}</p></div></article>; }
function WorkflowPreview() { return <div className="workflow-preview"><div className="preview-head"><span><span className="status-dot green-dot" /> PipelineMedic Test</span><code>push to main</code></div><div className="workflow-step done"><Check size={15} /><span>Checkout</span><small>3s</small></div><div className="workflow-step done"><Check size={15} /><span>Setup Python</span><small>5s</small></div><div className="workflow-step done"><Check size={15} /><span>Install dependencies</span><small>8s</small></div><div className="workflow-step failed"><span className="step-x">x</span><span>pytest</span><small>4s</small></div><div className="workflow-step pending"><span className="step-pending" /><span>Deploy</span><small>0s</small></div><div className="diagnosis-card"><span className="eyebrow">PIPELINEMEDIC ANALYSIS</span><strong>UNIT_TEST_FAILURE</strong><code>AssertionError: assert 1 == 2</code><a href="/login">View analysis <ArrowRight size={14} /></a></div></div>; }

function PasswordControl({ value, setValue, confirm, visible, setVisible, register }: { value: string; setValue: (value: string) => void; confirm?: boolean; visible: boolean; setVisible: (visible: boolean) => void; register: boolean }) {
  return <span className="password-control"><input aria-label={confirm ? "Confirm password" : "Password"} type={visible ? "text" : "password"} minLength={confirm ? undefined : 12} placeholder={confirm ? "Confirm your password" : register ? "Create a strong password" : "Your password"} value={value} onChange={(event) => setValue(event.target.value)} /><button type="button" className="password-toggle" aria-label={visible ? "Hide password" : "Show password"} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={16} /> : <Eye size={16} />}</button></span>;
}

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [organization, setOrganization] = useState("");
  const [error, setError] = useState(() => new URLSearchParams(location.search).get("github_error") || "");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const register = mode === "register";
  const run = async () => {
    if (register && password !== confirmPassword) { setError("Passwords do not match."); return; }
    setBusy(true); setError("");
    try { const result = await submit(register ? "/auth/register" : "/auth/login", register ? { email, password, organization } : { email, password }); setAccessToken(result.access_token); location.href = sessionStorage.getItem("pipelinemedic.returnTo") || "/"; sessionStorage.removeItem("pipelinemedic.returnTo"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to authenticate"); }
    finally { setBusy(false); }
  };
  const githubLogin = () => { location.href = `${API}/auth/github`; };
  return <main className="auth-page"><div className="auth-layout"><section className="auth-aside"><PipelineMedicLogo /><span className="eyebrow"><GitBranch size={13} /> BUILT FOR GITHUB ACTIONS</span><h1>{register ? "Join PipelineMedic and start turning CI/CD failures into faster fixes." : "Your GitHub CI/CD failure assistant."}</h1><p>{register ? "Create your account to connect repositories, analyze workflow failures, and get actionable insights." : "Turn noisy workflow output into a focused diagnosis your team can act on."}</p><ul>{(register ? ["Connect your GitHub repositories", "Automatically analyze workflow failures", "Find clear root causes", "Get practical recommendations", "Save time and ship faster"] : ["Analyze workflow failures", "Find important log evidence", "Understand root causes", "Get actionable recommendations"]).map((text) => <li key={text}><Check size={15} />{text}</li>)}</ul>{register && <WorkflowPreview />}</section><div className="auth-card"><span className="eyebrow">{register ? "CREATE WORKSPACE" : "PIPELINEMEDIC ACCOUNT"}</span><h2>{register ? "Create your account" : "Welcome back"}</h2><p className="muted">{register ? "Start using PipelineMedic today." : "Sign in to continue to your failure intelligence workspace."}</p>{error && <div className="notice" role="alert">{error}</div>}<label>Email address<input aria-label="Email" type="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>Password <PasswordControl value={password} setValue={setPassword} visible={showPassword} setVisible={setShowPassword} register={register} /></label>{register && <><label>Confirm password <PasswordControl value={confirmPassword} setValue={setConfirmPassword} confirm visible={showConfirmPassword} setVisible={setShowConfirmPassword} register={register} /></label><label>Organization<input aria-label="Organization" placeholder="Your workspace name" value={organization} onChange={(event) => setOrganization(event.target.value)} /></label><p className="auth-hint">Use a strong password with at least 12 characters.</p></>}<button className="button-primary wide" disabled={busy || !email || !password || (register && (!organization || !confirmPassword))} onClick={run}>{busy ? "Working..." : register ? "Create account" : "Sign in"}</button><div className="auth-divider"><span>or</span></div><button className="github-auth-button" type="button" onClick={githubLogin}><Github size={17} /> Continue with GitHub</button><button className="text-btn auth-switch" onClick={() => { location.href = register ? "/login" : "/register" }}>{register ? "Already have an account? Sign in" : "Need an account? Create account"}</button></div></div></main>;
}

export function OrganizationPage() {
  const [items, setItems] = useState<Array<{ id: string; name: string }>>([]);
  const [selected, setSelected] = useState("");
  const [members, setMembers] = useState<Array<{ email: string; role: string }>>([]);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const headers = { Authorization: `Bearer ${accessToken}` };
  const load = () => { fetch(API + "/organizations", { headers, credentials: "include" }).then((response) => response.json()).then((result) => setItems(result.items || [])).catch(() => setMessage("Could not load organizations.")); };
  useEffect(() => { load(); }, []);
  useEffect(() => { if (!selected) return; fetch(`${API}/organizations/${selected}/members`, { headers: { ...headers, "X-Organization-ID": selected }, credentials: "include" }).then((response) => response.json()).then((result) => setMembers(result.items || [])).catch(() => setMessage("Could not load members.")); }, [selected]);
  const create = async () => { const response = await fetch(API + "/organizations", { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ name }) }); if (response.ok) { setName(""); load(); setMessage("Organization created."); } else setMessage("Could not create organization."); };
  return <main className="content narrow"><div className="panel form-panel"><h2>Organizations</h2>{message && <div className="notice" role="alert">{message}</div>}<label>New organization<input value={name} onChange={(event) => setName(event.target.value)} /></label><button className="primary" disabled={!name.trim()} onClick={create}>Create organization</button></div><div className="panel form-panel"><label>Active organization<select value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Select an organization</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{selected && <div>{members.length ? members.map((member) => <div className="failure-row" key={member.email}><span className="row-main"><strong>{member.email}</strong><small>{member.role}</small></span></div>) : <div className="empty">No members found.</div>}</div>}</div></main>;
}
