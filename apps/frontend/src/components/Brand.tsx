import { Activity } from "lucide-react";

export function PipelineMedicLogo({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? "brand-compact" : ""}`}>
      <div className="mark" aria-hidden="true">
        <Activity size={18} />
      </div>
      <span className="brand-name">
        Pipeline<span>Medic</span>
      </span>
    </div>
  );
}