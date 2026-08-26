import { useEffect, useState } from "react";
import {
  Activity,
  LayoutDashboard,
  LogOut,
  Settings,
  ShieldCheck,
  Users,
  UserPlus,
} from "lucide-react";
import { accessToken, setAccessToken } from "./App";
import { MemberList, type Member } from "./features/members/MemberList";
import {
  InvitationList,
  type Invitation,
} from "./features/invitations/InvitationList";
import { JobsPage } from "./features/jobs/JobsPage";
import { PRCommentSettings } from "./features/repositories/PRCommentSettings";
import { PRCommentDeliveryPanel } from "./features/jobs/PRCommentDeliveryPanel";
import { request as authenticatedRequest } from "./api/client";
const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";
type Org = { id: string; name: string };
const call = authenticatedRequest;
export function AuthenticatedShell() {
  const [path, setPath] = useState(location.pathname);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [selected, setSelected] = useState(
    localStorage.getItem("pipelinemedic.organization") || "",
  );
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("VIEWER");
  const [message, setMessage] = useState("");
  useEffect(() => {
    call("/auth/me")
      .then((result) => {
        setEmail(result.email);
        setRole(
          result.organizations?.find(
            (item: { id: string; role: string }) => item.id === selected,
          )?.role || "VIEWER",
        );
      })
      .catch(() => setMessage("Session expired. Please log in again."));
    call("/organizations")
      .then((result) => {
        const available = result.items || [];
        setOrgs(available);
        if (!(available as Org[]).some((org) => org.id === selected)) {
          setSelected("");
          localStorage.removeItem("pipelinemedic.organization");
        }
      })
      .catch(() => setMessage("Could not load organizations."));
  }, []);
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
  };
  const analysisId = path.startsWith("/analyses/") ? path.split("/")[2] : "";
  const repositoryId = path.startsWith("/repositories/")
    ? path.split("/")[2]
    : "";
  const logout = async () => {
    await call("/auth/logout", { method: "POST" }).catch(() => {});
    setAccessToken("");
    localStorage.removeItem("pipelinemedic.organization");
    sessionStorage.clear();
    location.href = "/login";
  };
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <div className="mark">
            <Activity size={18} />
          </div>
          <span>
            Pipeline<span>Medic</span>
          </span>
        </div>
        <nav>
          <button
            className={path === "/" ? "selected" : ""}
            onClick={() => go("/")}
          >
            <LayoutDashboard size={16} />
            Overview
          </button>
          <button
            className={path === "/organizations" ? "selected" : ""}
            onClick={() => go("/organizations")}
          >
            <Users size={16} />
            Organizations
          </button>
          <button
            className={path === "/jobs" ? "selected" : ""}
            onClick={() => go("/jobs")}
          >
            <Activity size={16} />
            Jobs
          </button>
          <button
            className={path === "/repositories" ? "selected" : ""}
            onClick={() => go("/repositories")}
          >
            <Settings size={16} />
            Repositories
          </button>
          <button onClick={() => go("/settings")}>
            <Settings size={16} />
            Settings
          </button>
        </nav>
        <div className="sidebar-foot">
          <ShieldCheck size={16} />
          {orgs.find((org) => org.id === selected)?.name ||
            "Select organization"}
        </div>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">AUTHENTICATED WORKSPACE</p>
            <h1>PipelineMedic</h1>
          </div>
          <div className="header-status">
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
        {!selected ? (
          <OrganizationWorkspace
            orgs={orgs}
            selected={selected}
            setSelected={setSelected}
            role={role}
            setRole={setRole}
            setMessage={setMessage}
          />
        ) : path === "/organizations" ? (
          <OrganizationWorkspace
            orgs={orgs}
            selected={selected}
            setSelected={setSelected}
            role={role}
            setRole={setRole}
            setMessage={setMessage}
          />
        ) : path === "/jobs" ? (
          <JobsPage role={role} />
        ) : path === "/repositories" ? (
          <section className="content">
            <div className="panel empty">
              <h2>Repositories</h2>
              <span>Open a repository to manage PR comments.</span>
            </div>
          </section>
        ) : repositoryId ? (
          <section className="content">
            <PRCommentSettings repositoryId={repositoryId} role={role} />
          </section>
        ) : analysisId ? (
          <section className="content">
            <PRCommentDeliveryPanel analysisId={analysisId} role={role} />
          </section>
        ) : (
          <section className="content">
            <div className="panel empty">
              <h2>{orgs.find((org) => org.id === selected)?.name}</h2>
              <span>Organization-scoped workspace.</span>
              <button className="primary" onClick={() => go("/organizations")}>
                Manage workspace
              </button>
            </div>
          </section>
        )}
      </main>
    </div>
  );
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
    Promise.all([
      call(`/organizations/${selected}/members`, {
        headers: { "X-Organization-ID": selected },
      }),
      call(`/organizations/${selected}/invitations`, {
        headers: { "X-Organization-ID": selected },
      }),
    ])
      .then(([memberResult, inviteResult]) => {
        setMembers(memberResult.items || []);
        setInvites(inviteResult.items || []);
      })
      .catch(() => setMessage("Could not load workspace details."));
  };
  useEffect(load, [selected]);
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
      {selected && (
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
  const [state, setState] = useState("Accepting invitation...");
  useEffect(() => {
    call(`/invitations/${token}/accept`, { method: "POST" })
      .then((result) => {
        localStorage.setItem(
          "pipelinemedic.organization",
          result.organizationId,
        );
        setState("Invitation accepted.");
        setTimeout(() => (location.href = "/organizations"), 500);
      })
      .catch((error) =>
        setState(
          error instanceof Error
            ? error.message
            : "Invitation is invalid or expired.",
        ),
      );
  }, [token]);
  return (
    <main className="auth-page">
      <div className="panel empty">{state}</div>
    </main>
  );
}
