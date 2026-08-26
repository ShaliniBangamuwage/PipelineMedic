import { useEffect, useState } from "react";
import { Copy, Download, ShieldAlert } from "lucide-react";
import { request } from "../../api/client";

type Patch = {
  id: string;
  status: string;
  provider: string;
  model: string;
  unifiedDiff: string;
  explanation: string;
  confidence: number;
  riskLevel: string;
  affectedFiles: string[];
  validationErrors: string[];
};
export function PatchSuggestionsPanel({
  analysisId,
  role = "DEVELOPER",
}: {
  analysisId: string;
  role?: string;
}) {
  const [patch, setPatch] = useState<Patch | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [feedback, setFeedback] = useState("");
  const load = () =>
    request(`/analyses/${analysisId}/patches`)
      .then((result) => setPatch(result.items?.[0] || null))
      .catch(() => setMessage("Could not load patch suggestions."))
      .finally(() => setLoading(false));
  useEffect(() => {
    load();
  }, [analysisId]);
  const generate = async () => {
    setLoading(true);
    try {
      await request(`/analyses/${analysisId}/generate-patch`, {
        method: "POST",
      });
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Patch generation failed.",
      );
      setLoading(false);
    }
  };
  const decide = async (decision: "ACCEPTED" | "REJECTED") => {
    if (!patch) return;
    try {
      await request(`/patches/${patch.id}/decision`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, feedback: feedback.slice(0, 500) }),
      });
      setMessage(`Patch ${decision.toLowerCase()}.`);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Could not save patch decision.",
      );
    }
  };
  if (loading)
    return <div className="panel empty">Loading patch suggestions...</div>;
  return (
    <div className="panel prose">
      <div className="detail-head">
        <div>
          <p className="kicker">SAFE PATCH SUGGESTION</p>
          <h3>Patch suggestions</h3>
        </div>
        {patch && <span className="tag">{patch.status}</span>}
      </div>
      <div className="notice">
        <ShieldAlert size={16} />
        PipelineMedic never applies patches automatically. Review every
        suggestion.
      </div>
      {message && (
        <div className="notice" role="alert">
          {message}
        </div>
      )}
      {!patch ? (
        <>
          <p className="muted">No patch suggestion exists.</p>
          {role !== "VIEWER" && (
            <button className="primary" onClick={generate}>
              Generate patch suggestion
            </button>
          )}
        </>
      ) : (
        <>
          <p>{patch.explanation}</p>
          <p>
            Provider: <b>{patch.provider}</b> · Risk: <b>{patch.riskLevel}</b> ·
            Confidence: <b>{Math.round(patch.confidence * 100)}%</b>
          </p>
          {patch.validationErrors.length > 0 && (
            <p className="muted">
              Validation: {patch.validationErrors.join("; ")}
            </p>
          )}
          {patch.affectedFiles.length > 0 && (
            <p>Affected files: {patch.affectedFiles.join(", ")}</p>
          )}
          {patch.unifiedDiff && (
            <>
              <pre>{patch.unifiedDiff}</pre>
              <button
                className="ghost"
                onClick={() => navigator.clipboard.writeText(patch.unifiedDiff)}
              >
                <Copy size={15} /> Copy diff
              </button>
              <a
                className="ghost"
                href={`/api/patches/${patch.id}/download`}
                download
              >
                <Download size={15} /> Download
              </a>
            </>
          )}
          {patch.status === "READY" && role !== "VIEWER" && (
            <>
              <label>
                Review feedback
                <input
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                />
              </label>
              <button className="ghost" onClick={() => decide("ACCEPTED")}>
                Accept suggestion
              </button>
              <button className="ghost" onClick={() => decide("REJECTED")}>
                Reject suggestion
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
